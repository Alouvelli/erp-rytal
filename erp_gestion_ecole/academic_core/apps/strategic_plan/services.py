"""
Recalcul en cascade du taux d'avancement : SousActivite -> Activite -> Projet.

Miroir de apps/strategic_plan/services.py du projet de référence.
"""


def recompute_activite_avancement(activite):
    """Taux d'avancement d'une Activite = moyenne des SousActivite (0 si aucune)."""
    sous_activites = list(activite.sous_activites.all())
    if sous_activites:
        taux = round(sum(s.taux_avancement for s in sous_activites) / len(sous_activites))
    else:
        taux = 0
    if activite.taux_avancement != taux:
        activite.taux_avancement = taux
        activite.save(update_fields=['taux_avancement'])
    recompute_projet_avancement(activite.projet)


def recompute_projet_avancement(projet):
    """Taux d'avancement d'un Projet = moyenne de ses Activite (0 si aucune)."""
    activites = list(projet.activites.all())
    if activites:
        taux = round(sum(a.taux_avancement for a in activites) / len(activites))
    else:
        taux = 0
    if projet.taux_avancement != taux:
        projet.taux_avancement = taux
        projet.save(update_fields=['taux_avancement'])
