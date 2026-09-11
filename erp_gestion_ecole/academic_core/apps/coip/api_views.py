from rest_framework import viewsets
from rest_framework.permissions import BasePermission
from django_filters.rest_framework import DjangoFilterBackend
from .models import Partner, Internship, Activity, Alumni
from .serializers import PartnerSerializer, InternshipSerializer, ActivitySerializer, AlumniSerializer
from .permissions import is_coip_staff, is_coip_responsable_access


class IsCoipStaff(BasePermission):
    def has_permission(self, request, view):
        return is_coip_staff(request.user)


class IsCoipResponsable(BasePermission):
    def has_permission(self, request, view):
        return is_coip_responsable_access(request.user)


class PartnerViewSet(viewsets.ReadOnlyModelViewSet):
    """Partenaires COIP — lecture seule, zone sensible (Responsable COIP)."""
    queryset = Partner.objects.filter(is_active=True).order_by('raison_sociale')
    serializer_class = PartnerSerializer
    permission_classes = [IsCoipResponsable]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['type_partenaire']


class InternshipViewSet(viewsets.ReadOnlyModelViewSet):
    """Stages — lecture seule."""
    queryset = Internship.objects.select_related('student__user', 'partner').order_by('-date_debut')
    serializer_class = InternshipSerializer
    permission_classes = [IsCoipStaff]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['status', 'partner']


class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """Activités COIP — lecture seule."""
    queryset = Activity.objects.select_related('responsable').order_by('-date_debut')
    serializer_class = ActivitySerializer
    permission_classes = [IsCoipStaff]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['type_activite', 'status']


class AlumniViewSet(viewsets.ReadOnlyModelViewSet):
    """Alumni — lecture seule."""
    queryset = Alumni.objects.select_related('filiere').order_by('-annee_obtention', 'last_name')
    serializer_class = AlumniSerializer
    permission_classes = [IsCoipStaff]
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['secteur_activite', 'is_employed']
