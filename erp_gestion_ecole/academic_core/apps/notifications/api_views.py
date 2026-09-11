from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Notifications du compte à l'origine de l'appel — lecture seule.
    Toujours restreint au destinataire courant (recipient=request.user),
    quel que soit le canal d'authentification (session ou clé d'API).
    """
    serializer_class = NotificationSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['notification_type', 'is_read', 'priority']

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).order_by('-created_at')
