from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# Colonnes requises par table pour la base accounting sur les bases tenant.
# Format : { 'table': [(colonne, définition_SQL), ...] }
REQUIRED_TENANT_COLUMNS = {
    'caisse_payments': [
        ('enrollment_id', 'INTEGER REFERENCES enrollments(id)'),
    ],
    'enrollments': [
        ('advance_months', "VARCHAR(100) NOT NULL DEFAULT ''"),
    ],
}


def ensure_tenant_schema(db_alias: str) -> None:
    """
    Vérifie que toutes les colonnes requises existent dans la base tenant `db_alias`.
    Ajoute silencieusement les colonnes manquantes via ALTER TABLE.
    """
    import logging
    from django.conf import settings
    from django.db import connections

    logger = logging.getLogger(__name__)

    if db_alias not in settings.DATABASES or db_alias == 'default':
        return

    try:
        with connections[db_alias].cursor() as cur:
            # Lister les tables existantes
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            existing_tables = {row[0] for row in cur.fetchall()}

            for table, columns in REQUIRED_TENANT_COLUMNS.items():
                if table not in existing_tables:
                    continue
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    [table],
                )
                existing_cols = {row[0] for row in cur.fetchall()}
                for col_name, col_def in columns:
                    if col_name not in existing_cols:
                        try:
                            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_def}')
                            logger.info(
                                'Schema tenant %s : colonne %s.%s ajoutée automatiquement.',
                                db_alias, table, col_name,
                            )
                        except Exception as exc:
                            if 'already exists' not in str(exc).lower():
                                logger.warning(
                                    'Schema tenant %s : ALTER TABLE %s ADD %s échoué : %s',
                                    db_alias, table, col_name, exc,
                                )
    except Exception as exc:
        logger.warning('ensure_tenant_schema(%s) : %s', db_alias, exc)


def sync_all_tenant_schemas() -> None:
    """Parcourt toutes les bases tenant connues et corrige le schéma si nécessaire."""
    from django.conf import settings
    for alias in list(settings.DATABASES.keys()):
        if alias == 'default':
            continue
        ensure_tenant_schema(alias)


class AccountingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academic_core.apps.accounting'
    verbose_name = _('Direction Administrative Financière')

    def ready(self):
        # Synchroniser les schémas tenant au démarrage du serveur
        try:
            sync_all_tenant_schemas()
        except Exception:
            pass  # Ne jamais bloquer le démarrage
