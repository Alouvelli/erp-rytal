from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import CommunityServiceActivity
from .forms import CommunityServiceActivityForm

# ── Rôles autorisés ──────────────────────────────────────────────────────────
# Le responsable du service (ADMIN_SC) plus les rôles de supervision globale
# habituels des autres modules "Direction X" (voir hr/views.py::_HR_ROLES,
# même famille de rôles).
_SC_ROLES = (
    'ADMIN', 'INST_ADMIN', 'SI_ADMIN', 'ASSISTANTE_DG',
    'ADMIN_DIRECTION', 'ADMIN_SC',
    'ASSISTANTE_DIRECTION', 'CONTROLEUR', 'CIAQ',
)


def _sc_required(view_func):
    """Décorateur : accès réservé au responsable Service à la Communauté et
    aux rôles de supervision (super/inst admin, direction, contrôleur)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if request.user.role and request.user.role.name in _SC_ROLES:
            return view_func(request, *args, **kwargs)
        messages.error(request, "Accès refusé : permissions insuffisantes.")
        return redirect('dashboard:index')
    return wrapper


class _SCRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not (request.user.role and request.user.role.name in _SC_ROLES):
            messages.error(request, "Accès refusé : permissions insuffisantes.")
            return redirect('dashboard:index')
        return super().dispatch(request, *args, **kwargs)


class ActivityListView(_SCRequiredMixin, ListView):
    model = CommunityServiceActivity
    template_name = 'community_service/activity_list.html'
    context_object_name = 'activities'

    def get_queryset(self):
        qs = CommunityServiceActivity.objects.select_related('responsable').order_by('-date_debut')
        statut = self.request.GET.get('statut')
        categorie = self.request.GET.get('categorie')
        q = self.request.GET.get('q')
        if statut:
            qs = qs.filter(statut=statut)
        if categorie:
            qs = qs.filter(categorie=categorie)
        if q:
            qs = qs.filter(Q(titre__icontains=q) | Q(lieu__icontains=q) | Q(beneficiaires__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categorie_choices'] = CommunityServiceActivity.CATEGORIE_CHOICES
        ctx['statut_choices'] = CommunityServiceActivity.STATUT_CHOICES
        ctx['selected_statut'] = self.request.GET.get('statut', '')
        ctx['selected_categorie'] = self.request.GET.get('categorie', '')
        return ctx


class ActivityCreateView(_SCRequiredMixin, CreateView):
    model = CommunityServiceActivity
    form_class = CommunityServiceActivityForm
    template_name = 'community_service/activity_form.html'
    success_url = reverse_lazy('community_service:list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        if not form.instance.responsable_id:
            form.instance.responsable = self.request.user
        messages.success(self.request, "Activité enregistrée.")
        return super().form_valid(form)


class ActivityUpdateView(_SCRequiredMixin, UpdateView):
    model = CommunityServiceActivity
    form_class = CommunityServiceActivityForm
    template_name = 'community_service/activity_form.html'
    success_url = reverse_lazy('community_service:list')

    def form_valid(self, form):
        messages.success(self.request, "Activité mise à jour.")
        return super().form_valid(form)


class ActivityDeleteView(_SCRequiredMixin, DeleteView):
    model = CommunityServiceActivity
    template_name = 'community_service/activity_confirm_delete.html'
    success_url = reverse_lazy('community_service:list')

    def form_valid(self, form):
        messages.success(self.request, "Activité supprimée.")
        return super().form_valid(form)
