from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import CourseCancellation
from .serializers import CourseCancellationSerializer


class CourseCancellationViewSet(viewsets.ReadOnlyModelViewSet):
    """Annulations et reports de cours — lecture seule."""
    queryset = CourseCancellation.objects.select_related(
        'timetable_entry__subject', 'timetable_entry__class_group',
        'requested_by', 'reviewed_by',
    ).order_by('-requested_at')
    serializer_class = CourseCancellationSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['status', 'request_type', 'session_date']
