from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AdmissionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academic_core.apps.admissions'
    verbose_name = _('Admissions en ligne')
