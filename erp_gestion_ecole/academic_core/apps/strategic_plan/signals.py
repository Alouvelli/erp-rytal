"""
Recalcul en cascade du taux d'avancement à chaque sauvegarde/suppression
d'une SousActivite ou d'une Activite (voir services.py).
"""
import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='strategic_plan.SousActivite')
@receiver(post_delete, sender='strategic_plan.SousActivite')
def on_sous_activite_change(sender, instance, **kwargs):
    from .services import recompute_activite_avancement
    try:
        recompute_activite_avancement(instance.activite)
    except Exception:
        logger.exception('Échec recalcul avancement Activite depuis SousActivite pk=%s', instance.pk)


@receiver(post_save, sender='strategic_plan.Activite')
@receiver(post_delete, sender='strategic_plan.Activite')
def on_activite_change(sender, instance, **kwargs):
    from .services import recompute_projet_avancement
    try:
        recompute_projet_avancement(instance.projet)
    except Exception:
        logger.exception('Échec recalcul avancement Projet depuis Activite pk=%s', instance.pk)
