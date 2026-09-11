from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import CritereQualite, PlanAmelioration
from .serializers import CritereQualiteSerializer, PlanAmeliorationSerializer


class CritereQualiteViewSet(viewsets.ReadOnlyModelViewSet):
    """Critères qualité (référentiels CAMES / ANAQ-Sup) — lecture seule."""
    queryset = CritereQualite.objects.order_by('referentiel', 'code')
    serializer_class = CritereQualiteSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['referentiel']


class PlanAmeliorationViewSet(viewsets.ReadOnlyModelViewSet):
    """Plans d'amélioration qualité — lecture seule."""
    queryset = PlanAmelioration.objects.select_related('critere', 'responsable').order_by('date_echeance')
    serializer_class = PlanAmeliorationSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['statut', 'critere']
