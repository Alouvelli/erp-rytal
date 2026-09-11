from django.apps import AppConfig


class TimetableConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.timetable'
    label = 'timetable'
    verbose_name = 'Emplois du Temps'
