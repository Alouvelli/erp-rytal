"""Tâches Celery pour le module émargement."""
from celery import shared_task
from datetime import date, timedelta, datetime
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def generate_daily_sheets(self):
    """
    Génère automatiquement les fiches d'émargement pour les séances du jour.
    Exécutée chaque matin à 5h00.
    """
    from .models import AttendanceSheet
    from academic_core.apps.timetable.models import TimetableEntry
    from academic_core.apps.academic_structure.models import Semester

    today       = date.today()
    day_of_week = today.isoweekday()  # 1=Mon … 7=Sun

    active_semesters = Semester.objects.filter(
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    )
    entries = TimetableEntry.objects.filter(
        semester__in=active_semesters,
        day_of_week=day_of_week,
        is_active=True,
    )

    created = 0
    for entry in entries:
        _, was_created = AttendanceSheet.objects.get_or_create(
            timetable_entry=entry,
            session_date=today,
        )
        if was_created:
            created += 1

    logger.info(f"generate_daily_sheets: {created} fiches créées pour le {today}")
    return {'created': created, 'date': str(today)}


@shared_task(bind=True)
def check_absence_alerts(self):
    """
    Envoie des alertes pour les étudiants ayant un taux d'absence >= 20%.
    Exécutée chaque lundi à 8h.
    """
    from .models import StudentAttendance, AttendanceSheet
    from academic_core.apps.students.models import Enrollment
    from academic_core.apps.academic_structure.models import Semester
    from academic_core.apps.notifications.utils import notify_users

    active_sem = Semester.objects.filter(is_active=True).first()
    if not active_sem:
        return {'alerts': 0}

    enrollments = Enrollment.objects.filter(
        academic_year=active_sem.academic_year,
        is_active=True,
    ).select_related('student__user', 'class_group')

    alerts = 0
    for enr in enrollments:
        student = enr.student
        sheets  = AttendanceSheet.objects.filter(
            timetable_entry__class_group=enr.class_group,
            timetable_entry__semester=active_sem,
        )
        total   = StudentAttendance.objects.filter(
            student=student, attendance_sheet__in=sheets
        ).count()
        absents = StudentAttendance.objects.filter(
            student=student, attendance_sheet__in=sheets,
            status='ABSENT',
        ).count()

        if total > 0 and (absents / total) >= 0.20:
            taux = round(absents / total * 100, 1)
            notify_users(
                recipients=[student.user],
                notification_type='ABSENCE',
                title="Alerte : taux d'absence élevé",
                message=f"Votre taux d'absence est de {taux}% ({absents}/{total} séances). "
                        f"Veuillez régulariser votre situation.",
                priority='HIGH',
            )
            alerts += 1

    logger.info(f"check_absence_alerts: {alerts} alertes envoyées")
    return {'alerts': alerts}


@shared_task(bind=True)
def check_student_absence_alerts_task(self):
    """
    Envoie les alertes email (tuteur + chef de département + assistante)
    aux étudiants ayant dépassé le seuil d'absences configuré par leur
    département (voir attendance/services.py::check_student_absence_alerts).
    Exécutée chaque jour à 7h00 — plus réactif que la vérification
    hebdomadaire de check_absence_alerts (taux d'absence, destinataire
    différent), avec laquelle elle coexiste sans redondance fonctionnelle.
    """
    from .services import check_student_absence_alerts

    result = check_student_absence_alerts()
    logger.info(f"check_student_absence_alerts_task: {result['alerts']} alerte(s) envoyée(s)")
    return result


@shared_task(bind=True)
def remind_unsigned_sheets(self):
    """Rappelle aux enseignants leurs fiches non signées du jour."""
    from .models import AttendanceSheet
    from academic_core.apps.notifications.utils import notify_users

    today    = date.today()
    unsigned = AttendanceSheet.objects.filter(
        session_date=today,
        status='PENDING',
    ).select_related('timetable_entry__teacher__user')

    teachers_notified = set()
    for sheet in unsigned:
        teacher_user = sheet.timetable_entry.teacher.user
        if teacher_user.id not in teachers_notified:
            notify_users(
                recipients=[teacher_user],
                notification_type='SHEET_VALIDATED',
                title="Rappel : émargement non signé",
                message=f"Vous avez {unsigned.filter(timetable_entry__teacher__user=teacher_user).count()} "
                        f"fiche(s) d'émargement non signée(s) pour aujourd'hui.",
                link="/attendance/",
                priority='MEDIUM',
            )
            teachers_notified.add(teacher_user.id)

    logger.info(f"remind_unsigned_sheets: {len(teachers_notified)} enseignant(s) rappelé(s)")
    return {'reminded': len(teachers_notified)}


@shared_task(bind=True)
def auto_mark_absent_after_session(self):
    """
    Toutes les 5 minutes : parcourt les fiches dont la séance est terminée
    (session_date + end_time < now) et marque Absent/Absente tous les inscrits
    qui n'ont pas encore de pointage.
    Une fiche est traitée au plus une fois grâce au flag absent_auto_done.
    """
    from django.utils import timezone as tz
    from .models import AttendanceSheet, StudentAttendance
    from academic_core.apps.students.models import Student, Enrollment

    now   = tz.now()
    today = now.date()

    # Fiches d'aujourd'hui ou plus anciennes, pas encore auto-traitées, pas validées
    sheets = (
        AttendanceSheet.objects
        .filter(session_date__lte=today, absent_auto_done=False)
        .exclude(status=AttendanceSheet.STATUS_VALIDATED)
        .select_related('timetable_entry__class_group', 'timetable_entry__semester__academic_year')
    )

    processed = 0
    for sheet in sheets:
        entry    = sheet.timetable_entry
        # Construire la datetime de fin de séance (aware)
        session_end = tz.make_aware(
            datetime.combine(sheet.session_date, entry.end_time)
        )
        if now < session_end:
            continue  # séance pas encore terminée

        # Marquer les absents
        enrolled = (
            Student.objects
            .filter(
                enrollments__class_group=entry.class_group,
                enrollments__academic_year=entry.semester.academic_year,
                enrollments__status=Enrollment.STATUS_VALIDATED,
            )
            .select_related('user')
            .distinct()
        )
        already_marked = set(
            StudentAttendance.objects.filter(attendance_sheet=sheet)
            .values_list('student_id', flat=True)
        )
        to_create = []
        for student in enrolled:
            if student.pk not in already_marked:
                genre = getattr(student, 'gender', None) or getattr(student.user, 'gender', None)
                if genre and str(genre).upper() in ('F', 'FEMALE', 'FEMININ', 'FÉMININ'):
                    comment = 'Absente (fin de séance)'
                else:
                    comment = 'Absent (fin de séance)'
                to_create.append(StudentAttendance(
                    attendance_sheet=sheet,
                    student=student,
                    status=StudentAttendance.STATUS_ABSENT,
                    comment=comment,
                ))
        if to_create:
            StudentAttendance.objects.bulk_create(to_create, ignore_conflicts=True)

        sheet.absent_auto_done = True
        sheet.save(update_fields=['absent_auto_done'])
        processed += 1

    logger.info(f"auto_mark_absent_after_session: {processed} fiche(s) traitée(s)")
    return {'processed': processed}
