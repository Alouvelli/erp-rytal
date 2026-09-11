from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import (
    CollaborationHistoryForm, PartnerContactForm, PartnerForm, PartnershipForm,
)
from .models import CollaborationHistory, Partner, PartnerContact, Partnership
from .permissions import CoipResponsableRequiredMixin, coip_responsable_required


# ── Partenaires (zone sensible → Responsable COIP, comme les conventions) ──

@coip_responsable_required
def partner_list(request):
    qs = Partner.objects.all().order_by('raison_sociale')
    q = request.GET.get('q')
    type_partenaire = request.GET.get('type')
    if q:
        qs = qs.filter(Q(raison_sociale__icontains=q) | Q(secteur__icontains=q) | Q(ville__icontains=q))
    if type_partenaire:
        qs = qs.filter(type_partenaire=type_partenaire)
    return render(request, 'coip/partner_list.html', {
        'partners': qs,
        'type_choices': Partner.TYPE_CHOICES,
        'selected_type': type_partenaire or '',
    })


@coip_responsable_required
def partner_detail(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    return render(request, 'coip/partner_detail.html', {
        'partner': partner,
        'contacts': partner.contacts.all(),
        'partnerships': partner.partnerships.order_by('-date_signature'),
        'contact_form': PartnerContactForm(),
    })


@coip_responsable_required
def partner_contact_add(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    if request.method == 'POST':
        form = PartnerContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.partner = partner
            contact.save()
            messages.success(request, 'Contact ajouté.')
        else:
            messages.error(request, 'Formulaire invalide.')
    return redirect('coip:partner_detail', pk=partner.pk)


@coip_responsable_required
def partner_contact_delete(request, pk, contact_pk):
    contact = get_object_or_404(PartnerContact, pk=contact_pk, partner_id=pk)
    if request.method == 'POST':
        contact.delete()
        messages.success(request, 'Contact supprimé.')
    return redirect('coip:partner_detail', pk=pk)


class PartnerCreateView(CoipResponsableRequiredMixin, CreateView):
    model = Partner
    form_class = PartnerForm
    template_name = 'coip/partner_form.html'
    success_url = reverse_lazy('coip:partner_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Partenaire créé.')
        return super().form_valid(form)


class PartnerUpdateView(CoipResponsableRequiredMixin, UpdateView):
    model = Partner
    form_class = PartnerForm
    template_name = 'coip/partner_form.html'
    success_url = reverse_lazy('coip:partner_list')

    def form_valid(self, form):
        messages.success(self.request, 'Partenaire mis à jour.')
        return super().form_valid(form)


class PartnerDeleteView(CoipResponsableRequiredMixin, DeleteView):
    model = Partner
    template_name = 'coip/partner_confirm_delete.html'
    success_url = reverse_lazy('coip:partner_list')

    def form_valid(self, form):
        messages.success(self.request, 'Partenaire supprimé.')
        return super().form_valid(form)


# ── Conventions / Partenariats (zone sensible → Responsable COIP) ──────────

@coip_responsable_required
def partnership_list(request):
    qs = Partnership.objects.select_related('partner').order_by('-date_signature')
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/partnership_list.html', {
        'partnerships': qs,
        'status_choices': Partnership.STATUT_CHOICES,
        'selected_status': status or '',
    })


@coip_responsable_required
def partnership_detail(request, pk):
    partnership = get_object_or_404(Partnership.objects.select_related('partner'), pk=pk)
    return render(request, 'coip/partnership_detail.html', {
        'partnership': partnership,
        'history': partnership.collaboration_history.all(),
        'history_form': CollaborationHistoryForm(),
    })


@coip_responsable_required
def partnership_history_add(request, pk):
    partnership = get_object_or_404(Partnership, pk=pk)
    if request.method == 'POST':
        form = CollaborationHistoryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.partnership = partnership
            entry.created_by = request.user
            entry.save()
            messages.success(request, 'Historique de collaboration ajouté.')
        else:
            messages.error(request, 'Formulaire invalide.')
    return redirect('coip:partnership_detail', pk=partnership.pk)


class PartnershipCreateView(CoipResponsableRequiredMixin, CreateView):
    model = Partnership
    form_class = PartnershipForm
    template_name = 'coip/partnership_form.html'
    success_url = reverse_lazy('coip:partnership_list')

    def form_valid(self, form):
        if not form.instance.responsable_id:
            form.instance.responsable = self.request.user
        messages.success(self.request, 'Convention créée.')
        return super().form_valid(form)


class PartnershipUpdateView(CoipResponsableRequiredMixin, UpdateView):
    model = Partnership
    form_class = PartnershipForm
    template_name = 'coip/partnership_form.html'
    success_url = reverse_lazy('coip:partnership_list')

    def form_valid(self, form):
        messages.success(self.request, 'Convention mise à jour.')
        return super().form_valid(form)


class PartnershipDeleteView(CoipResponsableRequiredMixin, DeleteView):
    model = Partnership
    template_name = 'coip/partnership_confirm_delete.html'
    success_url = reverse_lazy('coip:partnership_list')

    def form_valid(self, form):
        messages.success(self.request, 'Convention supprimée.')
        return super().form_valid(form)
