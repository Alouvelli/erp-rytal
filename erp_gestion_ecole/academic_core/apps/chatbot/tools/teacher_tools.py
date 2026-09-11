"""
Outils RYTAL pour le rôle ENSEIGNANT.

Règle de sécurité : chaque handler filtre TOUJOURS d'abord sur
`teacher__user=user` (jamais sur un identifiant d'enseignant fourni par le
modèle). Les arguments optionnels comme `class_group_id` ne servent qu'à
affiner une requête déjà restreinte aux séances de l'enseignant connecté :
si l'identifiant ne correspond à aucune de ses classes, le résultat est
simplement vide — jamais une erreur, jamais les données d'un autre enseignant.
"""
from academic_core.apps.timetable.models import TimetableEntry, SessionLog
from academic_core.apps.attendance.models import StudentAttendance
from .registry import register_tool


@register_tool('get_my_teaching_timetable', {
    'name': 'get_my_teaching_timetable',
    'description': (
        "Retourne l'emploi du temps de l'enseignant connecté (ses propres "
        "créneaux), éventuellement filtré par jour de la semaine."
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
def get_my_teaching_timetable(user, request, day_of_week=None):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'entries': []}

    qs = TimetableEntry.objects.filter(teacher__user=user, is_active=True)
    if day_of_week:
        qs = qs.filter(day_of_week=day_of_week)
    qs = qs.select_related('subject', 'class_group', 'room').order_by('day_of_week', 'start_time')

    return {'entries': [
        {
            'day_of_week': e.get_day_of_week_display(),
            'start_time': e.start_time.strftime('%H:%M'),
            'end_time': e.end_time.strftime('%H:%M'),
            'subject': e.subject.title,
            'class_group': e.class_group.name,
            'room': e.room.name if e.room else '',
        }
        for e in qs
    ]}


@register_tool('get_my_classes', {
    'name': 'get_my_classes',
    'description': "Retourne la liste des classes actuellement enseignées par l'enseignant connecté.",
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_classes(user, request):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'classes': []}

    class_groups = (
        TimetableEntry.objects.filter(teacher__user=user, is_active=True)
        .select_related('class_group', 'subject')
        .order_by('class_group__name')
    )
    seen = {}
    for e in class_groups:
        seen.setdefault(e.class_group_id, {
            'class_group': e.class_group.name,
            'class_group_id': e.class_group_id,
            'subjects': set(),
        })['subjects'].add(e.subject.title)

    return {'classes': [
        {'class_group': v['class_group'], 'class_group_id': v['class_group_id'], 'subjects': sorted(v['subjects'])}
        for v in seen.values()
    ]}


@register_tool('get_my_session_log', {
    'name': 'get_my_session_log',
    'description': (
        "Retourne le cahier de texte (objectifs, contenu réalisé, observations) "
        "des séances de l'enseignant connecté, éventuellement filtré sur une de "
        "ses classes (via class_group_id renvoyé par get_my_classes)."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'class_group_id': {
                'type': 'integer',
                'description': "Identifiant d'une des classes de l'enseignant, obtenu via get_my_classes.",
            },
        },
    },
})
def get_my_session_log(user, request, class_group_id=None):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'sessions': []}

    qs = SessionLog.objects.filter(timetable_entry__teacher__user=user)
    if class_group_id:
        qs = qs.filter(timetable_entry__class_group_id=class_group_id)
    qs = qs.select_related('timetable_entry__subject', 'timetable_entry__class_group').order_by('-session_date')[:30]

    return {'sessions': [
        {
            'date': s.session_date.isoformat(),
            'subject': s.timetable_entry.subject.title,
            'class_group': s.timetable_entry.class_group.name,
            'objectives': s.objectives,
            'content': s.content,
            'remarks': s.remarks,
        }
        for s in qs
    ]}


@register_tool('get_class_attendance_summary', {
    'name': 'get_class_attendance_summary',
    'description': (
        "Retourne un résumé des présences/absences pour les séances de "
        "l'enseignant connecté, éventuellement filtré sur une de ses classes."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'class_group_id': {
                'type': 'integer',
                'description': "Identifiant d'une des classes de l'enseignant, obtenu via get_my_classes.",
            },
        },
    },
})
def get_class_attendance_summary(user, request, class_group_id=None):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'stats': {}, 'sessions': []}

    qs = StudentAttendance.objects.filter(attendance_sheet__timetable_entry__teacher__user=user)
    if class_group_id:
        qs = qs.filter(attendance_sheet__timetable_entry__class_group_id=class_group_id)

    stats = {
        'total': qs.count(),
        'present': qs.filter(status=StudentAttendance.STATUS_PRESENT).count(),
        'absent': qs.filter(status=StudentAttendance.STATUS_ABSENT).count(),
        'justified': qs.filter(status=StudentAttendance.STATUS_JUSTIFIED).count(),
        'late': qs.filter(status=StudentAttendance.STATUS_LATE).count(),
    }

    sheets = (
        qs.select_related('attendance_sheet__timetable_entry__subject', 'attendance_sheet__timetable_entry__class_group')
        .values(
            'attendance_sheet__session_date',
            'attendance_sheet__timetable_entry__subject__title',
            'attendance_sheet__timetable_entry__class_group__name',
        )
        .distinct()
        .order_by('-attendance_sheet__session_date')[:20]
    )

    return {
        'stats': stats,
        'sessions': [
            {
                'date': str(s['attendance_sheet__session_date']),
                'subject': s['attendance_sheet__timetable_entry__subject__title'],
                'class_group': s['attendance_sheet__timetable_entry__class_group__name'],
            }
            for s in sheets
        ],
    }


@register_tool('get_my_honoraires', {
    'name': 'get_my_honoraires',
    'description': (
        "Retourne un résumé des honoraires de l'enseignant connecté : total du "
        "mois en cours et nombre de séances validées."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_honoraires(user, request):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'nb_sessions': 0}

    from decimal import Decimal
    from django.utils import timezone
    from academic_core.apps.accounting.models import TeacherHonoraire

    today = timezone.now().date()
    qs = TeacherHonoraire.objects.filter(
        teacher=teacher, session_date__year=today.year, session_date__month=today.month,
    )
    total = sum((h.amount for h in qs), Decimal('0'))
    net = sum((h.net_a_payer for h in qs), Decimal('0'))

    return {
        'month': today.month,
        'year': today.year,
        'nb_sessions': qs.count(),
        'total': str(total),
        'net': str(net),
    }


@register_tool('get_my_contract', {
    'name': 'get_my_contract',
    'description': (
        "Retourne la liste des contrats de prestation de service de l'enseignant "
        "connecté (un contrat par département où il intervient)."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_contract(user, request):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'contrats': []}

    from academic_core.apps.teachers.models import ContratEnseignant

    contrats = (
        ContratEnseignant.objects.filter(teacher=teacher)
        .select_related('department', 'academic_year')
        .order_by('department__name')
    )
    return {'contrats': [
        {'department': c.department.name, 'academic_year': c.academic_year.label}
        for c in contrats
    ]}


@register_tool('get_my_extra_requests', {
    'name': 'get_my_extra_requests',
    'description': (
        "Retourne les demandes de séances supplémentaires de l'enseignant "
        "connecté et leur statut."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_extra_requests(user, request):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'requests': []}

    from academic_core.apps.attendance.models import ExtraSessionRequest

    qs = (
        ExtraSessionRequest.objects.filter(teacher=teacher)
        .select_related('subject', 'class_group')
        .order_by('-created_at')[:10]
    )
    return {'requests': [
        {
            'subject': r.subject.title,
            'class_group': r.class_group.name,
            'extra_hours_requested': str(r.extra_hours_requested),
            'status': r.get_status_display(),
            'extra_hours_approved': str(r.extra_hours_approved) if r.extra_hours_approved is not None else None,
        }
        for r in qs
    ]}


@register_tool('get_my_shared_course_supports', {
    'name': 'get_my_shared_course_supports',
    'description': "Retourne les supports de cours partagés par l'enseignant connecté.",
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_shared_course_supports(user, request):
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {'supports': []}

    from academic_core.apps.timetable.models import CourseSupport

    qs = (
        CourseSupport.objects.filter(teacher=teacher, is_active=True)
        .select_related('subject', 'class_group')
        .order_by('-shared_at')[:10]
    )
    return {'supports': [
        {
            'title': s.title,
            'subject': s.subject.title,
            'class_group': s.class_group.name,
            'type': s.get_support_type_display(),
        }
        for s in qs
    ]}
