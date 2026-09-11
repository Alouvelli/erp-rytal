"""
Corrige rétroactivement les mensualités des étudiants boursiers pour qu'elles
reflètent automatiquement leur pourcentage de bourse (Enrollment.bourse_pourcentage),
au lieu de la mensualité pleine de la classe/niveau à laquelle certaines
inscriptions étaient retombées faute de calcul automatique (voir
_apply_boursier_discount dans academic_core/apps/accounting/views.py).

Ne touche JAMAIS une échéance déjà payée (PaymentInstallment.is_paid=True) —
seuls les mois futurs non encore encaissés sont recalculés.

Usage :
    python manage.py recompute_boursier_mensualites --dry-run
    python manage.py recompute_boursier_mensualites
    python manage.py recompute_boursier_mensualites --database db_rytal_isi
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Recalcule les mensualités futures non payées des étudiants boursiers "
        "à partir de leur pourcentage de bourse (bourse_pourcentage)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--database', type=str, default='',
            help="Limiter à une seule base (ex: db_rytal_isi). Par défaut : default + toutes les bases db_rytal_*.",
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="N'écrit rien, affiche seulement ce qui serait changé.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        only_db = options['database'].strip()

        if only_db:
            aliases = [only_db]
        else:
            aliases = ['default'] + sorted(
                a for a in settings.DATABASES if a.startswith('db_rytal_')
            )

        grand_total_enr = 0
        grand_total_inst = 0

        for alias in aliases:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== Base : {alias} ==='))
            try:
                nb_enr, nb_inst = self._process_db(alias, dry_run)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  [ERREUR] {alias} : {exc}'))
                continue
            grand_total_enr += nb_enr
            grand_total_inst += nb_inst

        verb = "seraient recalculées" if dry_run else "recalculées"
        self.stdout.write(self.style.SUCCESS(
            f"\n{grand_total_inst} échéance(s) non payée(s) sur {grand_total_enr} "
            f"inscription(s) boursier(s) {verb}."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("(--dry-run : aucune écriture effectuée)"))

    def _process_db(self, alias, dry_run):
        from academic_core.apps.students.models import Enrollment, PaymentInstallment
        from academic_core.apps.accounting.models import FraisGenerauxNiveau
        from academic_core.apps.accounting.views import _apply_boursier_discount

        def _resolve_full_fee(enr):
            try:
                full = enr.class_group.frais_mensuel_config.frais_mensuel
                if full is not None:
                    return full
            except Exception:
                pass
            try:
                return FraisGenerauxNiveau.objects.using(alias).get(level=enr.class_group.level).frais_mensuel
            except Exception:
                return None

        enrollments = (
            Enrollment.objects.using(alias)
            .filter(student__is_boursier=True, bourse_pourcentage__isnull=False)
            .select_related('student__user', 'class_group__level', 'class_group__frais_mensuel_config')
        )

        nb_enr_touched = 0
        nb_inst_touched = 0

        with transaction.atomic(using=alias):
            for enr in enrollments:
                full_fee = _resolve_full_fee(enr)
                if full_fee is None:
                    continue
                reduced = _apply_boursier_discount(enr, full_fee)
                if reduced is None:
                    continue

                unpaid = list(
                    PaymentInstallment.objects.using(alias).filter(enrollment=enr, is_paid=False)
                )
                changed_here = [inst for inst in unpaid if inst.amount_expected != reduced]

                if not changed_here and enr.monthly_installment == reduced:
                    continue

                nb_enr_touched += 1
                self.stdout.write(
                    f"  {enr.student.user.get_full_name()} ({enr.student.matricule}) - "
                    f"{enr.class_group.name} : {len(changed_here)} echeance(s) "
                    f"{enr.monthly_installment or '(vide)'} -> {reduced}"
                )

                if not dry_run:
                    for inst in changed_here:
                        inst.amount_expected = reduced
                        inst.save(update_fields=['amount_expected'])
                    if enr.monthly_installment != reduced:
                        enr.monthly_installment = reduced
                        enr.save(update_fields=['monthly_installment'])

                nb_inst_touched += len(changed_here)

            if dry_run:
                transaction.set_rollback(True, using=alias)

        return nb_enr_touched, nb_inst_touched
