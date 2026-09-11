from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.views.generic import ListView
from django.shortcuts import get_object_or_404, redirect, render
from .models import Notification
from .utils import notify_class_students


class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'notifications/list.html'
    context_object_name = 'notifications'
    paginate_by = 30

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user
        ).order_by('-created_at')


@login_required
def mark_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.is_read = True
    notif.read_at = timezone.now()
    notif.save(update_fields=['is_read', 'read_at'])
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect(notif.link or 'notifications:list')


@login_required
def mark_all_read(request):
    Notification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True, read_at=timezone.now())
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect('notifications:list')


@login_required
def delete_notification(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if request.method == 'POST':
        notif.delete()
    return redirect('notifications:list')


@login_required
def delete_all_notifications(request):
    if request.method == 'POST':
        Notification.objects.filter(recipient=request.user).delete()
    return redirect('notifications:list')


@login_required
def notify_teacher_absence(request):
    """Permet à l'assistante (ou responsable/admin) d'alerter une classe du retard ou de l'absence d'un enseignant."""
    user = request.user
    if not user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Class, AcademicYear
    from academic_core.apps.teachers.models import Teacher

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    classes = Class.objects.select_related('program__department').order_by('name')
    teachers = Teacher.objects.select_related('user').order_by('user__last_name')
    if dept:
        classes = classes.filter(program__department=dept)
        teachers = teachers.filter(user__department=dept)
    elif faculty:
        classes = classes.filter(program__department__faculty=faculty)
        teachers = teachers.filter(user__department__faculty=faculty)

    # Alerter une classe concerne forcément l'année académique en cours.
    fac_for_years = faculty or (dept.faculty if dept else None)
    if fac_for_years:
        current_year = AcademicYear.objects.filter(faculty=fac_for_years, is_current=True).first()
        if current_year:
            classes = classes.filter(academic_year=current_year)

    if request.method == 'POST':
        class_id    = request.POST.get('class_group')
        teacher_id  = request.POST.get('teacher')
        alert_type  = request.POST.get('alert_type')   # 'ABSENCE' ou 'RETARD'
        custom_msg  = request.POST.get('message', '').strip()

        errors = []
        if not class_id:
            errors.append("Veuillez sélectionner une classe.")
        if not teacher_id:
            errors.append("Veuillez sélectionner un enseignant.")
        if not alert_type:
            errors.append("Veuillez choisir le type d'alerte.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'notifications/notify_absence.html', {
                'classes': classes, 'teachers': teachers,
            })

        class_group = get_object_or_404(Class, pk=class_id)
        teacher     = get_object_or_404(Teacher, pk=teacher_id)

        if alert_type == 'ABSENCE':
            notif_type = Notification.TYPE_ABSENCE
            title = f"Absence de {teacher.full_name}"
            default_msg = f"L'enseignant(e) {teacher.full_name} est absent(e) pour la séance d'aujourd'hui."
        else:
            notif_type = Notification.TYPE_GENERAL
            title = f"Retard de {teacher.full_name}"
            default_msg = f"L'enseignant(e) {teacher.full_name} sera en retard pour la séance d'aujourd'hui."

        message = custom_msg if custom_msg else default_msg

        notify_class_students(
            class_group=class_group,
            notification_type=notif_type,
            title=title,
            message=message,
            priority='HIGH',
        )

        messages.success(
            request,
            f"Notification envoyée aux étudiants de {class_group.name} "
            f"({'absence' if alert_type == 'ABSENCE' else 'retard'} de {teacher.full_name})."
        )
        return redirect('notifications:notify_absence')

    return render(request, 'notifications/notify_absence.html', {
        'classes': classes,
        'teachers': teachers,
    })
