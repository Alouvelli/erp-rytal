"""
Fusionne les CaissePayments du meme etudiant a la meme date en un seul paiement.

Usage :
    python manage.py merge_same_day_payments               # simulation (dry-run)
    python manage.py merge_same_day_payments --apply       # fusion reelle
    python manage.py merge_same_day_payments --database=db_rytal_isi --apply
"""

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction


class Command(BaseCommand):
    help = 'Fusionne les paiements caisse du meme etudiant a la meme date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true', default=False,
            help='Applique la fusion (sans cet argument, simulation uniquement)',
        )
        parser.add_argument(
            '--database', default=None,
            help='Alias de la base a traiter (defaut : toutes les bases db_rytal_*)',
        )

    def handle(self, *args, **options):
        apply   = options['apply']
        db_arg  = options.get('database')

        if db_arg:
            dbs = [db_arg]
        else:
            dbs = [alias for alias in settings.DATABASES if alias.startswith('db_rytal_')]

        if not apply:
            self.stdout.write(self.style.WARNING(
                '[SIMULATION] Aucune modification - relancer avec --apply pour fusionner'
            ))

        for db_alias in dbs:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== {db_alias} ==='))
            self._process_db(db_alias, apply)

    def _process_db(self, db_alias, apply):
        from academic_core.apps.accounting.models import CaissePayment

        MOIS_FR = ['', 'Janvier', 'Fevrier', 'Mars', 'Avril', 'Mai', 'Juin',
                   'Juillet', 'Aout', 'Septembre', 'Octobre', 'Novembre', 'Decembre']

        # Trouver les groupes (student, date) ayant plusieurs paiements
        from django.db.models import Count
        groups = (
            CaissePayment.objects.using(db_alias)
            .values('student_id', 'payment_date')
            .annotate(nb=Count('id'))
            .filter(nb__gt=1)
            .order_by('student_id', 'payment_date')
        )

        if not groups.exists():
            self.stdout.write('  Aucun doublon trouve.')
            return

        total_fusions = 0

        for g in groups:
            payments = list(
                CaissePayment.objects.using(db_alias)
                .select_related('student__user', 'enrollment__class_group')
                .filter(student_id=g['student_id'], payment_date=g['payment_date'])
                .order_by('id')
            )

            # Le paiement maitre : de preference le TYPE_INSCRIPTION, sinon le premier
            master = next((p for p in payments if p.payment_type == CaissePayment.TYPE_INSCRIPTION), payments[0])
            duplicates = [p for p in payments if p.pk != master.pk]

            # Fusionner montants et mois
            total_amount = sum(p.amount for p in payments)

            all_months = set()
            for p in payments:
                for m in (p.payment_months or '').split(','):
                    m = m.strip()
                    if m.isdigit() and 1 <= int(m) <= 12:
                        all_months.add(int(m))
                if p.payment_month and 1 <= p.payment_month <= 12:
                    all_months.add(p.payment_month)

            months_str = ','.join(str(m) for m in sorted(all_months))
            months_label = ', '.join(MOIS_FR[m] for m in sorted(all_months))

            notes_parts = []
            if master.enrollment and master.enrollment.class_group:
                notes_parts.append(f"Frais d'inscription - {master.enrollment.class_group.name}")
            if months_label:
                notes_parts.append(f"Mois payes : {months_label}")
            notes = ' | '.join(notes_parts) if notes_parts else master.notes

            self.stdout.write(
                f'  Fusion : {master.student} [{g["payment_date"]}] '
                f'{len(payments)} paiements -> 1 | ref={master.reference} | '
                f'montant={total_amount} | mois={months_str or "-"}'
            )
            for d in duplicates:
                self.stdout.write(f'    - supprime ref={d.reference} ({d.amount} FCFA)')

            if apply:
                with transaction.atomic(using=db_alias):
                    master.amount         = total_amount
                    master.payment_months = months_str
                    master.notes          = notes
                    master.save(using=db_alias, update_fields=['amount', 'payment_months', 'notes'])

                    # Mettre a jour l'enrollment si besoin
                    if master.enrollment:
                        master.enrollment.payment_reference = master.reference
                        master.enrollment.save(update_fields=['payment_reference'])

                    CaissePayment.objects.using(db_alias).filter(
                        pk__in=[d.pk for d in duplicates]
                    ).delete()

            total_fusions += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'  {total_fusions} groupe(s) {"fusionnes" if apply else "a fusionner"}.'
            )
        )
