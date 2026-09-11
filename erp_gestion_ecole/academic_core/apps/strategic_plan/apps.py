from django.apps import AppConfig


class StrategicPlanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "academic_core.apps.strategic_plan"
    label = "strategic_plan"
    verbose_name = "Plan Stratégique"

    def ready(self):
        import academic_core.apps.strategic_plan.signals  # noqa: F401
