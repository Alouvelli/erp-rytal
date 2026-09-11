"""
Signals pour academic_structure.

- Création automatique de la base PostgreSQL dédiée lors de la sauvegarde d'un
  InstitutConfig avec un nouveau db_alias (voir
  academic_core/apps/academic_structure/pg_provisioning.py pour la création
  effective et academic_core/tenant_databases.py pour l'enregistrement dans
  settings.DATABASES + la persistance des paramètres d'accès dans .env).
"""

import re
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _slugify_code(code: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', code.lower()).strip('_')


@receiver(post_save, sender='academic_structure.InstitutConfig')
def auto_create_institute_db(sender, instance, created, **kwargs):
    """
    A chaque sauvegarde d'un InstitutConfig :
    1. Génère db_alias si absent (basé sur faculty.code) — db_alias EST le nom
       physique de la base PostgreSQL, ex: 'db_rytal_isi'.
    2. Crée la base PostgreSQL si elle n'existe pas encore côté serveur.
    3. Enregistre l'alias dans settings.DATABASES pour ce worker.
    4. Applique les vraies migrations Django (schéma + seed RunPython, ex: la
       table `roles` — contrairement à l'ancien clonage de schéma SQLite brut,
       qui ne rejouait jamais les RunPython et nécessitait le contournement
       sync_roles_to_institute_db ci-dessous à chaque fois).
    5. Persiste les paramètres d'accès de cette base dans .env.
    """
    from django.conf import settings
    from academic_core.tenant_databases import register_tenant_db, append_tenant_env_block
    from academic_core.apps.academic_structure.pg_provisioning import create_database

    # Exposé sur l'instance (même objet Python que celui manipulé par l'appelant,
    # ex: institut_create_view après config.save()) pour que l'admin voie un
    # avertissement au lieu du succès inconditionnel actuel si une étape échoue
    # silencieusement — voir _mark_provisioning_warning ci-dessous.
    instance._provisioning_warning = None

    faculty = getattr(instance, 'faculty', None)
    if not faculty:
        return

    # 1. Générer db_alias si vide
    if not instance.db_alias:
        alias = f'db_rytal_{_slugify_code(faculty.code)}'
        type(instance).objects.filter(pk=instance.pk).update(db_alias=alias)
        instance.db_alias = alias
    else:
        alias = instance.db_alias

    # 2. Créer la base PostgreSQL si nécessaire
    if not create_database(alias):
        logger.error('auto_create_institute_db: échec de la création de %s', alias)
        instance._provisioning_warning = (
            f"La base de données « {alias} » n'a pas pu être créée automatiquement. "
            "Contactez l'administrateur système."
        )
        return

    # 3. Enregistrer l'alias dans settings.DATABASES (ce worker)
    if not register_tenant_db(alias):
        logger.error('auto_create_institute_db: échec de l\'enregistrement de %s', alias)
        instance._provisioning_warning = (
            f"La base « {alias} » a été créée mais n'a pas pu être enregistrée. "
            "Contactez l'administrateur système."
        )
        return

    # 4. Appliquer les vraies migrations Django (schéma + seed RunPython)
    try:
        from django.core.management import call_command
        call_command('migrate', database=alias, run_syncdb=True, verbosity=0, interactive=False)
        logger.info('auto_create_institute_db: migrations appliquées sur %s', alias)
    except Exception as exc:
        logger.error('auto_create_institute_db: migration de %s échouée : %s', alias, exc)
        instance._provisioning_warning = (
            f"La base « {alias} » a été créée mais les migrations ont échoué "
            f"({exc}). L'institut ne sera pas fonctionnel tant que la commande "
            f"« python manage.py migrate --database={alias} » n'aura pas été relancée."
        )

    # 5. Persister les paramètres d'accès dans .env
    try:
        code_env = _slugify_code(faculty.code).upper()
        append_tenant_env_block(settings.BASE_DIR, code_env, alias)
    except Exception as exc:
        logger.warning('append_tenant_env_block(%s) après création : %s', alias, exc)
        if not instance._provisioning_warning:
            instance._provisioning_warning = (
                f"La base « {alias} » est prête mais l'écriture de sa configuration "
                f"dans .env a échoué ({exc}). Elle devra être ajoutée manuellement "
                "pour survivre à un redémarrage du serveur."
            )

    # 6. Réconcilier la table `roles` sur celle de 'default' (par id, pas
    #    seulement par nom manquant) : les migrations RunPython de seed
    #    attribuent des ids Postgres propres à CETTE base (ordre d'exécution),
    #    qui peuvent diverger de ceux de 'default' pour le même nom de rôle —
    #    sans cela, un compte synchronisé plus tard vers cette base (copie de
    #    son role_id depuis 'default') se retrouverait avec le mauvais rôle
    #    localement. Sûr uniquement ici : institut tout juste créé, aucune
    #    donnée locale ne référence encore ces ids.
    try:
        from academic_core.apps.accounts.db_utils import reconcile_roles_from_default
        reconcile_roles_from_default(alias)
    except Exception as exc:
        logger.warning('reconcile_roles_from_default(%s) apres creation : %s', alias, exc)
