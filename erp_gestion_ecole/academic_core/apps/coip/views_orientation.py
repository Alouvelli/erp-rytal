from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import OrientationSessionForm
from .models import OrientationSession
from .permissions import CoipStaffRequiredMixin, coip_staff_required, get_student_for_user


@coip_staff_required
def orientation_session_list(request):
    qs = OrientationSession.objects.select_related('student__user', 'conseiller').order_by('-date_session')
    q = request.GET.get('q')
    type_session = request.GET.get('type')
    if q:
        qs = qs.filter(
            Q(student__user__first_name__icontains=q) | Q(student__user__last_name__icontains=q)
        )
    if type_session:
        qs = qs.filter(type_session=type_session)
    return render(request, 'coip/orientation_session_list.html', {
        'sessions': qs,
        'type_choices': OrientationSession.TYPE_CHOICES,
        'selected_type': type_session or '',
    })


class OrientationSessionCreateView(CoipStaffRequiredMixin, CreateView):
    model = OrientationSession
    form_class = OrientationSessionForm
    template_name = 'coip/orientation_session_form.html'
    success_url = reverse_lazy('coip:orientation_session_list')

    def form_valid(self, form):
        if not form.instance.conseiller_id:
            form.instance.conseiller = self.request.user
        messages.success(self.request, "Séance d'orientation enregistrée.")
        return super().form_valid(form)


class OrientationSessionUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = OrientationSession
    form_class = OrientationSessionForm
    template_name = 'coip/orientation_session_form.html'
    success_url = reverse_lazy('coip:orientation_session_list')

    def form_valid(self, form):
        messages.success(self.request, "Séance d'orientation mise à jour.")
        return super().form_valid(form)


class OrientationSessionDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = OrientationSession
    template_name = 'coip/orientation_session_confirm_delete.html'
    success_url = reverse_lazy('coip:orientation_session_list')

    def form_valid(self, form):
        messages.success(self.request, "Séance d'orientation supprimée.")
        return super().form_valid(form)


@login_required
def my_orientation_sessions(request):
    student = get_student_for_user(request.user)
    if student is None:
        messages.error(request, "Cette page est réservée aux étudiants.")
        from django.shortcuts import redirect
        return redirect('dashboard:index')
    sessions = OrientationSession.objects.filter(student=student).select_related('conseiller').order_by('-date_session')
    return render(request, 'coip/my_orientation_sessions.html', {'sessions': sessions})
