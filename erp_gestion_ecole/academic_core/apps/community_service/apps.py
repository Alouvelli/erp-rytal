from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CommunityServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academic_core.apps.community_service'
    verbose_name = _('Service à la Communauté')
