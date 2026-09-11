from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.accounts'
    label = 'accounts'
    verbose_name = 'Comptes & Authentification'
