"""
Application effective (pas seulement visuelle) des onglets/fonctionnalités
désactivés par institut. Utilisé par FeatureGateMiddleware (academic_core/middleware.py).
"""
from .feature_registry import URL_TO_TAB


def _get_institut_config(request):
    """Réutilise institut_config déjà résolu par department_context si possible,
    sinon le dérive de request.active_faculty (même logique que context_processors.py)."""
    faculty = getattr(request, 'active_faculty', None)
    if not faculty:
        return None
    try:
        from academic_core.apps.academic_structure.models import InstitutConfig
        return InstitutConfig.objects.using('default').filter(faculty=faculty).first()
    except Exception:
        return None


def is_feature_blocked(request, view_name):
    """
    view_name : 'app_label:url_name' résolu via request.resolver_match.
    Retourne True seulement si la fonctionnalité (ou son onglet parent) a été
    explicitement désactivée pour l'institut courant. Toute route non répertoriée
    dans le registre n'est jamais bloquée (permissif par défaut, pour ne jamais
    casser une route non cataloguée).
    """
    if not view_name or view_name not in URL_TO_TAB:
        return False

    institut_config = _get_institut_config(request)
    if not institut_config:
        return False

    tab_key = URL_TO_TAB[view_name]

    from .models import InstitutDisabledTab, InstitutDisabledFeature

    if InstitutDisabledTab.objects.using('default').filter(
        institut_config=institut_config, tab_key=tab_key
    ).exists():
        return True

    if InstitutDisabledFeature.objects.using('default').filter(
        institut_config=institut_config, feature_key=view_name
    ).exists():
        return True

    return False
