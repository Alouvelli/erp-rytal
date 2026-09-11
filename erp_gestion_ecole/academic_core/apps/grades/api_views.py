from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from .models import Evaluation, Grade, SemesterAverage
from .serializers import EvaluationSerializer, GradeSerializer, SemesterAverageSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class EvaluationViewSet(viewsets.ModelViewSet):
    queryset = Evaluation.objects.select_related(
        'subject', 'semester', 'evaluation_type', 'teacher__user'
    ).order_by('-date')
    serializer_class = EvaluationSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['subject', 'semester', 'evaluation_type', 'is_locked']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_enseignant():
            return qs.filter(teacher__user=user)
        return qs

    @action(detail=True, methods=['post'], url_path='lock',
            permission_classes=[IsAdminOrResponsable])
    def lock(self, request, pk=None):
        evaluation = self.get_object()
        if evaluation.is_locked:
            return Response({'error': 'Déjà verrouillée.'}, status=400)
        evaluation.is_locked  = True
        evaluation.locked_at  = timezone.now()
        evaluation.locked_by  = request.user
        evaluation.save(update_fields=['is_locked', 'locked_at', 'locked_by'])
        return Response(self.get_serializer(evaluation).data)


class GradeViewSet(viewsets.ModelViewSet):
    queryset = Grade.objects.select_related(
        'student__user', 'evaluation__subject', 'evaluation__evaluation_type'
    )
    serializer_class = GradeSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['student', 'evaluation']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_etudiant():
            sp = getattr(user, 'student_profile', None)
            return qs.filter(student=sp) if sp else qs.none()
        if user.is_enseignant():
            return qs.filter(evaluation__teacher__user=user)
        return qs

    def perform_create(self, serializer):
        evaluation = serializer.validated_data.get('evaluation')
        if evaluation and evaluation.is_locked:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cette évaluation est verrouillée.")
        serializer.save(entered_by=self.request.user)


class SemesterAverageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SemesterAverage.objects.select_related(
        'student__user', 'semester'
    ).order_by('rank')
    serializer_class = SemesterAverageSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['student', 'semester']
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_etudiant():
            sp = getattr(user, 'student_profile', None)
            return qs.filter(student=sp) if sp else qs.none()
        return qs
