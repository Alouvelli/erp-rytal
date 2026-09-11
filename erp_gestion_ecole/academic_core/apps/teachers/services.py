"""
Services partagés pour les contrats enseignants — utilisés à la fois par le
signal (nouvelle affectation d'EC) et par la commande de backfill.
"""


def ensure_contrat(teacher, department, academic_year):
    """Crée le ContratEnseignant (teacher, department, academic_year) s'il n'existe pas déjà."""
    from .models import ContratEnseignant
    contrat, _created = ContratEnseignant.objects.get_or_create(
        teacher=teacher, department=department, academic_year=academic_year,
    )
    return contrat


def sync_contracts_for_teacher(teacher):
    """
    Parcourt les TimetableEntry actifs de l'enseignant et s'assure qu'un
    ContratEnseignant existe pour chaque (département, année académique) où
    il intervient actuellement.
    """
    from academic_core.apps.timetable.models import TimetableEntry

    entries = (
        TimetableEntry.objects
        .filter(teacher=teacher, is_active=True)
        .select_related('class_group__program__department', 'semester__academic_year')
    )
    seen = set()
    created = []
    for entry in entries:
        department = getattr(entry.class_group.program, 'department', None)
        academic_year = getattr(entry.semester, 'academic_year', None)
        if not department or not academic_year:
            continue
        key = (department.pk, academic_year.pk)
        if key in seen:
            continue
        seen.add(key)
        contrat = ensure_contrat(teacher, department, academic_year)
        created.append(contrat)
    return created
