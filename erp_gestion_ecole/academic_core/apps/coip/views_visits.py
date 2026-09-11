from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import EducationalVisitForm
from .models import EducationalVisit, VisitParticipant
from .permissions import CoipStaffRequiredMixin, coip_staff_required


@coip_staff_required
def visit_list(request):
    qs = EducationalVisit.objects.select_related('responsable').order_by('-date_depart')
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/visit_list.html', {
        'visits': qs,
        'status_choices': EducationalVisit.STATUT_CHOICES,
        'selected_status': status or '',
    })


@coip_staff_required
def visit_detail(request, pk):
    visit = get_object_or_404(EducationalVisit.objects.select_related('responsable'), pk=pk)
    return render(request, 'coip/visit_detail.html', {
        'visit': visit,
        'participants': visit.participants.select_related('user').all(),
    })


@coip_staff_required
def visit_participant_toggle(request, pk, participant_pk, field):
    if field not in ('present', 'autorisation'):
        return redirect('coip:visit_detail', pk=pk)
    participant = get_object_or_404(VisitParticipant, pk=participant_pk, visit_id=pk)
    if request.method == 'POST':
        setattr(participant, field, not getattr(participant, field))
        participant.save(update_fields=[field])
    return redirect('coip:visit_detail', pk=pk)


@coip_staff_required
def visit_participant_remove(request, pk, participant_pk):
    participant = get_object_or_404(VisitParticipant, pk=participant_pk, visit_id=pk)
    if request.method == 'POST':
        participant.delete()
        messages.success(request, 'Participant retiré.')
    return redirect('coip:visit_detail', pk=pk)


class VisitCreateView(CoipStaffRequiredMixin, CreateView):
    model = EducationalVisit
    form_class = EducationalVisitForm
    template_name = 'coip/visit_form.html'
    success_url = reverse_lazy('coip:visit_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Sortie pédagogique créée.")
        return super().form_valid(form)


class VisitUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = EducationalVisit
    form_class = EducationalVisitForm
    template_name = 'coip/visit_form.html'
    success_url = reverse_lazy('coip:visit_list')

    def form_valid(self, form):
        messages.success(self.request, "Sortie pédagogique mise à jour.")
        return super().form_valid(form)


class VisitDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = EducationalVisit
    template_name = 'coip/visit_confirm_delete.html'
    success_url = reverse_lazy('coip:visit_list')

    def form_valid(self, form):
        messages.success(self.request, "Sortie pédagogique supprimée.")
        return super().form_valid(form)


# ── Auto-inscription (enseignants et étudiants) ─────────────────────────────

@login_required
def visits_browse(request):
    now = timezone.now()
    qs = EducationalVisit.objects.filter(date_depart__gte=now, status__in=(
        EducationalVisit.STATUT_PLANIFIE, EducationalVisit.STATUT_VALIDE,
    )).order_by('date_depart')
    registered_ids = set(
        VisitParticipant.objects.filter(user=request.user).values_list('visit_id', flat=True)
    )
    return render(request, 'coip/visits_browse.html', {'visits': qs, 'registered_ids': registered_ids})


@login_required
def visit_register(request, pk):
    visit = get_object_or_404(EducationalVisit, pk=pk)
    if request.method == 'POST':
        if visit.places_restantes <= 0:
            messages.error(request, "Cette sortie n'a plus de places disponibles.")
        else:
            VisitParticipant.objects.get_or_create(visit=visit, user=request.user)
            messages.success(request, "Inscription enregistrée.")
    return redirect('coip:visits_browse')


@login_required
def visit_unregister(request, pk):
    if request.method == 'POST':
        VisitParticipant.objects.filter(visit_id=pk, user=request.user).delete()
        messages.success(request, "Désinscription effectuée.")
    return redirect('coip:visits_browse')
