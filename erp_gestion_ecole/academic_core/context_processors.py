from academic_core.apps.academic_structure.models import Department


def _user_institut_config(user):
    """Accès sûr à user.institut_config.

    getattr(user, 'institut_config', None) ne suffit PAS : quand la FK
    institut_config_id est renseignée mais que la ligne cible est absente de la
    base courante (cas d'un INST_ADMIN dont la config maître n'existe pas dans
    la base de session), l'accès lève RelatedObjectDoesNotExist — qui n'est pas
    un AttributeError, donc le défaut de getattr ne l'intercepte pas et la
    requête plante en 500. On rattrape ici pour retourner None proprement.
    """
    try:
        return user.institut_config
    except Exception:
        return None


def _get_institut_config(faculty):
    """Retourne l'InstitutConfig pour une faculté donnée, ou None."""
    if not faculty:
        return None
    try:
        from academic_core.apps.academic_structure.models import InstitutConfig
        return InstitutConfig.objects.using('default').select_related('faculty').get(faculty=faculty)
    except Exception:
        return None


def department_context(request):
    """Expose active_department, active_faculty, institut_config et la liste des départements."""
    faculty = getattr(request, 'active_faculty', None)
    # Fallback : récupérer la faculté depuis le profil si le middleware n'a pas résolu
    if not faculty and request.user.is_authenticated:
        from academic_core.middleware import _user_related
        user = request.user
        dept = _user_related(user, 'department')
        if dept:
            faculty = getattr(dept, 'faculty', None)
        if not faculty:
            direction = _user_related(user, 'direction')
            if direction:
                faculty = getattr(direction, 'faculty', None)
        if not faculty:
            user_cfg = _user_institut_config(user)
            if user_cfg:
                faculty = getattr(user_cfg, 'faculty', None)
    institut_config = _get_institut_config(faculty)
    disabled_tabs = set()
    disabled_features = set()
    if institut_config:
        from academic_core.apps.academic_structure.models import (
            InstitutDisabledTab, InstitutDisabledFeature,
        )
        disabled_tabs = set(
            InstitutDisabledTab.objects.using('default')
            .filter(institut_config=institut_config).values_list('tab_key', flat=True)
        )
        disabled_features = set(
            InstitutDisabledFeature.objects.using('default')
            .filter(institut_config=institut_config).values_list('feature_key', flat=True)
        )
    ctx = {
        'active_department': getattr(request, 'active_department', None),
        'active_faculty':    faculty,
        'all_departments':   [],
        'institut_config':   institut_config,
        'controlled_instituts': [],
        'disabled_tabs':      disabled_tabs,
        'disabled_features':  disabled_features,
    }
    if request.user.is_authenticated:
        user = request.user
        role = getattr(user, 'role_name', '')

        # Contrôleur Interne multi-instituts (ControllerInstitut) : liste des
        # instituts qu'il peut consulter, pour le sélecteur de bascule dans la
        # sidebar (visible seulement si 2+, cf. base.html).
        if role == 'CONTROLEUR':
            try:
                from academic_core.apps.academic_structure.models import InstitutConfig
                ctx['controlled_instituts'] = list(
                    InstitutConfig.objects.using('default')
                    .filter(controller_links__user=user)
                    .exclude(db_alias='').distinct().order_by('nom')
                )
            except Exception:
                pass
        _GLOBAL_ROLES = ('CONTROLEUR', 'COMPTABLE', 'TRESORIER_GENERAL', 'CAISSIER', 'CHARGE_EXAMENS_CONCOURS')
        _is_global = role in _GLOBAL_ROLES
        # is_responsable() couvre RESPONSABLE (Chef de Département) ET ASSISTANTE :
        # les deux doivent voir tous les départements de leur institut dans le
        # sélecteur (mêmes droits partout, pas seulement leur département
        # d'affectation), cf. can_manage_dept().
        if user.is_admin() or user.is_enseignant() or user.is_responsable() \
                or user.is_ciaq() or _is_global:
            qs = Department.objects.filter(is_active=True)
            faculty = ctx['active_faculty']

            # Pour INST_ADMIN : fallback sur leur institut_config si active_faculty non résolu
            if not faculty and user.is_inst_admin():
                config = _user_institut_config(user)
                faculty = getattr(config, 'faculty', None) if config else None

            if faculty:
                qs = qs.filter(faculty=faculty)
            elif user.is_inst_admin() and role not in _GLOBAL_ROLES:
                # INST_ADMIN sans faculté résolue → aucun département dans le dropdown
                qs = qs.none()
            # Rôles globaux (comptable/contrôleur/trésorier/caissier) sans faculty → tous les depts

            ctx['all_departments'] = qs.order_by('name')
    return ctx
