from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import AlumniCareerEventForm, AlumniForm
from .models import Alumni, AlumniCareerEvent
from .permissions import CoipStaffRequiredMixin, coip_staff_required


@coip_staff_required
def alumni_list(request):
    qs = Alumni.objects.select_related('filiere').order_by('-annee_obtention', 'last_name')
    q = request.GET.get('q')
    secteur = request.GET.get('secteur')
    promotion = request.GET.get('promotion')
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(entreprise_actuelle__icontains=q) | Q(poste_occupe__icontains=q)
        )
    if secteur:
        qs = qs.filter(secteur_activite=secteur)
    if promotion:
        qs = qs.filter(promotion=promotion)
    return render(request, 'coip/alumni_list.html', {
        'alumni_list': qs,
        'secteur_choices': Alumni.SECTEUR_CHOICES,
        'promotions': Alumni.objects.exclude(promotion='').values_list('promotion', flat=True).distinct().order_by('-promotion'),
        'selected_secteur': secteur or '',
        'selected_promotion': promotion or '',
    })


@coip_staff_required
def alumni_detail(request, pk):
    alumni = get_object_or_404(Alumni.objects.select_related('filiere', 'student'), pk=pk)
    return render(request, 'coip/alumni_detail.html', {
        'alumni': alumni,
        'career_events': alumni.career_events.all(),
        'career_event_form': AlumniCareerEventForm(),
    })


@coip_staff_required
def alumni_career_event_add(request, pk):
    alumni = get_object_or_404(Alumni, pk=pk)
    if request.method == 'POST':
        form = AlumniCareerEventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.alumni = alumni
            event.save()
            messages.success(request, 'Événement de carrière ajouté.')
        else:
            messages.error(request, "Formulaire invalide.")
    return redirect('coip:alumni_detail', pk=alumni.pk)


@coip_staff_required
def alumni_career_event_delete(request, pk, event_pk):
    event = get_object_or_404(AlumniCareerEvent, pk=event_pk, alumni_id=pk)
    if request.method == 'POST':
        event.delete()
        messages.success(request, 'Événement de carrière supprimé.')
    return redirect('coip:alumni_detail', pk=pk)


class AlumniCreateView(CoipStaffRequiredMixin, CreateView):
    model = Alumni
    form_class = AlumniForm
    template_name = 'coip/alumni_form.html'
    success_url = reverse_lazy('coip:alumni_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Fiche alumni créée.')
        return super().form_valid(form)


class AlumniUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = Alumni
    form_class = AlumniForm
    template_name = 'coip/alumni_form.html'
    success_url = reverse_lazy('coip:alumni_list')

    def form_valid(self, form):
        messages.success(self.request, 'Fiche alumni mise à jour.')
        return super().form_valid(form)


class AlumniDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = Alumni
    template_name = 'coip/alumni_confirm_delete.html'
    success_url = reverse_lazy('coip:alumni_list')

    def form_valid(self, form):
        messages.success(self.request, 'Fiche alumni supprimée.')
        return super().form_valid(form)
