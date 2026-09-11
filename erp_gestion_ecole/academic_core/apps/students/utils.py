SELECTED_YEAR_SESSION_KEY = 'student_selected_year_id'


def resolve_student_year(request, student, param='annee'):
    """
    Résout (années disponibles, année sélectionnée, inscription) pour le
    sélecteur d'année académique côté étudiant.

    Même esprit que academic_structure.utils.resolve_academic_years, mais
    scopé aux années où CET étudiant a réellement une inscription validée
    (pas toutes les années de l'institut) — un étudiant ne doit voir que son
    propre historique (année en cours + années précédentes de réinscription).

    Le choix est lu depuis le paramètre GET `param` si fourni et valide,
    sinon depuis la session (persistance entre les pages « Mes X »), sinon
    l'année courante. Il est toujours réécrit en session pour que la
    navigation vers une autre page conserve le même choix sans avoir à
    propager `?annee=` sur chaque lien.
    """
    from academic_core.apps.academic_structure.models import AcademicYear
    from .models import Enrollment

    years = AcademicYear.objects.filter(
        pk__in=Enrollment.objects.filter(
            student=student, status=Enrollment.STATUS_VALIDATED
        ).values('academic_year')
    ).order_by('-start_date').distinct()

    year_id = request.GET.get(param)
    selected = years.filter(pk=year_id).first() if year_id else None

    if not selected:
        session_year_id = request.session.get(SELECTED_YEAR_SESSION_KEY)
        selected = years.filter(pk=session_year_id).first() if session_year_id else None

    if not selected:
        selected = years.filter(is_current=True).first() or years.first()

    if selected:
        request.session[SELECTED_YEAR_SESSION_KEY] = selected.pk

    enrollment = student.enrollment_for_year(selected) if selected else None
    return selected, years, enrollment
