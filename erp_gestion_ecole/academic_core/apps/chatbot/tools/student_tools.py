"""
Outils RYTAL pour le rôle ETUDIANT.

Règle de sécurité : chaque handler résout TOUJOURS le périmètre depuis
`user.student_profile` (jamais depuis un argument fourni par le modèle) —
aucun schéma ci-dessous n'accepte d'identifiant d'étudiant, de classe ou
de département. Un étudiant sans profil ou sans inscription active reçoit
une liste vide, jamais une erreur qui pourrait laisser fuiter une info.
"""
from academic_core.apps.timetable.models import TimetableEntry
from academic_core.apps.grades.models import Grade, Bulletin
from academic_core.apps.attendance.models import StudentAttendance
from .registry import register_tool


def _current_semester():
    from academic_core.apps.academic_structure.models import Semester
    return Semester.objects.filter(academic_year__is_current=True, is_active=True).first()


@register_tool('get_my_timetable', {
    'name': 'get_my_timetable',
    'description': (
        "Retourne l'emploi du temps de l'étudiant connecté (créneaux de sa classe "
        "actuelle), éventuellement filtré par jour de la semaine."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'day_of_week': {
                'type': 'integer',
                'description': 'Jour précis : 1=Lundi ... 7=Dimanche. Omettre pour tous les jours.',
            },
        },
    },
})
def get_my_timetable(user, request, day_of_week=None):
    student = getattr(user, 'student_profile', None)
    if not student:
        return {'entries': []}
    enrollment = student.current_enrollment()
    if not enrollment:
        return {'entries': [], 'note': "Aucune inscription active pour l'année en cours."}

    qs = TimetableEntry.objects.filter(class_group=enrollment.class_group, is_active=True)
    if day_of_week:
        qs = qs.filter(day_of_week=day_of_week)
    qs = qs.select_related('subject', 'teacher__user', 'room').order_by('day_of_week', 'start_time')

    return {'entries': [
        {
            'day_of_week': e.get_day_of_week_display(),
            'start_time': e.start_time.strftime('%H:%M'),
            'end_time': e.end_time.strftime('%H:%M'),
            'subject': e.subject.title,
            'teacher': e.teacher.full_name if e.teacher else '',
            'room': e.room.name if e.room else '',
        }
        for e in qs
    ]}


@register_tool('get_my_grades', {
    'name': 'get_my_grades',
    'description': (
        "Retourne les notes obtenues par l'étudiant connecté pour le semestre en "
        "cours (ou un semestre précis si son identifiant est connu)."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'semester_id': {
                'type': 'integer',
                'description': "Identifiant du semestre à consulter. Omettre pour le semestre en cours.",
            },
        },
    },
})
def get_my_grades(user, request, semester_id=None):
    student = getattr(user, 'student_profile', None)
    if not student:
        return {'grades': []}

    qs = Grade.objects.filter(student=student).select_related(
        'evaluation__subject', 'evaluation__evaluation_type',
    )
    if semester_id:
        qs = qs.filter(evaluation__semester_id=semester_id)
    else:
        current = _current_semester()
        if current:
            qs = qs.filter(evaluation__semester=current)
    qs = qs.order_by('-evaluation__date')[:100]

    return {'grades': [
        {
            'subject': g.evaluation.subject.title,
            'evaluation_type': g.evaluation.evaluation_type.label,
            'title': g.evaluation.title,
            'date': g.evaluation.date.isoformat(),
            'score': str(g.score),
            'max_score': str(g.evaluation.max_score),
            'coefficient': str(g.evaluation.coefficient),
        }
        for g in qs
    ]}


@register_tool('get_my_bulletin', {
    'name': 'get_my_bulletin',
    'description': "Retourne le(s) bulletin(s) semestriel(s) de l'étudiant connecté.",
    'input_schema': {
        'type': 'object',
        'properties': {
            'semester_id': {
                'type': 'integer',
                'description': "Identifiant du semestre. Omettre pour tous les bulletins disponibles.",
            },
        },
    },
})
def get_my_bulletin(user, request, semester_id=None):
    student = getattr(user, 'student_profile', None)
    if not student:
        return {'bulletins': []}

    qs = Bulletin.objects.filter(student=student).select_related('semester')
    if semester_id:
        qs = qs.filter(semester_id=semester_id)
    qs = qs.order_by('-semester__academic_year__start_date', '-semester__number')

    return {'bulletins': [
        {
            'semester': b.semester.label,
            'status': b.get_status_display(),
            'semester_average': str(b.semester_average) if b.semester_average is not None else None,
            'mention': b.mention,
            'total_credits_obtained': b.total_credits_obtained,
            'total_credits_possible': b.total_credits_possible,
        }
        for b in qs
    ]}


@register_tool('get_my_absences', {
    'name': 'get_my_absences',
    'description': (
        "Retourne l'historique de présence/absence de l'étudiant connecté "
        "(présent, absent, absence justifiée, retard) avec un résumé chiffré."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'status': {
                'type': 'string',
                'enum': ['PRESENT', 'ABSENT', 'JUSTIFIED', 'LATE'],
                'description': "Filtrer sur un statut précis. Omettre pour tout l'historique.",
            },
        },
    },
})
def get_my_absences(user, request, status=None):
    student = getattr(user, 'student_profile', None)
    if not student:
        return {'records': [], 'stats': {}}

    qs = StudentAttendance.objects.filter(student=student).select_related(
        'attendance_sheet__timetable_entry__subject',
    )
    stats = {
        'total': qs.count(),
        'present': qs.filter(status=StudentAttendance.STATUS_PRESENT).count(),
        'absent': qs.filter(status=StudentAttendance.STATUS_ABSENT).count(),
        'justified': qs.filter(status=StudentAttendance.STATUS_JUSTIFIED).count(),
        'late': qs.filter(status=StudentAttendance.STATUS_LATE).count(),
    }
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by('-attendance_sheet__session_date')[:50]

    return {
        'stats': stats,
        'records': [
            {
                'date': a.attendance_sheet.session_date.isoformat(),
                'subject': a.attendance_sheet.timetable_entry.subject.title,
                'status': a.get_status_display(),
                'comment': a.comment,
            }
            for a in qs
        ],
    }


@register_tool('get_my_course_supports', {
    'name': 'get_my_course_supports',
    'description': "Retourne les supports de cours partagés pour la classe actuelle de l'étudiant connecté.",
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_course_supports(user, request):
    student = getattr(user, 'student_profile', None)
    if not student:
        return {'supports': []}
    enrollment = student.current_enrollment()
    if not enrollment:
        return {'supports': [], 'note': "Aucune inscription active pour l'année en cours."}

    from academic_core.apps.timetable.models import CourseSupport

    qs = (
        CourseSupport.objects.filter(class_group=enrollment.class_group, is_active=True)
        .select_related('subject', 'teacher__user')
        .order_by('-shared_at')[:10]
    )
    return {'supports': [
        {
            'title': s.title,
            'subject': s.subject.title,
            'teacher': s.teacher.full_name,
            'type': s.get_support_type_display(),
        }
        for s in qs
    ]}
