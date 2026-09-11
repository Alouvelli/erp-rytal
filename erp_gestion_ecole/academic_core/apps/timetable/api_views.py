from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .models import TimetableEntry
from .serializers import TimetableEntrySerializer, TimetableEntryCalendarSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class TimetableEntryViewSet(viewsets.ModelViewSet):
    """
    CRUD complet des entrées d'emploi du temps.
    Détection automatique des conflits enseignant/salle/classe.
    """
    queryset = TimetableEntry.objects.select_related(
        'semester', 'class_group', 'subject', 'teacher__user', 'room'
    ).filter(is_active=True)
    serializer_class = TimetableEntrySerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['semester', 'class_group', 'teacher', 'room', 'day_of_week']
    search_fields    = ['subject__title', 'class_group__name', 'teacher__user__last_name']
    ordering_fields  = ['day_of_week', 'start_time']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminOrResponsable()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_etudiant():
            sp = getattr(user, 'student_profile', None)
            if sp:
                current = sp.current_enrollment()
                if current:
                    return qs.filter(class_group=current.class_group)
            return qs.none()
        if user.is_enseignant():
            return qs.filter(teacher__user=user)
        return qs

    def perform_create(self, serializer):
        entry = serializer.save()
        conflicts = entry.check_conflicts()
        if conflicts:
            # Still save but return warnings in the response
            entry._conflicts = conflicts

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        data = serializer.data
        conflicts = getattr(serializer.instance, '_conflicts', [])
        if conflicts:
            data['warnings'] = conflicts
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    @extend_schema(description="Retourne les événements au format FullCalendar")
    @action(detail=False, methods=['get'], url_path='calendar')
    def calendar(self, request):
        qs = self.filter_queryset(self.get_queryset())
        serializer = TimetableEntryCalendarSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(description="Vérifie les conflits sans sauvegarder")
    @action(detail=False, methods=['post'], url_path='check-conflicts')
    def check_conflicts(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry    = TimetableEntry(**{
            k: v for k, v in serializer.validated_data.items()
        })
        conflicts = entry.check_conflicts()
        return Response({'conflicts': conflicts, 'has_conflicts': bool(conflicts)})
