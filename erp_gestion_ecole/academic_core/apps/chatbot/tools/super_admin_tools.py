"""
Outils RYTAL réservés au Super Admin (ADMIN) en mode gestion globale (aucun
institut sélectionné) : liste des instituts et de leurs administrateurs.
Distincts des outils du palier admin_tools.py, qui supposent un département/
institut déjà sélectionné (mode « visite » d'un institut par le Super Admin).
"""
from academic_core.apps.academic_structure.models import InstitutConfig
from academic_core.apps.accounts.models import User, Role
from .registry import register_tool


@register_tool('list_institutes', {
    'name': 'list_institutes',
    'description': (
        "Retourne la liste de tous les instituts de la plateforme, avec leur "
        "statut (actif/suspendu) et leur statut d'abonnement."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def list_institutes(user, request):
    configs = InstitutConfig.objects.select_related('faculty').order_by('nom')
    rows = []
    for c in configs:
        abonnement = c.abonnements.first()
        rows.append({
            'nom': c.nom or (c.faculty.name if c.faculty else '—'),
            'sigle': c.sigle or '—',
            'actif': c.actif,
            'abonnement_statut': abonnement.get_statut_display() if abonnement else 'Aucun',
        })
    return {'instituts': rows}


@register_tool('list_institut_admins', {
    'name': 'list_institut_admins',
    'description': (
        "Retourne la liste des administrateurs d'institut (INST_ADMIN/SI_ADMIN) "
        "de la plateforme, avec leur institut de rattachement."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def list_institut_admins(user, request):
    admins = (
        User.objects.filter(role__name__in=[Role.INST_ADMIN, Role.SI_ADMIN])
        .select_related('role', 'institut_config')
        .order_by('last_name', 'first_name')
    )
    return {'admins': [
        {
            'nom': a.get_full_name() or a.username,
            'email': a.email,
            'institut': a.institut_config.nom if a.institut_config else '—',
            'role': a.role.get_name_display() if a.role else '—',
        }
        for a in admins
    ]}
