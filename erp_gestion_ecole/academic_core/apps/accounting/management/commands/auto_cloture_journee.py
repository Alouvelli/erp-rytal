from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from academic_core.apps.accounting.models import AccountingClosure, CaissePayment
from academic_core.apps.academic_structure.models import AcademicYear
from academic_core.apps.students.models import Enrollment, PaymentInstallment, Student


class Command(BaseCommand):
    help = "Clôture automatique de la journée comptable (à lancer à 20h30 par le planificateur)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='',
            help="Date à clôturer au format YYYY-MM-DD (défaut : aujourd'hui)",
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help="Force la clôture même si elle a déjà été effectuée",
        )

    def handle(self, *args, **options):
        from datetime import datetime

        date_str = options.get('date', '')
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            target_date = date.today()

        if AccountingClosure.objects.filter(closure_date=target_date).exists():
            if not options.get('force'):
                self.stdout.write(self.style.WARNING(
                    f"La journée du {target_date.strftime('%d/%m/%Y')} est déjà clôturée. "
                    "Utilisez --force pour forcer."
                ))
                return
            AccountingClosure.objects.filter(closure_date=target_date).delete()
            self.stdout.write(self.style.WARNING("Clôture existante supprimée (--force)."))

        # Paiements d'inscription (ancien flux Enrollment)
        payments = Enrollment.objects.filter(
            payment_date=target_date, status=Enrollment.STATUS_VALIDATED
        )
        total_inscription = sum(e.payment_amount or 0 for e in payments)

        # Mensualités (ancien flux PaymentInstallment)
        installments = PaymentInstallment.objects.filter(paid_date=target_date, is_paid=True)
        total_mensualites = sum(i.amount_paid or 0 for i in installments)

        # Paiements caisse
        caisse = CaissePayment.objects.filter(payment_date=target_date)
        total_caisse_inscription = sum(
            c.amount or 0 for c in caisse.filter(payment_type=CaissePayment.TYPE_INSCRIPTION)
        )
        total_caisse_scolarite = sum(
            c.amount or 0 for c in caisse.filter(
                payment_type__in=[CaissePayment.TYPE_SCOLARITE, CaissePayment.TYPE_SOUTENANCE]
            )
        )

        total_collected = total_inscription + total_caisse_inscription
        total_installments_total = total_mensualites + total_caisse_scolarite

        nb_validated = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED).count()
        nb_pending   = Enrollment.objects.filter(status=Enrollment.STATUS_PENDING).count()
        nb_rejected  = Enrollment.objects.filter(status=Enrollment.STATUS_REJECTED).count()
        nb_suspended = Student.objects.filter(payment_suspended=True).count()
        total_remaining = sum(
            (e.remaining_amount or 0)
            for e in Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED)
        )

        current_year = AcademicYear.objects.filter(is_current=True).first()

        AccountingClosure.objects.create(
            closure_date=target_date,
            academic_year=current_year,
            nb_validated=nb_validated,
            nb_pending=nb_pending,
            nb_rejected=nb_rejected,
            nb_suspended=nb_suspended,
            total_collected=Decimal(str(total_collected)),
            total_installments=Decimal(str(total_installments_total)),
            total_remaining=Decimal(str(total_remaining)),
            notes="Clôture automatique (20h30)",
            closed_by=None,
        )

        self.stdout.write(self.style.SUCCESS(
            f"[{target_date.strftime('%d/%m/%Y')}] Clôture automatique effectuée — "
            f"Inscriptions: {total_collected} FCFA | Mensualités: {total_installments_total} FCFA"
        ))
