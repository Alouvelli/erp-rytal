from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import Projet, PlanTravailAnnuel
from .serializers import ProjetSerializer, PlanTravailAnnuelSerializer


class ProjetViewSet(viewsets.ReadOnlyModelViewSet):
    """Projets du Plan Stratégique de Développement — lecture seule."""
    queryset = Projet.objects.select_related('programme', 'responsable').order_by('-date_debut', 'code')
    serializer_class = ProjetSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['programme', 'statut']


class PlanTravailAnnuelViewSet(viewsets.ReadOnlyModelViewSet):
    """Plans de Travail Annuels — lecture seule."""
    queryset = PlanTravailAnnuel.objects.select_related(
        'academic_year', 'titulaire', 'direction'
    ).order_by('-academic_year__start_date')
    serializer_class = PlanTravailAnnuelSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['academic_year', 'direction', 'titulaire']
