from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import DemandeAchat, CommandeAchat, FactureAchat
from .serializers import DemandeAchatSerializer, CommandeAchatSerializer, FactureAchatSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class DemandeAchatViewSet(viewsets.ReadOnlyModelViewSet):
    """Demandes d'achat — lecture seule, données financières."""
    queryset = DemandeAchat.objects.select_related('centre_cout', 'demandeur').order_by('-date_demande')
    serializer_class = DemandeAchatSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['statut', 'type_depense', 'centre_cout']


class CommandeAchatViewSet(viewsets.ReadOnlyModelViewSet):
    """Commandes d'achat — lecture seule, données financières."""
    queryset = CommandeAchat.objects.select_related('fournisseur', 'demande_achat').order_by('-date_commande')
    serializer_class = CommandeAchatSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['statut', 'fournisseur']


class FactureAchatViewSet(viewsets.ReadOnlyModelViewSet):
    """Factures d'achat — lecture seule, données financières."""
    queryset = FactureAchat.objects.select_related('commande').order_by('-created_at')
    serializer_class = FactureAchatSerializer
    permission_classes = [IsAdminOrResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['statut', 'commande']
