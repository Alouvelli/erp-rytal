from django.apps import AppConfig


class GradesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.grades'
    label = 'grades'
    verbose_name = 'Notes & Évaluations'
