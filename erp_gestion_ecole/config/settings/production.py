from .base import *
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

# DATABASES ('default' + une base PostgreSQL par institut) et DATABASE_ROUTERS
# sont hérités tels quels de .base — jusqu'ici ce fichier ne les redéfinissait
# pas du tout, donc le multi-tenant n'était jamais actif en production (seul
# development.py le faisait, via des fichiers SQLite). Voir
# academic_core/tenant_databases.py::discover_tenant_databases.

# Verrou de démarrage : le serveur de production refuse de démarrer sans cette
# variable d'environnement, définie uniquement sur la machine de déploiement
# (jamais dans le dépôt, jamais visible depuis l'application web). C'est le
# premier des deux verrous du mécanisme d'activation de la plateforme — voir
# academic_core/apps/accounts/platform_activation.py pour le second verrou
# (code d'activation saisi une fois via l'interface web).
if not config('PLATFORM_MASTER_KEY', default=''):
    raise ImproperlyConfigured(
        "PLATFORM_MASTER_KEY doit être défini dans l'environnement du serveur "
        "pour que l'application puisse démarrer. Cette variable n'est connue "
        "que de l'opérateur du serveur et ne doit jamais être stockée dans le dépôt."
    )

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}', 'style': '{'},
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/django/app.log',
            'maxBytes': 1024 * 1024 * 10,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'root': {'handlers': ['file', 'console'], 'level': 'WARNING'},
}
