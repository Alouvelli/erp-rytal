from decouple import config
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

# Par défaut, aucun email réel n'est envoyé en développement (impression
# console uniquement) — évite d'envoyer accidentellement de vrais emails à de
# vrais destinataires pendant les tests locaux courants (création
# étudiant/enseignant, notifications, etc.). Pour tester réellement l'envoi
# (ex : vérifier le flux « code d'activation oublié »), définir explicitement
# DEV_FORCE_REAL_EMAIL=True dans .env — .base importe déjà EMAIL_BACKEND et
# les identifiants SMTP réels depuis .env dans ce cas.
if not config('DEV_FORCE_REAL_EMAIL', default=False, cast=bool):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

INTERNAL_IPS = ['127.0.0.1']

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False
CSRF_USE_SESSIONS = False

# Base 'default' + bases par institut : PostgreSQL, voir config/settings/base.py
# (DATABASES/DATABASE_ROUTERS déjà définis là, communs à dev et prod).

CORS_ALLOW_ALL_ORIGINS = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'root': {'handlers': ['console'], 'level': 'DEBUG'},
    'loggers': {
        'django.db.backends': {'handlers': ['console'], 'level': 'WARNING'},
    },
}
