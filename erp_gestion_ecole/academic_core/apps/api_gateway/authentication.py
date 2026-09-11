"""
Authentification par clé d'API générée depuis l'onglet « API de
Consommation » (voir models.py::APIAccessGrant). Distincte du JWT applicatif
existant (login utilisateur classique) : ce mécanisme sert des accès
ponctuels, révocables, scopés à UNE ressource précise, destinés à être
copiés/partagés en dehors de l'application (Postman, script, tableur…).

Contrairement à une requête navigateur normale, un appel API externe n'a pas
de session (donc pas de `request.session['_auth_db']` résolu par
DepartmentMiddleware) : cette classe route explicitement la requête vers la
bonne base tenant à partir de `APIAccessGrant.db_alias`, capturé au moment de
la création de l'accès.

La base tenant à laquelle appartient une clé donnée n'étant pas connue à
l'avance, on l'identifie en cherchant l'empreinte de la clé dans chacune des
bases tenant enregistrées (peu nombreuses, recherche indexée) plutôt que de
l'encoder dans la clé elle-même.
"""
from django.conf import settings
from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import hash_api_key


def _tenant_db_aliases():
    return [alias for alias in settings.DATABASES if alias != 'default']


class APIKeyAuthentication(authentication.BaseAuthentication):
    keyword = 'Api-Key'

    def authenticate(self, request):
        raw_key = self._extract_key(request)
        if not raw_key:
            return None

        from academic_core.db_router import set_current_db
        from .models import APIAccessGrant

        key_hash = hash_api_key(raw_key)
        grant = None
        for alias in _tenant_db_aliases():
            try:
                found = (
                    APIAccessGrant.objects
                    .using(alias)
                    .select_related('user', 'resource')
                    .filter(key_hash=key_hash)
                    .first()
                )
            except Exception:
                # Une base tenant indisponible (redémarrage, réseau…) ne doit
                # jamais empêcher l'authentification d'une clé qui appartient
                # à une AUTRE base, parfaitement saine — on continue le tour
                # plutôt que de laisser une exception de connexion invalider
                # toute la requête.
                continue
            if found:
                grant = found
                set_current_db(alias)
                break

        if grant is None:
            raise exceptions.AuthenticationFailed("Clé d'API invalide.")
        if not grant.is_valid:
            raise exceptions.AuthenticationFailed("Clé d'API révoquée ou expirée.")
        if not grant.resource.is_active:
            raise exceptions.AuthenticationFailed("Cette ressource d'API n'est plus disponible.")

        # Une ressource du catalogue = un préfixe de chemin ; la clé ne donne
        # accès qu'à ce périmètre précis, jamais à l'ensemble de l'API.
        if not request.path.startswith(grant.resource.endpoint_path):
            raise exceptions.PermissionDenied(
                "Cette clé d'API ne donne accès qu'à : " + grant.resource.endpoint_path
            )

        # Les clés d'API sont un canal de PARTAGE DE LECTURE — jamais de
        # création/modification/suppression, quels que soient les droits de
        # l'utilisateur normalement autorisé par les permissions du ViewSet.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            raise exceptions.PermissionDenied(
                "Les clés d'API sont limitées à la lecture (GET)."
            )

        APIAccessGrant.objects.using(grant._state.db).filter(pk=grant.pk).update(
            last_used_at=timezone.now()
        )

        return (grant.user, grant)

    def _extract_key(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if header.startswith(f'{self.keyword} '):
            return header[len(self.keyword) + 1:].strip()
        return request.query_params.get('api_key') or None

    def authenticate_header(self, request):
        return self.keyword
