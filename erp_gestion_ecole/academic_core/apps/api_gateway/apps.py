from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ApiGatewayConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academic_core.apps.api_gateway'
    verbose_name = _('API de Consommation')

    def ready(self):
        # APIKeyAuthentication.authenticate() (voir authentication.py) appelle
        # set_current_db(grant.db_alias) EN PLEIN MILIEU d'une requête API,
        # pour router cette requête vers la bonne base tenant — un alias
        # externe, non lié à la session de navigation habituelle (voir
        # ResetDBMiddleware, qui ne connaît que request.session['_auth_db']).
        # Si ce thread de travail sert ensuite une autre requête AVANT que
        # ResetDBMiddleware n'ait eu l'occasion de le réinitialiser (ex :
        # exécution différée, tâche de fond, ou tout code qui lirait
        # get_current_db() hors du cycle normal middleware → vue), l'alias
        # tenant de l'appel API resterait actif par erreur — au risque de
        # faire échouer silencieusement l'accès d'un utilisateur normal
        # (mauvaise base = utilisateur introuvable). On revient explicitement
        # à 'default' à la toute fin de CHAQUE requête (signal request_finished,
        # déclenché pour toutes les requêtes, API ou non) : filet de sécurité
        # qui garantit qu'aucun appel API ne peut laisser de contexte tenant
        # actif au-delà de sa propre requête, quelle que soit la manière dont
        # cette requête s'est terminée.
        from django.core.signals import request_finished

        def _reset_tenant_db_after_request(sender, **kwargs):
            from academic_core.db_router import set_current_db
            set_current_db('default')

        request_finished.connect(_reset_tenant_db_after_request, dispatch_uid='api_gateway_reset_tenant_db')
