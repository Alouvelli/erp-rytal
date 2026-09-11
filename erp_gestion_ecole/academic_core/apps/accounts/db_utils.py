"""
Utilitaires pour la synchronisation multi-tenant des utilisateurs administrateurs.

Problème :
  Les INST_ADMIN / SI_ADMIN sont créés dans la base 'default' par le Super Admin.
  Pour que le routing fonctionne correctement (current_db = db_rytal_xxx après login),
  l'enregistrement utilisateur doit aussi exister dans la base de l'institut.
  Les FK cross-DB (role, institut_config) empêchent un simple ORM save() → on utilise
  du SQL brut, via le pool de connexions Django (connections[alias]), avec les
  triggers de contraintes temporairement désactivés (ALTER TABLE ... DISABLE
  TRIGGER ALL — fonctionne sans superuser car le compte admin est propriétaire
  de toutes les tables qu'il a migrées, voir
  academic_core/apps/academic_structure/pg_provisioning.py).
"""

import logging

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        [table],
    )
    return cursor.fetchone() is not None


# ── Migration automatique ──────────────────────────────────────────────────────

# Colonnes qui doivent exister dans chaque base tenant mais peuvent être manquantes
# à cause de migrations fakées ou de bases créées avant certains AlterField.
# Format : { 'table': [(colonne, définition_SQL), ...] }
_REQUIRED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    'institut_config': [
        ('matricule_prefix', "VARCHAR(10) NOT NULL DEFAULT ''"),
        ('actif',            "BOOLEAN NOT NULL DEFAULT TRUE"),
        ('motif_suspension', "TEXT NOT NULL DEFAULT ''"),
        ('date_suspension',  "DATE NULL"),
        ('db_alias',         "VARCHAR(60) NOT NULL DEFAULT ''"),
    ],
}


def _ensure_required_columns(db_alias: str) -> None:
    """Ajoute silencieusement toute colonne manquante listée dans _REQUIRED_COLUMNS."""
    from django.db import connections
    try:
        with connections[db_alias].cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            existing_tables = {r[0] for r in cur.fetchall()}

            for table, columns in _REQUIRED_COLUMNS.items():
                if table not in existing_tables:
                    continue
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    [table],
                )
                existing_cols = {r[0] for r in cur.fetchall()}
                for col_name, col_def in columns:
                    if col_name not in existing_cols:
                        try:
                            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_def}')
                            logger.info(
                                'Schema tenant %s : colonne %s.%s ajoutée.', db_alias, table, col_name
                            )
                        except Exception as e:
                            if 'already exists' not in str(e).lower():
                                logger.warning('ALTER TABLE %s ADD %s : %s', table, col_name, e)
    except Exception as e:
        logger.warning('_ensure_required_columns(%s): %s', db_alias, e)


def reconcile_roles_from_default(db_alias: str) -> int:
    """
    Remplace intégralement la table `roles` de `db_alias` par son contenu
    dans 'default' (ids inclus) — utilisé UNIQUEMENT juste après le
    provisioning d'un institut tout juste créé (voir
    academic_structure/signals.py::auto_create_institute_db), avant toute
    synchronisation d'utilisateur vers cette base.

    Les migrations RunPython de seed (get_or_create par nom) attribuent des
    ids Postgres dans l'ordre d'exécution des migrations, propre à CETTE
    base — ils ne correspondent pas forcément à ceux de 'default'. Or les
    comptes synchronisés ensuite (sync_user_to_institute_db) copient
    `role_id` tel quel depuis 'default' : sans cette réconciliation, un
    compte peut se retrouver avec le mauvais rôle localement dès sa création
    (même bug que celui corrigé pour la migration des données historiques —
    voir setup_multitenant.py::_reconcile_roles_from_sqlite).

    Ne PAS utiliser sur une base tenant qui contient déjà de vraies données
    utilisateur — utiliser sync_roles_to_institute_db (additif, conservateur)
    dans ce cas.
    """
    from django.conf import settings
    from django.db import connections

    if not db_alias or db_alias == 'default' or db_alias not in settings.DATABASES:
        return 0

    try:
        with connections['default'].cursor() as src_cur:
            src_cur.execute('SELECT id, name, description, created_at FROM roles ORDER BY id')
            rows = src_cur.fetchall()
        if not rows:
            return 0

        with connections[db_alias].cursor() as dst_cur:
            dst_cur.execute('ALTER TABLE "roles" DISABLE TRIGGER ALL')
            try:
                dst_cur.execute('DELETE FROM roles')
                dst_cur.executemany(
                    'INSERT INTO roles (id, name, description, created_at) VALUES (%s, %s, %s, %s)',
                    rows,
                )
            finally:
                dst_cur.execute('ALTER TABLE "roles" ENABLE TRIGGER ALL')

            dst_cur.execute("SELECT pg_get_serial_sequence('roles', 'id')")
            seq = dst_cur.fetchone()[0]
            if seq:
                dst_cur.execute('SELECT MAX(id) FROM roles')
                max_id = dst_cur.fetchone()[0]
                if max_id is not None:
                    dst_cur.execute('SELECT setval(%s, %s)', [seq, max_id])

        logger.info('reconcile_roles_from_default(%s): %d rôle(s) réconciliés', db_alias, len(rows))
        return len(rows)
    except Exception as e:
        logger.warning('reconcile_roles_from_default(%s): %s', db_alias, e)
        return 0


def sync_roles_to_institute_db(db_alias: str) -> int:
    """
    Copie vers la base tenant `db_alias` tout rôle présent dans 'default' mais
    absent localement (par id manquant). Retourne le nombre de rôles copiés.

    Role est un modèle routé par tenant (une ligne par base, voir InstitutRouter :
    'accounts' n'est ni dans MASTER_APP_LABELS ni MASTER_MODEL_NAMES) mais son
    contenu doit être identique partout : les FK cross-DB (User.role_id, copiées
    telles quelles par sync_user_to_institute_db) supposent que les ids
    correspondent d'une base à l'autre. Une base tenant dont les migrations
    RunPython de seed auraient été sautées démarre avec une table `roles`
    vide : la toute première connexion de son administrateur lève alors
    Role.DoesNotExist. Idempotent (ne réinsère jamais un id déjà présent) donc
    peut être appelée à chaque requête sans coût significatif.
    """
    from django.conf import settings
    from django.db import connections

    if not db_alias or db_alias == 'default' or db_alias not in settings.DATABASES:
        return 0

    try:
        with connections[db_alias].cursor() as dst_cur:
            if not _table_exists(dst_cur, 'roles'):
                return 0

            dst_cur.execute('SELECT id, name FROM roles')
            existing = dst_cur.fetchall()
            existing_ids = {r[0] for r in existing}
            existing_names = {r[1] for r in existing}

            with connections['default'].cursor() as src_cur:
                src_cur.execute('SELECT id, name, description, created_at FROM roles')
                rows = src_cur.fetchall()

            missing = [r for r in rows if r[0] not in existing_ids and r[1] not in existing_names]
            skipped = [r for r in rows if r[0] not in existing_ids and r[1] in existing_names]
            if skipped:
                logger.warning(
                    'sync_roles_to_institute_db(%s): %d rôle(s) avec id divergent ignoré(s) : %s',
                    db_alias, len(skipped), [r[1] for r in skipped],
                )

            if missing:
                dst_cur.executemany(
                    'INSERT INTO roles (id, name, description, created_at) VALUES (%s, %s, %s, %s)',
                    missing,
                )
                logger.info(
                    'sync_roles_to_institute_db(%s): %d rôle(s) copié(s) depuis default (%s)',
                    db_alias, len(missing), [r[1] for r in missing],
                )
        return len(missing)
    except Exception as e:
        logger.warning('sync_roles_to_institute_db(%s): %s', db_alias, e)
        return 0


def ensure_institute_db_schema(db_alias: str) -> bool:
    """
    S'assure que le schéma Django est appliqué sur la base `db_alias`.
    Lance `migrate --database <alias>` si la table `users` est absente.
    Retourne True si le schéma est opérationnel.
    """
    from django.conf import settings
    from django.db import connections

    if db_alias == 'default' or db_alias not in settings.DATABASES:
        return False

    try:
        with connections[db_alias].cursor() as cur:
            has_users = _table_exists(cur, 'users')
    except Exception as e:
        logger.warning('ensure_institute_db_schema: connexion échouée sur %s : %s', db_alias, e)
        return False

    if has_users:
        # Vérifier quand même que les colonnes requises existent (migrations déphasées)
        _ensure_required_columns(db_alias)
        # Et que les rôles de référence sont bien présents
        sync_roles_to_institute_db(db_alias)
        return True

    # Lancer les migrations
    logger.info('ensure_institute_db_schema: migration de %s…', db_alias)
    try:
        from django.core.management import call_command
        call_command('migrate', '--database', db_alias, '--run-syncdb', verbosity=0)
        logger.info('ensure_institute_db_schema: migration %s terminée.', db_alias)
        sync_roles_to_institute_db(db_alias)
        return True
    except Exception as e:
        logger.error('ensure_institute_db_schema: migration %s échouée : %s', db_alias, e)
        return False


# ── Synchronisation utilisateur ────────────────────────────────────────────────

def _user_row_values(UserModel, user):
    """Extrait (col_names, values) depuis les local_fields du modèle User."""
    fields = [f for f in UserModel._meta.local_fields]
    col_names = [f.column for f in fields]
    values = []
    for f in fields:
        val = getattr(user, f.attname)  # attname donne role_id, department_id, etc.
        # Pour les ImageField : stocker le name (chemin relatif)
        if hasattr(val, 'name'):
            val = val.name or None
        values.append(val)
    return col_names, values


def sync_user_to_institute_db(user, db_alias: str) -> bool:
    """
    Insère ou met à jour l'utilisateur dans la base de son institut.

    Retourne True si la synchronisation a réussi.
    """
    from django.conf import settings

    if not db_alias or db_alias == 'default':
        return True  # rien à faire

    if db_alias not in settings.DATABASES:
        logger.warning('sync_user_to_institute_db: alias %s inconnu', db_alias)
        return False

    # Garantir que le schéma existe
    if not ensure_institute_db_schema(db_alias):
        return False

    from django.contrib.auth import get_user_model
    from django.db import connections
    UserModel = get_user_model()
    table = UserModel._meta.db_table
    pk_col = UserModel._meta.pk.column

    col_names, values = _user_row_values(UserModel, user)
    placeholders = ', '.join(['%s'] * len(col_names))
    cols_sql = ', '.join(f'"{c}"' for c in col_names)
    update_sql = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in col_names if c != pk_col)

    try:
        with connections[db_alias].cursor() as cur:
            cur.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER ALL')
            try:
                cur.execute(
                    f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders}) '
                    f'ON CONFLICT ("{pk_col}") DO UPDATE SET {update_sql}',
                    values,
                )
            finally:
                cur.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER ALL')
        logger.info('sync_user_to_institute_db: user %s synced → %s', user.username, db_alias)
        return True
    except Exception as e:
        logger.error(
            'sync_user_to_institute_db: échec pour %s → %s : %s',
            user.username, db_alias, e,
        )
        return False


def sync_user_to_default_db(user) -> bool:
    """
    Duplique vers 'default' un utilisateur qui vient d'être créé dans une base
    institut (cas normal : ENSEIGNANT/ETUDIANT/... créés par un admin pendant
    que current_db pointe vers la base de son institut).

    Nécessaire car 'default' est la seule base connue d'AuditLog (FK vers User)
    et login_view écrit toujours last_login_ip dans 'default' : sans copie,
    la toute première connexion de ce compte lève
    "Save with update_fields did not affect any rows".

    Même technique que sync_user_to_institute_db (SQL brut + triggers désactivés)
    car les FK role_id/department_id/direction_id pointent vers des lignes
    qui n'existent pas forcément dans 'default'.
    """
    from django.contrib.auth import get_user_model
    from django.db import connections
    UserModel = get_user_model()
    table = UserModel._meta.db_table
    pk_col = UserModel._meta.pk.column

    col_names, values = _user_row_values(UserModel, user)
    placeholders = ', '.join(['%s'] * len(col_names))
    cols_sql = ', '.join(f'"{c}"' for c in col_names)

    try:
        with connections['default'].cursor() as cur:
            cur.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER ALL')
            try:
                cur.execute(
                    f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders}) '
                    f'ON CONFLICT ("{pk_col}") DO NOTHING',
                    values,
                )
            finally:
                cur.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER ALL')
        logger.info('sync_user_to_default_db: user %s dupliqué vers default', user.username)
        return True
    except Exception as e:
        logger.error('sync_user_to_default_db: échec pour %s : %s', user.username, e)
        return False


def remove_user_from_institute_db(user_pk: int, db_alias: str) -> bool:
    """Supprime l'enregistrement utilisateur de la base de l'institut."""
    from django.conf import settings
    from django.db import connections

    if not db_alias or db_alias == 'default' or db_alias not in settings.DATABASES:
        return False

    from django.contrib.auth import get_user_model
    UserModel = get_user_model()
    table = UserModel._meta.db_table
    pk_col = UserModel._meta.pk.column

    try:
        with connections[db_alias].cursor() as cur:
            cur.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER ALL')
            try:
                cur.execute(f'DELETE FROM "{table}" WHERE "{pk_col}" = %s', [user_pk])
            finally:
                cur.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER ALL')
        logger.info('remove_user_from_institute_db: user pk=%s supprimé de %s', user_pk, db_alias)
        return True
    except Exception as e:
        logger.warning('remove_user_from_institute_db: %s', e)
        return False


def deactivate_user_everywhere(user) -> None:
    """
    Désactive (is_active=False) un compte dans TOUTES les bases où il possède
    une copie (default + base(s) institut) — pas seulement celle où l'appelant
    travaille actuellement.

    Nécessaire car User.save() ne synchronise vers 'default' que le mot de
    passe (voir User.save()), jamais is_active : sans ceci, une copie 'default'
    encore active permettrait à MultiDBAuthBackend.authenticate() (qui parcourt
    toutes les bases) de continuer à authentifier un compte censé être désactivé.
    """
    from django.conf import settings
    from django.contrib.auth import get_user_model
    UserModel = get_user_model()
    for alias in settings.DATABASES:
        try:
            UserModel.objects.using(alias).filter(pk=user.pk, username=user.username).update(is_active=False)
        except Exception as e:
            logger.warning('deactivate_user_everywhere: échec sur %s pour %s : %s', alias, user.username, e)


def delete_user_everywhere(user) -> None:
    """
    Supprime un compte de TOUTES les bases où il possède une copie (default +
    base(s) institut) — même raison que deactivate_user_everywhere : un
    User.delete() simple ne supprime que la copie de la base courante, laissant
    une copie 'default' encore authentifiable.

    Sur les bases institut, un User.objects...delete() classique lève
    "no such table: django_admin_log" : le collecteur de cascade Django
    inspecte TOUTES les relations vers User déclarées dans l'app registry
    (dont django.contrib.admin.LogEntry), y compris sur des bases où cette
    table n'a jamais été migrée (app "master", voir MASTER_APP_LABELS). On
    réutilise donc remove_user_from_institute_db (suppression SQL brute,
    triggers désactivés) pour ces bases, après avoir nettoyé le profil Enseignant
    éventuel (cascade normale, sûre : Teacher n'est référencé par aucune
    table hors-tenant).
    """
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from academic_core.apps.teachers.models import Teacher
    UserModel = get_user_model()
    for alias in settings.DATABASES:
        try:
            Teacher.objects.using(alias).filter(user_id=user.pk).delete()
        except Exception as e:
            logger.warning('delete_user_everywhere: nettoyage profil enseignant échoué sur %s pour %s : %s', alias, user.username, e)
        try:
            if alias == 'default':
                UserModel.objects.using(alias).filter(pk=user.pk, username=user.username).delete()
            else:
                remove_user_from_institute_db(user.pk, alias)
        except Exception as e:
            logger.warning('delete_user_everywhere: échec sur %s pour %s : %s', alias, user.username, e)


def save_user_to_all_dbs(user, update_fields=None) -> None:
    """
    Sauvegarde l'utilisateur dans 'default' (toujours) puis synchronise
    dans la base de son institut si applicable.

    Remplace les appels `user.save()` pour les INST_ADMIN / SI_ADMIN afin
    d'éviter les IntegrityError FK cross-DB quand current_db ≠ default.
    """
    kwargs = {}
    if update_fields:
        kwargs['update_fields'] = update_fields
    user.save(using='default', **kwargs)

    db_alias = get_institute_db_alias(user)
    if db_alias:
        sync_user_to_institute_db(user, db_alias)


def get_institute_db_alias(user) -> str | None:
    """
    Retourne le db_alias de l'institut lié à l'utilisateur, ou None.
    Fonctionne pour INST_ADMIN / SI_ADMIN (via institut_config).
    """
    from django.conf import settings
    try:
        cfg = getattr(user, 'institut_config', None)
        if cfg and cfg.db_alias and cfg.db_alias in settings.DATABASES:
            return cfg.db_alias
    except Exception:
        pass
    return None


def find_existing_user_by_identifier(identifier: str):
    """
    Cherche un compte existant par email OU identifiant (login) dans 'default'
    — la base maître alimentée par le double-écriture de User.save() (voir
    sync_user_to_default_db), seule base qui reflète tous les instituts.

    Sert à transformer le rejet « email/identifiant déjà utilisé » du
    formulaire de création d'utilisateur (accounts/forms.py::UserCreateForm)
    en piste actionnable — retrouver QUI possède déjà ce compte — plutôt
    qu'une simple impasse silencieuse pour l'administrateur.

    Retourne le User (copie 'default') ou None. Ne pas se fier au FK
    `department` de cette copie pour l'affichage : Department est routé par
    tenant, donc `default` ne reflète fidèlement aucun département précis —
    voir accounts/views.py::UserCreateView.form_invalid, qui recharge
    l'utilisateur depuis la base tenant cible quand elle est connue.
    """
    from django.db.models import Q
    from .models import User

    identifier = (identifier or '').strip()
    if not identifier:
        return None
    return User.objects.using('default').filter(
        Q(email__iexact=identifier) | Q(username__iexact=identifier)
    ).select_related('role').first()
