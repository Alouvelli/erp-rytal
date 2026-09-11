from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import Risque
from .serializers import RisqueSerializer


class RisqueViewSet(viewsets.ReadOnlyModelViewSet):
    """Cartographie des risques — lecture seule."""
    queryset = Risque.objects.select_related('responsable').order_by('-gravite', '-probabilite')
    serializer_class = RisqueSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['categorie', 'statut']
