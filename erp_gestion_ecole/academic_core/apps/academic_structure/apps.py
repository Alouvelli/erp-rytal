from django.apps import AppConfig


class AcademicStructureConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.academic_structure'
    label = 'academic_structure'
    verbose_name = 'Structure Académique'

    def ready(self):
        import academic_core.apps.academic_structure.signals  # noqa: F401
