"""
Base Django settings — partagés par tous les environnements.
"""
import os
from pathlib import Path
from datetime import timedelta
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'changeme-in-production')

DEBUG = False

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

# Application definition
DJANGO_APPS = [
    # Pas de django.contrib.admin : l'administration de la plateforme se fait
    # exclusivement via les rôles applicatifs dédiés, jamais via l'interface
    # d'admin générique de Django (voir config/urls.py).
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'celery',
    'django_celery_beat',
    'crispy_forms',
    'crispy_bootstrap5',
    'django_extensions',
]

LOCAL_APPS = [
    'academic_core.apps.accounts',
    'academic_core.apps.academic_structure',
    'academic_core.apps.teachers',
    'academic_core.apps.students',
    'academic_core.apps.subjects',
    'academic_core.apps.rooms',
    'academic_core.apps.timetable',
    'academic_core.apps.attendance',
    'academic_core.apps.grades',
    'academic_core.apps.cancellations',
    'academic_core.apps.notifications',
    'academic_core.apps.reports',
    'academic_core.apps.dashboard',
    'academic_core.apps.accounting',
    'academic_core.apps.hr',
    'academic_core.apps.community_service',
    'academic_core.apps.api_gateway',
    'academic_core.apps.coip',
    'academic_core.apps.chatbot',
    'academic_core.apps.strategic_plan',
    'academic_core.apps.indicators',
    'academic_core.apps.procurement',
    'academic_core.apps.quality',
    'academic_core.apps.risks',
    'academic_core.apps.admissions',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'academic_core.middleware.ResetDBMiddleware',
    'academic_core.middleware.PlatformActivationMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'academic_core.apps.accounts.middleware.AuditMiddleware',
    'academic_core.middleware.InstitutSuspensionMiddleware',
    'academic_core.middleware.DepartmentMiddleware',
    'academic_core.middleware.FeatureGateMiddleware',
    'academic_core.middleware.NoCacheMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'academic_core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'academic_core.apps.notifications.context_processors.unread_notifications',
                'academic_core.apps.accounting.context_processors.pending_inscriptions_count',
                'academic_core.context_processors.department_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database — 'default' (données maîtres : Faculty, InstitutConfig, auth…) +
# une base PostgreSQL par institut, découverte depuis .env (voir
# academic_core/tenant_databases.py). Un seul compte administrateur PostgreSQL
# (POSTGRES_USER/POSTGRES_PASSWORD) gère 'default' et toutes les bases instituts,
# actuelles et futures, sur le même serveur.
#
# IMPORTANT : decouple.config() ici, PAS os.environ.get() — os.environ.get()
# ne lit PAS le fichier .env (rien dans ce projet n'injecte .env dans
# os.environ hors du conteneur Docker, qui le fait via `env_file:`), voir le
# même piège déjà documenté plus bas pour EMAIL_*. Avec os.environ.get(), ces
# variables ne prenaient leur valeur .env qu'en conteneur Docker et
# retombaient sinon sur les défauts codés en dur (host "db", inexistant hors
# Docker) — cassant toute connexion PostgreSQL en développement local.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('POSTGRES_DB', default='academic_db'),
        'USER': config('POSTGRES_USER', default='academic_user'),
        'PASSWORD': config('POSTGRES_PASSWORD', default='academic_pass'),
        'HOST': config('POSTGRES_HOST', default='db'),
        'PORT': config('POSTGRES_PORT', default='5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
        'CONN_MAX_AGE': 600,
    }
}

from academic_core.tenant_databases import discover_tenant_databases  # noqa: E402
DATABASES.update(discover_tenant_databases(BASE_DIR))

DATABASE_ROUTERS = ['academic_core.db_router.InstitutRouter']

# Auth
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'academic_core.apps.accounts.backends.MultiDBAuthBackend',
]
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]

# Internationalization
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Dakar'
USE_I18N = True
USE_L10N = True
USE_TZ = True
DATE_FORMAT = 'd/m/Y'
DATETIME_FORMAT = 'd/m/Y H:i'

# Static & Media
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'academic_core' / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'academic_core' / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'academic_core.apps.api_gateway.authentication.APIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# ── Chatbot RYTAL (Anthropic Claude) ────────────────────────────────────────
# CHATBOT_USE_LLM=False : RYTAL répond via le moteur à règles (rule_engine.py),
# sans appel LLM ni coût API — bascule prévue vers l'IA une fois activée.
CHATBOT_USE_LLM = config('CHATBOT_USE_LLM', default=False, cast=bool)
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY', default='')
CHATBOT_LLM_MODEL = config('CHATBOT_LLM_MODEL', default='claude-sonnet-5')
CHATBOT_MAX_TOKENS = config('CHATBOT_MAX_TOKENS', default=1024, cast=int)
CHATBOT_MAX_TOOL_ITERATIONS = 5
CHATBOT_MAX_HISTORY_MESSAGES = config('CHATBOT_MAX_HISTORY_MESSAGES', default=30, cast=int)
CHATBOT_MAX_MESSAGE_LENGTH = 2000

# JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Celery
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Email
# IMPORTANT : os.environ.get() ne lit PAS le fichier .env (rien dans ce projet
# n'injecte .env dans os.environ) — seul decouple.config() le fait, comme déjà
# utilisé plus haut pour CHATBOT_*. Utiliser os.environ.get() ici faisait que
# les identifiants SMTP réels du .env n'étaient jamais pris en compte, quelle
# que soit leur valeur.
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@university.edu')

# Swagger / OpenAPI
SPECTACULAR_SETTINGS = {
    'TITLE': 'API Gestion Académique',
    'DESCRIPTION': 'API complète pour la gestion académique universitaire',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
}

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# Session
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 28800  # 8 heures

# Security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# CORS — en production, définir CORS_ALLOWED_ORIGINS dans .env
_cors_origins = [o for o in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]
if _cors_origins:
    CORS_ALLOWED_ORIGINS = _cors_origins
else:
    CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
