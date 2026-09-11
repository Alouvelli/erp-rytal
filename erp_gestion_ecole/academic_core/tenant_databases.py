"""
Découverte et enregistrement des bases PostgreSQL par institut dans
settings.DATABASES.

Chaque institut a sa propre base PostgreSQL nommée "db_rytal_<code>", sur le
même serveur et avec le même compte administrateur que la base 'default'
(POSTGRES_* dans .env) — un seul compte gère toutes les bases, actuelles et
futures (voir academic_core/apps/academic_structure/pg_provisioning.py pour la
création/le renommage effectifs).

Deux mécanismes complémentaires, à l'image de ce qui existait pour les
fichiers SQLite avant cette migration :
  - discover_tenant_databases() : lu une seule fois au chargement des settings,
    pré-peuple DATABASES avec tous les instituts déjà connus au démarrage du
    process, depuis les blocs DB_RYTAL_<CODE>_* du fichier .env.
  - register_tenant_db(alias) : enregistrement paresseux, appelé à la volée
    quand un alias attendu n'est pas encore dans DATABASES pour CE worker —
    cas d'un institut créé par un autre worker après le démarrage. Vérifie
    l'existence de la base via pg_database (équivalent du test d'existence de
    fichier utilisé du temps de SQLite) plutôt que de relire .env, qui peut ne
    pas encore refléter un institut tout juste créé par un autre process.
"""

import logging
from pathlib import Path

from decouple import config as _config, RepositoryEnv

logger = logging.getLogger(__name__)

TENANT_PREFIX = 'db_rytal_'


def _master_credentials() -> tuple[str, str, str, str]:
    """(host, port, user, password) du compte admin partagé, lu depuis .env."""
    return (
        _config('POSTGRES_HOST', default='localhost'),
        _config('POSTGRES_PORT', default='5432'),
        _config('POSTGRES_USER', default='postgres'),
        _config('POSTGRES_PASSWORD', default=''),
    )


def _tenant_db_entry(name: str, host: str, port: str, user: str, password: str) -> dict:
    """
    Django ne remplit automatiquement les clés par défaut d'une entrée
    DATABASES (TIME_ZONE, ATOMIC_REQUESTS, AUTOCOMMIT, CONN_HEALTH_CHECKS,
    TEST…) qu'une seule fois, à la première résolution de
    ConnectionHandler.settings (cached_property) — voir
    django.db.utils.ConnectionHandler.configure_settings. Une entrée ajoutée
    dynamiquement à settings.DATABASES APRÈS ce premier accès (notre cas :
    institut créé après le démarrage du process) ne passe jamais par
    configure_settings et doit donc fournir toutes ces clés elle-même, sous
    peine de KeyError('TIME_ZONE') dès la première connexion.
    """
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': name,
        'USER': user,
        'PASSWORD': password,
        'HOST': host,
        'PORT': str(port),
        'OPTIONS': {'connect_timeout': 10},
        'TIME_ZONE': None,
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 600,
        'CONN_HEALTH_CHECKS': False,
        'TEST': {'CHARSET': None, 'COLLATION': None, 'MIGRATE': True, 'MIRROR': None, 'NAME': None},
    }


def discover_tenant_databases(base_dir) -> dict:
    """
    Construit une entrée DATABASES pour chaque bloc DB_RYTAL_<CODE>_NAME
    présent dans .env. Lit le fichier directement via decouple.RepositoryEnv
    plutôt que os.environ : os.environ.get() ne reflète PAS forcément le
    contenu de .env (piège déjà documenté dans config/settings/base.py pour
    les identifiants EMAIL_*) — RepositoryEnv parse le fichier lui-même, donc
    fonctionne de façon fiable même hors Docker (où .env n'est pas injecté
    dans l'environnement réel du process).
    """
    env_path = Path(base_dir) / '.env'
    if not env_path.exists():
        return {}

    try:
        repo = RepositoryEnv(str(env_path))
    except Exception as exc:
        logger.warning('discover_tenant_databases: lecture .env échouée : %s', exc)
        return {}

    codes = {
        key[len('DB_RYTAL_'):-len('_NAME')]
        for key in repo.data
        if key.startswith('DB_RYTAL_') and key.endswith('_NAME')
    }

    default_host, default_port, default_user, default_password = _master_credentials()

    databases = {}
    for code in codes:
        name = repo.data.get(f'DB_RYTAL_{code}_NAME')
        if not name:
            continue
        host = repo.data.get(f'DB_RYTAL_{code}_HOST') or default_host
        port = repo.data.get(f'DB_RYTAL_{code}_PORT') or default_port
        user = repo.data.get(f'DB_RYTAL_{code}_USER') or default_user
        password = repo.data.get(f'DB_RYTAL_{code}_PASSWORD') or default_password
        databases[name] = _tenant_db_entry(name, host, port, user, password)

    return databases


def register_tenant_db(alias: str) -> str | None:
    """
    S'assure que `alias` (= nom de la base Postgres, ex: db_rytal_isi) est
    chargé dans settings.DATABASES pour le worker courant, en vérifiant son
    existence réelle côté serveur PostgreSQL. Retourne l'alias si utilisable,
    sinon None (base inexistante).
    """
    from django.conf import settings

    if not alias or alias == 'default':
        return None
    if alias in settings.DATABASES:
        return alias

    from academic_core.apps.academic_structure.pg_provisioning import database_exists

    if not database_exists(alias):
        return None

    host, port, user, password = _master_credentials()
    settings.DATABASES[alias] = _tenant_db_entry(alias, host, port, user, password)

    try:
        from academic_core.apps.accounting.apps import ensure_tenant_schema
        ensure_tenant_schema(alias)
    except Exception:
        pass

    return alias


def append_tenant_env_block(base_dir, code: str, db_name: str) -> None:
    """
    Ajoute (si absent) le bloc DB_RYTAL_<CODE>_* pour un institut fraîchement
    provisionné, avec les identifiants du compte admin partagé — matérialise
    dans .env les paramètres d'accès de chaque institut, tout en laissant la
    possibilité d'éditer ce bloc à la main plus tard pour faire pointer un
    institut donné vers un host/compte différent.

    Idempotent : n'écrit rien si le bloc existe déjà (ex: process redémarré
    après une création partiellement effectuée).
    """
    env_path = Path(base_dir) / '.env'
    marker = f'DB_RYTAL_{code}_NAME='

    try:
        content = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
    except Exception as exc:
        logger.warning('append_tenant_env_block(%s): lecture .env échouée : %s', code, exc)
        return

    if marker in content:
        return

    host, port, user, password = _master_credentials()
    block = (
        f"\n# ── Base PostgreSQL de l'institut {code} (générée automatiquement) ──\n"
        f'DB_RYTAL_{code}_NAME={db_name}\n'
        f'DB_RYTAL_{code}_HOST={host}\n'
        f'DB_RYTAL_{code}_PORT={port}\n'
        f'DB_RYTAL_{code}_USER={user}\n'
        f'DB_RYTAL_{code}_PASSWORD={password}\n'
    )
    try:
        with open(env_path, 'a', encoding='utf-8') as f:
            f.write(block)
    except Exception as exc:
        logger.error('append_tenant_env_block(%s): écriture .env échouée : %s', code, exc)


def remove_tenant_env_block(base_dir, alias: str) -> bool:
    """
    Symétrique de append_tenant_env_block : retire du .env le bloc
    DB_RYTAL_<CODE>_* dont la valeur NAME correspond à `alias`.

    Appelée quand l'institut est supprimé et sa base archivée (renommée) —
    voir academic_structure/utils.py::archive_institut_db. Sans ce nettoyage,
    discover_tenant_databases() recharge cet alias mort dans
    settings.DATABASES à chaque redémarrage du process (il reste dans .env
    alors que la base réelle a été renommée), ce qui trompe tout code qui se
    fie à `alias in settings.DATABASES` pour juger qu'une base est utilisable.

    Idempotent et silencieux si aucun bloc ne correspond (déjà nettoyé, ou
    institut qui n'avait pas de bloc .env — ex: ajouté à la main).
    """
    import re

    env_path = Path(base_dir) / '.env'
    if not env_path.exists():
        return False

    try:
        content = env_path.read_text(encoding='utf-8')
    except Exception as exc:
        logger.warning('remove_tenant_env_block(%s): lecture .env échouée : %s', alias, exc)
        return False

    match = re.search(rf'^DB_RYTAL_([A-Z0-9_]+)_NAME={re.escape(alias)}\s*$', content, re.MULTILINE)
    if not match:
        return False
    code = match.group(1)

    block_pattern = re.compile(
        rf"\n?(?:# ── Base PostgreSQL de l'institut {re.escape(code)}.*\n)?"
        rf'DB_RYTAL_{re.escape(code)}_NAME=.*\n'
        rf'DB_RYTAL_{re.escape(code)}_HOST=.*\n'
        rf'DB_RYTAL_{re.escape(code)}_PORT=.*\n'
        rf'DB_RYTAL_{re.escape(code)}_USER=.*\n'
        rf'DB_RYTAL_{re.escape(code)}_PASSWORD=.*\n?',
    )
    new_content, n = block_pattern.subn('\n', content, count=1)
    if n == 0:
        return False

    try:
        env_path.write_text(new_content, encoding='utf-8')
    except Exception as exc:
        logger.error('remove_tenant_env_block(%s): écriture .env échouée : %s', alias, exc)
        return False

    logger.info('remove_tenant_env_block: bloc DB_RYTAL_%s_* retiré de .env (institut archivé).', code)
    return True
