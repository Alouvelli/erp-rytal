from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import InternshipForm, InternshipOfferForm
from .models import Internship, InternshipOffer
from .permissions import CoipStaffRequiredMixin, coip_staff_required


# ── Offres de stage ──────────────────────────────────────────────────────────

@coip_staff_required
def offer_list(request):
    qs = InternshipOffer.objects.select_related('partner', 'filiere_cible').order_by('-created_at')
    q = request.GET.get('q')
    status = request.GET.get('status')
    if q:
        qs = qs.filter(Q(titre__icontains=q) | Q(partner__raison_sociale__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/offer_list.html', {
        'offers': qs,
        'status_choices': InternshipOffer.STATUT_CHOICES,
        'selected_status': status or '',
    })


class OfferCreateView(CoipStaffRequiredMixin, CreateView):
    model = InternshipOffer
    form_class = InternshipOfferForm
    template_name = 'coip/offer_form.html'
    success_url = reverse_lazy('coip:offer_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Offre de stage créée.")
        return super().form_valid(form)


class OfferUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = InternshipOffer
    form_class = InternshipOfferForm
    template_name = 'coip/offer_form.html'
    success_url = reverse_lazy('coip:offer_list')

    def form_valid(self, form):
        messages.success(self.request, "Offre de stage mise à jour.")
        return super().form_valid(form)


class OfferDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = InternshipOffer
    template_name = 'coip/offer_confirm_delete.html'
    success_url = reverse_lazy('coip:offer_list')

    def form_valid(self, form):
        messages.success(self.request, "Offre de stage supprimée.")
        return super().form_valid(form)


# ── Stages (affectations) ────────────────────────────────────────────────────

@coip_staff_required
def internship_list(request):
    qs = Internship.objects.select_related('student__user', 'partner', 'encadreur_isi').order_by('-date_debut')
    q = request.GET.get('q')
    status = request.GET.get('status')
    if q:
        qs = qs.filter(
            Q(titre__icontains=q) | Q(student__user__first_name__icontains=q)
            | Q(student__user__last_name__icontains=q) | Q(partner__raison_sociale__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/internship_list.html', {
        'internships': qs,
        'status_choices': Internship.STATUT_CHOICES,
        'selected_status': status or '',
    })


class InternshipCreateView(CoipStaffRequiredMixin, CreateView):
    model = Internship
    form_class = InternshipForm
    template_name = 'coip/internship_form.html'
    success_url = reverse_lazy('coip:internship_list')

    def form_valid(self, form):
        messages.success(self.request, "Stage enregistré.")
        return super().form_valid(form)


class InternshipUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = Internship
    form_class = InternshipForm
    template_name = 'coip/internship_form.html'
    success_url = reverse_lazy('coip:internship_list')

    def form_valid(self, form):
        messages.success(self.request, "Stage mis à jour.")
        return super().form_valid(form)


class InternshipDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = Internship
    template_name = 'coip/internship_confirm_delete.html'
    success_url = reverse_lazy('coip:internship_list')

    def form_valid(self, form):
        messages.success(self.request, "Stage supprimé.")
        return super().form_valid(form)
