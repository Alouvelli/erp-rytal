"""
Commande migrate étendue : applique les migrations sur DEFAULT + toutes les bases
d'institutions (alias commençant par 'db_rytal_') automatiquement.

Avec PostgreSQL, les migrations sont de vraies transactions DDL fiables — plus
besoin des contournements SQLite historiques (désactivation de PRAGMA
foreign_keys, fake automatique sur erreur de contrainte résiduelle) : une
migration qui échoue sur une base tenant est désormais une vraie erreur à
corriger, pas un état à masquer.

Usage identique à la commande standard :
    python manage.py migrate
    python manage.py migrate notifications
    python manage.py migrate timetable 0004
    python manage.py migrate --database=db_rytal_isi   (cible une seule DB)
"""

from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand


def _refresh_tenant_databases():
    """Relit .env et complète settings.DATABASES avec tout alias tenant absent
    — un institut ajouté à .env après le démarrage de CE process (par un autre
    worker, ou par une commande manage.py précédente) n'y figure pas tant que
    personne n'a appelé register_tenant_db/discover_tenant_databases pour lui ;
    sans ce rafraîchissement, `migrate` cascaderait sur un instantané périmé de
    settings.DATABASES et sauterait silencieusement ce tenant (voir
    tenant_databases.py::discover_tenant_databases)."""
    from academic_core.tenant_databases import discover_tenant_databases
    for alias, entry in discover_tenant_databases(settings.BASE_DIR).items():
        settings.DATABASES.setdefault(alias, entry)


def _tenant_aliases():
    _refresh_tenant_databases()
    return [a for a in settings.DATABASES if a.startswith('db_rytal_')]


class Command(MigrateCommand):
    help = (
        "Applique les migrations sur la base DEFAULT et sur toutes les bases "
        "d'institutions (db_rytal_*) connues du process courant."
    )

    def handle(self, *app_labels, **options):
        explicit_db = options.get('database')

        # L'utilisateur cible explicitement une seule base → comportement standard
        if explicit_db and explicit_db != 'default':
            super().handle(*app_labels, **options)
            return

        # 1. Migrer default
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Base : default ==='))
        options['database'] = 'default'
        super().handle(*app_labels, **options)

        # 2. Migrer chaque base tenant déjà connue de ce process (voir
        #    academic_core/tenant_databases.py::discover_tenant_databases —
        #    un institut créé par un autre worker après le démarrage n'apparaît
        #    ici qu'après redémarrage de CE process).
        for alias in _tenant_aliases():
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== Base : {alias} ==='))
            options['database'] = alias
            try:
                super().handle(*app_labels, **options)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  [ERREUR] Migration {alias} : {exc}'))
