from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.reports'
    label = 'reports'
    verbose_name = 'Rapports'
