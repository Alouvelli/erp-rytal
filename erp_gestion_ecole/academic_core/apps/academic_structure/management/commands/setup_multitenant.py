"""
Management command : provisionne la base PostgreSQL de chaque institut et,
avec --copy-data, migre les données historiques SQLite (db.sqlite3 pour
'default' + db_inst_<code>.sqlite3 par institut) utilisées avant le passage à
PostgreSQL.

Ce script :
  0. Avec --copy-data : si la base 'default' PostgreSQL est encore vide et que
     db.sqlite3 existe, copie d'abord ses données maîtres (Faculty,
     InstitutConfig, User, Role, AuditLog…) — sans quoi aucun InstitutConfig
     n'existe encore côté PostgreSQL pour les étapes suivantes.
  1. Assigne un alias PostgreSQL (db_rytal_<code>) à chaque InstitutConfig qui
     n'en a pas encore (ex: instituts créés par bulk_create, qui ne déclenche
     pas le signal post_save — voir signals.py::auto_create_institute_db).
  2. Provisionne (CREATE DATABASE + migrate) la base de chaque institut.
  3. Avec --copy-data : si un fichier db_inst_<code>.sqlite3 existe encore à la
     racine du dépôt, copie ses données vers la nouvelle base PostgreSQL. Les
     fichiers SQLite originaux ne sont jamais supprimés par ce script.

Usage :
    python manage.py setup_multitenant                # assigne/provisionne les alias manquants
    python manage.py setup_multitenant --copy-data     # + migre les données historiques
"""

import re
import sqlite3
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


def _slugify_code(code: str) -> str:
    """'ISI' -> 'isi', 'ESP-DAKAR' -> 'esp_dakar'"""
    return re.sub(r'[^a-z0-9]+', '_', code.lower()).strip('_')


# Modèles à ne PAS copier depuis un fichier SQLite historique vers une base
# TENANT (données maîtres/globales, déjà gérées côté 'default' PostgreSQL —
# voir MASTER_MODEL_NAMES / MASTER_APP_LABELS dans academic_core/db_router.py).
SKIP_MODELS = frozenset([
    'faculty', 'institutconfig', 'abonnementinstitut', 'institutfiliation',
    'archivedinstitutdatabase', 'controllerinstitut', 'institutdisabledtab',
    'institutdisabledfeature', 'platformactivation', 'platformactivationresettoken',
    'logentry', 'permission', 'group', 'contenttype', 'session',
    'auditlog', 'auditbackup', 'passwordresettoken',
])
# Modèles Django internes à ne jamais copier tels quels (auto-gérés par
# `migrate`/post_migrate — copier de vieux PKs SQLite les corromprait).
SKIP_MODELS_DJANGO_INTERNAL = frozenset(['logentry', 'permission', 'group', 'contenttype', 'session'])
SKIP_APPS = frozenset(['sessions', 'contenttypes', 'admin'])


class Command(BaseCommand):
    help = (
        "Provisionne la base PostgreSQL de chaque institut (db_rytal_<code>) et, "
        "avec --copy-data, migre les données de son ancienne base SQLite "
        "historique (db_inst_<code>.sqlite3) si elle existe encore."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--copy-data',
            action='store_true',
            default=False,
            help="Copier les données de l'ancienne base SQLite (db_inst_<code>.sqlite3) si elle existe",
        )

    def handle(self, *args, **options):
        copy_data = options['copy_data']

        from academic_core.apps.academic_structure.models import InstitutConfig
        from academic_core.apps.academic_structure.pg_provisioning import create_database
        from academic_core.tenant_databases import register_tenant_db, append_tenant_env_block

        if copy_data:
            self._maybe_copy_default_from_sqlite()

        configs = InstitutConfig.objects.using('default').select_related('faculty').all()
        if not configs.exists():
            self.stdout.write(self.style.WARNING('Aucun InstitutConfig trouvé.'))
            return

        for config in configs:
            faculty = config.faculty
            if not faculty:
                self.stdout.write(
                    self.style.WARNING(f'InstitutConfig pk={config.pk} sans faculté, ignoré.')
                )
                continue

            # Alias SQLite historique éventuel (db_inst_*, convention utilisée
            # avant cette migration) — sert à retrouver le fichier .sqlite3 à
            # copier, indépendamment du nouvel alias PostgreSQL calculé ci-dessous.
            legacy_alias = config.db_alias if config.db_alias.startswith('db_inst_') else None

            code = _slugify_code(faculty.code)
            alias = f'db_rytal_{code}'

            if config.db_alias != alias:
                self.stdout.write(f'  → {config.nom} : "{config.db_alias or "(aucun)"}" → "{alias}"')

            # 1. Provisionner la base PostgreSQL
            if not create_database(alias):
                self.stderr.write(self.style.ERROR(f'  [ERREUR] Création de {alias} échouée, institut ignoré.'))
                continue
            if not register_tenant_db(alias):
                self.stderr.write(self.style.ERROR(f'  [ERREUR] Enregistrement de {alias} échoué, institut ignoré.'))
                continue

            # 2. Migrer le schéma (idempotent : ne rejoue pas les migrations déjà appliquées)
            self.stdout.write(f'  → Migration du schéma sur {alias}...')
            call_command('migrate', database=alias, run_syncdb=True, verbosity=0, interactive=False)

            # 3. Copier les données historiques si demandé
            if copy_data and legacy_alias:
                legacy_path = settings.BASE_DIR / f'{legacy_alias}.sqlite3'
                if legacy_path.exists():
                    self._reconcile_roles_from_sqlite(legacy_path, alias)
                    self._copy_data_from_sqlite(legacy_path, alias, skip_models=SKIP_MODELS | {'role'})
                else:
                    self.stdout.write(f'    (pas de fichier {legacy_path.name}, rien à copier)')

            # 4. Mettre à jour db_alias + persister les paramètres d'accès dans .env
            InstitutConfig.objects.using('default').filter(pk=config.pk).update(db_alias=alias)
            append_tenant_env_block(settings.BASE_DIR, code.upper(), alias)

        self.stdout.write(self.style.SUCCESS('\n[OK] Setup multi-tenant terminé.'))

    # ── Copie des données depuis l'ancienne base SQLite ────────────────────────

    def _reconcile_roles_from_sqlite(self, sqlite_path: Path, dest_alias: str) -> None:
        """
        Remplace intégralement la table `roles` de `dest_alias` par son
        contenu SQLite d'origine (ids inclus) — AVANT toute autre copie de
        données.

        `roles` est peuplée par de nombreuses migrations RunPython
        (get_or_create par nom) qui s'exécutent AVANT ce script : leurs ids
        Postgres, attribués dans l'ordre d'exécution des migrations, ne
        correspondent PAS forcément aux ids historiques du fichier SQLite.
        Or toutes les FK copiées ensuite (User.role_id, etc.) référencent les
        ids SQLITE. Sans cette réconciliation faite EN PREMIER, `ON CONFLICT
        DO NOTHING` (dans _copy_table) ignore silencieusement les lignes en
        conflit de nom/id, laissant une table `roles` hybride où un même id
        désigne un rôle différent selon la base — et donc des comptes
        réassignés à un mauvais rôle après copie (bug constaté : un compte
        SI_ADMIN redevenait RESPONSABLE après migration).

        Sûr uniquement parce qu'appelée avant toute copie de `users` :
        aucune ligne ne référence encore les ids qu'on s'apprête à remplacer.
        """
        src = sqlite3.connect(str(sqlite_path))
        try:
            rows = src.execute(
                'SELECT id, name, description, created_at FROM roles ORDER BY id'
            ).fetchall()
        except sqlite3.OperationalError:
            return
        finally:
            src.close()
        if not rows:
            return

        from django.db import connections
        with connections[dest_alias].cursor() as cur:
            cur.execute('ALTER TABLE "roles" DISABLE TRIGGER ALL')
            try:
                cur.execute('DELETE FROM roles')
                cur.executemany(
                    'INSERT INTO roles (id, name, description, created_at) VALUES (%s, %s, %s, %s)',
                    rows,
                )
            finally:
                cur.execute('ALTER TABLE "roles" ENABLE TRIGGER ALL')
            self._reset_sequence(cur, 'roles', 'id')
        self.stdout.write(f'    [OK] roles réconciliés avec {sqlite_path.name} ({len(rows)} lignes)')

    def _maybe_copy_default_from_sqlite(self) -> None:
        """
        Si 'default' (PostgreSQL) est encore vide de tout InstitutConfig et que
        l'ancien fichier maître db.sqlite3 existe, copie ses données (Faculty,
        InstitutConfig, User, Role, AuditLog, PlatformActivation…) vers
        'default' — sans quoi aucun institut n'est visible pour le reste de
        cette commande. Les modèles tenant-only (voir TENANT_ONLY_APP_LABELS
        dans academic_core/db_router.py) sont exclus : ils ne doivent jamais
        contenir de données côté 'default'.
        """
        from academic_core.apps.academic_structure.models import InstitutConfig
        from academic_core.db_router import TENANT_ONLY_APP_LABELS

        if InstitutConfig.objects.using('default').exists():
            return

        sqlite_path = settings.BASE_DIR / 'db.sqlite3'
        if not sqlite_path.exists():
            self.stdout.write('  (pas de db.sqlite3 historique, "default" reste tel quel)')
            return

        self.stdout.write(f'→ "default" est vide : copie des données maîtres depuis {sqlite_path.name}...')
        self._reconcile_roles_from_sqlite(sqlite_path, 'default')
        skip_apps = SKIP_APPS | TENANT_ONLY_APP_LABELS
        self._copy_data_from_sqlite(
            sqlite_path, 'default',
            skip_models=SKIP_MODELS_DJANGO_INTERNAL | {'role'}, skip_apps=skip_apps,
        )

    def _copy_data_from_sqlite(self, sqlite_path: Path, dest_alias: str, skip_models=SKIP_MODELS, skip_apps=SKIP_APPS) -> None:
        """
        Copie toutes les tables (hors `skip_models`/`skip_apps`) depuis le
        fichier SQLite historique `sqlite_path` vers la base PostgreSQL
        `dest_alias`, via le pool de connexions Django. ON CONFLICT DO NOTHING
        rend l'opération rejouable sans risque de doublon.
        """
        from django.db import connections

        src = sqlite3.connect(str(sqlite_path))
        copied_tables = 0
        try:
            with connections[dest_alias].cursor() as dst_cur:
                for app_config in apps.get_app_configs():
                    if app_config.label in skip_apps:
                        continue
                    for model in app_config.get_models():
                        if model._meta.model_name in skip_models:
                            continue
                        try:
                            if self._copy_table(src, dst_cur, model):
                                copied_tables += 1
                        except Exception as exc:
                            self.stdout.write(
                                self.style.WARNING(f'    [!] {model._meta.label} : {exc}')
                            )
        finally:
            src.close()

        self.stdout.write(f'    → {copied_tables} table(s) copiée(s) vers {dest_alias}')

    def _copy_table(self, src: sqlite3.Connection, dst_cur, model) -> bool:
        table = model._meta.db_table

        try:
            rows = src.execute(f'SELECT * FROM "{table}"').fetchall()
        except sqlite3.OperationalError:
            return False  # table absente de l'ancienne base (migration ajoutée depuis)
        if not rows:
            return False

        col_info = src.execute(f'PRAGMA table_info("{table}")').fetchall()
        col_names = [c[1] for c in col_info]

        # SQLite stocke les booléens comme des entiers 0/1 (affinité de colonne,
        # pas de vrai type booléen) ; PostgreSQL a un type boolean strict qui
        # n'accepte aucune conversion implicite depuis un entier — sans cette
        # conversion, l'INSERT échoue avec "column ... is of type boolean but
        # expression is of type integer" pour chaque BooleanField.
        bool_columns = {
            f.column for f in model._meta.concrete_fields
            if f.get_internal_type() == 'BooleanField'
        }
        bool_indexes = [i for i, c in enumerate(col_names) if c in bool_columns]
        if bool_indexes:
            fixed_rows = []
            for row in rows:
                row = list(row)
                for idx in bool_indexes:
                    if row[idx] is not None:
                        row[idx] = bool(row[idx])
                fixed_rows.append(tuple(row))
            rows = fixed_rows

        placeholders = ','.join(['%s'] * len(col_names))
        cols_str = ','.join(f'"{c}"' for c in col_names)

        dst_cur.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER ALL')
        try:
            dst_cur.executemany(
                f'INSERT INTO "{table}" ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING',
                rows,
            )
        finally:
            dst_cur.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER ALL')

        self._reset_sequence(dst_cur, table, model._meta.pk.column)

        self.stdout.write(f'    [OK] {model._meta.label} : {len(rows)} ligne(s)')
        return True

    def _reset_sequence(self, dst_cur, table: str, pk_col: str) -> None:
        """
        Aligne la séquence PostgreSQL de la clé primaire sur le MAX(pk)
        réellement copié — sans ça, la séquence reste à sa valeur de départ
        (1) et la première création ORM ultérieure (id auto-assigné par
        nextval()) entre en collision avec une ligne copiée avec un id
        explicite (IntegrityError "duplicate key value violates unique
        constraint"). Ne fait rien si la colonne n'est pas une séquence
        (ex: PK non entière) ou si la table est restée vide.
        """
        dst_cur.execute('SELECT pg_get_serial_sequence(%s, %s)', [table, pk_col])
        seq = dst_cur.fetchone()[0]
        if not seq:
            return
        dst_cur.execute(f'SELECT MAX("{pk_col}") FROM "{table}"')
        max_id = dst_cur.fetchone()[0]
        if max_id is None:
            return
        dst_cur.execute('SELECT setval(%s, %s)', [seq, max_id])
