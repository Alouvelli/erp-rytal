from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.attendance'
    label = 'attendance'
    verbose_name = 'Émargements'
