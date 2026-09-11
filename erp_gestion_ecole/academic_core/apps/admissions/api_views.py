from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import Candidature
from .serializers import CandidatureSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class CandidatureViewSet(viewsets.ReadOnlyModelViewSet):
    """Candidatures déposées sur le portail d'admission — lecture seule."""
    queryset = Candidature.objects.select_related('user', 'program').order_by('-submitted_at')
    serializer_class = CandidatureSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['status', 'program', 'niveau_entree']
