import re
import random
from decimal import Decimal
from academic_core.apps.notifications.utils import notify_users, send_branded_email


def check_subject_progress(sheet):
    """
    Mise à jour du suivi de progression de la matière après validation d'une fiche.
    Envoie les notifications à 60% (devoir) et 90% (examen).
    """
    from .models import SubjectProgress

    entry = sheet.timetable_entry
    subject = entry.subject
    class_group = entry.class_group
    academic_year = entry.semester.academic_year
    teacher = entry.teacher

    if not subject.volume_hours or subject.volume_hours <= 0:
        return None

    progress, _ = SubjectProgress.objects.get_or_create(
        subject=subject,
        class_group=class_group,
        academic_year=academic_year,
        defaults={'teacher': teacher, 'hours_done': Decimal('0')},
    )

    duration = Decimal(str(entry.duration_hours))
    progress.hours_done += duration
    if not progress.teacher:
        progress.teacher = teacher

    pct = progress.percent_done

    if pct >= 60 and not progress.notified_60:
        notify_users(
            recipients=[teacher.user],
            notification_type='EVAL_DEVOIR',
            title=f"Programmez un devoir — {subject.title}",
            message=(
                f"Vous avez effectué {progress.hours_done}h sur {progress.volume_total}h "
                f"({pct}%) en {subject.title} pour {class_group}. "
                f"Il est recommandé de programmer un devoir."
            ),
            priority='MEDIUM',
        )
        progress.notified_60 = True

    if pct >= 90 and not progress.notified_90:
        notify_users(
            recipients=[teacher.user],
            notification_type='EVAL_EXAMEN',
            title=f"Programmez un examen — {subject.title}",
            message=(
                f"Vous avez effectué {progress.hours_done}h sur {progress.volume_total}h "
                f"({pct}%) en {subject.title} pour {class_group}. "
                f"Il vous reste moins de 10% du volume horaire. Programmez l'examen final."
            ),
            priority='HIGH',
        )
        progress.notified_90 = True

    if progress.is_complete:
        notify_users(
            recipients=[teacher.user],
            notification_type='VOL_COMPLETE',
            title=f"Volume horaire atteint — {subject.title}",
            message=(
                f"Vous avez atteint 100% du volume horaire de {subject.title} "
                f"pour {class_group} ({progress.hours_done}h / {progress.volume_total}h). "
                f"Vous ne pouvez plus émarger pour ce module (EC). "
                f"Si nécessaire, vous pouvez faire une demande de séances supplémentaires."
            ),
            priority='HIGH',
            link=f"/attendance/extra-request/create/?subject={subject.pk}&class={class_group.pk}&year={academic_year.pk}",
        )

    progress.save()
    return progress


def can_sign_sheet(sheet):
    """
    Vérifie si l'enseignant peut encore émarger pour cette matière/classe.
    Retourne (True, None) si OK, (False, message) si bloqué.
    """
    from .models import SubjectProgress

    entry = sheet.timetable_entry
    subject = entry.subject

    if not subject.volume_hours or subject.volume_hours <= 0:
        return True, None

    try:
        progress = SubjectProgress.objects.get(
            subject=subject,
            class_group=entry.class_group,
            academic_year=entry.semester.academic_year,
        )
    except SubjectProgress.DoesNotExist:
        return True, None

    if progress.is_complete:
        return False, (
            f"Le volume horaire de {subject.title} pour {entry.class_group} est atteint "
            f"({progress.hours_done}h / {progress.volume_total}h). "
            f"Vous pouvez faire une demande de séances supplémentaires à l'administrateur du département."
        )
    return True, None


def check_student_absence_alerts():
    """
    Parcourt les inscriptions validées du semestre actif, compte les absences
    NON justifiées (STATUS_ABSENT uniquement — une absence déjà justifiée
    n'a pas à être « expliquée » par le tuteur) de chaque étudiant sur ce
    semestre, et si ce compte dépasse le seuil configuré par le département
    (AbsenceAlertConfig, 10 par défaut) :
      - envoie un email au tuteur (Student.guardian_email) lui demandant les
        raisons des absences répétées, via send_branded_email (pas de compte
        User pour un tuteur) ;
      - notifie (in-app + email) le chef de département et son assistante
        via notify_users.
    Dédoublonné par (student, semester) via StudentAbsenceAlert : une seule
    alerte est envoyée par étudiant par semestre, même si le compteur
    continue d'augmenter après le franchissement du seuil.

    Retourne {'alerts': n, 'semester': str|None}.
    """
    from academic_core.apps.students.models import Enrollment
    from academic_core.apps.academic_structure.models import Semester

    active_sem = Semester.objects.filter(is_active=True).select_related('academic_year').first()
    if not active_sem:
        return {'alerts': 0, 'semester': None}

    enrollments = (
        Enrollment.objects
        .filter(academic_year=active_sem.academic_year, status=Enrollment.STATUS_VALIDATED)
        .select_related('student__user', 'class_group__program__department')
    )

    alerts_sent = 0
    for enr in enrollments:
        # Un étudiant dont les données posent problème (département manquant,
        # erreur d'envoi, etc.) ne doit jamais interrompre le traitement de
        # tous les autres étudiants de l'institut pour cette exécution —
        # on isole chaque itération et on continue la suivante en cas d'échec.
        try:
            if _check_one_student_absence_alert(enr, active_sem):
                alerts_sent += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                f"check_student_absence_alerts: échec pour l'étudiant {enr.student_id}, on continue."
            )

    return {'alerts': alerts_sent, 'semester': str(active_sem)}


def _check_one_student_absence_alert(enr, active_sem):
    """
    Traite un seul étudiant pour check_student_absence_alerts — isolé dans sa
    propre fonction pour qu'une exception sur un étudiant n'interrompe pas le
    traitement des autres (voir la boucle appelante). Retourne True si une
    alerte a été créée pour cet étudiant, False sinon.
    """
    from .models import StudentAttendance, AbsenceAlertConfig, StudentAbsenceAlert
    from academic_core.apps.accounts.models import User, Role

    student = enr.student
    department = getattr(getattr(enr.class_group, 'program', None), 'department', None)
    if not department:
        return False

    already_alerted = StudentAbsenceAlert.objects.filter(
        student=student, semester=active_sem
    ).exists()
    if already_alerted:
        return False

    seuil = AbsenceAlertConfig.get_seuil(department)

    absences = StudentAttendance.objects.filter(
        student=student,
        status=StudentAttendance.STATUS_ABSENT,
        attendance_sheet__timetable_entry__class_group=enr.class_group,
        attendance_sheet__timetable_entry__semester=active_sem,
    ).count()

    if absences < seuil:
        return False

    guardian_email_sent = False
    if student.guardian_email:
        guardian_name = (
            f"{student.guardian_first_name} {student.guardian_last_name}".strip()
            or "Cher tuteur / Chère tutrice"
        )
        send_branded_email(
            to_email=student.guardian_email,
            subject=f"Alerte absences — {student.full_name}",
            heading="Absences répétées à signaler",
            paragraphs=[
                f"Bonjour {guardian_name},",
                f"Nous vous informons que l'étudiant(e) {student.full_name} "
                f"({student.matricule or 'sans matricule'}), inscrit(e) en classe "
                f"{enr.class_group.name}, a accumulé {absences} séance(s) d'absence "
                f"pour le semestre {active_sem} — un nombre jugé préoccupant.",
                "Nous vous serions reconnaissants de bien vouloir nous communiquer "
                "les raisons de ces absences répétées, et de sensibiliser l'étudiant(e) "
                "à l'importance de l'assiduité aux cours.",
                "Pour toute question, veuillez contacter l'administration du département.",
            ],
            fallback_text=(
                f"L'étudiant(e) {student.full_name} a accumulé {absences} absences "
                f"pour le semestre {active_sem}. Merci de nous communiquer les raisons."
            ),
        )
        guardian_email_sent = True

    dept_recipients = list(
        User.objects.filter(
            role__name__in=[Role.RESPONSABLE, Role.ASSISTANTE],
            department=department,
            is_active=True,
        ).distinct()
    )
    if dept_recipients:
        notify_users(
            recipients=dept_recipients,
            notification_type='ABSENCE',
            title=f"Absences préoccupantes — {student.full_name}",
            message=(
                f"L'étudiant(e) {student.full_name} ({student.matricule or 'sans matricule'}) "
                f"de la classe {enr.class_group.name} a accumulé {absences} séance(s) "
                f"d'absence pour le semestre {active_sem} (seuil configuré : {seuil}). "
                f"Le tuteur a été informé et invité à en indiquer les raisons."
            ),
            priority='HIGH',
            send_email=True,
            email_heading="Absences préoccupantes à surveiller",
            email_paragraphs=[
                f"L'étudiant(e) {student.full_name} ({student.matricule or 'sans matricule'}), "
                f"classe {enr.class_group.name}, a accumulé {absences} séance(s) d'absence "
                f"pour le semestre {active_sem} — au-delà du seuil configuré ({seuil}).",
                "Un email a été envoyé au tuteur pour lui demander les raisons de ces "
                "absences répétées." if guardian_email_sent else
                "Aucun email tuteur n'a pu être envoyé (adresse tuteur manquante) — "
                "merci de contacter la famille directement.",
            ],
        )

    StudentAbsenceAlert.objects.create(
        student=student,
        semester=active_sem,
        department=department,
        absence_count=absences,
        threshold_used=seuil,
        guardian_email_sent=guardian_email_sent,
    )
    return True


# ---------------------------------------------------------------------------
# Plan de cours (syllabus) & conformité
# ---------------------------------------------------------------------------

_FR_STOPWORDS = {
    'dans', 'pour', 'avec', 'sans', 'sur', 'sous', 'entre', 'chez', 'vers',
    'les', 'des', 'une', 'un', 'du', 'de', 'la', 'le', 'et', 'ou', 'au', 'aux',
    'ces', 'cette', 'cet', 'son', 'sa', 'ses', 'leur', 'leurs', 'notre', 'nos',
    'votre', 'vos', 'nous', 'vous', 'ils', 'elles', 'être', 'avoir', 'fait',
    'faire', 'plus', 'moins', 'très', 'bien', 'tout', 'tous', 'toute', 'toutes',
    'comme', 'ainsi', 'donc', 'mais', 'car', 'que', 'qui', 'quoi', 'dont',
    'où', 'quand', 'comment', 'pourquoi', 'ceci', 'cela', 'celui', 'celle',
    'ceux', 'celles', 'sera', 'seront', 'était', 'étaient', 'sont', 'est',
    'cours', 'séance', 'seance', 'chapitre', 'partie', 'module', 'introduction',
    'notion', 'notions', 'exercice', 'exercices', 'travaux', 'pratique',
    'pratiques', 'dirigés', 'diriges',
}


def generate_syllabus_keywords(course_plan, n_min=5, n_max=10):
    """
    Extrait aléatoirement `n_min` à `n_max` mots-clés significatifs (mots de
    4 lettres ou plus, hors mots vides français usuels) à partir du titre +
    contenu prévu de toutes les séances du plan de cours, et les enregistre
    sur `course_plan.syllabus_keywords`. Retourne la liste générée (vide si
    le plan ne contient pas assez de texte).
    """
    text = ' '.join(
        f"{s.titre} {s.contenu_prevu}" for s in course_plan.sessions.all()
    ).lower()
    words = re.findall(r"[a-zàâäéèêëïîôöùûüç]{4,}", text)
    candidates = sorted({w for w in words if w not in _FR_STOPWORDS})

    if not candidates:
        course_plan.syllabus_keywords = []
        course_plan.save(update_fields=['syllabus_keywords'])
        return []

    n = min(len(candidates), n_max) if len(candidates) > n_min else len(candidates)
    keywords = random.sample(candidates, n)

    course_plan.syllabus_keywords = keywords
    course_plan.save(update_fields=['syllabus_keywords'])
    return keywords


def compute_course_plan_progress(course_plan):
    """Retourne {'total', 'faites', 'restantes', 'percent'} pour un plan de cours."""
    return {
        'total':      course_plan.total_seances_planifiees,
        'faites':     course_plan.seances_faites,
        'restantes':  course_plan.seances_restantes,
        'percent':    course_plan.percent_progression,
    }


def check_syllabus_compliance(sheet):
    """
    Vérifie, une fois que 5 séances ont été émargées (validées, contenu non
    vide) pour un EC donné par un enseignant, si le contenu réellement
    dispensé respecte le plan de cours défini : les mots-clés générés
    aléatoirement à partir du syllabus (CoursePlan.syllabus_keywords)
    doivent être retrouvés à au moins 50% dans le contenu cumulé de ces 5
    premières séances. En-deçà de 50%, un email d'alerte est envoyé à
    l'enseignant et au chef de département (+ assistante) pour l'inviter à
    réorienter le contenu du cours vers le syllabus.

    Ne fait rien si : aucun plan de cours n'existe pour cet EC/enseignant
    ("s'il existe" — le plan de cours est optionnel), le plan n'a pas de
    mots-clés exploitables, moins de 5 séances ne sont encore validées avec
    contenu, ou la vérification a déjà été effectuée (une seule fois par
    plan de cours).
    """
    from django.utils import timezone
    from .models import CoursePlan, AttendanceSheet
    from academic_core.apps.accounts.models import User, Role

    entry = sheet.timetable_entry
    teacher = entry.teacher
    subject = entry.subject
    class_group = entry.class_group
    academic_year = entry.semester.academic_year if entry.semester else None
    if not academic_year:
        return None

    try:
        plan = CoursePlan.objects.get(
            subject=subject, class_group=class_group,
            academic_year=academic_year, teacher=teacher,
        )
    except CoursePlan.DoesNotExist:
        return None

    if plan.compliance_checked:
        return None

    if not plan.syllabus_keywords:
        return None

    first_five = list(
        AttendanceSheet.objects.filter(
            timetable_entry__subject=subject,
            timetable_entry__class_group=class_group,
            timetable_entry__teacher=teacher,
            timetable_entry__semester__academic_year=academic_year,
            status=AttendanceSheet.STATUS_VALIDATED,
        ).exclude(lesson_content='').order_by('session_date')[:5]
    )
    if len(first_five) < 5:
        return None

    combined_content = ' '.join(s.lesson_content for s in first_five).lower()
    found = [kw for kw in plan.syllabus_keywords if kw.lower() in combined_content]
    match_pct = round(len(found) / len(plan.syllabus_keywords) * 100, 1)

    plan.compliance_checked = True
    plan.compliance_match_pct = match_pct
    plan.compliance_checked_at = timezone.now()

    non_compliant = match_pct < 50
    if non_compliant:
        department = getattr(getattr(class_group, 'program', None), 'department', None)
        recipients = [teacher.user] if teacher.user else []
        if department:
            recipients += list(
                User.objects.filter(
                    role__name__in=[Role.RESPONSABLE, Role.ASSISTANTE],
                    department=department, is_active=True,
                ).distinct()
            )
        recipients = [u for u in recipients if u and u.email]

        if recipients:
            title = f"Non-conformité au syllabus — {subject.title} ({class_group.name})"
            message = (
                f"Le contenu des 5 premières séances émargées par {teacher.user.get_full_name()} "
                f"pour le module {subject.title} ({class_group.name}) ne correspond qu'à {match_pct}% "
                f"des mots-clés attendus du syllabus (seuil minimum : 50%). "
                f"Le contenu du cours doit être réorienté en fonction du plan de cours défini."
            )
            notify_users(
                recipients=recipients,
                notification_type='ABSENCE',
                title=title,
                message=message,
                priority='HIGH',
                send_email=True,
                email_heading="Non-conformité au syllabus détectée",
                email_paragraphs=[
                    f"Le contenu des 5 premières séances émargées pour le module « {subject.title} » "
                    f"({class_group.name}) ne correspond qu'à {match_pct}% des mots-clés attendus du "
                    f"syllabus défini dans le plan de cours (seuil minimum attendu : 50%).",
                    "Merci de réorienter le contenu des prochaines séances en fonction du plan de "
                    "cours défini pour ce module.",
                ],
            )
        plan.compliance_alert_sent = bool(recipients)

    plan.save(update_fields=[
        'compliance_checked', 'compliance_match_pct',
        'compliance_checked_at', 'compliance_alert_sent',
    ])
    return {'match_pct': match_pct, 'non_compliant': non_compliant}
