from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Subject
from .serializers import SubjectSerializer


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    """Modules (EC) enseignés — lecture seule."""
    queryset = Subject.objects.select_related(
        'program', 'semester', 'responsible_teacher__user'
    ).order_by('code')
    serializer_class = SubjectSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['program', 'semester', 'subject_type']
    search_fields    = ['code', 'title']
