"""
Tâches Celery pour la gestion des paiements de scolarité.

Règle métier :
  - Les étudiants doivent régler leur mensualité avant le 10 de chaque mois.
  - À partir du 11 (jour > 10), si la mensualité du mois courant est impayée,
    le compte est automatiquement suspendu (user.is_active = False).
  - Dès que le paiement est enregistré, le compte est réactivé immédiatement.
"""
from celery import shared_task
from datetime import date
import logging

logger = logging.getLogger(__name__)


@shared_task(name='academic_core.apps.students.tasks.check_tuition_deadlines')
def check_tuition_deadlines():
    """
    Tâche quotidienne :
      1. Suspendre les étudiants dont la mensualité du mois est impayée au-delà du 10.
      2. Réactiver les étudiants dont toutes les mensualités dues sont réglées.
    """
    today = date.today()
    from .models import Student, PaymentInstallment, Enrollment

    suspended_count = 0
    reactivated_count = 0

    # ── Cas 1 : après le 10 du mois → suspendre les impayés ────────────────
    if today.day > 10:
        overdue = PaymentInstallment.objects.filter(
            due_date__year=today.year,
            due_date__month=today.month,
            is_paid=False,
            enrollment__status=Enrollment.STATUS_VALIDATED,
            enrollment__is_active=True,
        ).select_related('enrollment__student__user')

        for inst in overdue:
            student = inst.enrollment.student
            user    = student.user
            if user.is_active and not student.payment_suspended:
                user.is_active          = False
                student.payment_suspended = True
                student.suspension_date   = today
                user.save(update_fields=['is_active'])
                student.save(update_fields=['payment_suspended', 'suspension_date'])
                suspended_count += 1
                logger.info(
                    "Compte suspendu (impayé mois %s/%s) : %s",
                    today.month, today.year, student.matricule,
                )

    # ── Cas 2 : réactiver les étudiants suspendus qui ont tout réglé ───────
    suspended_students = Student.objects.filter(
        payment_suspended=True,
    ).select_related('user')

    for student in suspended_students:
        # Vérifie qu'il n'existe aucune mensualité passée impayée
        has_overdue = PaymentInstallment.objects.filter(
            enrollment__student=student,
            enrollment__status=Enrollment.STATUS_VALIDATED,
            is_paid=False,
            due_date__lte=today,
        ).exists()

        if not has_overdue:
            user                    = student.user
            user.is_active          = True
            student.payment_suspended = False
            student.suspension_date   = None
            user.save(update_fields=['is_active'])
            student.save(update_fields=['payment_suspended', 'suspension_date'])
            reactivated_count += 1
            logger.info("Compte réactivé : %s", student.matricule)

    logger.info(
        "Vérification mensualités : %d suspendu(s), %d réactivé(s)",
        suspended_count, reactivated_count,
    )
    return {'suspended': suspended_count, 'reactivated': reactivated_count}
