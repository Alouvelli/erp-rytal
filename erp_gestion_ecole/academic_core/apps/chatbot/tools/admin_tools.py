"""
Outils RYTAL pour le palier gestion de département/institut
(RESPONSABLE, ASSISTANTE, INST_ADMIN, ADMIN, ASSISTANTE_DG).

Règle de sécurité : chaque handler reproduit exactement le repli utilisé par
`EvaluationListView.get_queryset` (apps/grades/views.py) et `attendance_dashboard`
(apps/attendance/views.py) : filtrer par `request.active_department` s'il est
défini, sinon par `request.active_faculty`, sinon ne rien renvoyer. Aucun
identifiant de département/institut n'est jamais accepté en argument — le
périmètre vient uniquement de la session de la personne connectée
(résolu par DepartmentMiddleware).
"""
from django.db.models import Avg, Count
from academic_core.apps.timetable.models import TimetableEntry
from academic_core.apps.grades.models import Grade
from academic_core.apps.attendance.models import StudentAttendance
from .registry import register_tool


def _scope_filter(request, field_prefix):
    """Retourne un dict de filtre Django ou None si aucun périmètre résolu."""
    dept = getattr(request, 'active_department', None)
    if dept:
        return {f'{field_prefix}__department': dept}
    faculty = getattr(request, 'active_faculty', None)
    if faculty:
        return {f'{field_prefix}__department__faculty': faculty}
    return None


def _resolve_faculty(request):
    """Périmètre institut pour les outils de palier INST_ADMIN (RH, finance,
    utilisateurs...) : ces vues sont toujours à l'échelle de l'institut, pas
    du département — on retombe sur la faculté du département actif si aucun
    institut n'est directement sélectionné."""
    faculty = getattr(request, 'active_faculty', None)
    if faculty:
        return faculty
    dept = getattr(request, 'active_department', None)
    return getattr(dept, 'faculty', None) if dept else None


@register_tool('get_department_timetable', {
    'name': 'get_department_timetable',
    'description': (
        "Retourne l'emploi du temps de toutes les classes du département (ou de "
        "l'institut) actuellement sélectionné par la personne connectée."
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
def get_department_timetable(user, request, day_of_week=None):
    scope = _scope_filter(request, 'class_group__program')
    if scope is None:
        return {'entries': [], 'note': "Aucun département/institut sélectionné."}

    qs = TimetableEntry.objects.filter(is_active=True, **scope)
    if day_of_week:
        qs = qs.filter(day_of_week=day_of_week)
    qs = qs.select_related('subject', 'teacher__user', 'class_group', 'room').order_by(
        'day_of_week', 'start_time',
    )[:100]

    return {'entries': [
        {
            'day_of_week': e.get_day_of_week_display(),
            'start_time': e.start_time.strftime('%H:%M'),
            'end_time': e.end_time.strftime('%H:%M'),
            'class_group': e.class_group.name,
            'subject': e.subject.title,
            'teacher': e.teacher.full_name if e.teacher else '',
            'room': e.room.name if e.room else '',
        }
        for e in qs
    ]}


@register_tool('get_department_grades_summary', {
    'name': 'get_department_grades_summary',
    'description': (
        "Retourne une moyenne par module (EC) pour le département (ou l'institut) "
        "actuellement sélectionné, pour le semestre en cours ou un semestre précis."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'semester_id': {
                'type': 'integer',
                'description': "Identifiant du semestre. Omettre pour le semestre en cours.",
            },
        },
    },
})
def get_department_grades_summary(user, request, semester_id=None):
    scope = _scope_filter(request, 'evaluation__class_group__program')
    if scope is None:
        return {'subjects': [], 'note': "Aucun département/institut sélectionné."}

    qs = Grade.objects.filter(**scope)
    if semester_id:
        qs = qs.filter(evaluation__semester_id=semester_id)
    else:
        from academic_core.apps.academic_structure.models import Semester
        current = Semester.objects.filter(academic_year__is_current=True, is_active=True).first()
        if current:
            qs = qs.filter(evaluation__semester=current)

    rows = (
        qs.values('evaluation__subject__title')
        .annotate(average=Avg('score'), nb_notes=Count('id'))
        .order_by('evaluation__subject__title')[:50]
    )

    return {'subjects': [
        {
            'subject': r['evaluation__subject__title'],
            'average': round(r['average'], 2) if r['average'] is not None else None,
            'nb_notes': r['nb_notes'],
        }
        for r in rows
    ]}


@register_tool('get_department_attendance_summary', {
    'name': 'get_department_attendance_summary',
    'description': (
        "Retourne un résumé chiffré des présences/absences pour le département "
        "(ou l'institut) actuellement sélectionné."
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'date_from': {'type': 'string', 'description': 'Date de début (AAAA-MM-JJ). Optionnel.'},
            'date_to': {'type': 'string', 'description': 'Date de fin (AAAA-MM-JJ). Optionnel.'},
        },
    },
})
def get_department_attendance_summary(user, request, date_from=None, date_to=None):
    scope = _scope_filter(request, 'attendance_sheet__timetable_entry__class_group__program')
    if scope is None:
        return {'stats': {}, 'note': "Aucun département/institut sélectionné."}

    qs = StudentAttendance.objects.filter(**scope)
    if date_from:
        qs = qs.filter(attendance_sheet__session_date__gte=date_from)
    if date_to:
        qs = qs.filter(attendance_sheet__session_date__lte=date_to)

    return {'stats': {
        'total': qs.count(),
        'present': qs.filter(status=StudentAttendance.STATUS_PRESENT).count(),
        'absent': qs.filter(status=StudentAttendance.STATUS_ABSENT).count(),
        'justified': qs.filter(status=StudentAttendance.STATUS_JUSTIFIED).count(),
        'late': qs.filter(status=StudentAttendance.STATUS_LATE).count(),
    }}


@register_tool('get_institut_overview', {
    'name': 'get_institut_overview',
    'description': (
        "Retourne les chiffres clés de l'institut sélectionné : effectifs "
        "(étudiants, enseignants, utilisateurs), feuilles d'émargement en "
        "attente/validées, annulations/reports en attente."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_institut_overview(user, request):
    from academic_core.apps.students.models import Student
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.accounts.models import User as UserModel
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.cancellations.models import CourseCancellation

    faculty = _resolve_faculty(request)
    if not faculty:
        return {'note': "Aucun institut sélectionné."}

    students_qs = Student.objects.filter(
        enrollments__class_group__program__department__faculty=faculty,
        enrollments__is_active=True,
    ).distinct()
    teachers_qs = Teacher.objects.filter(user__department__faculty=faculty)
    users_qs = UserModel.objects.filter(is_active=True, department__faculty=faculty)
    sheets_qs = AttendanceSheet.objects.filter(
        timetable_entry__class_group__program__department__faculty=faculty
    )
    cancels_qs = CourseCancellation.objects.filter(
        timetable_entry__class_group__program__department__faculty=faculty
    )

    return {
        'total_students': students_qs.count(),
        'total_teachers': teachers_qs.count(),
        'total_users': users_qs.count(),
        'sheets_pending': sheets_qs.filter(status=AttendanceSheet.STATUS_PENDING).count(),
        'sheets_validated': sheets_qs.filter(status=AttendanceSheet.STATUS_VALIDATED).count(),
        'cancellations_pending': cancels_qs.filter(status=CourseCancellation.STATUS_PENDING).count(),
    }


@register_tool('get_pending_cancellations', {
    'name': 'get_pending_cancellations',
    'description': (
        "Retourne la liste des demandes d'annulation/report de séance en "
        "attente de validation pour l'institut sélectionné."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_pending_cancellations(user, request):
    from academic_core.apps.cancellations.models import CourseCancellation

    faculty = _resolve_faculty(request)
    if not faculty:
        return {'cancellations': [], 'note': "Aucun institut sélectionné."}

    qs = (
        CourseCancellation.objects.filter(
            timetable_entry__class_group__program__department__faculty=faculty,
            status=CourseCancellation.STATUS_PENDING,
        )
        .select_related('timetable_entry__subject', 'timetable_entry__class_group', 'requested_by')
        .order_by('-requested_at')[:20]
    )
    return {'cancellations': [
        {
            'type': c.get_request_type_display(),
            'session_date': c.session_date.strftime('%d/%m/%Y'),
            'subject': c.timetable_entry.subject.title if c.timetable_entry and c.timetable_entry.subject else '—',
            'class_group': c.timetable_entry.class_group.name if c.timetable_entry and c.timetable_entry.class_group else '—',
            'requested_by': c.requested_by.get_full_name() if c.requested_by else '—',
            'reason': c.reason,
        }
        for c in qs
    ]}


@register_tool('get_institut_users_summary', {
    'name': 'get_institut_users_summary',
    'description': (
        "Retourne la répartition des utilisateurs actifs de l'institut "
        "sélectionné par rôle (enseignants, personnel administratif, etc.)."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_institut_users_summary(user, request):
    from academic_core.apps.accounts.models import User as UserModel

    faculty = _resolve_faculty(request)
    if not faculty:
        return {'roles': [], 'note': "Aucun institut sélectionné."}

    rows = (
        UserModel.objects.filter(is_active=True, department__faculty=faculty)
        .values('role__name')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    role_labels = dict(UserModel._meta.get_field('role').related_model.ROLE_CHOICES)
    return {'roles': [
        {'role': role_labels.get(r['role__name'], r['role__name'] or '—'), 'total': r['total']}
        for r in rows
    ]}


@register_tool('get_institut_finance_summary', {
    'name': 'get_institut_finance_summary',
    'description': (
        "Retourne un résumé financier de l'institut sélectionné : inscriptions "
        "en attente/validées, montant encaissé aujourd'hui et ce mois-ci, "
        "reste à recouvrer."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_institut_finance_summary(user, request):
    from datetime import date
    from django.db.models import Sum
    from academic_core.apps.students.models import Enrollment, PaymentInstallment
    from academic_core.apps.accounting.models import CaissePayment

    faculty = _resolve_faculty(request)
    if not faculty:
        return {'note': "Aucun institut sélectionné."}

    today = date.today()
    enr_qs = Enrollment.objects.filter(class_group__program__department__faculty=faculty)
    caisse_qs = CaissePayment.objects.filter(
        student__enrollments__class_group__program__department__faculty=faculty
    ).distinct()
    inst_qs = PaymentInstallment.objects.filter(
        enrollment__status=Enrollment.STATUS_VALIDATED, is_paid=False,
        enrollment__class_group__program__department__faculty=faculty,
    )

    total_collected = (
        caisse_qs.filter(enrollment__status=Enrollment.STATUS_VALIDATED)
        .aggregate(s=Sum('amount'))['s'] or 0
    )
    total_remaining = inst_qs.aggregate(s=Sum('amount_expected'))['s'] or 0
    encaisse_jour = caisse_qs.filter(payment_date=today).aggregate(s=Sum('amount'))['s'] or 0
    encaisse_mois = caisse_qs.filter(
        payment_date__year=today.year, payment_date__month=today.month
    ).aggregate(s=Sum('amount'))['s'] or 0

    return {
        'nb_pending': enr_qs.filter(status=Enrollment.STATUS_PENDING).count(),
        'nb_validated': enr_qs.filter(status=Enrollment.STATUS_VALIDATED).count(),
        'total_collected': total_collected,
        'total_remaining': total_remaining,
        'encaisse_jour': encaisse_jour,
        'encaisse_mois': encaisse_mois,
    }


@register_tool('get_department_pending_cancellations', {
    'name': 'get_department_pending_cancellations',
    'description': (
        "Retourne la liste des demandes d'annulation/report de séance en "
        "attente de validation pour le département (ou l'institut) sélectionné."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_department_pending_cancellations(user, request):
    from academic_core.apps.cancellations.models import CourseCancellation

    scope = _scope_filter(request, 'timetable_entry__class_group__program')
    if scope is None:
        return {'cancellations': [], 'note': "Aucun département/institut sélectionné."}

    qs = (
        CourseCancellation.objects.filter(status=CourseCancellation.STATUS_PENDING, **scope)
        .select_related('timetable_entry__subject', 'timetable_entry__class_group', 'requested_by')
        .order_by('-requested_at')[:20]
    )
    return {'cancellations': [
        {
            'type': c.get_request_type_display(),
            'session_date': c.session_date.strftime('%d/%m/%Y'),
            'subject': c.timetable_entry.subject.title if c.timetable_entry and c.timetable_entry.subject else '—',
            'class_group': c.timetable_entry.class_group.name if c.timetable_entry and c.timetable_entry.class_group else '—',
            'requested_by': c.requested_by.get_full_name() if c.requested_by else '—',
            'reason': c.reason,
        }
        for c in qs
    ]}


@register_tool('get_department_enrollment_summary', {
    'name': 'get_department_enrollment_summary',
    'description': (
        "Retourne le nombre d'inscriptions en attente/validées et la liste des "
        "inscriptions récentes en attente pour le département (ou l'institut) "
        "sélectionné."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_department_enrollment_summary(user, request):
    from academic_core.apps.students.models import Enrollment

    scope = _scope_filter(request, 'class_group__program')
    if scope is None:
        return {'note': "Aucun département/institut sélectionné."}

    enr_qs = Enrollment.objects.filter(**scope)
    pending = (
        enr_qs.filter(status=Enrollment.STATUS_PENDING)
        .select_related('student__user', 'class_group')
        .order_by('-enrollment_date')[:20]
    )
    return {
        'nb_pending': enr_qs.filter(status=Enrollment.STATUS_PENDING).count(),
        'nb_validated': enr_qs.filter(status=Enrollment.STATUS_VALIDATED).count(),
        'pending_list': [
            {
                'student': e.student.full_name,
                'matricule': e.student.matricule,
                'class_group': e.class_group.name,
                'enrollment_date': e.enrollment_date.strftime('%d/%m/%Y'),
            }
            for e in pending
        ],
    }
