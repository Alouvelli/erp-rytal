"""
Signals pour teachers.

- Dès qu'un TimetableEntry actif est enregistré pour un enseignant, on
  s'assure qu'un ContratEnseignant existe pour son (département, année
  académique) — le contenu du contrat (tableau des modules) est toujours
  recalculé en direct, ce get_or_create ne fait que garantir l'existence
  du contrat lui-même.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='timetable.TimetableEntry')
def sync_contrat_on_timetable_entry(sender, instance, **kwargs):
    if not instance.is_active or not instance.teacher_id:
        return

    department = getattr(instance.class_group.program, 'department', None) if instance.class_group_id else None
    academic_year = getattr(instance.semester, 'academic_year', None) if instance.semester_id else None
    if not department or not academic_year:
        return

    from .services import ensure_contrat
    try:
        ensure_contrat(instance.teacher, department, academic_year)
    except Exception:
        logger.exception(
            'Échec création automatique du contrat pour teacher=%s department=%s',
            instance.teacher_id, department.pk,
        )
