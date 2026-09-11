from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Indicateur
from .serializers import IndicateurSerializer, ValeurIndicateurSerializer


class IndicateurViewSet(viewsets.ReadOnlyModelViewSet):
    """Indicateurs KPI (Balanced Scorecard) — lecture seule."""
    queryset = Indicateur.objects.select_related('responsable').order_by('code')
    serializer_class = IndicateurSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['periodicite', 'sens_amelioration']

    @action(detail=True, methods=['get'])
    def historique(self, request, pk=None):
        indicateur = self.get_object()
        serializer = ValeurIndicateurSerializer(indicateur.historique.all(), many=True)
        return Response(serializer.data)
