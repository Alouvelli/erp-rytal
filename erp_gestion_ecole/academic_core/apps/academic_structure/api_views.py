from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Department, Program, Class
from .serializers import DepartmentSerializer, ProgramSerializer, ClassSerializer


class DepartmentViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalogue des départements de l'institut — lecture seule."""
    queryset = Department.objects.select_related('faculty').filter(is_active=True).order_by('name')
    serializer_class = DepartmentSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['faculty']
    search_fields    = ['code', 'name']


class ProgramViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalogue des filières — lecture seule."""
    queryset = Program.objects.select_related('department').order_by('name')
    serializer_class = ProgramSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['department']
    search_fields    = ['code', 'name']


class ClassViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalogue des classes — lecture seule."""
    queryset = Class.objects.select_related('program', 'level', 'academic_year').order_by('name')
    serializer_class = ClassSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['program', 'level', 'academic_year']
    search_fields    = ['code', 'name']
