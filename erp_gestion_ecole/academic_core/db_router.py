"""
Router multi-tenant : route les requêtes vers la base SQLite de l'institut actif.

Règles :
  • Models maîtres (Faculty, InstitutConfig, sessions…)   → toujours 'default'
  • Django internals (contenttypes, auth, admin, sessions) → toujours 'default'
  • Tous les autres models (données opérationnelles)       → base de l'institut actif

IMPORTANT : les données opérationnelles (étudiants, inscriptions, paiements, …)
ne doivent JAMAIS être écrites dans 'default'.  Si aucune base institut n'est
active, db_for_write retourne None pour refuser l'écriture plutôt que de polluer
'default'.  db_for_read continue de fonctionner en retournant 'default' en
dernier recours (lecture seule tolérée pour éviter les crashs d'affichage).
"""

import logging
import threading

logger = logging.getLogger(__name__)

_thread_locals = threading.local()

# ── Models qui restent TOUJOURS dans la base master (default) ──────────────
MASTER_MODEL_NAMES = frozenset([
    'faculty',
    'institutconfig',
    'abonnementinstitut',
    'institutfiliation',
    'contratarticle',
    'auditlog',
    'auditbackup',
    'passwordresettoken',
    'controllerinstitut',
    'institutdisabledtab',
    'institutdisabledfeature',
    'archivedinstitutdatabase',
    'platformactivation',
    'platformactivationresettoken',
    'emailverificationtoken',
    'institutemailconfig',
    'institutpaymentconfig',
])

# ── Apps Django internes → toujours default ────────────────────────────────
MASTER_APP_LABELS = frozenset([
    'sessions',
    'contenttypes',
    'auth',
    'admin',
    'django_celery_beat',
])

# ── Apps opérationnelles → JAMAIS dans default ─────────────────────────────
# Les schémas existent dans default (pour clonage), mais aucune donnée ne doit
# y être stockée.
TENANT_ONLY_APP_LABELS = frozenset([
    'students',
    'accounting',
    'timetable',
    'attendance',
    'grades',
    'cancellations',
    'teachers',
    'subjects',
    'rooms',
    'notifications',
    'reports',
    'chatbot',
    'hr',
    'community_service',
    'api_gateway',
    'coip',
    'strategic_plan',
    'indicators',
    'procurement',
    'quality',
    'risks',
    'admissions',
])


def get_current_db() -> str:
    """Retourne l'alias de la DB active pour le thread courant."""
    return getattr(_thread_locals, 'current_db', 'default')


def set_current_db(alias: str) -> None:
    """Définit la DB active pour le thread courant (appelé par DepartmentMiddleware)."""
    _thread_locals.current_db = alias


def _is_master(model) -> bool:
    return (
        model._meta.app_label in MASTER_APP_LABELS
        or model._meta.model_name in MASTER_MODEL_NAMES
    )


def _is_tenant_only(model) -> bool:
    return model._meta.app_label in TENANT_ONLY_APP_LABELS


class InstitutRouter:
    """
    Django database router pour le multi-tenant par institut.

    Chaque institut dispose de sa propre base SQLite.
    Le middleware DepartmentMiddleware appelle set_current_db() à chaque requête.
    """

    def db_for_read(self, model, **hints) -> str:
        if _is_master(model):
            return 'default'
        return get_current_db()

    def db_for_write(self, model, **hints):
        if _is_master(model):
            return 'default'

        current = get_current_db()

        # Données opérationnelles : refuser l'écriture vers default
        if current == 'default' and _is_tenant_only(model):
            logger.warning(
                '[DB-ROUTER] Écriture refusée vers default pour %s.%s — '
                'aucune base institut active. Vérifiez DepartmentMiddleware.',
                model._meta.app_label,
                model._meta.model_name,
            )
            return None  # Django n'exécutera pas le INSERT/UPDATE

        return current

    def allow_relation(self, obj1, obj2, **hints) -> bool:
        # Relations cross-DB autorisées (intégrité gérée au niveau applicatif)
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints) -> bool:
        # Apps internes → seulement default
        if app_label in MASTER_APP_LABELS:
            return db == 'default'
        # Tous les autres models migrent vers TOUTES les bases
        # (default sert de template de clonage pour les nouvelles bases tenant)
        return True
