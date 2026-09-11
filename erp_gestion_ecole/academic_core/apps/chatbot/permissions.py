"""
Frontière de sécurité de RYTAL : quel rôle a le droit d'utiliser quel outil.

Allowlist EXPLICITE par constante de Role — volontairement PAS
`user.is_admin()` / `user.can_manage_dept()` / `user.is_inst_admin()`, qui
regroupent aussi CIAQ/CONTROLEUR/COMPTABLE/TRESORIER_GENERAL/CAISSIER/
ADMIN_DIRECTION (cf. academic_core/apps/accounts/models.py:208-232) : ces
rôles doivent rester en aide générique (+ notifications) tant que leurs
outils dédiés ne sont pas ajoutés.

Pour ajouter des outils à un rôle : créer `tools/xxx_tools.py`, puis ajouter
une entrée ci-dessous. Aucune autre modification requise.
"""
from academic_core.apps.accounts.models import Role
from .tools import TOOL_REGISTRY

# Outil universel : chaque rôle a sa propre boîte de notifications (onglet
# NOTIFICATIONS présent pour tout le monde dans l'interface), donc offert à
# absolument tous les rôles plutôt que de laisser certains sans aucun outil.
_UNIVERSAL_TOOLS = (
    'get_my_notifications',
)

_ADMIN_TIER_TOOLS = _UNIVERSAL_TOOLS + (
    'get_department_timetable',
    'get_department_grades_summary',
    'get_department_attendance_summary',
    'get_department_pending_cancellations',
    'get_department_enrollment_summary',
)

# Outils à l'échelle de l'institut entier (RH, finance, utilisateurs) —
# réservés aux rôles qui administrent l'institut dans son ensemble
# (INST_ADMIN/SI_ADMIN, ASSISTANTE_DG, et le Super Admin quand il "visite" un
# institut), pas aux rôles de palier département (RESPONSABLE, ASSISTANTE),
# qui n'ont pas accès à ces onglets dans l'interface. Les annulations/
# inscriptions sont déjà couvertes par _ADMIN_TIER_TOOLS (get_department_*
# gère aussi bien le département que l'institut entier selon la sélection
# active), donc pas dupliquées ici.
_INSTITUT_ADMIN_TOOLS = _ADMIN_TIER_TOOLS + (
    'get_institut_overview',
    'get_institut_users_summary',
    'get_institut_finance_summary',
)

# Outils de gestion globale (aucun institut/département requis) — Super Admin
# uniquement, en plus des outils ci-dessus (utiles quand il "visite" un
# institut via active_faculty).
_SUPER_ADMIN_GLOBAL_TOOLS = (
    'list_institutes',
    'list_institut_admins',
)

ROLE_TOOL_NAMES = {
    Role.ETUDIANT: _UNIVERSAL_TOOLS + (
        'get_my_timetable', 'get_my_grades', 'get_my_bulletin', 'get_my_absences',
        'get_my_course_supports',
    ),
    Role.ENSEIGNANT: _UNIVERSAL_TOOLS + (
        'get_my_teaching_timetable', 'get_my_classes', 'get_my_session_log', 'get_class_attendance_summary',
        'get_my_honoraires', 'get_my_contract', 'get_my_extra_requests', 'get_my_shared_course_supports',
    ),
    Role.RESPONSABLE: _ADMIN_TIER_TOOLS,
    Role.ASSISTANTE: _ADMIN_TIER_TOOLS,
    Role.INST_ADMIN: _INSTITUT_ADMIN_TOOLS,
    Role.ADMIN: _INSTITUT_ADMIN_TOOLS + _SUPER_ADMIN_GLOBAL_TOOLS,
    Role.ASSISTANTE_DG: _INSTITUT_ADMIN_TOOLS,
    # Rôles sans outil dédié pour l'instant : au moins l'outil universel
    # (notifications) plutôt qu'une aide 100% générique.
    Role.SI_ADMIN: _UNIVERSAL_TOOLS,
    Role.ADMIN_DIRECTION: _UNIVERSAL_TOOLS,
    Role.ADMIN_DE: _UNIVERSAL_TOOLS,
    Role.ADMIN_DAF: _UNIVERSAL_TOOLS,
    Role.ADMIN_COM: _UNIVERSAL_TOOLS,
    Role.ADMIN_RH: _UNIVERSAL_TOOLS,
    Role.ASSISTANTE_DIRECTION: _UNIVERSAL_TOOLS,
    Role.ASSISTANTE_DE: _UNIVERSAL_TOOLS,
    Role.CIAQ: _UNIVERSAL_TOOLS,
    Role.CONTROLEUR: _UNIVERSAL_TOOLS,
    Role.COMPTABLE: _UNIVERSAL_TOOLS,
    Role.TRESORIER_GENERAL: _UNIVERSAL_TOOLS,
    Role.CAISSIER: _UNIVERSAL_TOOLS,
    Role.CHARGE_EXAMENS_CONCOURS: _UNIVERSAL_TOOLS,
    Role.CONTROLE_ACCUEIL: _UNIVERSAL_TOOLS,
}


def get_allowed_tool_names(user):
    return ROLE_TOOL_NAMES.get(user.role_name, _UNIVERSAL_TOOLS)


def get_allowed_tool_schemas(user):
    return [
        TOOL_REGISTRY[name]['schema']
        for name in get_allowed_tool_names(user)
        if name in TOOL_REGISTRY
    ]


def get_tool_handler(name, user):
    """Revalide l'allowlist du rôle avant d'exécuter — défense en profondeur,
    même si seuls les schémas autorisés ont été proposés au modèle."""
    if name not in get_allowed_tool_names(user):
        return None
    entry = TOOL_REGISTRY.get(name)
    return entry['handler'] if entry else None
