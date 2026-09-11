from django.apps import AppConfig


class IndicatorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "academic_core.apps.indicators"
    label = "indicators"
    verbose_name = "Indicateurs"

    def ready(self):
        import academic_core.apps.indicators.signals  # noqa: F401
