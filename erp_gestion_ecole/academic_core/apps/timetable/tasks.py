"""
Tâches Celery pour les supports de cours.

Règle métier :
  - Un support de cours partagé par un enseignant est automatiquement
    supprimé (fichier + enregistrement) 72 heures après son partage.
"""
import os
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

SUPPORT_EXPIRY_HOURS = 72


@shared_task(name='academic_core.apps.timetable.tasks.cleanup_expired_course_supports')
def cleanup_expired_course_supports():
    """
    Supprime, dans chaque base institut, les supports de cours partagés
    depuis plus de 72 heures (fichier physique + enregistrement).
    """
    from academic_core.apps.academic_structure.models import InstitutConfig
    from .models import CourseSupport

    cutoff = timezone.now() - timedelta(hours=SUPPORT_EXPIRY_HOURS)
    total_deleted = 0

    for config in InstitutConfig.objects.using('default').exclude(db_alias=''):
        alias = config.db_alias
        if not alias or alias == 'default' or alias not in settings.DATABASES:
            continue

        expired = list(CourseSupport.objects.using(alias).filter(shared_at__lt=cutoff))
        deleted_here = 0
        for support in expired:
            try:
                if support.file and os.path.isfile(support.file.path):
                    os.remove(support.file.path)
            except Exception as exc:
                logger.warning("Suppression fichier support %s échouée : %s", support.pk, exc)
            support.delete(using=alias)
            deleted_here += 1

        if deleted_here:
            logger.info("Nettoyage supports expirés (%s) : %d supprimé(s)", alias, deleted_here)
        total_deleted += deleted_here

    return {'deleted': total_deleted}
