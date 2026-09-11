def register_institut_db(alias):
    """
    S'assure que l'alias d'une base institut est chargé dans settings.DATABASES,
    y compris pour un institut créé après le démarrage du process par un autre
    worker (settings.DATABASES n'est peuplé qu'une fois, au démarrage, depuis
    les blocs DB_RYTAL_* de .env — voir academic_core/tenant_databases.py).

    Retourne l'alias si utilisable (base PostgreSQL existante), sinon None.
    """
    from academic_core.tenant_databases import register_tenant_db
    return register_tenant_db(alias)


def archive_institut_db(alias):
    """
    Appelée à la suppression d'un institut : renomme sa base PostgreSQL
    (db_rytal_xxx -> db_rytal_xxx_archived_<timestamp>) plutôt que de la
    supprimer — les données restent récupérables, mais la base n'est plus à
    son nom actif. Retire aussi l'alias de settings.DATABASES et ferme sa
    connexion ouverte, pour qu'aucune requête ultérieure ne puisse encore la
    router vers ce nom (le RENAME échouerait sinon avec "database is being
    accessed by other users").

    Ne fait rien silencieusement si la base n'existe pas ou plus (institut
    déjà sans base tenant) — pas une erreur bloquante à ce stade, la
    suppression de l'InstitutConfig doit rester possible.

    Retourne le nouveau nom de base archivé (ou None) — stocké dans
    ArchivedInstitutDatabase.archived_path (champ générique, réutilisé ici
    pour un nom de base plutôt qu'un chemin de fichier).
    """
    from datetime import datetime
    from django.conf import settings
    from django.db import connections
    from academic_core.apps.academic_structure.pg_provisioning import database_exists, rename_database

    if not alias or alias == 'default':
        return None

    if alias in connections.databases:
        connections[alias].close()

    if not database_exists(alias):
        settings.DATABASES.pop(alias, None)
        return None

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    archived_name = f'{alias}_archived_{timestamp}'

    if not rename_database(alias, archived_name):
        return None

    settings.DATABASES.pop(alias, None)

    # Retire aussi le bloc .env de cet alias : sinon discover_tenant_databases()
    # le recharge tel quel dans settings.DATABASES au prochain redémarrage du
    # process, alors que la base a été renommée — un alias mort réapparaîtrait
    # à chaque boot (voir tenant_databases.py::remove_tenant_env_block).
    # Best-effort : un échec ici ne doit jamais bloquer l'archivage déjà fait.
    try:
        from academic_core.tenant_databases import remove_tenant_env_block
        remove_tenant_env_block(settings.BASE_DIR, alias)
    except Exception:
        pass

    return archived_name


def iter_institut_dbs():
    """
    Itère chaque InstitutConfig disposant d'une base tenant valide, sous la
    forme (config, alias) — alias étant déjà enregistré dans settings.DATABASES
    (voir register_institut_db). Couvre automatiquement tout institut créé
    après le démarrage du serveur, sans redémarrage requis.
    """
    from academic_core.apps.academic_structure.models import InstitutConfig

    configs = (InstitutConfig.objects.using('default')
               .exclude(db_alias='').exclude(db_alias__isnull=True)
               .select_related('faculty').order_by('nom'))
    for config in configs:
        alias = register_institut_db(config.db_alias)
        if alias:
            yield config, alias


def resolve_academic_years(request, param='annee', using=None):
    """
    Résout (années disponibles, année sélectionnée) scopées à la faculté active.

    Convention utilisée dans tout le projet (Modules EC, Maquettes) : l'année
    sélectionnée vient du paramètre GET `param` si valide, sinon l'année
    `is_current=True` de la faculté, sinon la plus récente.

    `using` permet de forcer un alias de base explicite (ex: certaines vues
    comptables forcent `_auth_db` de la session plutôt que le routeur
    thread-local, pour ignorer le filtre département) — par défaut, le
    routeur multi-tenant résout normalement via le thread-local courant.
    """
    from .models import AcademicYear

    faculty = getattr(request, 'active_faculty', None)
    years = AcademicYear.objects.using(using).order_by('-start_date') if using else AcademicYear.objects.order_by('-start_date')
    years = years.filter(faculty=faculty) if faculty else years.none()

    year_id = request.GET.get(param)
    selected = years.filter(pk=year_id).first() if year_id else None
    if not selected:
        selected = years.filter(is_current=True).first() or years.first()
    return years, selected
