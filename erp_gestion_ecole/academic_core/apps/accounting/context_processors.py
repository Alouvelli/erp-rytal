def pending_inscriptions_count(request):
    """
    Badge de notification sur le lien sidebar « Validation Inscription » —
    nombre total d'inscriptions en attente d'une action, tous statuts
    « En attente » (côté Trésorier) et « À la caisse » (côté Caissier)
    confondus, dans le périmètre (institut actif) de l'utilisateur courant.
    Ne calcule rien pour les utilisateurs sans accès à cette fonctionnalité
    (même garde que accounting/views.py::_require_inscription_access), pour
    ne pas ajouter de requête inutile sur chaque page vue par un enseignant
    ou un étudiant.
    """
    if not request.user.is_authenticated:
        return {'pending_inscriptions_count': 0}

    user = request.user
    if not (user.is_admin() or user.is_responsable()):
        return {'pending_inscriptions_count': 0}

    try:
        from academic_core.apps.students.models import Enrollment

        global_view = user.is_controleur() or user.is_comptable()
        faculty = None if global_view else getattr(request, 'active_faculty', None)

        qs = Enrollment.objects.filter(
            status__in=(Enrollment.STATUS_PENDING, Enrollment.STATUS_PENDING_CAISSE),
        )
        if faculty:
            qs = qs.filter(class_group__program__department__faculty=faculty)
        count = qs.count()
    except Exception:
        count = 0

    return {'pending_inscriptions_count': count}
