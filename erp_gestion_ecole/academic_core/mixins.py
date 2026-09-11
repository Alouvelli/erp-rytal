"""
Mixins transversaux pour le filtrage par département actif.
"""
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages


class DepartmentRequiredMixin:
    """
    Bloque l'accès si aucun département actif n'est sélectionné.
    Le SuperAdmin est redirigé vers la page de sélection.
    Les autres rôles reçoivent un message d'erreur.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.active_department:
            if request.user.is_admin():
                messages.warning(
                    request,
                    "Veuillez sélectionner un département pour accéder à cette fonctionnalité."
                )
                return redirect('academic_structure:select_department')
            else:
                messages.error(
                    request,
                    "Votre compte n'est pas associé à un département. "
                    "Contactez votre administrateur."
                )
                return redirect('dashboard:index')
        return super().dispatch(request, *args, **kwargs)

    def get_department(self):
        return self.request.active_department


class DepartmentFilterMixin:
    """
    Filtre automatiquement les querysets par département actif.
    Utiliser avec DepartmentRequiredMixin.
    Usage: surcharger `department_field` (chemin vers le champ Department dans le modèle).
    """
    department_field = 'department'  # ex: 'program__department' pour Class

    def get_queryset(self):
        qs = super().get_queryset()
        dept = getattr(self.request, 'active_department', None)
        if dept:
            qs = qs.filter(**{self.department_field: dept})
        return qs
