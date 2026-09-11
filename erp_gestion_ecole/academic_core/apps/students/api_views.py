from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Student, Enrollment
from .serializers import StudentSerializer, EnrollmentSerializer
from academic_core.apps.accounts.api_permissions import IsAdminOrResponsable


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.select_related('user').order_by('user__last_name')
    serializer_class = StudentSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    search_fields    = ['matricule', 'user__first_name', 'user__last_name']
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminOrResponsable()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if user.is_etudiant():
            sp = getattr(user, 'student_profile', None)
            return qs.filter(pk=sp.pk) if sp else qs.none()
        return qs

    @action(detail=True, methods=['get'])
    def enrollments(self, request, pk=None):
        student = self.get_object()
        serializer = EnrollmentSerializer(
            student.enrollments.select_related('class_group', 'academic_year'),
            many=True
        )
        return Response(serializer.data)
