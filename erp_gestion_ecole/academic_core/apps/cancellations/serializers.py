from rest_framework import serializers
from .models import CourseCancellation


class CourseCancellationSerializer(serializers.ModelSerializer):
    subject_name    = serializers.CharField(source='timetable_entry.subject.title', read_only=True)
    class_name      = serializers.CharField(source='timetable_entry.class_group.name', read_only=True)
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    request_type_display = serializers.CharField(source='get_request_type_display', read_only=True)
    status_display  = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = CourseCancellation
        fields = [
            'id', 'timetable_entry', 'subject_name', 'class_name', 'session_date',
            'request_type', 'request_type_display', 'reason',
            'requested_by', 'requested_by_name', 'requested_at',
            'status', 'status_display', 'reviewed_by', 'reviewed_at', 'review_comment',
            'rescheduled_date', 'rescheduled_start', 'rescheduled_end', 'rescheduled_room',
        ]
