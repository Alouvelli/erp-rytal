from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from .models import AcademicYear, Faculty, Department, Program, Class, Semester, Level, InstitutConfig, InstitutFiliation, AbonnementInstitut, InstitutEmailConfig, InstitutPaymentConfig, seed_default_contrat_articles
from django.utils import timezone as tz_utils
from academic_core.apps.accounts.models import User


def _forcer_deconnexion_institut(config, requester=None):
    """
    Supprime toutes les sessions Django actives des utilisateurs appartenant
    à l'institut donné (InstitutConfig). Appelée dès qu'un institut est suspendu
    ou que son abonnement devient invalide.
    Retourne le nombre de sessions invalidées.
    """
    from django.contrib.sessions.models import Session

    # 1. Collecter les PKs de tous les utilisateurs de l'institut
    #    a) via faculty → departments → users
    faculty = getattr(config, 'faculty', None)
    user_pks = set()
    if faculty:
        user_pks = set(
            User.objects.filter(department__faculty=faculty)
            .values_list('pk', flat=True)
        )
    #    b) les administrateurs d'institut directement liés à cette config
    user_pks |= set(
        User.objects.filter(institut_config=config)
        .values_list('pk', flat=True)
    )
    # Ne jamais déconnecter le compte qui effectue l'action
    if requester:
        user_pks.discard(requester.pk)

    if not user_pks:
        return 0

    # 2. Parcourir toutes les sessions et supprimer celles de ces utilisateurs
    deleted = 0
    for session in Session.objects.all():
        try:
            data = session.get_decoded()
            uid = data.get('_auth_user_id')
            if uid and int(uid) in user_pks:
                session.delete()
                deleted += 1
        except Exception:
            pass
    return deleted


# ── Mixin admin/responsable ───────────────────────────────────────────────────
class _AdminResponsableMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_manage_dept()


# ── Index structure ───────────────────────────────────────────────────────────
@login_required
def structure_index(request):
    from django.urls import reverse
    dept     = request.active_department
    faculty  = getattr(request, 'active_faculty', None)
    user     = request.user
    is_super      = user.is_super_admin()
    can_see_global = is_super or user.is_inst_admin()  # INST_ADMIN, ASSISTANTE_DG, CONTROLEUR

    if faculty and not is_super:
        years_qs = AcademicYear.objects.filter(faculty=faculty)
        dept_qs  = Department.objects.filter(faculty=faculty)
    elif is_super:
        years_qs = AcademicYear.objects.all()
        dept_qs  = Department.objects.all()
    else:
        years_qs = AcademicYear.objects.none()
        dept_qs  = Department.objects.none()

    # Accès rapides filtrés selon le rôle
    quick_links = []
    if can_see_global:
        quick_links += [
            ('Années académiques', reverse('academic_structure:years'),       'bi bi-calendar3',     '#00173B'),
            ('Instituts',          reverse('academic_structure:faculties'),    'bi bi-building',      '#7c3aed'),
        ]
    quick_links += [
        ('Départements',          reverse('academic_structure:departments'),  'bi bi-diagram-3',     '#16a34a'),
        ('Filières / Programmes', reverse('academic_structure:programs'),     'bi bi-collection',    '#d97706'),
        ('Classes',               reverse('academic_structure:classes'),      'bi bi-mortarboard',   '#dc2626'),
        ('Semestres',             reverse('academic_structure:semesters'),    'bi bi-calendar-range','#00173B'),
        ('Niveaux',               reverse('academic_structure:levels'),       'bi bi-bar-chart-steps','#0891b2'),
    ]

    # Seuls super-admin et inst-admin peuvent gérer les départements
    can_manage_departments = is_super or user.is_inst_admin()

    return render(request, 'academic_structure/index.html', {
        'total_years':            years_qs.count() if can_see_global else None,
        'total_departments':      dept_qs.count(),
        'total_classes':          Class.objects.filter(
            program__department=dept).count() if dept else 0,
        'can_see_global':         can_see_global,
        'can_manage_departments': can_manage_departments,
        'quick_links':            quick_links,
    })


# ── Sélection de département ───────────────────────────────────────────────────
@login_required
def select_department(request):
    user = request.user

    # Pas de select_related('faculty') : Faculty est un modèle maître, Department
    # est routé par tenant — voir DepartmentManageView.get_queryset() pour le détail.
    all_depts = Department.objects.filter(is_active=True).select_related('admin').order_by('name')
    # INST_ADMIN can only switch between departments of their own institute
    if user.is_inst_admin():
        config = getattr(user, 'institut_config', None)
        if config:
            inst_faculty = getattr(config, 'faculty', None)
            if inst_faculty:
                all_depts = all_depts.filter(faculty=inst_faculty)

    # Pour un enseignant : ses départements en premier (là où il a des séances)
    teacher_dept_ids = set()
    if user.is_enseignant():
        from academic_core.apps.timetable.models import TimetableEntry
        teacher_profile = getattr(user, 'teacher_profile', None)
        if teacher_profile:
            teacher_dept_ids = set(
                TimetableEntry.objects.filter(teacher=teacher_profile, is_active=True)
                .values_list('class_group__program__department_id', flat=True)
                .distinct()
            )

    if request.method == 'POST':
        dept_id = request.POST.get('department_id')
        if dept_id:
            try:
                dept = Department.objects.get(pk=dept_id, is_active=True)
                request.session['active_department_id'] = dept.pk
                messages.success(request, f"Département « {dept.name} » sélectionné.")
                next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard:index'
                return redirect(next_url)
            except Department.DoesNotExist:
                messages.error(request, "Département introuvable.")
        else:
            request.session.pop('active_department_id', None)
            messages.info(request, "Département désélectionné.")
            return redirect('dashboard:index')

    return render(request, 'academic_structure/select_department.html', {
        'departments': all_depts,
        'teacher_dept_ids': teacher_dept_ids,
        'active_department': request.active_department,
        'next': request.GET.get('next', ''),
    })


# ── Gestion des départements (CRUD SuperAdmin) ────────────────────────────────
class DepartmentManageView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = Department
    template_name = 'academic_structure/departments_manage.html'
    context_object_name = 'departments'

    def test_func(self):
        return self.request.user.is_admin()

    def get_queryset(self):
        # Pas de select_related('faculty') : Faculty est un modèle maître
        # (toujours en base "default") alors que Department est routé par
        # tenant — select_related générerait un INNER JOIN exécuté sur la
        # base tenant, dont la table locale `faculties` est vide par
        # conception (aucune donnée Faculty n'y est jamais écrite). Ça
        # filtrait silencieusement TOUS les départements. `dept.faculty` reste
        # accessible normalement (requête séparée, correctement routée vers
        # "default" par le routeur).
        qs = Department.objects.select_related('admin').order_by('name')
        faculty  = getattr(self.request, 'active_faculty', None)
        is_super = self.request.user.is_super_admin()

        if is_super and not faculty:
            # Super Admin sans institut sélectionné : aucun département
            return qs.none()
        if faculty:
            qs = qs.filter(faculty=faculty)
        elif not is_super:
            # INST_ADMIN sans faculté résolue : aucun département
            return qs.none()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        faculty  = getattr(self.request, 'active_faculty', None)
        is_super = self.request.user.is_super_admin()

        # Super Admin voit toutes les facultés dans le formulaire de création
        ctx['faculties'] = Faculty.objects.all() if is_super else (
            Faculty.objects.filter(pk=faculty.pk) if faculty else Faculty.objects.none()
        )
        # Inclut aussi ENSEIGNANT (pas seulement RESPONSABLE) : un enseignant
        # existant doit pouvoir être nommé chef de département directement
        # depuis ce sélecteur, sans détour par la création d'un nouveau
        # compte — _assign_admin bascule désormais réellement son rôle vers
        # RESPONSABLE (voir academic_structure/services.py::assign_department_head).
        responsables_qs = User.objects.filter(
            role__name__in=['RESPONSABLE', 'ENSEIGNANT']
        ).select_related('role').order_by('role__name', 'last_name')
        if faculty:
            responsables_qs = responsables_qs.filter(department__faculty=faculty)
        elif not is_super:
            responsables_qs = responsables_qs.none()
        ctx['responsables'] = responsables_qs
        ctx['institut_required'] = is_super and not faculty
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'create':
            return self._create(request)
        elif action == 'edit':
            return self._edit(request)
        elif action == 'toggle':
            return self._toggle(request)
        elif action == 'assign_admin':
            return self._assign_admin(request)
        return redirect('academic_structure:departments_manage')

    def _create(self, request):
        code     = request.POST.get('code', '').strip()
        name     = request.POST.get('name', '').strip()
        fac_id   = request.POST.get('faculty')
        desc     = request.POST.get('description', '').strip()
        admin_id = request.POST.get('admin_user')
        if not code or not name:
            messages.error(request, "Code et nom sont obligatoires.")
            return redirect('academic_structure:departments_manage')
        try:
            faculty = Faculty.objects.get(pk=fac_id)
        except (Faculty.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Institut invalide.")
            return redirect('academic_structure:departments_manage')
        dept = Department.objects.create(code=code, name=name, faculty=faculty, description=desc)
        if admin_id:
            try:
                admin_user = User.objects.get(pk=admin_id)
                dept.admin = admin_user
                dept.save()
                admin_user.department = dept
                admin_user.save(update_fields=['department'])
            except User.DoesNotExist:
                pass
        messages.success(request, f"Département « {dept.name} » créé.")
        return redirect('academic_structure:departments_manage')

    def _edit(self, request):
        dept = get_object_or_404(Department, pk=request.POST.get('dept_id'))
        dept.name = request.POST.get('name', dept.name).strip()
        dept.description = request.POST.get('description', '').strip()
        fac_id = request.POST.get('faculty')
        if fac_id:
            try:
                dept.faculty = Faculty.objects.get(pk=fac_id)
            except Faculty.DoesNotExist:
                pass
        dept.save()
        messages.success(request, f"Département « {dept.name} » mis à jour.")
        return redirect('academic_structure:departments_manage')

    def _toggle(self, request):
        dept = get_object_or_404(Department, pk=request.POST.get('dept_id'))
        dept.is_active = not dept.is_active
        dept.save(update_fields=['is_active'])
        status = "activé" if dept.is_active else "désactivé"
        messages.success(request, f"Département « {dept.name} » {status}.")
        return redirect('academic_structure:departments_manage')

    def _assign_admin(self, request):
        from .services import assign_department_head

        dept = get_object_or_404(Department, pk=request.POST.get('dept_id'))
        admin_id = request.POST.get('admin_user')
        if admin_id:
            try:
                new_admin = User.objects.get(pk=admin_id)
                assign_department_head(dept, new_admin)
                messages.success(request, f"« {new_admin.get_full_name()} » nommé(e) Chef de Département de {dept.name}.")
            except User.DoesNotExist:
                messages.error(request, "Utilisateur introuvable.")
        else:
            if dept.admin:
                old = dept.admin
                old.department = None
                old.save(update_fields=['department'])
            dept.admin = None
            dept.save()
            messages.info(request, f"Admin retiré du département {dept.name}.")
        return redirect('academic_structure:departments_manage')


# ── Listes standards ──────────────────────────────────────────────────────────
class AcademicYearListView(_AdminResponsableMixin, ListView):
    model = AcademicYear
    template_name = 'academic_structure/years.html'
    context_object_name = 'years'

    def _faculty(self):
        if self.request.user.is_super_admin():
            return None  # super admin voit tout → pas de filtre
        faculty = getattr(self.request, 'active_faculty', None)
        if faculty:
            return faculty
        # Fallback : dériver la faculty depuis la base de l'institut en session
        try:
            auth_db = self.request.session.get('_auth_db', 'default')
            if auth_db and auth_db != 'default':
                config = InstitutConfig.objects.using('default').filter(db_alias=auth_db).first()
                if config and config.faculty:
                    return config.faculty
        except Exception:
            pass
        return None

    def get_queryset(self):
        qs = AcademicYear.objects.all()
        fac = self._faculty()
        if self.request.user.is_super_admin():
            return qs
        if fac:
            # Chaque institut a sa propre base de données : une année académique
            # sans faculty renseignée (données historiques/anciennes) appartient
            # forcément à l'unique institut de cette base, donc on l'inclut aussi.
            return qs.filter(Q(faculty=fac) | Q(faculty__isnull=True))
        return qs.none()

    def post(self, request, *args, **kwargs):
        fac = self._faculty()
        action = request.POST.get('action', 'create')
        if action == 'edit':
            qs = AcademicYear.objects.filter(Q(faculty=fac) | Q(faculty__isnull=True)) if fac else AcademicYear.objects.all()
            year = get_object_or_404(qs, pk=request.POST.get('pk'))
            year.label      = request.POST.get('name', year.label).strip()
            year.start_date = request.POST.get('start_date') or year.start_date
            year.end_date   = request.POST.get('end_date') or year.end_date
            year.is_current = bool(request.POST.get('is_current'))
            if not year.faculty_id and fac:
                # Auto-corrige les anciennes années créées sans faculty renseignée
                year.faculty = fac
            year.save()
            messages.success(request, f"Année « {year.label} » modifiée.")
            return redirect('academic_structure:years')
        if action == 'delete':
            qs = AcademicYear.objects.filter(Q(faculty=fac) | Q(faculty__isnull=True)) if fac else AcademicYear.objects.all()
            year = get_object_or_404(qs, pk=request.POST.get('pk'))
            label = year.label
            year.delete()
            messages.success(request, f"Année « {label} » supprimée.")
            return redirect('academic_structure:years')
        # create
        label = request.POST.get('name', '').strip()
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        is_current = bool(request.POST.get('is_current'))
        if not label:
            messages.error(request, "Le nom de l'année est obligatoire.")
            return redirect('academic_structure:years')
        if AcademicYear.objects.filter(label=label, faculty=fac).exists():
            messages.error(request, f"L'année « {label} » existe déjà.")
            return redirect('academic_structure:years')
        year = AcademicYear.objects.create(
            label=label, start_date=start_date, end_date=end_date,
            is_current=is_current, faculty=fac,
        )
        messages.success(request, f"Année académique « {year.label} » créée.")
        return redirect('academic_structure:years')


# ── Gestion des niveaux d'études ──────────────────────────────────────────────
class LevelListView(_AdminResponsableMixin, ListView):
    """
    Niveaux d'études (BT, DTS, BTS, PF2E, Licence 1-3, Master 1-2…). Level est
    routé par tenant (pas de FK faculty) : chaque institut a sa propre liste,
    initialisée automatiquement avec les niveaux standards au premier accès
    si elle est vide (table clonée vide à la création de l'institut, comme
    pour Role — voir sync_roles_to_institute_db).
    """
    model = Level
    template_name = 'academic_structure/levels.html'
    context_object_name = 'levels'

    STANDARD_LEVELS = [
        'BT', 'DTS', 'BTS', 'PF2E',
        'Licence 1', 'Licence 2', 'Licence 3', 'Master 1', 'Master 2',
    ]

    def get_queryset(self):
        qs = Level.objects.order_by('order', 'name')
        if not qs.exists():
            Level.objects.bulk_create([
                Level(name=name, order=i + 1)
                for i, name in enumerate(self.STANDARD_LEVELS)
            ])
            qs = Level.objects.order_by('order', 'name')
        return qs

    def post(self, request, *args, **kwargs):
        from django.db.models import Max
        action = request.POST.get('action', 'create')
        if action == 'edit':
            level = get_object_or_404(Level, pk=request.POST.get('pk'))
            name = request.POST.get('name', '').strip()
            if not name:
                messages.error(request, "Le nom du niveau est obligatoire.")
                return redirect('academic_structure:levels')
            if Level.objects.exclude(pk=level.pk).filter(name=name).exists():
                messages.error(request, f"Le niveau « {name} » existe déjà.")
                return redirect('academic_structure:levels')
            level.name = name
            level.order = request.POST.get('order') or level.order
            level.save()
            messages.success(request, f"Niveau « {level.name} » modifié.")
            return redirect('academic_structure:levels')
        if action == 'delete':
            level = get_object_or_404(Level, pk=request.POST.get('pk'))
            from academic_core.apps.accounting.models import FraisGenerauxNiveau, HourlyRate
            if FraisGenerauxNiveau.objects.filter(level=level).exists() or HourlyRate.objects.filter(level=level).exists():
                messages.error(
                    request,
                    f"Impossible de supprimer « {level.name} » : des configurations "
                    "financières (frais généraux ou taux horaire) y sont rattachées. "
                    "Supprimez-les d'abord."
                )
                return redirect('academic_structure:levels')
            name = level.name
            level.delete()
            messages.success(request, f"Niveau « {name} » supprimé.")
            return redirect('academic_structure:levels')
        # create
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "Le nom du niveau est obligatoire.")
            return redirect('academic_structure:levels')
        if Level.objects.filter(name=name).exists():
            messages.error(request, f"Le niveau « {name} » existe déjà.")
            return redirect('academic_structure:levels')
        order = request.POST.get('order') or ((Level.objects.aggregate(m=Max('order'))['m'] or 0) + 1)
        Level.objects.create(name=name, order=order)
        messages.success(request, f"Niveau « {name} » créé.")
        return redirect('academic_structure:levels')


class FacultyListView(_AdminResponsableMixin, ListView):
    """
    Liste des instituts (Faculty — l'entité racine du multi-tenant). Un Super
    Admin voit et gère tous les instituts ; tout autre rôle (INST_ADMIN,
    Administrateur de direction, Contrôleur interne, Chef de département…) ne
    voit et ne peut modifier QUE son propre institut — jamais les autres, et
    jamais en créer ou en supprimer (opérations réservées au Super Admin, car
    elles créent/détruisent un tenant entier de la plateforme).
    """
    model = Faculty
    template_name = 'academic_structure/faculties.html'
    context_object_name = 'faculties'

    def get_queryset(self):
        qs = Faculty.objects.order_by('code')
        if not self.request.user.is_super_admin():
            faculty = getattr(self.request, 'active_faculty', None)
            qs = qs.filter(pk=faculty.pk) if faculty else qs.none()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['departments_count'] = {
            f.pk: f.departments.count() for f in ctx['faculties']
        }
        ctx['is_super_admin'] = self.request.user.is_super_admin()
        return ctx

    def post(self, request, *args, **kwargs):
        is_super = request.user.is_super_admin()
        action = request.POST.get('action', 'create')

        if action in ('edit', 'delete'):
            f = get_object_or_404(Faculty, pk=request.POST.get('pk'))
            own_faculty = getattr(request, 'active_faculty', None)
            if not is_super and (not own_faculty or f.pk != own_faculty.pk):
                messages.error(request, "Vous ne pouvez gérer que votre propre institut.")
                return redirect('academic_structure:faculties')

        if action == 'edit':
            f = get_object_or_404(Faculty, pk=request.POST.get('pk'))
            f.code = request.POST.get('code', f.code).strip().upper()
            f.name = request.POST.get('name', f.name).strip()
            f.dean = request.POST.get('description', f.dean).strip()
            f.save()
            messages.success(request, f"Institut « {f.name} » modifiée.")
            return redirect('academic_structure:faculties')
        if action == 'delete':
            if not is_super:
                messages.error(request, "La suppression d'un institut est réservée au Super Admin.")
                return redirect('academic_structure:faculties')
            f = get_object_or_404(Faculty, pk=request.POST.get('pk'))
            name = f.name
            f.delete()
            messages.success(request, f"Institut « {name} » supprimée.")
            return redirect('academic_structure:faculties')

        # Création d'un nouvel institut : réservée au Super Admin (crée un
        # nouveau tenant de la plateforme).
        if not is_super:
            messages.error(request, "La création d'un institut est réservée au Super Admin.")
            return redirect('academic_structure:faculties')
        code = request.POST.get('code', '').strip().upper()
        name = request.POST.get('name', '').strip()
        desc = request.POST.get('description', '').strip()
        if not code or not name:
            messages.error(request, "Code et nom sont obligatoires.")
            return redirect('academic_structure:faculties')
        if Faculty.objects.filter(code=code).exists():
            messages.error(request, f"Le code « {code} » existe déjà.")
            return redirect('academic_structure:faculties')
        Faculty.objects.create(code=code, name=name, dean=desc)
        messages.success(request, f"Institut « {name} » créée.")
        return redirect('academic_structure:faculties')


class DepartmentListView(_AdminResponsableMixin, ListView):
    model = Department
    template_name = 'academic_structure/departments.html'
    context_object_name = 'departments'

    def get_queryset(self):
        # Pas de select_related('faculty') ni order_by('faculty__code', ...) :
        # Faculty est un modèle maître, Department est routé par tenant — les
        # deux forceraient un JOIN sur la table locale `faculties`, toujours
        # vide côté tenant (voir DepartmentManageView.get_queryset()).
        qs = Department.objects.select_related('admin').order_by('code')
        faculty = getattr(self.request, 'active_faculty', None)
        if faculty and not self.request.user.is_admin():
            qs = qs.filter(faculty=faculty)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        faculty = getattr(self.request, 'active_faculty', None)
        if faculty and not self.request.user.is_admin():
            ctx['faculties'] = Faculty.objects.filter(pk=faculty.pk)
        else:
            ctx['faculties'] = Faculty.objects.all()
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', 'create')
        if action == 'edit':
            d = get_object_or_404(Department, pk=request.POST.get('pk'))
            d.code = request.POST.get('code', d.code).strip()
            d.name = request.POST.get('name', d.name).strip()
            fac_id = request.POST.get('faculty')
            if fac_id:
                try:
                    d.faculty = Faculty.objects.get(pk=fac_id)
                except Faculty.DoesNotExist:
                    pass
            d.save()
            messages.success(request, f"Département « {d.name} » modifié.")
            return redirect('academic_structure:departments')
        if action == 'delete':
            d = get_object_or_404(Department, pk=request.POST.get('pk'))
            name = d.name
            d.delete()
            messages.success(request, f"Département « {name} » supprimé.")
            return redirect('academic_structure:departments')
        code   = request.POST.get('code', '').strip()
        name   = request.POST.get('name', '').strip()
        fac_id = request.POST.get('faculty')
        if not code or not name:
            messages.error(request, "Code et nom sont obligatoires.")
            return redirect('academic_structure:departments')
        try:
            faculty = Faculty.objects.get(pk=fac_id)
        except (Faculty.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Institut invalide.")
            return redirect('academic_structure:departments')
        Department.objects.create(code=code, name=name, faculty=faculty)
        messages.success(request, f"Département « {name} » créé.")
        return redirect('academic_structure:departments')


class ProgramListView(_AdminResponsableMixin, ListView):
    model = Program
    template_name = 'academic_structure/programs.html'
    context_object_name = 'programs'

    def get_queryset(self):
        # Pas de select_related('department__faculty') : Faculty est un modèle
        # maître, Department (et donc Program) est routé par tenant — le hop
        # __faculty forcerait un INNER JOIN chaîné sur la table locale
        # `faculties`, toujours vide côté tenant, faisant disparaître tous
        # les programmes.
        qs = Program.objects.select_related('department').order_by('code')
        dept    = self.request.active_department
        faculty = getattr(self.request, 'active_faculty', None)
        if dept:
            qs = qs.filter(department=dept)
        elif faculty:
            qs = qs.filter(department__faculty=faculty)
        elif not self.request.user.is_admin():
            qs = qs.none()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        faculty = getattr(self.request, 'active_faculty', None)
        depts_qs = Department.objects.filter(is_active=True).order_by('name')
        if faculty:
            depts_qs = depts_qs.filter(faculty=faculty)
        ctx['departments'] = depts_qs
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', 'create')
        if action == 'edit':
            p = get_object_or_404(Program, pk=request.POST.get('pk'))
            p.code  = request.POST.get('code', p.code).strip()
            p.name  = request.POST.get('name', p.name).strip()
            p.level = request.POST.get('level', p.level or '').strip()
            dept_id = request.POST.get('department')
            if dept_id:
                try:
                    p.department = Department.objects.get(pk=dept_id)
                except Department.DoesNotExist:
                    pass
            p.save()
            messages.success(request, f"Filière « {p.name} » modifiée.")
            return redirect('academic_structure:programs')
        if action == 'delete':
            p = get_object_or_404(Program, pk=request.POST.get('pk'))
            name = p.name
            p.delete()
            messages.success(request, f"Filière « {name} » supprimée.")
            return redirect('academic_structure:programs')
        code    = request.POST.get('code', '').strip()
        name    = request.POST.get('name', '').strip()
        level   = request.POST.get('level', '').strip()
        dept_id = request.POST.get('department')
        if not code or not name:
            messages.error(request, "Code et nom sont obligatoires.")
            return redirect('academic_structure:programs')
        try:
            dept = Department.objects.get(pk=dept_id)
        except (Department.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Département invalide.")
            return redirect('academic_structure:programs')
        Program.objects.create(code=code, name=name, level=level, department=dept)
        messages.success(request, f"Filière « {name} » créée.")
        return redirect('academic_structure:programs')


_FRAIS_FIELDS = (
    'montant_global', 'frais_mensuel', 'frais_inscription', 'frais_tenue',
    'frais_assurance', 'frais_amea', 'frais_bibliotheque', 'frais_soutenance',
    'frais_soutenance_speciale',
)


def _frais_obligatoires_error(request):
    """
    Valide que le montant global et la mensualité de la formation sont bien
    renseignés (champs obligatoires). Retourne un message d'erreur, ou None
    si la saisie est valide.
    """
    for field, label in (('montant_global', 'Montant global de la formation'),
                          ('frais_mensuel', 'Mensualité de la formation')):
        raw = (request.POST.get(field) or '').strip()
        if not raw:
            return f"Le champ « {label} » est obligatoire."
        try:
            float(raw)
        except ValueError:
            return f"Le champ « {label} » doit être un nombre valide."
    return None


def _save_frais_classe(cls, request):
    """
    Crée/modifie/supprime la configuration de frais (FraisMensuelClasse) liée à
    une classe, à partir des champs POST (montant_global, frais_mensuel,
    frais_tenue, frais_assurance, frais_amea, frais_bibliotheque).
    Supprime la configuration si tous les champs sont vides.
    """
    from academic_core.apps.accounting.models import FraisMensuelClasse

    values = {}
    any_value = False
    for field in _FRAIS_FIELDS:
        raw = (request.POST.get(field) or '').strip()
        if raw:
            try:
                values[field] = float(raw)
                any_value = True
            except ValueError:
                values[field] = None
        else:
            values[field] = None

    if not any_value:
        FraisMensuelClasse.objects.filter(class_group=cls).delete()
        return

    obj, _created = FraisMensuelClasse.objects.get_or_create(class_group=cls)
    for field, val in values.items():
        setattr(obj, field, val)
    obj.updated_by = request.user
    obj.save()


class ClassListView(_AdminResponsableMixin, ListView):
    model = Class
    template_name = 'academic_structure/classes.html'
    context_object_name = 'classes'

    def get_queryset(self):
        qs = Class.objects.select_related(
            'program__department', 'level', 'academic_year', 'frais_mensuel_config'
        ).order_by('academic_year', 'code')
        dept    = self.request.active_department
        faculty = getattr(self.request, 'active_faculty', None)
        if dept:
            qs = qs.filter(program__department=dept)
        elif faculty:
            qs = qs.filter(program__department__faculty=faculty)
        elif not self.request.user.is_admin():
            qs = qs.none()

        # Année académique : par défaut, seules les classes de l'année en cours
        # sont affichées — celles d'une année précédente ne doivent pas rester
        # mélangées avec l'année en cours. "Toutes les années" reste
        # sélectionnable explicitement pour consulter l'historique.
        year_param = self.request.GET.get('year')
        if year_param == 'all':
            pass
        elif year_param:
            qs = qs.filter(academic_year_id=year_param)
        else:
            fac_for_years = faculty or (dept.faculty if dept else None)
            current_year_qs = AcademicYear.objects.filter(is_current=True)
            if fac_for_years:
                current_year_qs = current_year_qs.filter(faculty=fac_for_years)
            current_year = current_year_qs.first()
            if current_year:
                qs = qs.filter(academic_year=current_year)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        faculty = getattr(self.request, 'active_faculty', None)
        programs_qs = Program.objects.select_related('department').order_by('name')
        if faculty:
            programs_qs = programs_qs.filter(department__faculty=faculty)
        ctx['programs'] = programs_qs
        from academic_core.apps.academic_structure.models import Department
        dept_qs = Department.objects.order_by('name')
        if faculty:
            dept_qs = dept_qs.filter(faculty=faculty)
        ctx['departments'] = dept_qs
        fac_years = getattr(self.request, 'active_faculty', None)
        years_qs = AcademicYear.objects.order_by('-start_date')
        if fac_years and not self.request.user.is_super_admin():
            years_qs = years_qs.filter(faculty=fac_years)
        ctx['academic_years'] = years_qs
        ctx['levels'] = Level.objects.order_by('order')
        ctx['selected_year_param'] = self.request.GET.get('year', '')
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', 'create')
        if action == 'edit':
            frais_error = _frais_obligatoires_error(request)
            if frais_error:
                messages.error(request, frais_error)
                return redirect('academic_structure:classes')
            c = get_object_or_404(Class, pk=request.POST.get('pk'))
            c.name     = request.POST.get('name', c.name).strip()
            c.domaine  = request.POST.get('domaine', c.domaine or '').strip()
            c.mention  = request.POST.get('mention', c.mention or '').strip()
            c.capacity = int(request.POST.get('max_students') or c.capacity)
            prog_id  = request.POST.get('program')
            yr_id    = request.POST.get('academic_year')
            lvl_id   = request.POST.get('level')
            if prog_id:
                try:
                    c.program = Program.objects.get(pk=prog_id)
                except Program.DoesNotExist:
                    pass
            if yr_id:
                try:
                    c.academic_year = AcademicYear.objects.get(pk=yr_id)
                except AcademicYear.DoesNotExist:
                    pass
            if lvl_id:
                try:
                    c.level = Level.objects.get(pk=lvl_id)
                except Level.DoesNotExist:
                    pass
            else:
                c.level = None
            c.save()
            _save_frais_classe(c, request)
            messages.success(request, f"Classe « {c.name} » modifiée.")
            return redirect('academic_structure:classes')
        if action == 'delete':
            c = get_object_or_404(Class, pk=request.POST.get('pk'))
            name = c.name
            c.delete()
            messages.success(request, f"Classe « {name} » supprimée.")
            return redirect('academic_structure:classes')
        name       = request.POST.get('name', '').strip()
        domaine    = request.POST.get('domaine', '').strip()
        mention    = request.POST.get('mention', '').strip()
        prog_id    = request.POST.get('program')
        yr_id      = request.POST.get('academic_year')
        lvl_id     = request.POST.get('level')
        capacity   = request.POST.get('max_students') or 40
        if not name:
            messages.error(request, "Le nom de la classe est obligatoire.")
            return redirect('academic_structure:classes')
        frais_error = _frais_obligatoires_error(request)
        if frais_error:
            messages.error(request, frais_error)
            return redirect('academic_structure:classes')
        try:
            program = Program.objects.get(pk=prog_id)
        except (Program.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Filière invalide.")
            return redirect('academic_structure:classes')
        try:
            academic_year = AcademicYear.objects.get(pk=yr_id)
        except (AcademicYear.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Année académique invalide.")
            return redirect('academic_structure:classes')
        level = None
        if lvl_id:
            try:
                level = Level.objects.get(pk=lvl_id)
            except Level.DoesNotExist:
                pass
        code = f"{program.code}-{name[:10].upper().replace(' ', '')}"
        if Class.objects.filter(code=code).exists():
            code = f"{code}-{Class.objects.count()}"
        new_class = Class.objects.create(
            code=code, name=name, program=program,
            academic_year=academic_year, capacity=int(capacity), level=level,
            domaine=domaine, mention=mention,
        )
        _save_frais_classe(new_class, request)
        messages.success(request, f"Classe « {name} » créée.")
        return redirect('academic_structure:classes')


def _lmd_base_offset(level_name):
    """Décalage LMD (0, 2, 4...) pour un niveau, dérivé du chiffre terminal de
    son nom (« Licence 3 » -> 4, « Master 2 » -> 2) — la numérotation
    redémarre à chaque cycle (Licence puis Master), d'où le calcul séparé
    par « famille » de niveau plutôt qu'un simple Level.order cumulatif."""
    import re
    m = re.search(r'(\d+)\s*$', level_name or '')
    if not m:
        return 0
    return (int(m.group(1)) - 1) * 2


class SemesterListView(_AdminResponsableMixin, ListView):
    model = Semester
    template_name = 'academic_structure/semesters.html'
    context_object_name = 'semesters'

    def get_queryset(self):
        # Une même base tenant peut héberger plusieurs instituts (Faculty) —
        # les semestres doivent donc rester filtrés à l'institut actif de
        # l'utilisateur, comme pour les autres listes de structure.
        qs = Semester.objects.select_related('academic_year', 'level').order_by(
            '-academic_year__start_date', 'number'
        )
        faculty = getattr(self.request, 'active_faculty', None)
        if faculty:
            qs = qs.filter(academic_year__faculty=faculty)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        faculty = getattr(self.request, 'active_faculty', None)
        academic_years = AcademicYear.objects.order_by('-start_date')
        if faculty:
            academic_years = academic_years.filter(faculty=faculty)
        ctx['academic_years'] = academic_years
        ctx['levels'] = Level.objects.order_by('order')
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', 'create')
        if action == 'edit':
            s = get_object_or_404(Semester, pk=request.POST.get('pk'))
            s.label      = request.POST.get('name', s.label).strip()
            s.start_date = request.POST.get('start_date') or s.start_date
            s.end_date   = request.POST.get('end_date') or s.end_date
            s.is_active  = bool(request.POST.get('is_current'))
            level_id = request.POST.get('level')
            if level_id:
                s.level = Level.objects.filter(pk=level_id).first()
            s.save()
            messages.success(request, f"Semestre « {s.label} » modifié.")
            return redirect('academic_structure:semesters')
        if action == 'delete':
            s = get_object_or_404(Semester, pk=request.POST.get('pk'))
            label = s.label
            s.delete()
            messages.success(request, f"Semestre « {label} » supprimé.")
            return redirect('academic_structure:semesters')
        label      = request.POST.get('name', '').strip()
        yr_id      = request.POST.get('academic_year')
        level_id   = request.POST.get('level')
        number     = request.POST.get('number') or None
        start_date = request.POST.get('start_date') or None
        end_date   = request.POST.get('end_date') or None
        is_active  = bool(request.POST.get('is_current'))
        if not label:
            messages.error(request, "Le nom du semestre est obligatoire.")
            return redirect('academic_structure:semesters')
        try:
            academic_year = AcademicYear.objects.get(pk=yr_id)
        except (AcademicYear.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Année académique invalide.")
            return redirect('academic_structure:semesters')
        level = Level.objects.filter(pk=level_id).first() if level_id else None
        if not number:
            # Numérotation LMD automatique : décalage du niveau (0 pour L1/M1,
            # 2 pour L2/M2, 4 pour L3...) + position (1er ou 2e semestre déjà
            # créé pour ce niveau sur cette année).
            existing = Semester.objects.filter(academic_year=academic_year, level=level).count()
            number = _lmd_base_offset(level.name if level else '') + existing + 1
        if Semester.objects.filter(academic_year=academic_year, number=number, level=level).exists():
            messages.error(request, f"Le semestre {number} existe déjà pour ce niveau sur cette année.")
            return redirect('academic_structure:semesters')
        Semester.objects.create(
            academic_year=academic_year, level=level, number=number, label=label,
            start_date=start_date, end_date=end_date, is_active=is_active
        )
        messages.success(request, f"Semestre « {label} » créé.")
        return redirect('academic_structure:semesters')


# ── Liste & gestion des instituts (Super Admin + INST_ADMIN) ─────────────────
@login_required
def institut_list(request):
    """Liste des InstitutConfig. Super Admin : tous. Autres rôles admin : leur seul institut."""
    user = request.user
    if not (user.is_admin() or user.is_inst_admin()):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    is_super = user.is_super_admin()

    if is_super:
        configs = InstitutConfig.objects.select_related('faculty', 'updated_by').order_by('nom')
    else:
        # Rôle admin non-super : ne voit que son propre institut. La faculté est
        # dérivée du profil (department → direction → institut_config, voir
        # DepartmentMiddleware) pour couvrir tous les rôles admin, pas seulement
        # INST_ADMIN dont le champ institut_config est directement renseigné.
        faculty = getattr(request, 'active_faculty', None)
        ic = getattr(request.user, 'institut_config', None) or (
            InstitutConfig.objects.filter(faculty=faculty).first() if faculty else None
        )
        configs = InstitutConfig.objects.filter(pk=ic.pk) if ic else InstitutConfig.objects.none()

    if request.method == 'POST':
        action = request.POST.get('action')
        pk     = request.POST.get('pk')
        config = get_object_or_404(InstitutConfig, pk=pk)

        # INST_ADMIN : seules actions autorisées → gérer ses propres abonnements (via abonnement_list)
        # toggle et delete sont réservés au super admin
        if not is_super:
            messages.error(request, "Action non autorisée.")
            return redirect('academic_structure:institut_list')

        if action == 'toggle':
            from django.utils import timezone

            reactivating = not config.actif  # transition suspendu -> actif

            if reactivating:
                # Réactivation d'un institut : exige la confirmation du code
                # d'activation de la plateforme (même mécanisme et même
                # protection anti brute-force que PlatformActivation — voir
                # accounts/platform_activation_rotate). Empêche qu'une session
                # Super Admin compromise seule suffise à rouvrir l'accès d'un
                # client sans connaître ce code séparé.
                from academic_core.apps.accounts.models import PlatformActivation
                activation = PlatformActivation.get_singleton()
                if activation.is_locked():
                    messages.error(request, "Trop de tentatives échouées avec le code d'activation. Réessayez plus tard.")
                    return redirect('academic_structure:institut_list')
                activation_code = request.POST.get('activation_code', '')
                if not activation.check_code(activation_code):
                    activation.register_failed_attempt()
                    messages.error(request, "Code d'activation incorrect — l'institut n'a pas été réactivé.")
                    return redirect('academic_structure:institut_list')
                activation.register_success()

            config.actif = not config.actif
            if not config.actif:
                config.date_suspension  = timezone.now()
                config.motif_suspension = request.POST.get('motif', '').strip()
            else:
                config.date_suspension  = None
                config.motif_suspension = ''
            config.updated_by = request.user
            config.save()
            etat = "réactivé" if config.actif else "suspendu"
            if not config.actif:
                nb = _forcer_deconnexion_institut(config, requester=request.user)
                suffix = f" — {nb} session(s) utilisateur(s) invalidée(s)." if nb else "."
            else:
                suffix = "."
            messages.success(request, f"Institut « {config.nom or config.sigle} » {etat}{suffix}")

        elif action == 'delete':
            nom = config.nom or config.sigle or f"Institut #{pk}"
            db_alias = config.db_alias
            admins_count = User.objects.using('default').filter(institut_config=config).count()
            if admins_count > 0:
                messages.error(request, f"Impossible de supprimer : {admins_count} utilisateur(s) rattaché(s) à cet institut.")
                return redirect('academic_structure:institut_list')

            config.delete()

            # Archive le fichier de base tenant (au lieu de le supprimer) et
            # retire son alias de settings.DATABASES — évite qu'une requête
            # ultérieure ne route encore vers ce fichier maintenant orphelin.
            from academic_core.apps.academic_structure.utils import archive_institut_db
            try:
                archived = archive_institut_db(db_alias)
            except OSError:
                archived = None
                messages.warning(request, "Institut supprimé, mais l'archivage automatique de sa base a échoué — à faire manuellement.")
            else:
                if archived:
                    messages.success(request, f"Institut « {nom} » supprimé et sa base archivée.")
                else:
                    messages.success(request, f"Institut « {nom} » supprimé.")

        elif action == 'assign_admin':
            user_pk = request.POST.get('user_pk', '').strip()
            # Les comptes INST_ADMIN vivent toujours dans 'default' (voir le
            # commentaire au-dessus de candidats_admin) — pinner ces requêtes
            # là aussi, sinon get_object_or_404 peut renvoyer 404 pour un
            # candidat jamais synchronisé vers le tenant actuellement actif.
            if user_pk:
                from academic_core.apps.accounts.models import Role
                new_admin = get_object_or_404(User.objects.using('default'), pk=user_pk)
                # S'assurer que le rôle INST_ADMIN est assigné
                inst_admin_role = Role.objects.filter(name=Role.INST_ADMIN).first()
                if inst_admin_role:
                    new_admin.role = inst_admin_role
                new_admin.institut_config = config
                new_admin.save(update_fields=['role', 'institut_config'])
                messages.success(request, f"« {new_admin.get_full_name() or new_admin.username} » est maintenant administrateur de « {config.nom or config.sigle} ».")
            else:
                # Désaffecter tous les admins de cet institut
                User.objects.using('default').filter(institut_config=config).update(institut_config=None)
                messages.success(request, "Administrateur(s) désaffecté(s).")

        return redirect('academic_structure:institut_list')

    from datetime import date as dt_date
    today = dt_date.today()

    # Candidats à l'affectation : uniquement les utilisateurs avec le rôle INST_ADMIN.
    # Pas de select_related('institut_config') : InstitutConfig est un modèle
    # maître, User est routé par tenant — le LEFT JOIN sur la table locale
    # `institut_configs` (toujours vide côté tenant) mettrait systématiquement
    # `user.institut_config` à None même si `institut_config_id` est renseigné.
    # `.using('default')` est indispensable ici (et pour `admins` ci-dessous) :
    # les comptes INST_ADMIN/SI_ADMIN vivent TOUJOURS dans 'default' (dual-write,
    # voir User.save()) — sans ce pin, la requête suit le thread-local
    # get_current_db(), qui peut pointer vers la base d'un institut tenant si le
    # Super Admin y a « Accédé » plus tôt dans sa session ; elle y renvoie alors
    # silencieusement 0 ou de mauvais résultats (chaque tenant n'a en local que
    # la copie synchronisée de SON PROPRE admin, jamais celle des autres),
    # donnant l'impression que les administrateurs assignés ont disparu.
    candidats_admin = (User.objects.using('default')
                       .filter(is_active=True, role__name='INST_ADMIN')
                       .select_related('role')
                       .order_by('last_name', 'first_name')) if is_super else User.objects.none()

    # Enrichir chaque config avec son abonnement actif et ses admins
    configs_data = []
    for c in configs:
        abo_actif = (AbonnementInstitut.objects
                     .filter(config=c, statut='ACTIF', date_fin__gte=today)
                     .order_by('-date_fin').first())
        abo_prochain = (AbonnementInstitut.objects
                        .filter(config=c)
                        .order_by('-date_fin').first())
        admins = list(User.objects.using('default').filter(institut_config=c).select_related('role'))
        configs_data.append({
            'config':      c,
            'abo_actif':   abo_actif,
            'abo_dernier': abo_prochain,
            'admins':      admins,
        })

    return render(request, 'academic_structure/institut_list.html', {
        'configs_data':    configs_data,
        'today':           today,
        'is_super':        is_super,
        'candidats_admin': candidats_admin,
    })


# ── Créer un nouvel institut ──────────────────────────────────────────────────
@login_required
def institut_create_view(request):
    """Super Admin : créer un nouvel institut (Faculty + InstitutConfig)."""
    if request.user.role_name != 'ADMIN':
        messages.error(request, "Accès réservé à l'administrateur.")
        return redirect('academic_structure:institut_list')

    if request.method == 'POST':
        nom   = request.POST.get('nom', '').strip()
        sigle = request.POST.get('sigle', '').strip()
        code  = request.POST.get('code', '').strip().upper()

        errors = {}
        if not nom:
            errors['nom'] = 'Le nom est obligatoire.'
        if not code:
            errors['code'] = 'Le code est obligatoire.'
        elif Faculty.objects.filter(code=code).exists():
            errors['code'] = f'Le code « {code} » est déjà utilisé.'

        if errors:
            from types import SimpleNamespace
            p = request.POST
            fake_config = SimpleNamespace(
                nom=p.get('nom', ''), sigle=p.get('sigle', ''),
                slogan=p.get('slogan', ''), annee_creation=p.get('annee_creation', ''),
                statut_juridique=p.get('statut_juridique', ''),
                numero_autorisation=p.get('numero_autorisation', ''),
                logo=None,
                couleur_primaire=p.get('couleur_primaire', '#00173B'),
                couleur_secondaire=p.get('couleur_secondaire', '#D4AF37'),
                pays=p.get('pays', 'Sénégal'), ville=p.get('ville', ''),
                adresse=p.get('adresse', ''), telephone=p.get('telephone', ''),
                email=p.get('email', ''), site_web=p.get('site_web', ''),
                dg_titre=p.get('dg_titre', 'Directeur Général'), dg_nom=p.get('dg_nom', ''),
                de_titre=p.get('de_titre', 'Directeur des Études'), de_nom=p.get('de_nom', ''),
                informations_paiement=p.get('informations_paiement', ''),
                faculty=SimpleNamespace(code=p.get('code', '')),
            )
            return render(request, 'academic_structure/institut_create.html', {
                'config': fake_config, 'errors': errors, 'editing': False,
            })

        # Créer la Faculty (entité organisationnelle)
        faculty = Faculty.objects.create(
            code=code,
            name=nom,
            dean=request.POST.get('dg_nom', '').strip(),
        )

        # Créer l'InstitutConfig lié
        config = InstitutConfig(
            faculty=faculty,
            nom=nom,
            sigle=sigle,
            pays=request.POST.get('pays', 'Sénégal').strip() or 'Sénégal',
            ville=request.POST.get('ville', '').strip(),
            adresse=request.POST.get('adresse', '').strip(),
            telephone=request.POST.get('telephone', '').strip(),
            email=request.POST.get('email', '').strip(),
            site_web=request.POST.get('site_web', '').strip(),
            slogan=request.POST.get('slogan', '').strip(),
            statut_juridique=request.POST.get('statut_juridique', '').strip(),
            numero_autorisation=request.POST.get('numero_autorisation', '').strip(),
            dg_titre=request.POST.get('dg_titre', 'Directeur Général').strip() or 'Directeur Général',
            dg_nom=request.POST.get('dg_nom', '').strip(),
            de_titre=request.POST.get('de_titre', 'Directeur des Études').strip() or 'Directeur des Études',
            de_nom=request.POST.get('de_nom', '').strip(),
            couleur_primaire=request.POST.get('couleur_primaire', '#00173B').strip() or '#00173B',
            couleur_secondaire=request.POST.get('couleur_secondaire', '#D4AF37').strip() or '#D4AF37',
            informations_paiement=request.POST.get('informations_paiement', '').strip(),
            # Suspendu par défaut dès la création : aucun utilisateur de ce nouvel
            # institut ne peut se connecter tant que le Super Admin ne l'a pas
            # explicitement activé en confirmant le code d'activation de la
            # plateforme (voir institut_list, action 'toggle').
            actif=False,
            date_suspension=tz_utils.now(),
            motif_suspension="Nouvel institut — activation requise par le Super Administrateur.",
            updated_by=request.user,
        )
        annee_raw = request.POST.get('annee_creation', '').strip()
        config.annee_creation = int(annee_raw) if annee_raw.isdigit() else None
        if 'logo' in request.FILES:
            config.logo = request.FILES['logo']
        config.save()
        seed_default_contrat_articles(config)

        # auto_create_institute_db (signals.py) a tourné de façon synchrone dans
        # ce .save() et pose _provisioning_warning sur ce même objet `config` en
        # cas d'échec partiel (base créée mais migrations/écriture .env en
        # échec) — sans ce contrôle, l'admin ne voit qu'un succès inconditionnel
        # alors que l'institut peut être non fonctionnel.
        provisioning_warning = getattr(config, '_provisioning_warning', None)
        if provisioning_warning:
            messages.warning(
                request,
                f"Institut « {nom} » créé, mais la préparation de sa base de "
                f"données a rencontré un problème : {provisioning_warning}",
            )
        else:
            messages.success(
                request,
                f"Institut « {nom} » créé avec succès — suspendu par défaut. "
                "Activez-le depuis la liste des instituts (code d'activation requis) "
                "pour permettre à ses utilisateurs de se connecter.",
            )
        return redirect('academic_structure:institut_edit', config_pk=config.pk)

    from types import SimpleNamespace
    empty_config = SimpleNamespace(
        nom='', sigle='', slogan='', annee_creation='',
        statut_juridique='', numero_autorisation='', logo=None,
        couleur_primaire='#00173B', couleur_secondaire='#D4AF37',
        pays='Sénégal', ville='', adresse='', telephone='', email='', site_web='',
        dg_titre='Directeur Général', dg_nom='',
        de_titre='Directeur des Études', de_nom='',
        faculty=SimpleNamespace(code=''),
    )
    return render(request, 'academic_structure/institut_create.html', {
        'config': empty_config, 'editing': False, 'errors': {},
    })


# ── Modifier un institut existant ─────────────────────────────────────────────
@login_required
def institut_edit_view(request, config_pk):
    """Super Admin : modifier un institut existant."""
    if request.user.role_name != 'ADMIN':
        messages.error(request, "Accès réservé à l'administrateur.")
        return redirect('academic_structure:institut_list')

    config = get_object_or_404(InstitutConfig, pk=config_pk)

    if request.method == 'POST':
        config.nom                 = request.POST.get('nom', '').strip()
        config.sigle               = request.POST.get('sigle', '').strip()
        config.pays                = request.POST.get('pays', 'Sénégal').strip() or 'Sénégal'
        config.ville               = request.POST.get('ville', '').strip()
        config.adresse             = request.POST.get('adresse', '').strip()
        config.telephone           = request.POST.get('telephone', '').strip()
        config.email               = request.POST.get('email', '').strip()
        config.site_web            = request.POST.get('site_web', '').strip()
        config.slogan              = request.POST.get('slogan', '').strip()
        config.statut_juridique    = request.POST.get('statut_juridique', '').strip()
        config.numero_autorisation = request.POST.get('numero_autorisation', '').strip()
        config.dg_titre            = request.POST.get('dg_titre', 'Directeur Général').strip() or 'Directeur Général'
        config.dg_nom              = request.POST.get('dg_nom', '').strip()
        config.de_titre            = request.POST.get('de_titre', 'Directeur des Études').strip() or 'Directeur des Études'
        config.de_nom              = request.POST.get('de_nom', '').strip()
        config.couleur_primaire    = request.POST.get('couleur_primaire', '#00173B').strip() or '#00173B'
        config.couleur_secondaire  = request.POST.get('couleur_secondaire', '#D4AF37').strip() or '#D4AF37'
        config.informations_paiement = request.POST.get('informations_paiement', '').strip()
        annee_raw = request.POST.get('annee_creation', '').strip()
        config.annee_creation = int(annee_raw) if annee_raw.isdigit() else None
        if 'logo' in request.FILES:
            config.logo = request.FILES['logo']
        elif request.POST.get('remove_logo') == '1':
            config.logo = None
        # Mettre à jour le code/nom de la Faculty liée
        if config.faculty:
            code_new = request.POST.get('code', '').strip().upper()
            if code_new and code_new != config.faculty.code:
                if not Faculty.objects.filter(code=code_new).exclude(pk=config.faculty.pk).exists():
                    config.faculty.code = code_new
            config.faculty.name = config.nom
            config.faculty.dean = config.dg_nom
            config.faculty.save(update_fields=['code', 'name', 'dean'])
        config.updated_by = request.user
        config.save()
        messages.success(request, f"Institut « {config.nom} » mis à jour.")
        return redirect('academic_structure:institut_edit', config_pk=config.pk)

    return render(request, 'academic_structure/institut_create.html', {
        'config': config,
        'post': {},
        'editing': True,
    })


# ── Abonnements Institut (Super Admin + INST_ADMIN) ───────────────────────────
@login_required
def abonnement_list(request, config_pk):
    """Liste + gestion des abonnements d'un institut."""
    user = request.user
    if not (user.is_admin() or user.is_inst_admin()):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    is_super = user.is_super_admin()

    # Rôle admin non-super : ne peut accéder qu'à son propre institut (voir
    # institut_list ci-dessus pour la résolution de faculté par profil).
    if not is_super:
        faculty = getattr(request, 'active_faculty', None)
        own_config = getattr(request.user, 'institut_config', None) or (
            InstitutConfig.objects.filter(faculty=faculty).first() if faculty else None
        )
        if not own_config or own_config.pk != config_pk:
            messages.error(request, "Vous ne pouvez gérer que votre propre institut.")
            return redirect('academic_structure:institut_list')

    config       = get_object_or_404(InstitutConfig, pk=config_pk)
    abonnements  = AbonnementInstitut.objects.filter(config=config).order_by('-date_debut')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'add':
            from datetime import date as dt_date
            from decimal import Decimal, InvalidOperation
            from academic_core.apps.accounts.models import PlatformActivation
            date_debut_raw = request.POST.get('date_debut', '').strip()
            duree_raw      = request.POST.get('duree_annees', '1').strip()
            montant_raw    = request.POST.get('montant', '').strip()
            statut         = request.POST.get('statut', AbonnementInstitut.STATUT_EN_ATTENTE)
            ref            = request.POST.get('reference_paiement', '').strip()
            notes          = request.POST.get('notes', '').strip()
            code_saisi     = request.POST.get('code_activation', '').strip()
            errors = []
            if not date_debut_raw:
                errors.append("La date de début est obligatoire.")
            if not montant_raw:
                errors.append("Le montant est obligatoire.")
            # Le code d'activation actuellement en vigueur pour la plateforme
            # doit obligatoirement être ressaisi pour valider un abonnement —
            # on réutilise tel quel le verrou existant (PlatformActivation),
            # sans le modifier : même hash, même compteur anti brute-force
            # que la page /accounts/plateforme/rotation/.
            activation = PlatformActivation.get_singleton()
            if not code_saisi:
                errors.append("Le code d'activation de la plateforme est obligatoire.")
            elif activation.is_locked():
                errors.append(
                    "Vérification du code d'activation temporairement bloquée "
                    "suite à plusieurs échecs. Réessayez plus tard."
                )
            elif not activation.check_code(code_saisi):
                activation.register_failed_attempt()
                errors.append("Code d'activation incorrect.")
            else:
                activation.register_success()
            if errors:
                for e in errors:
                    messages.error(request, e)
            else:
                try:
                    date_debut = dt_date.fromisoformat(date_debut_raw)
                    duree      = max(1, int(duree_raw) if duree_raw.isdigit() else 1)
                    montant    = Decimal(montant_raw.replace(' ', '').replace(',', '.'))
                    abo = AbonnementInstitut.objects.create(
                        config=config,
                        date_debut=date_debut,
                        duree_annees=duree,
                        montant=montant,
                        statut=statut,
                        reference_paiement=ref,
                        notes=notes,
                        created_by=request.user,
                    )
                    # Si actif → synchroniser InstitutConfig.actif
                    if statut == AbonnementInstitut.STATUT_ACTIF:
                        config.actif = True
                        config.date_suspension  = None
                        config.motif_suspension = ''
                        config.updated_by = request.user
                        config.save()
                    messages.success(request, f"Abonnement enregistré — expire le {abo.date_fin.strftime('%d/%m/%Y')}.")
                except Exception as exc:
                    messages.error(request, f"Erreur : {exc}")

        elif action == 'toggle_statut':
            pk_abo  = request.POST.get('abo_pk')
            abo     = get_object_or_404(AbonnementInstitut, pk=pk_abo, config=config)
            nouveau = request.POST.get('nouveau_statut', '')
            # INST_ADMIN : uniquement résiliation (→ SUSPENDU)
            if not is_super and nouveau != AbonnementInstitut.STATUT_SUSPENDU:
                messages.error(request, "Vous pouvez uniquement résilier votre contrat.")
                return redirect('academic_structure:abonnement_list', config_pk=config.pk)
            if nouveau in dict(AbonnementInstitut.STATUT_CHOICES):
                abo.statut = nouveau
                abo.save()
                from datetime import date as dt_date
                has_valid = AbonnementInstitut.objects.filter(
                    config=config, statut='ACTIF', date_fin__gte=dt_date.today()
                ).exists()
                config.actif = has_valid
                if not has_valid:
                    from django.utils import timezone
                    config.date_suspension  = timezone.now()
                    config.motif_suspension = "Contrat résilié par l'administrateur de l'institut." if not is_super else "Aucun abonnement actif valide."
                else:
                    config.date_suspension  = None
                    config.motif_suspension = ''
                config.updated_by = request.user
                config.save()
                if not has_valid:
                    nb = _forcer_deconnexion_institut(config, requester=request.user)
                    suffix = f" — {nb} session(s) invalidée(s)." if nb else "."
                    messages.success(request, f"Statut mis à jour : {abo.get_statut_display()}{suffix}")
                else:
                    messages.success(request, f"Statut mis à jour : {abo.get_statut_display()}.")

        elif action == 'delete':
            if not is_super:
                messages.error(request, "Suppression réservée au Super Administrateur.")
                return redirect('academic_structure:abonnement_list', config_pk=config.pk)
            pk_abo = request.POST.get('abo_pk')
            abo    = get_object_or_404(AbonnementInstitut, pk=pk_abo, config=config)
            abo.delete()
            messages.success(request, "Abonnement supprimé.")

        return redirect('academic_structure:abonnement_list', config_pk=config.pk)

    from datetime import date as dt_date
    abo_actif = abonnements.filter(statut='ACTIF', date_fin__gte=dt_date.today()).first()

    return render(request, 'academic_structure/abonnement_list.html', {
        'config':          config,
        'abonnements':     abonnements,
        'abo_actif':       abo_actif,
        'STATUT_CHOICES':  AbonnementInstitut.STATUT_CHOICES,
        'today':           dt_date.today(),
        'is_super':        is_super,
    })


# ── Fonctionnalités activées/désactivées par institut ────────────────────────
@login_required
def institut_feature_flags(request, config_pk):
    """
    Super Admin only : active/désactive des onglets entiers ou des
    fonctionnalités précises de la sidebar pour un institut donné.
    Désactiver un onglet désactive automatiquement toutes ses fonctionnalités
    (cascade appliquée par InstitutDisabledTab dans le registre, voir
    feature_gate.is_feature_blocked et le filtrage de base.html).
    """
    from .feature_registry import TAB_LABELS, TAB_FEATURES
    from .models import InstitutDisabledTab, InstitutDisabledFeature

    if not request.user.is_super_admin():
        messages.error(request, "Accès réservé au Super Administrateur.")
        return redirect('dashboard:index')

    config = get_object_or_404(InstitutConfig, pk=config_pk)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'toggle_tab':
            tab_key = request.POST.get('tab_key', '')
            if tab_key in TAB_LABELS:
                existing = InstitutDisabledTab.objects.filter(
                    institut_config=config, tab_key=tab_key
                ).first()
                if existing:
                    existing.delete()
                    messages.success(request, f"Onglet « {TAB_LABELS[tab_key]} » réactivé.")
                else:
                    InstitutDisabledTab.objects.create(
                        institut_config=config, tab_key=tab_key, disabled_by=request.user,
                    )
                    messages.success(request, f"Onglet « {TAB_LABELS[tab_key]} » désactivé.")

        elif action == 'toggle_feature':
            tab_key     = request.POST.get('tab_key', '')
            feature_key = request.POST.get('feature_key', '')
            valid_keys  = {name for feats in TAB_FEATURES.values() for name, _label in feats}
            if feature_key in valid_keys:
                existing = InstitutDisabledFeature.objects.filter(
                    institut_config=config, feature_key=feature_key
                ).first()
                if existing:
                    existing.delete()
                    messages.success(request, "Fonctionnalité réactivée.")
                else:
                    InstitutDisabledFeature.objects.create(
                        institut_config=config, tab_key=tab_key,
                        feature_key=feature_key, disabled_by=request.user,
                    )
                    messages.success(request, "Fonctionnalité désactivée.")

        return redirect('academic_structure:institut_feature_flags', config_pk=config.pk)

    disabled_tabs = set(
        InstitutDisabledTab.objects.filter(institut_config=config).values_list('tab_key', flat=True)
    )
    disabled_features = set(
        InstitutDisabledFeature.objects.filter(institut_config=config).values_list('feature_key', flat=True)
    )

    tabs = []
    for tab_key, label in TAB_LABELS.items():
        tabs.append({
            'key':       tab_key,
            'label':     label,
            'disabled':  tab_key in disabled_tabs,
            'features': [
                {
                    'key':      feature_key,
                    'label':    feature_label,
                    'disabled': feature_key in disabled_features,
                }
                for feature_key, feature_label in TAB_FEATURES.get(tab_key, [])
            ],
        })

    return render(request, 'academic_structure/institut_feature_flags.html', {
        'config': config,
        'tabs':   tabs,
    })


# ── Configuration Institut ────────────────────────────────────────────────────
@login_required
def institut_config_view(request):
    if request.user.role_name != 'ADMIN':
        messages.error(request, "Accès réservé à l'administrateur.")
        return redirect('dashboard:index')

    config      = InstitutConfig.get()
    filiations  = config.filiations.all()
    tab         = request.GET.get('tab', 'identite')
    errors      = {}

    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ── Sauvegarder identité / coordonnées / légal / signataires / apparence ──
        if action == 'save_config':
            config.nom                  = request.POST.get('nom', '').strip()
            config.sigle                = request.POST.get('sigle', '').strip()
            config.slogan               = request.POST.get('slogan', '').strip()
            config.pays                 = request.POST.get('pays', '').strip()
            config.ville                = request.POST.get('ville', '').strip()
            config.adresse              = request.POST.get('adresse', '').strip()
            config.telephone            = request.POST.get('telephone', '').strip()
            config.email                = request.POST.get('email', '').strip()
            config.site_web             = request.POST.get('site_web', '').strip()
            config.annee_creation_raw   = request.POST.get('annee_creation', '').strip()
            config.numero_autorisation  = request.POST.get('numero_autorisation', '').strip()
            config.statut_juridique     = request.POST.get('statut_juridique', '').strip()
            config.dg_titre             = request.POST.get('dg_titre', '').strip()
            config.dg_nom               = request.POST.get('dg_nom', '').strip()
            config.de_titre             = request.POST.get('de_titre', '').strip()
            config.de_nom               = request.POST.get('de_nom', '').strip()
            config.couleur_primaire     = request.POST.get('couleur_primaire', '#00173B').strip() or '#00173B'
            config.couleur_secondaire   = request.POST.get('couleur_secondaire', '#D4AF37').strip() or '#D4AF37'
            annee_raw = request.POST.get('annee_creation', '').strip()
            config.annee_creation = int(annee_raw) if annee_raw.isdigit() else None
            if 'logo' in request.FILES:
                config.logo = request.FILES['logo']
            elif request.POST.get('remove_logo') == '1':
                config.logo = None
            config.updated_by = request.user
            config.save()
            messages.success(request, 'Configuration enregistrée avec succès.')
            return redirect(request.path + '?tab=' + request.POST.get('current_tab', 'identite'))

        # ── Ajouter une filiation ──
        elif action == 'add_filiation':
            nom  = request.POST.get('fil_nom', '').strip()
            if not nom:
                errors['fil_nom'] = 'Le nom est obligatoire.'
            else:
                fil = InstitutFiliation(
                    config=config,
                    nom=nom,
                    type_filiation=request.POST.get('fil_type', InstitutFiliation.TYPE_TUTELLE),
                    site_web=request.POST.get('fil_site_web', '').strip(),
                    ordre=int(request.POST.get('fil_ordre', 0) or 0),
                    actif=request.POST.get('fil_actif') == '1',
                )
                if 'fil_logo' in request.FILES:
                    fil.logo = request.FILES['fil_logo']
                fil.save()
                messages.success(request, f'Filiation "{nom}" ajoutee.')
            return redirect(request.path + '?tab=filiations')

        # ── Modifier une filiation ──
        elif action == 'edit_filiation':
            pk  = request.POST.get('fil_pk')
            fil = get_object_or_404(InstitutFiliation, pk=pk, config=config)
            fil.nom             = request.POST.get('fil_nom', '').strip() or fil.nom
            fil.type_filiation  = request.POST.get('fil_type', fil.type_filiation)
            fil.site_web        = request.POST.get('fil_site_web', '').strip()
            fil.ordre           = int(request.POST.get('fil_ordre', 0) or 0)
            fil.actif           = request.POST.get('fil_actif') == '1'
            if 'fil_logo' in request.FILES:
                fil.logo = request.FILES['fil_logo']
            elif request.POST.get('remove_fil_logo') == '1':
                fil.logo = None
            fil.save()
            messages.success(request, 'Filiation mise à jour.')
            return redirect(request.path + '?tab=filiations')

        # ── Supprimer une filiation ──
        elif action == 'delete_filiation':
            pk  = request.POST.get('fil_pk')
            fil = get_object_or_404(InstitutFiliation, pk=pk, config=config)
            fil.delete()
            messages.success(request, 'Filiation supprimée.')
            return redirect(request.path + '?tab=filiations')

    TABS = [
        ('identite',    'Identité',           'buildings'),
        ('legal',       'Légal',              'file-earmark-text'),
        ('signataires', 'Signataires',        'pen'),
        ('filiations',  'Filiations',         'diagram-2'),
        ('apparence',   'Apparence',          'palette2'),
    ]
    return render(request, 'academic_structure/institut_config.html', {
        'config':       config,
        'filiations':   filiations,
        'tab':          tab,
        'tabs':         TABS,
        'TYPE_CHOICES': InstitutFiliation.TYPE_CHOICES,
        'errors':       errors,
    })


@login_required
def institut_email_config_view(request):
    """
    Configuration des emails de notification de SON institut — réservée à
    l'Administrateur d'institut (INST_ADMIN/SI_ADMIN), à ne pas confondre
    avec le mécanisme d'activation de la plateforme (code d'activation,
    PLATFORM_RESET_EMAIL_1/2, EMAIL_* globaux du .env — voir
    academic_core/apps/accounts/platform_activation.py), qui reste
    entièrement inchangé et n'utilise jamais cette configuration.

    Détermine l'institut via request.user.institut_config (lien direct des
    comptes INST_ADMIN/SI_ADMIN — voir accounts/models.py), pas via la base
    tenant active, pour rester correct même visité par un Super Admin en
    mode "accès" à un institut qui n'a pas ce lien.
    """
    if not request.user.is_inst_admin():
        messages.error(request, "Accès réservé à l'administrateur d'institut.")
        return redirect('dashboard:index')

    institut_config = getattr(request.user, 'institut_config', None)
    if not institut_config:
        messages.error(request, "Votre compte n'est rattaché à aucun institut.")
        return redirect('dashboard:index')

    email_config, _ = InstitutEmailConfig.objects.using('default').get_or_create(
        institut_config=institut_config,
    )

    if request.method == 'POST':
        email_config.is_active = request.POST.get('is_active') == '1'
        email_config.email_host = request.POST.get('email_host', '').strip()
        port_raw = request.POST.get('email_port', '').strip()
        email_config.email_port = int(port_raw) if port_raw.isdigit() else 587
        email_config.email_use_tls = request.POST.get('email_use_tls') == '1'
        email_config.email_host_user = request.POST.get('email_host_user', '').strip()
        new_password = request.POST.get('email_host_password', '').strip()
        if new_password:
            email_config.email_host_password = new_password
        email_config.default_from_email = request.POST.get('default_from_email', '').strip()
        email_config.updated_by = request.user
        email_config.save()
        messages.success(request, "Configuration email de l'institut enregistrée.")
        return redirect('academic_structure:institut_email_config')

    return render(request, 'academic_structure/institut_email_config.html', {
        'institut_config': institut_config,
        'email_config':    email_config,
    })


@login_required
def institut_payment_config_view(request):
    """
    Configuration des moyens de paiement en ligne (Wave, Orange Money,
    virement bancaire) de SON institut — réservée à l'Administrateur
    d'institut, même principe et mêmes garde-fous que
    institut_email_config_view. Sans rapport avec le mécanisme d'activation
    de la plateforme.
    """
    if not request.user.is_inst_admin():
        messages.error(request, "Accès réservé à l'administrateur d'institut.")
        return redirect('dashboard:index')

    institut_config = getattr(request.user, 'institut_config', None)
    if not institut_config:
        messages.error(request, "Votre compte n'est rattaché à aucun institut.")
        return redirect('dashboard:index')

    payment_config, _ = InstitutPaymentConfig.objects.using('default').get_or_create(
        institut_config=institut_config,
    )

    if request.method == 'POST':
        # Wave
        payment_config.wave_active = request.POST.get('wave_active') == '1'
        new_wave_key = request.POST.get('wave_api_key', '').strip()
        if new_wave_key:
            payment_config.wave_api_key = new_wave_key

        # Orange Money
        payment_config.om_active = request.POST.get('om_active') == '1'
        payment_config.om_client_id = request.POST.get('om_client_id', '').strip()
        new_om_secret = request.POST.get('om_client_secret', '').strip()
        if new_om_secret:
            payment_config.om_client_secret = new_om_secret
        new_om_merchant_key = request.POST.get('om_merchant_key', '').strip()
        if new_om_merchant_key:
            payment_config.om_merchant_key = new_om_merchant_key
        payment_config.om_mode = request.POST.get('om_mode', InstitutPaymentConfig.MODE_TEST)
        payment_config.om_region = request.POST.get('om_region', 'sn').strip() or 'sn'

        # Virement bancaire
        payment_config.virement_active = request.POST.get('virement_active') == '1'
        payment_config.banque_nom = request.POST.get('banque_nom', '').strip()
        payment_config.banque_titulaire = request.POST.get('banque_titulaire', '').strip()
        payment_config.banque_iban = request.POST.get('banque_iban', '').strip()
        payment_config.banque_rib = request.POST.get('banque_rib', '').strip()
        payment_config.banque_swift = request.POST.get('banque_swift', '').strip()
        payment_config.virement_instructions = request.POST.get('virement_instructions', '').strip()

        payment_config.updated_by = request.user
        payment_config.save()
        messages.success(request, "Configuration de paiement en ligne enregistrée.")
        return redirect('academic_structure:institut_payment_config')

    return render(request, 'academic_structure/institut_payment_config.html', {
        'institut_config': institut_config,
        'payment_config':  payment_config,
    })


def _require_diploma_supplement_access(user):
    """Direction des Études (+ admins par sécurité) — signataire du supplément
    de diplôme, voir accounting/views.py::diploma_supplement_pdf."""
    return user.is_admin_direction() or user.is_admin() or user.is_inst_admin()


@login_required
def diploma_supplement_config_list(request):
    if not _require_diploma_supplement_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import DiplomaSupplementConfig

    faculty = getattr(request, 'active_faculty', None)
    programs = Program.objects.select_related('department').order_by('department__name', 'name')
    if faculty:
        programs = programs.filter(department__faculty=faculty)

    configured_ids = set(
        DiplomaSupplementConfig.objects.filter(program__in=programs)
        .values_list('program_id', flat=True)
    )

    return render(request, 'academic_structure/diploma_supplement_config_list.html', {
        'programs': programs,
        'configured_ids': configured_ids,
    })


@login_required
def diploma_supplement_config_edit(request, program_id):
    if not _require_diploma_supplement_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import DiplomaSupplementConfig

    program = get_object_or_404(Program, pk=program_id)
    config, _created = DiplomaSupplementConfig.objects.get_or_create(program=program)

    if request.method == 'POST':
        config.domaine                   = request.POST.get('domaine', '').strip()
        config.langue_etudes             = request.POST.get('langue_etudes', '').strip()
        config.definition_qualification  = request.POST.get('definition_qualification', '').strip()
        config.duree_texte               = request.POST.get('duree_texte', '').strip()
        config.conditions_admission      = request.POST.get('conditions_admission', '').strip()
        config.poursuite_etudes          = request.POST.get('poursuite_etudes', '').strip()
        config.statut_professionnel      = request.POST.get('statut_professionnel', '').strip()
        config.forme_etudes              = request.POST.get('forme_etudes', '').strip()
        config.updated_by = request.user
        config.save()
        messages.success(request, f"Configuration du supplément de diplôme enregistrée pour « {program.name} ».")
        return redirect('academic_structure:diploma_supplement_config_list')

    return render(request, 'academic_structure/diploma_supplement_config_form.html', {
        'program': program,
        'config': config,
    })
