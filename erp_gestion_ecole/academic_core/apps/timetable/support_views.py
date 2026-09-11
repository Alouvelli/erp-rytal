"""
Supports de cours — vues pour enseignants et étudiants.
"""
import os
import mimetypes
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404

from .models import TimetableEntry, CourseSupport
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification
from academic_core.apps.students.models import Enrollment


# ── Helpers ────────────────────────────────────────────────────────────────────

def _notify_students(support):
    """Envoie une notification à tous les étudiants actifs de la classe."""
    from academic_core.db_router import get_current_db
    _db = get_current_db() or 'default'
    enrollments = Enrollment.objects.using(_db).filter(
        class_group=support.class_group,
        is_active=True,
        status='VALIDATED',
    ).select_related('student__user')
    recipients = [e.student.user for e in enrollments if hasattr(e.student, 'user')]
    if recipients:
        notify_users(
            recipients=recipients,
            notification_type=Notification.TYPE_COURSE_SUPPORT,
            title=f"Nouveau support — {support.subject.title}",
            message=(
                f"{support.teacher.full_name} a partagé un support de type "
                f"{support.get_support_type_display()} : « {support.title} » "
                f"pour la classe {support.class_group.name}. "
                f"Vous devez le télécharger dans les 72 heures, passé ce délai "
                f"il sera automatiquement supprimé."
            ),
            priority='MEDIUM',
            link=f"/timetable/supports/student/{support.class_group_id}/{support.subject_id}/",
        )


# ── Vues enseignant ────────────────────────────────────────────────────────────

@login_required
def teacher_supports_list(request):
    """Enseignant : liste de tous ses supports partagés."""
    if not getattr(request.user, 'is_enseignant', lambda: False)():
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    teacher = request.user.teacher_profile
    dept = getattr(request, 'active_department', None)

    qs = CourseSupport.objects.filter(teacher=teacher, is_active=True).select_related(
        'subject', 'class_group', 'semester'
    )
    if dept:
        qs = qs.filter(class_group__program__department=dept)

    # Grouper par matière
    by_subject = {}
    for s in qs:
        key = s.subject_id
        if key not in by_subject:
            by_subject[key] = {'subject': s.subject, 'supports': []}
        by_subject[key]['supports'].append(s)

    return render(request, 'timetable/teacher_supports_list.html', {
        'by_subject': list(by_subject.values()),
        'total': qs.count(),
    })


@login_required
def teacher_support_upload(request):
    """Enseignant : formulaire de partage d'un nouveau support."""
    if not getattr(request.user, 'is_enseignant', lambda: False)():
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    teacher = request.user.teacher_profile
    dept = getattr(request, 'active_department', None)

    # Récupérer les entrées d'emploi du temps de l'enseignant (pour peupler les selects)
    entries_qs = TimetableEntry.objects.filter(
        teacher=teacher, is_active=True
    ).select_related('subject', 'class_group', 'semester')
    if dept:
        entries_qs = entries_qs.filter(class_group__program__department=dept)

    # Dédoublonner subject × class_group × semester, grouper par semestre
    seen = {}
    for e in entries_qs:
        key = (e.subject_id, e.class_group_id, e.semester_id)
        if key not in seen:
            seen[key] = {'subject': e.subject, 'class_group': e.class_group, 'semester': e.semester}

    # Grouper par semestre (ordre croissant)
    from collections import defaultdict
    groups = defaultdict(list)
    for item in seen.values():
        groups[item['semester']].append(item)
    combos_by_semester = [
        {'semester': sem, 'items': sorted(items, key=lambda x: x['subject'].title)}
        for sem, items in sorted(groups.items(), key=lambda kv: kv[0].number)
    ]
    combos = list(seen.values())

    if request.method == 'POST':
        title        = request.POST.get('title', '').strip()
        description  = request.POST.get('description', '').strip()
        support_type = request.POST.get('support_type', CourseSupport.TYPE_CM)
        subject_id   = request.POST.get('subject_id')
        class_id     = request.POST.get('class_group_id')
        semester_id  = request.POST.get('semester_id')
        uploaded     = request.FILES.get('file')

        if not all([title, subject_id, class_id, semester_id, uploaded]):
            messages.error(request, "Tous les champs obligatoires doivent être remplis.")
        else:
            from academic_core.apps.subjects.models import Subject
            from academic_core.apps.academic_structure.models import Class, Semester
            subject     = get_object_or_404(Subject, pk=subject_id)
            class_group = get_object_or_404(Class,   pk=class_id)
            semester    = get_object_or_404(Semester, pk=semester_id)

            support = CourseSupport.objects.create(
                teacher=teacher,
                subject=subject,
                class_group=class_group,
                semester=semester,
                title=title,
                description=description,
                support_type=support_type,
                file=uploaded,
            )
            _notify_students(support)
            messages.success(request, f"Support « {title} » partagé — les étudiants ont été notifiés.")
            return redirect('timetable:teacher_supports_list')

    return render(request, 'timetable/teacher_support_upload.html', {
        'combos':             combos,
        'combos_by_semester': combos_by_semester,
        'support_types':      CourseSupport.TYPE_CHOICES,
    })


@login_required
def teacher_support_delete(request, pk):
    """Enseignant : suppression d'un support."""
    if not getattr(request.user, 'is_enseignant', lambda: False)():
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    support = get_object_or_404(CourseSupport, pk=pk, teacher=request.user.teacher_profile)
    if request.method == 'POST':
        # Supprimer le fichier physique
        if support.file and os.path.isfile(support.file.path):
            os.remove(support.file.path)
        support.delete()
        messages.success(request, "Support supprimé.")
        return redirect('timetable:teacher_supports_list')
    return render(request, 'timetable/teacher_support_confirm_delete.html', {'support': support})


# ── Vue étudiant ───────────────────────────────────────────────────────────────

@login_required
def student_supports_list(request):
    """Étudiant : liste des supports partagés pour ses classes."""
    if not getattr(request.user, 'is_etudiant', lambda: False)():
        messages.error(request, "Accès réservé aux étudiants.")
        return redirect('dashboard:index')

    student = request.user.student_profile
    from academic_core.db_router import get_current_db
    _db = get_current_db() or 'default'

    # Classes actives de l'étudiant
    enrollments = Enrollment.objects.using(_db).filter(
        student=student, is_active=True, status='VALIDATED'
    ).select_related('class_group')
    class_ids = [e.class_group_id for e in enrollments]

    supports = CourseSupport.objects.filter(
        class_group_id__in=class_ids, is_active=True
    ).select_related('subject', 'class_group', 'semester', 'teacher__user').order_by('-shared_at')

    # Filtre facultatif par type
    filter_type = request.GET.get('type', '')
    if filter_type:
        supports = supports.filter(support_type=filter_type)

    # Grouper par matière
    by_subject = {}
    for s in supports:
        key = s.subject_id
        if key not in by_subject:
            by_subject[key] = {'subject': s.subject, 'supports': []}
        by_subject[key]['supports'].append(s)

    return render(request, 'timetable/student_supports_list.html', {
        'by_subject':    list(by_subject.values()),
        'support_types': CourseSupport.TYPE_CHOICES,
        'filter_type':   filter_type,
        'total':         supports.count(),
    })


# ── Téléchargement sécurisé ────────────────────────────────────────────────────

@login_required
def support_download(request, pk):
    """Téléchargement sécurisé d'un fichier support."""
    support = get_object_or_404(CourseSupport, pk=pk, is_active=True)
    user = request.user

    # Vérifier l'accès : enseignant propriétaire OU étudiant de la classe
    is_owner = (
        getattr(user, 'is_enseignant', lambda: False)()
        and hasattr(user, 'teacher_profile')
        and user.teacher_profile == support.teacher
    )
    is_student_of_class = False
    if getattr(user, 'is_etudiant', lambda: False)() and hasattr(user, 'student_profile'):
        from academic_core.db_router import get_current_db
        _db = get_current_db() or 'default'
        is_student_of_class = Enrollment.objects.using(_db).filter(
            student=user.student_profile,
            class_group=support.class_group,
            is_active=True,
        ).exists()
    is_admin = getattr(user, 'can_manage_dept', lambda: False)() or getattr(user, 'is_admin', False)

    if not (is_owner or is_student_of_class or is_admin):
        raise Http404

    if not support.file or not os.path.isfile(support.file.path):
        raise Http404

    inline = request.GET.get('view') == '1'
    mime, _ = mimetypes.guess_type(support.file.path)
    response = FileResponse(
        open(support.file.path, 'rb'),
        content_type=mime or 'application/octet-stream',
    )
    disposition = 'inline' if inline else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{support.filename}"'
    return response
