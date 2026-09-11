"""
Outil RYTAL universel : notifications de l'utilisateur connecté. Contrairement
aux autres outils (scindés par palier de rôle), celui-ci est pertinent pour
absolument tous les rôles — chacun a sa propre boîte de notifications,
strictement filtrée par `recipient=user` (jamais un autre utilisateur).
"""
from .registry import register_tool


@register_tool('get_my_notifications', {
    'name': 'get_my_notifications',
    'description': (
        "Retourne les notifications de la personne connectée (non lues en "
        "priorité), avec leur titre et leur date."
    ),
    'input_schema': {'type': 'object', 'properties': {}},
})
def get_my_notifications(user, request):
    from academic_core.apps.notifications.models import Notification

    qs = (
        Notification.objects.filter(recipient=user)
        .order_by('is_read', '-created_at')[:15]
    )
    return {
        'unread_count': Notification.objects.filter(recipient=user, is_read=False).count(),
        'notifications': [
            {
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'created_at': n.created_at.strftime('%d/%m/%Y %H:%M'),
            }
            for n in qs
        ],
    }
