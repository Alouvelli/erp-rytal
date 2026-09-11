from django.apps import AppConfig


class SubjectsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.subjects'
    label = 'subjects'
    verbose_name = 'Modules (EC)'
