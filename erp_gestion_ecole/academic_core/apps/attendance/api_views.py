from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from .models import AttendanceSheet, StudentAttendance
from .serializers import AttendanceSheetSerializer, StudentAttendanceSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable, IsTeacherOwner


class AttendanceSheetViewSet(viewsets.ModelViewSet):
    """Gestion des fiches d'émargement."""
    queryset = AttendanceSheet.objects.select_related(
        'timetable_entry__subject',
        'timetable_entry__teacher__user',
        'timetable_entry__class_group',
    ).order_by('-session_date')
    serializer_class = AttendanceSheetSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['status', 'session_date', 'timetable_entry__teacher']

    def get_permissions(self):
        if self.action in ['validate_sheet', 'reject_sheet']:
            return [IsAdminOrResponsable()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_enseignant():
            return qs.filter(timetable_entry__teacher__user=user)
        return qs

    @action(detail=True, methods=['post'], url_path='sign')
    def sign(self, request, pk=None):
        sheet = self.get_object()
        user  = request.user
        if not user.is_enseignant():
            return Response({'error': 'Seul un enseignant peut signer.'}, status=403)
        if sheet.timetable_entry.teacher.user != user:
            return Response({'error': 'Fiche non assignée à cet enseignant.'}, status=403)
        if sheet.status != AttendanceSheet.STATUS_PENDING:
            return Response({'error': 'Fiche déjà traitée.'}, status=400)

        sheet.status = AttendanceSheet.STATUS_SIGNED
        sheet.teacher_signature_at = timezone.now()
        sheet.teacher_comment = request.data.get('comment', '')
        sheet.save(update_fields=['status', 'teacher_signature_at', 'teacher_comment'])
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=['post'], url_path='validate')
    def validate_sheet(self, request, pk=None):
        sheet = self.get_object()
        if sheet.status != AttendanceSheet.STATUS_SIGNED:
            return Response({'error': 'La fiche doit être signée d\'abord.'}, status=400)
        sheet.status       = AttendanceSheet.STATUS_VALIDATED
        sheet.validated_by = request.user
        sheet.validated_at = timezone.now()
        sheet.save(update_fields=['status', 'validated_by', 'validated_at'])
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject_sheet(self, request, pk=None):
        sheet = self.get_object()
        sheet.status           = AttendanceSheet.STATUS_REJECTED
        sheet.rejection_reason = request.data.get('reason', '')
        sheet.validated_by     = request.user
        sheet.validated_at     = timezone.now()
        sheet.save(update_fields=['status', 'rejection_reason', 'validated_by', 'validated_at'])
        return Response(self.get_serializer(sheet).data)


class StudentAttendanceViewSet(viewsets.ModelViewSet):
    queryset = StudentAttendance.objects.select_related(
        'student__user', 'attendance_sheet'
    )
    serializer_class = StudentAttendanceSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['status', 'student', 'attendance_sheet']
    permission_classes = [permissions.IsAuthenticated]
