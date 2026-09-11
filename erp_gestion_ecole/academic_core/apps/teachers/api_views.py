from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Teacher
from .serializers import TeacherSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class TeacherViewSet(viewsets.ModelViewSet):
    queryset = Teacher.objects.select_related('user', 'grade').order_by('user__last_name')
    serializer_class = TeacherSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['statut', 'grade']
    search_fields    = ['matricule', 'user__first_name', 'user__last_name', 'specialty']
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminOrResponsable()]
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=['get'])
    def timetable(self, request, pk=None):
        from academic_core.apps.timetable.models import TimetableEntry
        from academic_core.apps.timetable.serializers import TimetableEntrySerializer
        teacher = self.get_object()
        entries = TimetableEntry.objects.filter(
            teacher=teacher, is_active=True
        ).select_related('subject', 'class_group', 'room', 'semester')
        return Response(TimetableEntrySerializer(entries, many=True).data)

    @action(detail=True, methods=['get'])
    def hours_summary(self, request, pk=None):
        from academic_core.apps.academic_structure.models import AcademicYear
        teacher = self.get_object()
        current_year = AcademicYear.objects.filter(is_current=True).first()
        hours = teacher.get_total_hours_taught(current_year)
        return Response({
            'teacher':            str(teacher),
            'contractual_hours':  float(teacher.contractual_hours),
            'hours_done':         float(hours),
            'completion_rate':    round(float(hours) / float(teacher.contractual_hours) * 100, 1)
                                  if teacher.contractual_hours else 0,
        })
