"""
Sauvegarde/suppression d'une ValeurIndicateur -> Indicateur.valeur_actuelle
est resynchronisée sur la mesure la plus récente (par date_mesure).
"""
import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='indicators.ValeurIndicateur')
@receiver(post_delete, sender='indicators.ValeurIndicateur')
def on_valeur_change(sender, instance, **kwargs):
    from .models import Indicateur
    try:
        indicateur = instance.indicateur
        derniere = indicateur.historique.order_by('-date_mesure').first()
        nouvelle_valeur = derniere.valeur if derniere else 0
        if indicateur.valeur_actuelle != nouvelle_valeur:
            indicateur.valeur_actuelle = nouvelle_valeur
            indicateur.save(update_fields=['valeur_actuelle'])
    except Exception:
        logger.exception('Échec resynchronisation Indicateur.valeur_actuelle pour ValeurIndicateur pk=%s', instance.pk)
