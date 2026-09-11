"""
Management command : crée et migre une base PostgreSQL pour un institut.

Usage :
    python manage.py create_institute_db db_rytal_isi
    python manage.py create_institute_db db_rytal_esp
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Crée et migre une base PostgreSQL dédiée à un institut'

    def add_arguments(self, parser):
        parser.add_argument(
            'db_alias',
            type=str,
            help='Alias de la base (ex: db_rytal_isi). Doit commencer par "db_rytal_".',
        )

    def handle(self, *args, **options):
        alias = options['db_alias'].strip()

        if not re.match(r'^db_rytal_[a-z0-9_]+$', alias):
            raise CommandError(
                f'Alias invalide : "{alias}". '
                'Format attendu : db_rytal_<code> (ex: db_rytal_isi)'
            )

        from academic_core.apps.academic_structure.pg_provisioning import create_database
        from academic_core.tenant_databases import register_tenant_db

        if not create_database(alias):
            raise CommandError(f'Échec de la création de la base "{alias}".')
        self.stdout.write(f'  → Base {alias} créée (ou déjà existante)')

        if not register_tenant_db(alias):
            raise CommandError(f'Échec de l\'enregistrement de "{alias}" dans DATABASES.')

        # Lancer les migrations
        self.stdout.write(f'  → Migration en cours sur {alias}...')
        call_command('migrate', database=alias, run_syncdb=True, verbosity=1, interactive=False)

        self.stdout.write(
            self.style.SUCCESS(f'✓ Base {alias} prête')
        )
