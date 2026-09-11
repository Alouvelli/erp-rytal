"""Contrôle d'accès de l'onglet COIP.

Deux paliers de permission calqués sur le motif déjà établi pour les autres
"Directions" (voir community_service/views.py::_SC_ROLES) :

- accès "staff" (saisie quotidienne : Alumni, Activités, Sorties, Stages,
  Orientation, Archives) — Responsable COIP, Personnel COIP, et les rôles de
  supervision globale habituels.
- accès "responsable" (zones sensibles : Partenariats/conventions, Rapports)
  — Responsable COIP uniquement, plus les mêmes rôles de supervision globale
  (PAS le Personnel COIP, motif identique à ADMIN_DE/ASSISTANTE_DE où les
  rôles "Assistante" sont exclus des zones les plus sensibles).

Contrairement à GestionCOIP (audit : de nombreuses vues `edit` n'y étaient
pas protégées), CHAQUE vue create/edit/delete de chaque sous-module doit
utiliser l'un de ces deux décorateurs — jamais laissée ouverte."""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

_SUPERVISION_ROLES = (
    'ADMIN', 'INST_ADMIN', 'SI_ADMIN', 'ASSISTANTE_DG',
    'ADMIN_DIRECTION', 'ASSISTANTE_DIRECTION', 'CONTROLEUR', 'CIAQ',
)

COIP_STAFF_ROLES = _SUPERVISION_ROLES + ('COIP', 'ASSISTANTE_COIP')
COIP_RESPONSABLE_ROLES = _SUPERVISION_ROLES + ('COIP',)


def _user_role_in(user, roles):
    return bool(user.is_authenticated and user.role and user.role.name in roles)


def is_coip_staff(user):
    return _user_role_in(user, COIP_STAFF_ROLES)


def is_coip_responsable_access(user):
    return _user_role_in(user, COIP_RESPONSABLE_ROLES)


def coip_staff_required(view_func):
    """Alumni, Activités, Sorties, Stages, Orientation, Archives : saisie quotidienne."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if is_coip_staff(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Accès refusé : permissions insuffisantes.")
        return redirect('dashboard:index')
    return wrapper


def coip_responsable_required(view_func):
    """Partenariats/conventions, Rapports : zones sensibles, Responsable COIP uniquement."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if is_coip_responsable_access(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Accès refusé : réservé au Responsable COIP.")
        return redirect('dashboard:index')
    return wrapper


class CoipStaffRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not is_coip_staff(request.user):
            messages.error(request, "Accès refusé : permissions insuffisantes.")
            return redirect('dashboard:index')
        return super().dispatch(request, *args, **kwargs)


class CoipResponsableRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not is_coip_responsable_access(request.user):
            messages.error(request, "Accès refusé : réservé au Responsable COIP.")
            return redirect('dashboard:index')
        return super().dispatch(request, *args, **kwargs)


def get_student_for_user(user):
    """Résout la fiche Student du user connecté (vues étudiant : mes
    recommandations, mes séances d'orientation, mes candidatures…), ou None
    si le compte n'a pas de dossier étudiant (ex. déjà diplômé et jamais
    ré-inscrit — cf. la vue de conversion en fiche Alumni pour ce cas)."""
    return getattr(user, 'student_profile', None)
