from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.conf import settings


def _all_databases():
    # Bases institut D'ABORD, 'default' en dernier recours. 'default' contient
    # souvent une copie fantôme d'un compte tenant (ENSEIGNANT/ETUDIANT/...) —
    # voir sync_user_to_default_db — utilisée uniquement pour l'intégrité FK
    # d'AuditLog, avec le mot de passe synchronisé mais AUCUNE des données
    # opérationnelles (Student, etc., toutes TENANT_ONLY_APP_LABELS). Si
    # 'default' était consulté en premier, authenticate() authentifiait sur
    # cette copie fantôme : la session entière restait ensuite routée vers
    # 'default' (base tenant introuvable, toutes les données propres à
    # l'utilisateur y apparaissant vides) au lieu de sa vraie base institut.
    return [alias for alias in settings.DATABASES if alias != 'default'] + ['default']


def _get_institute_db_for_user(user) -> str | None:
    """
    Détermine la base de données de l'institut auquel appartient l'utilisateur.

    Ordre de résolution :
      1. INST_ADMIN / SI_ADMIN  → via user.institut_config.db_alias
      2. Autres rôles           → via user.department.faculty  (RESPONSABLE, ENSEIGNANT…)
                                → via user.direction.faculty   (ADMIN_DIRECTION…)
      3. Aucun lien trouvé      → None (l'appelant utilise la base où l'user a été trouvé)

    Uniquement le Super Admin (ADMIN) retourne None intentionnellement : sa base est 'default'.
    """
    try:
        role_name = user.role.name if user.role_id and user.role else None
    except Exception:
        role_name = None

    # Super admin : toujours default (pas de base institut)
    if role_name == 'ADMIN':
        return None

    # INST_ADMIN / SI_ADMIN : via institut_config
    if role_name in ('INST_ADMIN', 'SI_ADMIN'):
        from academic_core.apps.accounts.db_utils import get_institute_db_alias
        return get_institute_db_alias(user)

    # Tous les autres rôles : déterminer l'institut via department ou direction.
    # IMPORTANT : ne jamais faire `user.department`/`user.direction` (accès
    # paresseux) — cette traversée ne respecte PAS user._state.db, elle
    # re-consulte le routeur via le thread-local get_current_db() qui, à ce
    # stade de l'authentification (avant DepartmentMiddleware), vaut 'default'.
    # La table Department locale de 'default' contient un schéma cloné avec
    # ses PROPRES lignes (résidu d'un institut quelconque), sans rapport avec
    # celles de la base institut où `user` a réellement été chargé — un même
    # pk y désigne un département totalement différent, faisant router
    # l'utilisateur vers le mauvais institut. On force donc explicitement la
    # requête sur user._state.db (la base où authenticate() a trouvé ce user).
    faculty_id = None
    user_db = user._state.db or 'default'
    try:
        if user.department_id:
            from academic_core.apps.academic_structure.models import Department
            dept = Department.objects.using(user_db).filter(pk=user.department_id).first()
            if dept:
                faculty_id = dept.faculty_id
    except Exception:
        pass

    if not faculty_id:
        try:
            if user.direction_id:
                from academic_core.apps.accounts.models import Direction
                direction = Direction.objects.using(user_db).filter(pk=user.direction_id).first()
                if direction:
                    faculty_id = direction.faculty_id
        except Exception:
            pass

    if not faculty_id:
        return None

    # Chercher db_alias dans la table institut_config (toujours dans default)
    try:
        from academic_core.apps.academic_structure.models import InstitutConfig
        alias = (InstitutConfig.objects.using('default')
                 .filter(faculty_id=faculty_id).exclude(db_alias='')
                 .values_list('db_alias', flat=True).first())
        if alias and alias in settings.DATABASES:
            return alias
    except Exception:
        pass

    return None


class MultiDBAuthBackend(ModelBackend):
    """
    Backend multi-tenant : parcourt toutes les bases (une par institut + default) pour trouver l'utilisateur.

    Règle d'isolation : seul le Super Admin (ADMIN) est autorisé à utiliser 'default'
    comme base de session. Tout autre utilisateur est routé vers la base de son institut.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        UserModel = get_user_model()

        for db in _all_databases():
            user = None
            # Identification strictement par email (cf. LoginForm.clean_username) —
            # plus de fallback/lookup par username, même si la valeur saisie
            # coïncide accidentellement avec le username d'un autre compte.
            try:
                user = UserModel._default_manager.using(db).get(email__iexact=username)
            except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
                continue
            except Exception:
                continue

            if user is None:
                continue
            if not user.check_password(password):
                continue
            if not self.user_can_authenticate(user):
                continue

            if request is not None:
                # Déterminer la base de session correcte.
                # La base default n'est accessible qu'au Super Admin.
                inst_db = _get_institute_db_for_user(user)
                request._auth_db_used = inst_db if inst_db else db

            return user

        # Anti-timing attack
        UserModel().set_password(password)
        return None

    def get_user(self, user_id):
        """
        Appelé par AuthenticationMiddleware à chaque requête.
        On essaie la base active (définie par ResetDBMiddleware depuis _auth_db en session)
        EN PREMIER pour que le hash de session corresponde au bon utilisateur.
        """
        from academic_core.db_router import get_current_db
        UserModel = get_user_model()

        current_db = get_current_db()
        # Priorité à la base active, puis les autres
        ordered = [current_db] + [db for db in _all_databases() if db != current_db]

        for db in ordered:
            try:
                user = UserModel._default_manager.using(db).get(pk=user_id)
                if self.user_can_authenticate(user):
                    return user
            except UserModel.DoesNotExist:
                continue
            except Exception:
                continue

        return None
