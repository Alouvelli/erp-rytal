from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import CaisseMovement, DemandeDepense, LigneBudgetaire
from .serializers import CaisseMovementSerializer, DemandeDepenseSerializer, LigneBudgetaireSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class CaisseMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """Mouvements de caisse (entrées/sorties) — lecture seule, données financières sensibles."""
    queryset = CaisseMovement.objects.select_related('direction').order_by('-movement_date', '-created_at')
    serializer_class = CaisseMovementSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['movement_type', 'categorie', 'direction', 'is_executed']


class DemandeDepenseViewSet(viewsets.ReadOnlyModelViewSet):
    """Demandes de dépense — lecture seule, données financières sensibles."""
    queryset = DemandeDepense.objects.select_related('direction', 'ligne_budgetaire').order_by('-requested_at')
    serializer_class = DemandeDepenseSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['statut', 'direction', 'categorie']


class LigneBudgetaireViewSet(viewsets.ReadOnlyModelViewSet):
    """Lignes budgétaires (suivi budgétaire par direction) — lecture seule, données financières sensibles."""
    queryset = LigneBudgetaire.objects.select_related(
        'direction', 'compte_comptable', 'academic_year'
    ).order_by('-academic_year__start_date', 'direction')
    serializer_class = LigneBudgetaireSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['academic_year', 'direction', 'nature']
