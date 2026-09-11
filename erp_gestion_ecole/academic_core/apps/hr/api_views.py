from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import FichePersonnel, Contract, DemandeConge
from .serializers import FichePersonnelSerializer, ContractSerializer, DemandeCongeSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class FichePersonnelViewSet(viewsets.ReadOnlyModelViewSet):
    """Fiches personnel (informations contractuelles) — lecture seule, réservé RH/admin."""
    queryset = FichePersonnel.objects.select_related('user').order_by('user__last_name')
    serializer_class = FichePersonnelSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['type_contrat']


class ContractViewSet(viewsets.ReadOnlyModelViewSet):
    """Contrats de travail — lecture seule, données salariales sensibles."""
    queryset = Contract.objects.select_related('user').order_by('-date_debut')
    serializer_class = ContractSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['type_contrat', 'statut', 'user']


class DemandeCongeViewSet(viewsets.ReadOnlyModelViewSet):
    """Demandes de congé — lecture seule."""
    queryset = DemandeConge.objects.select_related('user').order_by('-created_at')
    serializer_class = DemandeCongeSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['type_conge', 'statut', 'user']
