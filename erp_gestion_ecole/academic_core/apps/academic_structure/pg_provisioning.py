"""
Provisioning des bases PostgreSQL par institut.

Toutes les opérations (création, vérification d'existence, archivage par
renommage) passent par le même compte administrateur PostgreSQL que la base
'default' (POSTGRES_* dans .env) — un seul compte gère toutes les bases,
actuelles et futures, sur le même serveur (voir academic_core/tenant_databases.py
pour l'enregistrement de ces bases dans settings.DATABASES).
"""

import logging
import re

import psycopg2
from decouple import config

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _assert_safe_identifier(name: str) -> None:
    """
    CREATE DATABASE / ALTER DATABASE ne supportent pas les identifiants
    paramétrés (contrairement aux valeurs) : ce garde-fou empêche toute
    interpolation d'un identifiant SQL non maîtrisé, même si `name` provient
    en pratique toujours d'un code institut slugifié (voir
    signals.py::_slugify_code), jamais d'une entrée utilisateur libre.
    """
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f'Identifiant SQL invalide : {name!r}')


def _admin_connection(dbname: str | None = None):
    """
    Connexion psycopg2 directe (hors pool Django) au compte admin, sur la base
    de maintenance par défaut — nécessaire pour CREATE DATABASE / ALTER DATABASE,
    qui ne peuvent pas s'exécuter à l'intérieur d'une transaction.
    """
    conn = psycopg2.connect(
        host=config('POSTGRES_HOST', default='localhost'),
        port=config('POSTGRES_PORT', default='5432'),
        user=config('POSTGRES_USER', default='postgres'),
        password=config('POSTGRES_PASSWORD', default=''),
        dbname=dbname or config('POSTGRES_MAINTENANCE_DB', default='postgres'),
        connect_timeout=10,
    )
    conn.autocommit = True
    return conn


def database_exists(db_name: str) -> bool:
    conn = None
    try:
        conn = _admin_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', [db_name])
            return cur.fetchone() is not None
    except Exception as exc:
        logger.warning('database_exists(%s): %s', db_name, exc)
        return False
    finally:
        if conn:
            conn.close()


def create_database(db_name: str, owner: str | None = None) -> bool:
    """
    Crée la base `db_name` si elle n'existe pas déjà. Retourne True si la base
    est prête à l'usage (créée à l'instant ou déjà existante), False en cas
    d'échec de connexion/création.
    """
    if database_exists(db_name):
        return True

    owner = owner or config('POSTGRES_USER', default='postgres')
    _assert_safe_identifier(db_name)
    _assert_safe_identifier(owner)

    conn = None
    try:
        conn = _admin_connection()
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{owner}" ENCODING \'UTF8\'')
        logger.info('create_database: base %s créée (owner=%s)', db_name, owner)
        return True
    except Exception as exc:
        logger.error('create_database(%s): %s', db_name, exc)
        return False
    finally:
        if conn:
            conn.close()


def terminate_connections(db_name: str) -> None:
    """Coupe toute connexion active à `db_name` (préalable requis à un RENAME)."""
    conn = None
    try:
        conn = _admin_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [db_name],
            )
    except Exception as exc:
        logger.warning('terminate_connections(%s): %s', db_name, exc)
    finally:
        if conn:
            conn.close()


def drop_database(db_name: str) -> bool:
    """
    Supprime définitivement et irréversiblement `db_name` — utilisé uniquement
    pour la suppression permanente d'une base déjà archivée (voir
    accounts/views.py::institut_archive_delete_permanent, protégé par le code
    d'activation de la plateforme). Termine d'abord toute connexion active.
    """
    _assert_safe_identifier(db_name)

    if not database_exists(db_name):
        return True

    terminate_connections(db_name)

    conn = None
    try:
        conn = _admin_connection()
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE "{db_name}"')
        logger.info('drop_database: %s supprimée définitivement', db_name)
        return True
    except Exception as exc:
        logger.error('drop_database(%s): %s', db_name, exc)
        return False
    finally:
        if conn:
            conn.close()


def rename_database(old_name: str, new_name: str) -> bool:
    """
    Renomme la base `old_name` en `new_name` — utilisé pour archiver un institut
    supprimé sans jamais perdre ses données (voir
    academic_structure/utils.py::archive_institut_db). Termine d'abord toute
    connexion active, un RENAME DATABASE échouant sinon avec "database is being
    accessed by other users".
    """
    _assert_safe_identifier(old_name)
    _assert_safe_identifier(new_name)

    terminate_connections(old_name)

    conn = None
    try:
        conn = _admin_connection()
        with conn.cursor() as cur:
            cur.execute(f'ALTER DATABASE "{old_name}" RENAME TO "{new_name}"')
        logger.info('rename_database: %s -> %s', old_name, new_name)
        return True
    except Exception as exc:
        logger.error('rename_database(%s -> %s): %s', old_name, new_name, exc)
        return False
    finally:
        if conn:
            conn.close()
