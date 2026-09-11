from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import CommunityServiceActivity
from .serializers import CommunityServiceActivitySerializer


class CommunityServiceActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """Activités du service à la communauté — lecture seule."""
    queryset = CommunityServiceActivity.objects.select_related('responsable').order_by('-date_debut')
    serializer_class = CommunityServiceActivitySerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['categorie', 'statut']
