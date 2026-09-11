from django.apps import AppConfig


class TeachersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.teachers'
    label = 'teachers'
    verbose_name = 'Enseignants'

    def ready(self):
        import academic_core.apps.teachers.signals  # noqa: F401
