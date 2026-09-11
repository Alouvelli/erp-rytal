from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model  = Notification
        fields = [
            'id', 'notification_type', 'notification_type_display', 'title',
            'message', 'priority', 'priority_display', 'is_read', 'read_at',
            'link', 'created_at',
        ]
