"""
Backfill : crée les ContratEnseignant manquants pour les affectations d'EC
(TimetableEntry) déjà existantes avant la mise en place de la fonctionnalité
"Contrat Enseignant". Le signal ne couvre que les affectations futures.

Usage : python manage.py backfill_contrats
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from academic_core.db_router import set_current_db


class Command(BaseCommand):
    help = "Crée les ContratEnseignant manquants pour toutes les affectations d'EC existantes, sur chaque base institut."

    def handle(self, *args, **options):
        from academic_core.apps.teachers.models import Teacher
        from academic_core.apps.teachers.services import sync_contracts_for_teacher

        aliases = [a for a in settings.DATABASES if a.startswith('db_rytal_')]
        if not aliases:
            self.stdout.write(self.style.WARNING("Aucune base institut trouvée dans settings.DATABASES."))
            return

        total_created = 0
        for alias in aliases:
            set_current_db(alias)
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== Base : {alias} ==='))
            count = 0
            for teacher in Teacher.objects.using(alias).all():
                created = sync_contracts_for_teacher(teacher)
                count += len(created)
            self.stdout.write(f'  {count} contrat(s) assuré(s) présent(s).')
            total_created += count

        set_current_db('default')
        self.stdout.write(self.style.SUCCESS(f'\nTerminé — {total_created} contrat(s) au total.'))
