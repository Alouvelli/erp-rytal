from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import ActivityForm
from .models import Activity, ActivityParticipant
from .permissions import CoipStaffRequiredMixin, coip_staff_required


@coip_staff_required
def activity_list(request):
    qs = Activity.objects.select_related('responsable').order_by('-date_debut')
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/activity_list.html', {
        'activities': qs,
        'status_choices': Activity.STATUT_CHOICES,
        'selected_status': status or '',
    })


@coip_staff_required
def activity_detail(request, pk):
    activity = get_object_or_404(Activity.objects.select_related('responsable'), pk=pk)
    return render(request, 'coip/activity_detail.html', {
        'activity': activity,
        'participants': activity.participants.select_related('user').all(),
    })


@coip_staff_required
def activity_participant_toggle_present(request, pk, participant_pk):
    participant = get_object_or_404(ActivityParticipant, pk=participant_pk, activity_id=pk)
    if request.method == 'POST':
        participant.present = not participant.present
        participant.save(update_fields=['present'])
    return redirect('coip:activity_detail', pk=pk)


@coip_staff_required
def activity_participant_remove(request, pk, participant_pk):
    participant = get_object_or_404(ActivityParticipant, pk=participant_pk, activity_id=pk)
    if request.method == 'POST':
        participant.delete()
        messages.success(request, 'Participant retiré.')
    return redirect('coip:activity_detail', pk=pk)


class ActivityCreateView(CoipStaffRequiredMixin, CreateView):
    model = Activity
    form_class = ActivityForm
    template_name = 'coip/activity_form.html'
    success_url = reverse_lazy('coip:activity_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Activité créée.")
        return super().form_valid(form)


class ActivityUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = Activity
    form_class = ActivityForm
    template_name = 'coip/activity_form.html'
    success_url = reverse_lazy('coip:activity_list')

    def form_valid(self, form):
        messages.success(self.request, "Activité mise à jour.")
        return super().form_valid(form)


class ActivityDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = Activity
    template_name = 'coip/activity_confirm_delete.html'
    success_url = reverse_lazy('coip:activity_list')

    def form_valid(self, form):
        messages.success(self.request, "Activité supprimée.")
        return super().form_valid(form)


# ── Auto-inscription (enseignants et étudiants) ─────────────────────────────

@login_required
def activities_browse(request):
    now = timezone.now()
    qs = Activity.objects.filter(date_debut__gte=now, status=Activity.STATUT_PLANIFIE).order_by('date_debut')
    registered_ids = set(
        ActivityParticipant.objects.filter(user=request.user).values_list('activity_id', flat=True)
    )
    return render(request, 'coip/activities_browse.html', {'activities': qs, 'registered_ids': registered_ids})


@login_required
def activity_register(request, pk):
    activity = get_object_or_404(Activity, pk=pk)
    if request.method == 'POST':
        ActivityParticipant.objects.get_or_create(activity=activity, user=request.user)
        messages.success(request, "Inscription enregistrée.")
    return redirect('coip:activities_browse')


@login_required
def activity_unregister(request, pk):
    if request.method == 'POST':
        ActivityParticipant.objects.filter(activity_id=pk, user=request.user).delete()
        messages.success(request, "Désinscription effectuée.")
    return redirect('coip:activities_browse')
