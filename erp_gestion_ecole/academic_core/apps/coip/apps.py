from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoipConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academic_core.apps.coip'
    verbose_name = _("Cellule d'Orientation et d'Insertion Professionnelle")
