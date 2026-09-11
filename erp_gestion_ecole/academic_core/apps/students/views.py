import base64
import csv
import io
import json
import random
import string

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import ListView, UpdateView, DetailView, DeleteView, View
from django.urls import reverse_lazy, reverse
from django.db.models import Q
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import Student, Enrollment
from .forms import StudentUserForm, StudentForm, StudentImportForm
from academic_core.apps.accounts.models import User, Role, Direction
from academic_core.apps.academic_structure.models import Class, AcademicYear
from .services import (
    _get_institut_config, _get_sigle_institut, create_student_enrollment,
    generate_matricule as _generate_matricule,
    get_direction_etudes as _get_direction_etudes,
    webcam_b64_to_file as _webcam_b64_to_file,
)


class _AdminResponsableMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_manage_dept()


class StudentListView(_AdminResponsableMixin, ListView):
    model = Student
    template_name = 'students/list.html'
    context_object_name = 'students'
    paginate_by = 50

    def get_queryset(self):
        from django.db.models import OuterRef, Subquery
        class_id = self.request.GET.get('class_id')
        year_id  = self.request.GET.get('year_id')
        if not class_id or not year_id:
            return Student.objects.none()
        # Vérifier que la classe appartient au département/faculty actif
        dept    = getattr(self.request, 'active_department', None)
        faculty = getattr(self.request, 'active_faculty', None)
        cls_qs  = Class.objects.filter(pk=class_id)
        if dept:
            cls_qs = cls_qs.filter(program__department=dept)
        elif faculty:
            cls_qs = cls_qs.filter(program__department__faculty=faculty)
        if not cls_qs.exists():
            return Student.objects.none()
        # Sous-requête pour récupérer le pk de l'inscription validée
        enrollment_pk = Subquery(
            Enrollment.objects.filter(
                student=OuterRef('pk'),
                class_group_id=class_id,
                academic_year_id=year_id,
                status=Enrollment.STATUS_VALIDATED,
            ).values('pk')[:1]
        )
        # Pas de filtre `enrollments__is_active` ici : cette page est un
        # historique par (classe, année académique) — une inscription validée
        # y reste un fait acquis même après qu'une réinscription ultérieure
        # ait désactivé cet enrollment comme "non courant" (voir
        # ReinscriptionView.post, qui met is_active=False sur l'ancien
        # enrollment). Sans ce retrait, un étudiant réinscrit disparaissait de
        # la liste de sa classe/année précédente.
        return Student.objects.filter(
            enrollments__class_group_id=class_id,
            enrollments__academic_year_id=year_id,
            enrollments__status=Enrollment.STATUS_VALIDATED,
        ).select_related('user', 'current_class').annotate(
            enrollment_pk=enrollment_pk
        ).order_by('user__last_name', 'user__first_name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dept     = getattr(self.request, 'active_department', None)
        faculty  = getattr(self.request, 'active_faculty', None)
        is_super = self.request.user.is_super_admin()

        classes_qs = Class.objects.select_related('program__department').order_by('name')
        if dept:
            classes_qs = classes_qs.filter(program__department=dept)
        elif faculty:
            classes_qs = classes_qs.filter(program__department__faculty=faculty)
        else:
            classes_qs = classes_qs.none()

        ctx['all_classes']   = classes_qs
        ctx['dept_required'] = not is_super and not dept and not faculty
        fac_for_years = faculty or (dept.faculty if dept else None)
        all_years = AcademicYear.objects.order_by('-start_date')
        ctx['all_years'] = all_years.filter(faculty=fac_for_years) if fac_for_years else all_years

        # Année académique : pré-sélectionnée sur l'année en cours par défaut,
        # pour que la classe choisie soit bien recherchée dans l'année en
        # cours sans action supplémentaire de l'utilisateur.
        ctx['selected_class_id'] = self.request.GET.get('class_id', '')
        year_id_param = self.request.GET.get('year_id', '')
        if not year_id_param:
            current_year = ctx['all_years'].filter(is_current=True).first()
            year_id_param = str(current_year.pk) if current_year else ''
        ctx['selected_year_id'] = year_id_param
        ctx['selected_class'] = None
        ctx['selected_year'] = None
        if ctx['selected_class_id']:
            ctx['selected_class'] = Class.objects.filter(pk=ctx['selected_class_id']).first()
        if ctx['selected_year_id']:
            ctx['selected_year'] = AcademicYear.objects.filter(pk=ctx['selected_year_id']).first()
        ctx['filter_applied'] = bool(ctx['selected_class_id'] and ctx['selected_year_id'])

        # Départements disponibles pour le modal d'association
        from academic_core.apps.academic_structure.models import Department
        depts_qs = Department.objects.order_by('name')
        if faculty:
            depts_qs = depts_qs.filter(faculty=faculty)
        ctx['all_departments'] = depts_qs
        return ctx


class StudentDetailView(LoginRequiredMixin, DetailView):
    model = Student
    template_name = 'students/detail.html'
    context_object_name = 'student'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        student = self.object
        # Enrichir chaque inscription avec les semestres de SON niveau pour son
        # année académique — une même année académique porte les semestres de
        # tous les niveaux (ex : Semestre 1 d'une Licence 1 ET Semestre 3
        # d'une Licence 2), donc filtrer par niveau est indispensable pour ne
        # pas mélanger les semestres d'un autre niveau que celui de la classe.
        enrollments_with_semesters = []
        for enr in student.enrollments.select_related('class_group__level', 'academic_year').order_by('-academic_year__start_date'):
            semesters_qs = enr.academic_year.semesters.order_by('number')
            if enr.class_group_id and enr.class_group.level_id:
                semesters_qs = semesters_qs.filter(level_id=enr.class_group.level_id)
            semesters = list(semesters_qs)
            enrollments_with_semesters.append({'enrollment': enr, 'semesters': semesters})
        ctx['enrollments_with_semesters'] = enrollments_with_semesters
        return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Abandons & Suspensions d'inscription
# ─────────────────────────────────────────────────────────────────────────────

def _current_relevant_enrollment(student):
    """
    Retourne l'inscription à marquer comme abandonnée/suspendue : l'inscription
    active en cours, sinon la plus récente (par date d'inscription).
    """
    return (
        student.enrollments.filter(is_active=True).order_by('-enrollment_date').first()
        or student.enrollments.order_by('-enrollment_date').first()
    )


@login_required
def student_mark_abandoned(request, pk):
    """Marque l'étudiant comme ayant abandonné : désactive l'inscription et le compte."""
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('students:list')
    if request.method != 'POST':
        return redirect('students:list')

    student = get_object_or_404(Student, pk=pk)
    enrollment = _current_relevant_enrollment(student)
    if not enrollment:
        messages.error(request, f"Aucune inscription trouvée pour « {student.full_name} ».")
        return redirect(request.POST.get('next') or 'students:list')

    reason = request.POST.get('reason', '').strip()
    enrollment.status            = Enrollment.STATUS_ABANDONED
    enrollment.is_active          = False
    enrollment.status_changed_at  = timezone.now()
    enrollment.status_changed_by  = request.user
    enrollment.status_reason      = reason
    enrollment.save(update_fields=[
        'status', 'is_active', 'status_changed_at', 'status_changed_by', 'status_reason',
    ])

    student.user.__class__.objects.filter(pk=student.user_id).update(is_active=False)

    messages.success(request, f"« {student.full_name} » a été inscrit(e) sur la liste des abandons. Compte désactivé.")
    return redirect(request.POST.get('next') or 'students:list')


@login_required
def student_mark_suspended(request, pk):
    """Marque l'inscription de l'étudiant comme suspendue : désactive l'inscription et le compte pour l'année en cours."""
    if not request.user.is_tresorier():
        messages.error(request, "Accès réservé au Trésorier Général.")
        return redirect('students:list')
    if request.method != 'POST':
        return redirect('students:list')

    student = get_object_or_404(Student, pk=pk)
    enrollment = _current_relevant_enrollment(student)
    if not enrollment:
        messages.error(request, f"Aucune inscription trouvée pour « {student.full_name} ».")
        return redirect(request.POST.get('next') or 'students:list')

    reason = request.POST.get('reason', '').strip()
    enrollment.status            = Enrollment.STATUS_SUSPENDED
    enrollment.is_active          = False
    enrollment.status_changed_at  = timezone.now()
    enrollment.status_changed_by  = request.user
    enrollment.status_reason      = reason
    enrollment.save(update_fields=[
        'status', 'is_active', 'status_changed_at', 'status_changed_by', 'status_reason',
    ])

    student.user.__class__.objects.filter(pk=student.user_id).update(is_active=False)

    messages.success(
        request,
        f"L'inscription de « {student.full_name} » a été suspendue pour l'année en cours. Compte désactivé. "
        f"Les frais déjà payés seront automatiquement reportés en cas de réinscription."
    )
    return redirect(request.POST.get('next') or 'students:list')


@login_required
def student_set_class_rep(request, pk):
    """
    Nomme un étudiant Responsable de classe / Adjoint du responsable de classe
    (ou révoque cette désignation). L'étudiant conserve tous ses droits
    d'étudiant : il gagne uniquement l'accès au cahier de texte de sa classe.
    """
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('accounting:financial_student_list')
    if request.method != 'POST':
        return redirect('accounting:financial_student_list')

    student   = get_object_or_404(Student, pk=pk)
    role      = request.POST.get('role', '').strip()
    next_url  = request.POST.get('next') or 'accounting:financial_student_list'
    valid_roles = dict(Student.CLASS_REP_CHOICES)

    if role not in valid_roles:
        messages.error(request, "Rôle invalide.")
        return redirect(next_url)

    if role and not student.current_class_id:
        messages.error(request, f"« {student.full_name} » n'a pas de classe assignée.")
        return redirect(next_url)

    if role:
        # Un seul titulaire de ce rôle par classe : on désaffecte l'éventuel précédent.
        Student.objects.filter(
            current_class_id=student.current_class_id, class_rep_role=role,
        ).exclude(pk=student.pk).update(
            class_rep_role=Student.CLASS_REP_NONE, class_rep_since=None, class_rep_by=None,
        )
        student.class_rep_role  = role
        student.class_rep_since = timezone.now()
        student.class_rep_by    = request.user
        student.save(update_fields=['class_rep_role', 'class_rep_since', 'class_rep_by'])
        messages.success(
            request,
            f"« {student.full_name} » a été nommé(e) {valid_roles[role].lower()} de {student.current_class}."
        )
    else:
        student.class_rep_role  = Student.CLASS_REP_NONE
        student.class_rep_since = None
        student.class_rep_by    = None
        student.save(update_fields=['class_rep_role', 'class_rep_since', 'class_rep_by'])
        messages.success(request, f"« {student.full_name} » n'est plus responsable/adjoint de classe.")

    return redirect(next_url)


@login_required
def enrollment_reactivate(request, pk):
    """Annule un abandon/une suspension par erreur : réactive l'inscription et le compte étudiant."""
    if not request.user.is_tresorier():
        messages.error(request, "Accès réservé au Trésorier Général.")
        return redirect('students:suspension_list')
    if request.method != 'POST':
        return redirect('students:list')

    enrollment = get_object_or_404(Enrollment.objects.select_related('student__user'), pk=pk)
    was_abandoned = enrollment.status == Enrollment.STATUS_ABANDONED

    enrollment.status            = Enrollment.STATUS_VALIDATED
    enrollment.is_active          = True
    enrollment.status_changed_at  = None
    enrollment.status_changed_by  = None
    enrollment.status_reason      = ''
    enrollment.save(update_fields=[
        'status', 'is_active', 'status_changed_at', 'status_changed_by', 'status_reason',
    ])

    student = enrollment.student
    student.user.__class__.objects.filter(pk=student.user_id).update(is_active=True)

    label = 'Abandon' if was_abandoned else 'Suspension'
    messages.success(request, f"{label} annulé(e) : « {student.full_name} » réintégré(e) dans « {enrollment.class_group.name} ».")
    return redirect(request.POST.get('next') or 'students:abandon_list')


def _status_management_list(request, status, template_name):
    """Liste commune (abandons ou suspensions), filtrable par département/classe/année."""
    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    qs = Enrollment.objects.filter(status=status).select_related(
        'student__user', 'class_group__program__department', 'academic_year', 'status_changed_by',
    ).order_by('-status_changed_at')

    if dept:
        qs = qs.filter(class_group__program__department=dept)
    elif faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)

    fac_for_years = faculty or (dept.faculty if dept else None)
    all_years = AcademicYear.objects.order_by('-start_date')
    all_years = all_years.filter(faculty=fac_for_years) if fac_for_years else all_years

    # Année académique : par défaut l'année en cours — "Toutes les années"
    # (year_id=all) reste disponible pour consulter l'historique.
    class_id = request.GET.get('class_id', '').strip()
    year_id  = request.GET.get('year_id', '').strip()
    if year_id == 'all':
        selected_year_id = ''
    elif year_id:
        selected_year_id = year_id
    else:
        current_year = all_years.filter(is_current=True).first()
        selected_year_id = str(current_year.pk) if current_year else ''

    if class_id:
        qs = qs.filter(class_group_id=class_id)
    if selected_year_id:
        qs = qs.filter(academic_year_id=selected_year_id)

    classes_qs = Class.objects.select_related('program__department').order_by('name')
    if dept:
        classes_qs = classes_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)

    # Crédit disponible (pour les suspensions) = montant déjà payé sur l'inscription suspendue
    rows = []
    for enr in qs:
        rows.append({'enrollment': enr, 'credit': enr.total_paid_amount if status == Enrollment.STATUS_SUSPENDED else None})

    return render(request, template_name, {
        'rows': rows,
        'all_classes': classes_qs,
        'all_years': all_years,
        'selected_class_id': class_id,
        'selected_year_id': selected_year_id,
        'year_filter_raw': year_id,
    })


@login_required
def abandon_list(request):
    if not (request.user.can_manage_dept() or request.user.is_comptable()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    return _status_management_list(request, Enrollment.STATUS_ABANDONED, 'students/abandon_list.html')


@login_required
def abandon_reactivate_all(request):
    """
    Réactive en une seule action tous les abandons actuellement affichés (selon
    les filtres classe/année appliqués sur la liste des abandons, ou tous les
    abandons du département si aucun filtre n'est appliqué).
    """
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('students:abandon_list')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    qs = Enrollment.objects.filter(status=Enrollment.STATUS_ABANDONED).select_related('student__user')
    if dept:
        qs = qs.filter(class_group__program__department=dept)
    elif faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)

    class_id = request.POST.get('class_id', '').strip()
    year_id  = request.POST.get('year_id', '').strip()
    if class_id:
        qs = qs.filter(class_group_id=class_id)
    if year_id:
        qs = qs.filter(academic_year_id=year_id)

    count = 0
    for enr in qs:
        enr.status            = Enrollment.STATUS_VALIDATED
        enr.is_active          = True
        enr.status_changed_at  = None
        enr.status_changed_by  = None
        enr.status_reason      = ''
        enr.save(update_fields=[
            'status', 'is_active', 'status_changed_at', 'status_changed_by', 'status_reason',
        ])
        student = enr.student
        student.user.__class__.objects.filter(pk=student.user_id).update(is_active=True)
        count += 1

    if count:
        messages.success(request, f"{count} étudiant(s) réactivé(s) et réintégré(s) dans leur classe.")
    else:
        messages.info(request, "Aucun abandon à réactiver pour ces filtres.")

    redirect_url = reverse('students:abandon_list')
    params = []
    if class_id:
        params.append(f'class_id={class_id}')
    if year_id:
        params.append(f'year_id={year_id}')
    if params:
        redirect_url += '?' + '&'.join(params)
    return redirect(redirect_url)


@login_required
def suspension_list(request):
    if not (request.user.can_manage_dept() or request.user.is_comptable()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    return _status_management_list(request, Enrollment.STATUS_SUSPENDED, 'students/suspension_list.html')


def _activate_institut_db(institut_config):
    """
    Active la base de données de l'institut sélectionné pour le thread courant.
    Retourne l'alias de base utilisé.
    """
    from academic_core.db_router import set_current_db, get_current_db
    if not institut_config:
        return get_current_db()
    alias = getattr(institut_config, 'db_alias', '') or ''
    if not alias:
        return 'default'
    from academic_core.tenant_databases import register_tenant_db
    alias = register_tenant_db(alias)
    if not alias:
        return 'default'
    set_current_db(alias)
    return alias


class StudentCreateView(_AdminResponsableMixin, View):
    template_name = 'students/form.html'

    def _form_with_choices(self, request, data=None, files=None):
        from academic_core.apps.academic_structure.models import Class, AcademicYear, InstitutConfig
        dept    = getattr(request, 'active_department', None)
        faculty = getattr(request, 'active_faculty', None)
        form    = StudentUserForm(data, files)

        # ── Institut d'appartenance ────────────────────────────────────────
        # Seul le Super Admin global (ADMIN sans institut/département propre) peut
        # choisir parmi tous les instituts. Tout autre utilisateur connecté (INST_ADMIN,
        # ASSISTANTE_DG, RESPONSABLE, ASSISTANTE, CONTROLEUR, COMPTABLE, ...) ne doit voir
        # que son propre institut d'appartenance.
        inst_qs = InstitutConfig.objects.select_related('faculty').order_by('nom')
        user_institut = getattr(request.user, 'institut_config', None)
        if not user_institut and faculty:
            user_institut = InstitutConfig.objects.filter(faculty=faculty).first()

        form.institut_locked = False
        if not request.user.is_super_admin() and user_institut:
            inst_qs = inst_qs.filter(pk=user_institut.pk)
            form.fields['target_institut'].initial = user_institut.pk
            form.fields['target_institut'].empty_label = None
            form.institut_locked = True
            form.institut_display = str(user_institut)
        form.fields['target_institut'].queryset = inst_qs

        # ── Classes (filtrées par l'institut sélectionné en POST ou par contexte) ──
        # En GET : filtre par faculty/dept du contexte
        # En POST : filtre par l'institut soumis dans le formulaire
        selected_inst = None
        if data:
            inst_pk = data.get('target_institut')
            if inst_pk:
                try:
                    selected_inst = InstitutConfig.objects.get(pk=inst_pk)
                except InstitutConfig.DoesNotExist:
                    pass

        classes = Class.objects.select_related(
            'program__department', 'level', 'academic_year'
        ).order_by('name')

        if selected_inst:
            classes = classes.filter(program__department__faculty=selected_inst.faculty)
        elif dept:
            classes = classes.filter(program__department=dept)
        elif faculty:
            classes = classes.filter(program__department__faculty=faculty)

        years = AcademicYear.objects.order_by('-start_date')
        fac = selected_inst.faculty if selected_inst else faculty
        if fac and not request.user.is_super_admin():
            fy = years.filter(faculty=fac)
            years = fy if fy.exists() else years

        # Un nouvel étudiant est inscrit dans l'année académique en cours —
        # la classe proposée doit donc être celle de l'année en cours.
        current_year = years.filter(is_current=True).first()
        if current_year:
            classes = classes.filter(academic_year=current_year)

        form.fields['class_group'].choices  = (
            [('', '— Sélectionner une classe —')] + [(c.pk, c.name) for c in classes]
        )
        form.fields['academic_year'].choices = (
            [('', '— Sélectionner une année —')] + [(y.pk, str(y)) for y in years]
        )
        return form

    def get(self, request, *args, **kwargs):
        form = self._form_with_choices(request)
        return render(request, self.template_name, {'form': form, 'is_create': True})

    def post(self, request, *args, **kwargs):
        from academic_core.apps.academic_structure.models import Class, AcademicYear
        from academic_core.apps.students.models import Enrollment
        form = self._form_with_choices(request, request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_create': True})

        cd = form.cleaned_data

        # ── Activer la base de l'institut choisi ──────────────────────────
        target_cfg = cd.get('target_institut')
        db_alias   = _activate_institut_db(target_cfg)

        class_group = Class.objects.filter(pk=cd['class_group']).first()
        acad_year   = AcademicYear.objects.filter(pk=cd['academic_year']).first()
        if not class_group or not acad_year:
            messages.error(request, "Classe ou année académique invalide.")
            return render(request, self.template_name, {'form': form, 'is_create': True})

        user, student, enrollment, matricule, plain_password = create_student_enrollment(
            db_alias=db_alias, cd=cd, class_group=class_group, academic_year=acad_year,
        )

        request.session['created_credentials'] = {
            'type':      'étudiant',
            'full_name': user.get_full_name(),
            'username':  user.username,
            'matricule': matricule,
            'password':  plain_password,
            'student_pk': student.pk,
            'institut':  getattr(target_cfg, 'nom', ''),
        }
        return redirect('students:credentials_created')


class StudentCredentialsView(_AdminResponsableMixin, View):
    """Affiche les identifiants générés juste après la création d'un étudiant."""
    def get(self, request, *args, **kwargs):
        creds = request.session.pop('created_credentials', None)
        if not creds:
            return redirect('students:list')
        return render(request, 'students/credentials_created.html', {'creds': creds})


@login_required
def ajax_classes_by_institut(request):
    """
    AJAX GET — retourne les classes et années académiques d'un institut.
    Param: institut_id (PK de InstitutConfig)
    """
    from django.http import JsonResponse
    from academic_core.apps.academic_structure.models import InstitutConfig, Class, AcademicYear

    inst_id = request.GET.get('institut_id')
    if not inst_id:
        return JsonResponse({'classes': [], 'years': []})

    try:
        config = InstitutConfig.objects.using('default').get(pk=inst_id)
        faculty = config.faculty
    except InstitutConfig.DoesNotExist:
        return JsonResponse({'classes': [], 'years': []})

    years = (AcademicYear.objects
             .filter(faculty=faculty)
             .order_by('-start_date'))
    if not years.exists():
        years = AcademicYear.objects.order_by('-start_date')

    # Un nouvel étudiant est inscrit dans l'année académique en cours — la
    # classe proposée doit donc être celle de l'année en cours.
    classes = (Class.objects
               .filter(program__department__faculty=faculty)
               .select_related('program__department')
               .order_by('name'))
    current_year = years.filter(is_current=True).first()
    if current_year:
        classes = classes.filter(academic_year=current_year)

    return JsonResponse({
        'classes': [{'id': c.pk, 'label': c.name} for c in classes],
        'years':   [{'id': y.pk, 'label': str(y)} for y in years],
    })


@login_required
def ajax_generate_matricule(request):
    """
    AJAX GET — génère un matricule unique et le retourne en JSON.
    Params: class_id, year_id
    """
    import json
    from django.http import JsonResponse
    class_id = request.GET.get('class_id')
    year_id  = request.GET.get('year_id')
    if not class_id or not year_id:
        return JsonResponse({'error': 'class_id et year_id sont requis'}, status=400)
    class_group   = Class.objects.filter(pk=class_id).first()
    academic_year = AcademicYear.objects.filter(pk=year_id).first()
    if not class_group or not academic_year:
        return JsonResponse({'error': 'Classe ou année académique introuvable'}, status=404)
    matricule = _generate_matricule(class_group, academic_year)
    return JsonResponse({'matricule': matricule})


class StudentUpdateView(_AdminResponsableMixin, View):
    template_name = 'students/form.html'

    def _get_context(self, request, student, form):
        dept    = getattr(request, 'active_department', None)
        faculty = getattr(request, 'active_faculty', None)
        classes_qs = Class.objects.select_related('program__department', 'academic_year').order_by('name')
        if dept:
            classes_qs = classes_qs.filter(program__department=dept)
        elif faculty:
            classes_qs = classes_qs.filter(program__department__faculty=faculty)
        years_qs = AcademicYear.objects.order_by('-start_date')
        if faculty and not request.user.is_super_admin():
            filtered = years_qs.filter(faculty=faculty)
            years_qs = filtered if filtered.exists() else years_qs
        current_enrollment = student.current_enrollment()

        # Ne proposer que les classes de l'année en cours — sauf la classe déjà
        # affectée à l'étudiant si elle appartient à une autre année, pour ne
        # pas la faire disparaître silencieusement du formulaire.
        current_year = years_qs.filter(is_current=True).first()
        if current_year:
            existing_class_id = current_enrollment.class_group_id if current_enrollment else student.current_class_id
            year_scoped = classes_qs.filter(academic_year=current_year)
            if existing_class_id and not year_scoped.filter(pk=existing_class_id).exists():
                classes_qs = year_scoped | classes_qs.filter(pk=existing_class_id)
            else:
                classes_qs = year_scoped
        return {
            'form': form,
            'student': student,
            'is_create': False,
            'classes': classes_qs,
            'academic_years': years_qs,
            'current_enrollment': current_enrollment,
        }

    def _user_initial(self, student):
        u = student.user
        return {
            'first_name': u.first_name,
            'last_name':  u.last_name,
            'email':      u.email,
            'username':   u.username,
        }

    def get(self, request, pk):
        student = get_object_or_404(Student, pk=pk)
        form    = StudentForm(instance=student, initial=self._user_initial(student))
        return render(request, self.template_name, self._get_context(request, student, form))

    def post(self, request, pk):
        student = get_object_or_404(Student, pk=pk)
        form    = StudentForm(request.POST, request.FILES, instance=student)
        if not form.is_valid():
            return render(request, self.template_name, self._get_context(request, student, form))

        form.save()

        # Photo : uniquement si une nouvelle est fournie (fichier ou webcam)
        _raw_photo = form.cleaned_data.get('photo')
        photo_file = (_raw_photo if _raw_photo and _raw_photo is not False else None) \
                     or _webcam_b64_to_file(request.POST.get('photo_webcam', ''), student.matricule)
        if photo_file:
            if student.photo:
                try:
                    student.photo.delete(save=False)
                except Exception:
                    pass
            student.photo.save(photo_file.name, photo_file, save=True)

        # Sauvegarder les champs utilisateur
        cd = form.cleaned_data
        u = student.user
        u.first_name = cd['first_name']
        u.last_name  = cd['last_name']
        u.email      = cd['email']
        u.username   = cd['username']
        u.save(update_fields=['first_name', 'last_name', 'email', 'username'])

        # Réinitialisation du mot de passe (optionnelle) — sauvegarde séparée
        # de la précédente : le mot de passe est le seul champ dont
        # User.save() synchronise le hash vers la copie fantôme de 'default'
        # (voir models.py), et cette synchro filtre par username COURANT —
        # la combiner avec un changement de username dans le même appel
        # risquerait de la manquer si le username vient justement de changer.
        new_pwd = cd.get('new_password', '')
        if new_pwd:
            u.set_password(new_pwd)
            u.must_change_password = True
            u.save(update_fields=['password', 'must_change_password'])

        # Mise à jour classe / année académique
        class_id = request.POST.get('class_group')
        year_id  = request.POST.get('academic_year')
        if class_id and year_id:
            try:
                new_class = Class.objects.get(pk=class_id)
                new_year  = AcademicYear.objects.get(pk=year_id)
                # Mettre à jour current_class sur le profil
                student.current_class = new_class
                student.save(update_fields=['current_class'])
                # Mettre à jour l'enrollment actif ou en créer un nouveau
                enrollment = student.current_enrollment()
                if enrollment:
                    enrollment.class_group   = new_class
                    enrollment.academic_year = new_year
                    enrollment.is_active     = True
                    enrollment.save(update_fields=['class_group', 'academic_year', 'is_active'])
                else:
                    from .models import Enrollment
                    Enrollment.objects.create(
                        student=student,
                        class_group=new_class,
                        academic_year=new_year,
                        status=Enrollment.STATUS_PENDING,
                    )
                # Corriger aussi user.department
                if new_class.program and new_class.program.department:
                    student.user.department = new_class.program.department
                    student.user.__class__.objects.filter(pk=student.user.pk).update(
                        department=new_class.program.department
                    )
            except (Class.DoesNotExist, AcademicYear.DoesNotExist):
                pass

        messages.success(request, f"Les informations de « {student.full_name} » ont été mises à jour avec succès.")
        return redirect('students:detail', pk=student.pk)


class StudentDeleteView(_AdminResponsableMixin, DeleteView):
    model = Student
    template_name = 'students/confirm_delete.html'
    success_url = reverse_lazy('students:list')

    def delete(self, request, *args, **kwargs):
        student = self.get_object()
        messages.success(request, f"Étudiant « {student.full_name} » supprimé.")
        return super().delete(request, *args, **kwargs)


def _generate_excel_template(request):
    """Génère un fichier Excel (.xlsx) avec onglet saisie + onglet classes de référence."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side,
                                  GradientFill)
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()

    NAVY_FILL  = PatternFill('solid', fgColor='1E3A5F')
    GREEN_FILL = PatternFill('solid', fgColor='16A34A')
    LIGHT_FILL = PatternFill('solid', fgColor='EFF6FF')
    EXAMPLE_FILL = PatternFill('solid', fgColor='F0FDF4')
    WHITE_FONT = Font(color='FFFFFF', bold=True, size=10)
    BOLD_FONT  = Font(bold=True, size=10)
    NORMAL_FONT = Font(size=10)
    EXAMPLE_FONT = Font(size=10, italic=True, color='166534')
    thin = Side(style='thin', color='CBD5E1')
    BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ── Onglet 1 : Saisie des étudiants ──────────────────────────────────
    ws = wb.active
    ws.title = 'Étudiants'
    ws.sheet_view.showGridLines = True

    # Récupérer classes disponibles (pour la liste déroulante + onglet 2)
    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    classes_qs = (Class.objects
                  .select_related('program__department', 'academic_year')
                  .order_by('name'))
    if dept:
        classes_qs = classes_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)
    classes_list = list(classes_qs)

    years_qs = AcademicYear.objects.order_by('-start_date')
    if faculty:
        years_qs = years_qs.filter(faculty=faculty)
    years_list = list(years_qs)

    # Titre
    ws.merge_cells('A1:N1')
    title_cell = ws['A1']
    title_cell.value = "Modèle d'importation des étudiants"
    title_cell.font  = Font(color='FFFFFF', bold=True, size=14)
    title_cell.fill  = NAVY_FILL
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 32

    ws.merge_cells('A2:N2')
    sub = ws['A2']
    sub.value = "Remplissez à partir de la ligne 4. La ligne 3 est un exemple. Utilisez les noms exacts de l'onglet « Référence »."
    sub.font  = Font(size=9, italic=True, color='64748B')
    sub.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 18

    # En-têtes (ligne 3)
    headers = [col for col, _, _ in CSV_COLUMNS]
    examples = [ex for _, ex, _ in CSV_COLUMNS]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col_idx, value=header)
        cell.font      = WHITE_FONT
        cell.fill      = NAVY_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border    = BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = 18
    ws.row_dimensions[3].height = 24

    # Ligne exemple (ligne 4)
    for col_idx, ex in enumerate(examples, start=1):
        cell = ws.cell(row=4, column=col_idx, value=ex)
        cell.font      = EXAMPLE_FONT
        cell.fill      = EXAMPLE_FILL
        cell.alignment = Alignment(vertical='center')
        cell.border    = BORDER
    ws.row_dimensions[4].height = 20

    # Lignes de saisie vides (5 à 104)
    for row in range(5, 105):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row, column=col_idx)
            cell.fill   = PatternFill('solid', fgColor='FFFFFF') if row % 2 == 0 else PatternFill('solid', fgColor='F8FAFC')
            cell.font   = NORMAL_FONT
            cell.border = BORDER
            cell.alignment = Alignment(vertical='center')
        ws.row_dimensions[row].height = 18

    # Figer la ligne d'en-tête
    ws.freeze_panes = 'A5'

    # ── Onglet 2 : Référence classes + années ────────────────────────────
    ws2 = wb.create_sheet('Référence')
    ws2.sheet_view.showGridLines = True

    # Titre onglet 2
    ws2.merge_cells('A1:D1')
    t2 = ws2['A1']
    t2.value = "Classes et années académiques disponibles"
    t2.font  = Font(color='FFFFFF', bold=True, size=12)
    t2.fill  = GREEN_FILL
    t2.alignment = Alignment(horizontal='center', vertical='center')
    ws2.row_dimensions[1].height = 28

    ws2.merge_cells('A2:D2')
    n2 = ws2['A2']
    n2.value = "Utilisez exactement les noms ci-dessous dans les colonnes « classe » et « annee_academique » de l'onglet Étudiants."
    n2.font  = Font(size=9, italic=True, color='64748B')
    n2.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws2.row_dimensions[2].height = 30

    cls_headers = ['Nom de la classe', 'Filière', 'Département', 'Année académique']
    for ci, h in enumerate(cls_headers, 1):
        c = ws2.cell(row=3, column=ci, value=h)
        c.font   = WHITE_FONT
        c.fill   = NAVY_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal='center', vertical='center')
    ws2.row_dimensions[3].height = 22

    cls_names  = []
    year_names = []
    for ri, cls in enumerate(classes_list, start=4):
        ws2.cell(row=ri, column=1, value=cls.name).border = BORDER
        ws2.cell(row=ri, column=2, value=cls.program.name if cls.program else '—').border = BORDER
        ws2.cell(row=ri, column=3, value=cls.program.department.name if cls.program and cls.program.department else '—').border = BORDER
        ws2.cell(row=ri, column=4, value=cls.academic_year.name if cls.academic_year else '—').border = BORDER
        for ci in range(1, 5):
            ws2.cell(row=ri, column=ci).font = NORMAL_FONT
            ws2.cell(row=ri, column=ci).fill = LIGHT_FILL if ri % 2 == 0 else PatternFill('solid', fgColor='FFFFFF')
        if cls.name not in cls_names:
            cls_names.append(cls.name)

    for yr in years_list:
        if yr.name not in year_names:
            year_names.append(yr.name)

    for ci, w in enumerate([28, 30, 30, 20], 1):
        ws2.column_dimensions[get_column_letter(ci)].width = w

    # ── Validation données : liste déroulante classe dans onglet 1 ───────
    if cls_names:
        # Écrire les noms dans une zone cachée de l'onglet référence (col F)
        for ri, name in enumerate(cls_names, start=1):
            ws2.cell(row=ri, column=6, value=name)
        col_letter = get_column_letter(headers.index('classe') + 1) if 'classe' in headers else None
        if col_letter:
            ref_range = f"Référence!$F$1:$F${len(cls_names)}"
            dv = DataValidation(type='list', formula1=ref_range, allow_blank=True,
                                showErrorMessage=True,
                                errorTitle='Classe invalide',
                                error='Choisissez une classe de la liste.')
            dv.sqref = f"{col_letter}5:{col_letter}104"
            ws.add_data_validation(dv)

    # ── Réponse HTTP ─────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="modele_import_etudiants.xlsx"'
    return response


CSV_COLUMNS = [
    ('matricule',        'ETU-2024-001',      True),
    ('prenom',           'Fatou',             True),
    ('nom',              'Diallo',            True),
    ('email',            'f.diallo@isi.sn',   True),
    ('date_naissance',   '2002-03-15',        True),
    ('lieu_naissance',   'Dakar',             True),
    ('genre',            'M ou F',            True),
    ('telephone',        '+221 77 000 0000',  True),
    ('adresse',          'Dakar, Sénégal',    True),
    ('classe',             'L3 Informatique A', True),
    ('annee_academique',   '2024-2025',         True),
    ('tuteur_prenom',      'Mamadou',           True),
    ('tuteur_nom',       'Diallo',            True),
    ('tuteur_telephone', '+221 76 000 0000',  True),
    ('tuteur_email',     'm.diallo@gmail.com',True),
]


class StudentImportView(_AdminResponsableMixin, View):
    template_name = 'students/import.html'

    def get(self, request):
        # Téléchargement du modèle Excel
        if request.GET.get('download'):
            return _generate_excel_template(request)


        form = StudentImportForm()
        return render(request, self.template_name, {'form': form, 'columns': CSV_COLUMNS})

    def post(self, request):
        form = StudentImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'columns': CSV_COLUMNS})

        csv_file = request.FILES['csv_file']
        if not csv_file.name.endswith('.csv'):
            messages.error(request, "Le fichier doit être au format CSV.")
            return render(request, self.template_name, {'form': form, 'columns': CSV_COLUMNS})

        try:
            role = Role.objects.get(name=Role.ETUDIANT)
        except Role.DoesNotExist:
            messages.error(request, "Le rôle ETUDIANT n'existe pas.")
            return render(request, self.template_name, {'form': form, 'columns': CSV_COLUMNS})

        decoded = csv_file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))

        created, skipped, errors = 0, 0, []
        alphabet = string.ascii_letters + string.digits

        for i, row in enumerate(reader, start=2):
            matricule      = (row.get('matricule') or '').strip()
            email          = (row.get('email') or '').strip()
            first_name     = (row.get('prenom') or '').strip()
            last_name      = (row.get('nom') or '').strip()
            date_naissance = (row.get('date_naissance') or '').strip()
            lieu_naissance = (row.get('lieu_naissance') or '').strip()
            genre          = (row.get('genre') or '').strip().upper()
            telephone      = (row.get('telephone') or '').strip()
            adresse        = (row.get('adresse') or '').strip()
            classe           = (row.get('classe') or '').strip()
            annee_academique = (row.get('annee_academique') or '').strip()
            tuteur_prenom    = (row.get('tuteur_prenom') or '').strip()
            tuteur_nom     = (row.get('tuteur_nom') or '').strip()
            tuteur_tel     = (row.get('tuteur_telephone') or '').strip()
            tuteur_email   = (row.get('tuteur_email') or '').strip()

            manquants = []
            if not matricule:      manquants.append('matricule')
            if not email:          manquants.append('email')
            if not first_name:     manquants.append('prenom')
            if not last_name:      manquants.append('nom')
            if not date_naissance: manquants.append('date_naissance')
            if not lieu_naissance: manquants.append('lieu_naissance')
            if genre not in ('M', 'F'): manquants.append('genre (M ou F)')
            if not telephone:      manquants.append('telephone')
            if not adresse:        manquants.append('adresse')
            if not classe:             manquants.append('classe')
            if not annee_academique:   manquants.append('annee_academique')
            if not tuteur_prenom:  manquants.append('tuteur_prenom')
            if not tuteur_nom:     manquants.append('tuteur_nom')
            if not tuteur_tel:     manquants.append('tuteur_telephone')
            if not tuteur_email:   manquants.append('tuteur_email')

            if manquants:
                errors.append(f"Ligne {i} : champs manquants ou invalides → {', '.join(manquants)}.")
                skipped += 1
                continue

            if Student.objects.filter(matricule=matricule).exists():
                errors.append(f"Ligne {i} : matricule « {matricule} » déjà existant, ignoré.")
                skipped += 1
                continue

            if User.objects.filter(email=email).exists():
                errors.append(f"Ligne {i} : email « {email} » déjà utilisé, ignoré.")
                skipped += 1
                continue

            target_class = Class.objects.filter(name__iexact=classe).first() if classe else None

            password = ''.join(secrets.choice(alphabet) for _ in range(12))
            # Dériver le département depuis la classe
            import_dept = None
            if target_class and hasattr(target_class, 'program') and target_class.program:
                import_dept = getattr(target_class.program, 'department', None)
            import_faculty = getattr(import_dept, 'faculty', None) if import_dept else None
            import_direction = _get_direction_etudes(import_faculty)

            user = User.objects.create(
                first_name=first_name, last_name=last_name,
                email=email, username=email,
                password=make_password(password), role=role,
                department=import_dept,
                direction=import_direction,
                is_active=False,  # activé uniquement après validation comptable
            )
            student = Student.objects.create(
                user=user, matricule=matricule,
                date_of_birth=date_naissance or None,
                place_of_birth=lieu_naissance,
                gender=genre,
                phone=telephone,
                address=adresse,
                guardian_first_name=tuteur_prenom,
                guardian_last_name=tuteur_nom,
                guardian_phone=tuteur_tel,
                guardian_email=tuteur_email,
            )
            # Créer une inscription en attente si une classe est fournie.
            # L'affectation réelle se fait via la validation comptable.
            if target_class:
                acad_year = None
                if annee_academique:
                    acad_year = AcademicYear.objects.filter(name__iexact=annee_academique).first()
                if not acad_year:
                    acad_year = AcademicYear.objects.filter(is_current=True).first()
                if acad_year:
                    Enrollment.objects.get_or_create(
                        student=student,
                        class_group=target_class,
                        academic_year=acad_year,
                        defaults={'is_active': False, 'status': Enrollment.STATUS_PENDING},
                    )
            created += 1

        if created:
            messages.success(request, f"{created} étudiant(s) importé(s) avec succès.")
        if skipped:
            messages.warning(request, f"{skipped} ligne(s) ignorée(s).")
        for err in errors[:5]:
            messages.error(request, err)

        return redirect('students:list')

    def _render_form(self, request, form):
        return render(request, self.template_name, {'form': form, 'columns': CSV_COLUMNS})


@login_required
def class_list_pdf(request):
    """Génère un PDF de la liste des étudiants d'une classe pour une année académique."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from academic_core.apps.academic_structure.models import BulletinConfig
    from academic_core.pdf_utils import logo_image as _logo_img_cl_fn, get_institut_config_for_request as _gcfr_cl, watermark_canvas
    _logo_img_cl = lambda **kw: _logo_img_cl_fn(config=_gcfr_cl(request), **kw)  # noqa: E731
    from datetime import date as dt

    class_id = request.GET.get('class_id')
    year_id  = request.GET.get('year_id')
    if not class_id or not year_id:
        messages.error(request, "Classe et année académique requises.")
        return redirect('students:list')

    cls      = get_object_or_404(Class.objects.select_related('program__department', 'level'), pk=class_id)
    acad_year = get_object_or_404(AcademicYear, pk=year_id)
    # Pas de filtre `enrollments__is_active` : voir StudentListView.get_queryset
    # (historique par classe/année, indépendant d'une réinscription ultérieure).
    students  = Student.objects.filter(
        enrollments__class_group=cls,
        enrollments__academic_year=acad_year,
        enrollments__status=Enrollment.STATUS_VALIDATED,
    ).select_related('user').order_by('user__last_name', 'user__first_name')

    config = BulletinConfig.get()
    inst_config = _gcfr_cl(request)
    nom_inst = getattr(inst_config, 'nom', None) or "Institut Supérieur d'Informatique"

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                               rightMargin=1.3*cm, leftMargin=1.3*cm,
                               topMargin=1.2*cm, bottomMargin=1.2*cm)

    navy      = colors.HexColor('#00173B')
    navy_soft = colors.HexColor('#1E3A5F')
    gold      = colors.HexColor('#D4AF37')
    light     = colors.HexColor('#EFF6FF')
    stripe    = colors.HexColor('#F8FAFC')
    border    = colors.HexColor('#CBD5E1')
    grey      = colors.HexColor('#64748B')
    ss    = getSampleStyleSheet()

    s_inst_name = ParagraphStyle('instname', parent=ss['Normal'], alignment=TA_LEFT,
                                  fontSize=13, fontName='Helvetica-Bold', textColor=navy, leading=15)
    s_inst_sub  = ParagraphStyle('instsub', parent=ss['Normal'], alignment=TA_LEFT,
                                  fontSize=8.5, textColor=grey, leading=11)
    s_ttl_band  = ParagraphStyle('ttlband', parent=ss['Normal'], alignment=TA_CENTER,
                                  fontSize=15, fontName='Helvetica-Bold', textColor=colors.white)
    s_info_lbl  = ParagraphStyle('ilbl', parent=ss['Normal'], fontSize=7.5,
                                  fontName='Helvetica-Bold', textColor=grey, alignment=TA_CENTER)
    s_info_val  = ParagraphStyle('ival', parent=ss['Normal'], fontSize=10,
                                  fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER)
    s_cell      = ParagraphStyle('cell', parent=ss['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#1E293B'))
    s_cell_ctr  = ParagraphStyle('cellc', parent=s_cell, alignment=TA_CENTER)
    s_head      = ParagraphStyle('head', parent=ss['Normal'], fontSize=9, leading=11,
                                  fontName='Helvetica-Bold', textColor=colors.white)
    s_head_ctr  = ParagraphStyle('headc', parent=s_head, alignment=TA_CENTER)
    s_foot      = ParagraphStyle('foot', parent=ss['Normal'], fontSize=8, textColor=grey)
    s_sign      = ParagraphStyle('sign', parent=ss['Normal'], alignment=TA_CENTER, fontSize=9.5,
                                  fontName='Helvetica-Bold', textColor=navy)

    # ── En-tête institut (logo + nom, comme un papier à en-tête) ────────────────
    _logo_cl = _logo_img_cl(width=2*cm, height=2*cm)
    header_cells = [
        _logo_cl or Paragraph('', s_inst_name),
        Paragraph(
            f"{nom_inst}<br/>"
            f"<font color='#64748B' size='8.5'>{getattr(inst_config, 'ville', '') or 'Dakar, Sénégal'}"
            f"{' — ' + getattr(inst_config, 'telephone', '') if getattr(inst_config, 'telephone', '') else ''}</font>",
            s_inst_name,
        ),
        Paragraph(
            f"<font size='8' color='#64748B'>Année académique</font><br/>"
            f"<font size='11' color='#00173B'><b>{acad_year.label}</b></font>",
            ParagraphStyle('yr', parent=ss['Normal'], alignment=TA_RIGHT, leading=14),
        ),
    ]
    hdr_tbl = Table([header_cells], colWidths=[2.4*cm, 17*cm, 4.6*cm])
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    # ── Bandeau titre (fond navy pleine largeur) ─────────────────────────────────
    title_tbl = Table(
        [[Paragraph(f"LISTE DES ÉTUDIANTS — {cls.name}", s_ttl_band)]],
        colWidths=[24*cm],
    )
    title_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), navy),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW',     (0, 0), (-1, -1), 2.5, gold),
    ]))

    # ── Bandeau d'informations (département, filière, niveau, année, effectif) ──
    info_headers = ['Département', 'Filière', 'Niveau', 'Effectif']
    info_values  = [
        cls.program.department.name if cls.program and cls.program.department else '—',
        cls.program.name if cls.program else '—',
        str(cls.level) if cls.level else '—',
        f"{students.count()} étudiant(s)",
    ]
    info_tbl = Table(
        [[Paragraph(h, s_info_lbl) for h in info_headers],
         [Paragraph(v, s_info_val) for v in info_values]],
        colWidths=[6*cm, 8*cm, 4*cm, 6*cm],
    )
    info_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), light),
        ('BOX',           (0, 0), (-1, -1), 0.75, border),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, colors.white),
        ('TOPPADDING',    (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
        ('TOPPADDING',    (0, 1), (-1, 1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 8),
    ]))

    story = [
        hdr_tbl,
        Spacer(1, .35*cm),
        title_tbl,
        Spacer(1, .3*cm),
        info_tbl,
        Spacer(1, .5*cm),
    ]

    # ── Tableau des étudiants ────────────────────────────────────────────────────
    GENDER_LABELS = {'M': 'M', 'F': 'F'}
    headers = [
        Paragraph('N°',               s_head_ctr),
        Paragraph('Matricule',        s_head),
        Paragraph('Nom',              s_head),
        Paragraph('Prénom(s)',        s_head),
        Paragraph('Genre',            s_head_ctr),
        Paragraph('Date de naissance', s_head_ctr),
        Paragraph('Lieu de naissance', s_head),
    ]
    data = [headers]
    for i, s in enumerate(students, 1):
        data.append([
            Paragraph(str(i), s_cell_ctr),
            Paragraph(s.matricule or '—', s_cell),
            Paragraph((s.user.last_name or '—').upper(), s_cell),
            Paragraph(s.user.first_name or '—', s_cell),
            Paragraph(GENDER_LABELS.get(s.gender, '—'), s_cell_ctr),
            Paragraph(s.date_of_birth.strftime('%d/%m/%Y') if s.date_of_birth else '—', s_cell_ctr),
            Paragraph(s.place_of_birth or '—', s_cell),
        ])

    col_w = [1.2*cm, 3*cm, 4.5*cm, 4.5*cm, 1.8*cm, 3.5*cm, 5.5*cm]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl_style = [
        ('BACKGROUND',    (0, 0), (-1, 0), navy),
        ('LINEBELOW',     (0, 0), (-1, 0), 1.5, gold),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, stripe]),
        ('GRID',          (0, 0), (-1, -1), 0.4, border),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
    ]
    # Ligne de séparation plus marquée toutes les 5 lignes pour faciliter la lecture
    for row_idx in range(6, len(data), 5):
        tbl_style.append(('LINEABOVE', (0, row_idx), (-1, row_idx), 0.9, navy_soft))
    tbl.setStyle(TableStyle(tbl_style))

    if students.exists():
        story.append(tbl)
    else:
        story.append(Paragraph("Aucun étudiant inscrit et validé dans cette classe pour cette année académique.",
                                ParagraphStyle('empty', parent=ss['Normal'], alignment=TA_CENTER,
                                               fontSize=10, textColor=grey)))

    # ── Pied de page : génération + signature ────────────────────────────────────
    story.append(Spacer(1, 1.2*cm))
    footer_tbl = Table([[
        Paragraph(f"Document généré le {dt.today().strftime('%d/%m/%Y')} — {nom_inst}", s_foot),
        Paragraph(
            f"Le Directeur — {config.director_title or ''}<br/>"
            f"<font size='10'>{config.director_name or ''}</font>",
            s_sign,
        ),
    ]], colWidths=[13*cm, 11*cm])
    footer_tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM')]))
    story.append(HRFlowable(width='100%', thickness=0.5, color=border, spaceAfter=8))
    story.append(footer_tbl)
    story.append(Spacer(1, .3*cm))

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    filename = f"liste_{cls.name}_{acad_year.label}.pdf".replace(' ', '_').replace('/', '-')
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{filename}"'
    return resp


@login_required
def fiche_inscription_pdf(request, pk):
    """Génère la fiche d'inscription PDF à remettre à la comptabilité."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from academic_core.pdf_utils import logo_image as _logo_img_fiche_fn, senegal_flag as _flag, get_institut_config_for_request as _gcfr_fi, watermark_canvas
    _logo_img = lambda **kw: _logo_img_fiche_fn(config=_gcfr_fi(request), **kw)  # noqa: E731
    from academic_core.apps.academic_structure.models import BulletinConfig
    from datetime import date as dt

    student = get_object_or_404(
        Student.objects.select_related('user', 'current_class__program__department', 'current_class__level'),
        pk=pk,
    )
    if not (request.user.can_manage_dept() or request.user.is_admin()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    config = BulletinConfig.get()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=1*cm, bottomMargin=1*cm,
    )

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')

    ss = getSampleStyleSheet()
    sc = ParagraphStyle

    W = 17.4*cm  # largeur utile

    s_ctr  = sc('c',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl  = sc('t',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=13, fontName='Helvetica-Bold', textColor=navy, spaceAfter=0)
    s_sub  = sc('s',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=8, textColor=grey, spaceAfter=0)
    s_lbl  = sc('l',  parent=ss['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=navy)
    s_val  = sc('v',  parent=ss['Normal'], fontSize=8)
    s_sec  = sc('sec',parent=ss['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=colors.white)
    s_warn = sc('w',  parent=ss['Normal'], fontSize=8, textColor=colors.HexColor('#92400e'), alignment=TA_CENTER)
    s_sgn  = sc('sg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=8, fontName='Helvetica-Bold', textColor=navy)
    s_foot = sc('ft', parent=ss['Normal'], alignment=TA_CENTER, fontSize=6.5, textColor=grey)

    _flag_el = _flag(width=2*cm, height=1.3*cm)
    _logo_el = _logo_img(width=2*cm, height=1.3*cm) or Paragraph(
        'ISI', sc('lb', parent=s_ctr, fontSize=8, fontName='Helvetica-Bold', textColor=navy)
    )
    _hdr_tbl = Table(
        [[_flag_el,
          Paragraph(
            '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="7">Un Peuple — Un But — Une Foi</font>'
            '<br/><font size="11"><b>GROUPE ISI</b></font><br/>'
            "<font size='8'>Institut Supérieur d'Informatique</font>",
            sc('rh', parent=ss['Normal'], alignment=TA_CENTER, leading=12),
          ),
          _logo_el]],
        colWidths=[2.5*cm, 12.4*cm, 2.5*cm],
    )
    _hdr_tbl.setStyle(TableStyle([
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
    ]))

    def section_header(title):
        tbl = Table([[Paragraph(f"<b>{title}</b>", s_sec)]], colWidths=[W])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), navy),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ]))
        return tbl

    def info_table(rows, col1=5*cm):
        tbl = Table(rows, colWidths=[col1, W - col1])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (0, -1), light),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',     (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
            ('LEFTPADDING',    (0, 0), (-1, -1), 6),
        ]))
        return tbl

    gender_display = 'Masculin' if student.gender == 'M' else ('Féminin' if student.gender == 'F' else '—')

    story = [
        _hdr_tbl,
        Spacer(1, .15*cm),
        HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=4),
        Paragraph("FICHE D'INSCRIPTION", s_ttl),
        Paragraph("À remettre à la Direction Administrative Financière accompagnée du reçu de paiement", s_sub),
        Spacer(1, .15*cm),
        HRFlowable(width='40%', thickness=1, color=gold, hAlign='CENTER'),
        Spacer(1, .2*cm),

        # Avertissement compact
        Table(
            [[Paragraph(
                "<b>IMPORTANT :</b> Ce document doit être présenté à la Direction Administrative Financière accompagné du reçu de paiement "
                "pour la validation définitive de l'inscription.",
                s_warn
            )]],
            colWidths=[W],
            style=[
                ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#FEF3C7')),
                ('BOX',           (0, 0), (-1, -1), 1, colors.HexColor('#F59E0B')),
                ('TOPPADDING',    (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING',   (0, 0), (-1, -1), 8),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ]
        ),
        Spacer(1, .25*cm),

        # Section 1 — Informations personnelles
        section_header("1. Informations personnelles"),
        info_table([
            [Paragraph("<b>Matricule</b>", s_lbl),            Paragraph(student.matricule, s_val)],
            [Paragraph("<b>Nom &amp; Prénom(s)</b>", s_lbl),  Paragraph(student.full_name, s_val)],
            [Paragraph("<b>Date de naissance</b>", s_lbl),    Paragraph(student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '—', s_val)],
            [Paragraph("<b>Lieu de naissance</b>", s_lbl),    Paragraph(student.place_of_birth or '—', s_val)],
            [Paragraph("<b>Genre</b>", s_lbl),                Paragraph(gender_display, s_val)],
            [Paragraph("<b>Téléphone</b>", s_lbl),            Paragraph(student.phone or '—', s_val)],
            [Paragraph("<b>Adresse</b>", s_lbl),              Paragraph(student.address or '—', s_val)],
            [Paragraph("<b>Email</b>", s_lbl),                Paragraph(student.email or '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 2 — Informations sur la Bourse
        section_header("2. Informations sur la Bourse"),
        info_table([
            [Paragraph("<b>Boursier</b>", s_lbl), Paragraph("Oui" if student.is_boursier else "Non", s_val)],
            [Paragraph("<b>Partenaire de bourse</b>", s_lbl),
             Paragraph(str(student.partenaire_bourse) if student.is_boursier and student.partenaire_bourse else '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 3 — Personne à contacter
        section_header("3. Personne à contacter (Tuteur / Parent)"),
        info_table([
            [Paragraph("<b>Prénom &amp; Nom</b>", s_lbl),  Paragraph(f"{student.guardian_first_name} {student.guardian_last_name}".strip() or '—', s_val)],
            [Paragraph("<b>Téléphone</b>", s_lbl),          Paragraph(student.guardian_phone or '—', s_val)],
            [Paragraph("<b>Email</b>", s_lbl),              Paragraph(student.guardian_email or '—', s_val)],
            [Paragraph("<b>Adresse</b>", s_lbl),            Paragraph(student.guardian_address or '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 4 — Réservé à la Direction Administrative Financière
        section_header("4. Réservé à la Direction Administrative Financière"),
        Table(
            [
                [Paragraph("<b>Montant versé (FCFA)</b>", s_lbl), Paragraph('', s_val),
                 Paragraph("<b>Référence reçu</b>", s_lbl),       Paragraph('', s_val)],
                [Paragraph("<b>Date de paiement</b>", s_lbl),     Paragraph('', s_val),
                 Paragraph("<b>Validé par</b>", s_lbl),           Paragraph('', s_val)],
            ],
            colWidths=[4.5*cm, 4.2*cm, 4.5*cm, 4.2*cm],
            style=TableStyle([
                ('BACKGROUND',     (0, 0), (0, -1), light),
                ('BACKGROUND',     (2, 0), (2, -1), light),
                ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
                ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',     (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING',  (0, 0), (-1, -1), 8),
                ('LEFTPADDING',    (0, 0), (-1, -1), 6),
            ])
        ),
        Spacer(1, .5*cm),

        # Signatures
        Table(
            [[Paragraph("Dakar, le _____ / _____ / _______", sc('dl', parent=ss['Normal'], fontSize=8)),
              Paragraph("Signature &amp; Cachet de la Direction Administrative Financière", s_sgn)]],
            colWidths=[9*cm, 8.4*cm],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, .6*cm),
        HRFlowable(width='100%', thickness=0.5, color=grey),
        Spacer(1, .1*cm),
        Paragraph(
            f"Fiche générée le {dt.today().strftime('%d/%m/%Y')}  —  Institut Supérieur d'Informatique - ISI  —  Dakar, Sénégal",
            s_foot
        ),
    ]

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="fiche_inscription_{student.matricule}.pdf"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Association rapide département
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def assign_department_view(request):
    if request.method != 'POST':
        return redirect('students:list')
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('students:list')

    user_pk  = request.POST.get('user_pk')
    dept_id  = request.POST.get('department_id')
    next_url = request.POST.get('next') or 'students:list'

    from academic_core.apps.academic_structure.models import Department
    from academic_core.db_router import get_current_db
    from django.conf import settings

    # La base courante est déjà résolue par DepartmentMiddleware (ex: db_inst_isi)
    current_db = get_current_db()
    # Ordre de recherche : base courante d'abord, puis les autres
    ordered_dbs = [current_db] + [db for db in settings.DATABASES if db != current_db]

    # Trouver l'utilisateur en cherchant depuis la base active en premier
    target_user = None
    target_db   = None
    for db_alias in ordered_dbs:
        try:
            u = User.objects.using(db_alias).get(pk=user_pk)
            target_user = u
            target_db   = db_alias
            break
        except (User.DoesNotExist, Exception):
            continue

    if not target_user:
        messages.error(request, "Utilisateur introuvable.")
        return redirect(next_url)

    # Chercher le département dans la même base que l'utilisateur
    try:
        dept = Department.objects.using(target_db).get(pk=dept_id)
    except Department.DoesNotExist:
        # Fallback : chercher dans default
        try:
            dept = Department.objects.using('default').get(pk=dept_id)
        except Department.DoesNotExist:
            messages.error(request, "Département introuvable.")
            return redirect(next_url)

    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"[ASSIGN_DEPT] user pk={user_pk} trouvé dans '{target_db}', dept pk={dept_id} '{dept.name}' → update(department_id={dept.pk})")

    User.objects.using(target_db).filter(pk=target_user.pk).update(department_id=dept.pk)

    messages.success(request, f"Département « {dept.name} » associé à {target_user.get_full_name()}.")
    return redirect(next_url)


# ─────────────────────────────────────────────────────────────────────────────
# Réinscription
# ─────────────────────────────────────────────────────────────────────────────

class ReinscriptionView(_AdminResponsableMixin, View):
    template_name = 'students/reinscription.html'

    # Lors d'une réinscription, la nouvelle filière peut appartenir à
    # n'importe quel département de l'institut (pas seulement le département
    # actuellement actif pour le membre du personnel) — l'étudiant peut donc
    # être réinscrit dans une autre filière au passage. ChangementFiliereView
    # (ci-dessous) hérite de cette classe mais repasse à False : son périmètre
    # départemental n'a pas été demandé et reste inchangé.
    scope_all_departments = True

    def _context_base(self, request):
        """Données communes : classes disponibles, années, query de recherche."""
        dept    = getattr(request, 'active_department', None)
        faculty = getattr(request, 'active_faculty', None)

        classes_qs = (Class.objects
                      .select_related('program__department', 'level', 'academic_year')
                      .order_by('program__department__name', 'level__order', 'name'))
        if self.scope_all_departments:
            if faculty:
                classes_qs = classes_qs.filter(program__department__faculty=faculty)
        elif dept:
            classes_qs = classes_qs.filter(program__department=dept)
        elif faculty:
            classes_qs = classes_qs.filter(program__department__faculty=faculty)

        years_qs = AcademicYear.objects.order_by('-start_date')
        if faculty and not request.user.is_super_admin():
            years_qs = years_qs.filter(faculty=faculty)

        return {
            'classes': classes_qs,
            'academic_years': years_qs,
        }

    def _search_students(self, request, query):
        """Recherche d'étudiants par username, prénom ou nom."""
        dept    = getattr(request, 'active_department', None)
        faculty = getattr(request, 'active_faculty', None)
        qs = (Student.objects
              .select_related('user', 'current_class__level', 'current_class__program__department')
              .filter(
                  Q(user__username__icontains=query) |
                  Q(user__first_name__icontains=query) |
                  Q(user__last_name__icontains=query) |
                  Q(matricule__icontains=query)
              ))
        if dept:
            qs = qs.filter(user__department=dept)
        elif faculty:
            qs = qs.filter(user__department__faculty=faculty)
        return qs[:20]

    def _next_level_classes(self, student, classes_qs):
        """Retourne les classes de niveau N+1 dans le même programme."""
        current_class = student.current_class
        if not current_class or not current_class.level:
            return classes_qs, None
        current_order = current_class.level.order
        from academic_core.apps.academic_structure.models import Level
        next_level = Level.objects.filter(order=current_order + 1).first()
        if not next_level:
            return classes_qs, None
        suggested = classes_qs.filter(
            level=next_level,
            program=current_class.program,
        )
        return classes_qs, suggested.first()

    def get(self, request):
        ctx = self._context_base(request)
        query = request.GET.get('q', '').strip()
        student_id = request.GET.get('student_id', '').strip()

        ctx['query'] = query
        ctx['search_results'] = []
        ctx['selected_student'] = None
        ctx['suggested_class'] = None

        if query:
            ctx['search_results'] = self._search_students(request, query)

        if student_id:
            student = Student.objects.select_related(
                'user', 'current_class__level', 'current_class__program__department',
                'current_class__academic_year',
            ).filter(pk=student_id).first()
            if student:
                ctx['selected_student'] = student
                _, suggested = self._next_level_classes(student, ctx['classes'])
                ctx['suggested_class'] = suggested
                # Année courante par défaut
                ctx['current_year'] = AcademicYear.objects.filter(is_current=True).first()

        return render(request, self.template_name, ctx)

    def post(self, request):
        student_id = request.POST.get('student_id')
        class_id   = request.POST.get('class_group')
        year_id    = request.POST.get('academic_year')

        student = get_object_or_404(Student, pk=student_id)
        try:
            new_class = Class.objects.get(pk=class_id)
            new_year  = AcademicYear.objects.get(pk=year_id)
        except (Class.DoesNotExist, AcademicYear.DoesNotExist):
            messages.error(request, "Classe ou année académique invalide.")
            return redirect('students:reinscription')

        # Vérifier pas de double réinscription pour la même année
        existing = Enrollment.objects.filter(
            student=student,
            academic_year=new_year,
            class_group=new_class,
        ).first()
        if existing:
            messages.warning(
                request,
                f"« {student.full_name} » est déjà inscrit(e) dans « {new_class.name} » "
                f"pour l'année {new_year.name} (statut : {existing.get_status_display()})."
            )
            return redirect('students:reinscription')

        # Désactiver l'ancien enrollment actif
        Enrollment.objects.filter(student=student, is_active=True).update(is_active=False)

        # Report automatique du crédit d'une inscription suspendue précédente
        # (frais d'inscription + mensualités déjà réglés cette année-là)
        suspended_enrollment = student.enrollments.filter(
            status=Enrollment.STATUS_SUSPENDED
        ).order_by('-enrollment_date').first()
        credit = suspended_enrollment.total_paid_amount if suspended_enrollment else 0

        # Créer le nouvel enrollment en attente
        enrollment = Enrollment.objects.create(
            student=student,
            class_group=new_class,
            academic_year=new_year,
            enrollment_type=Enrollment.TYPE_REINSCRIPTION,
            previous_class=student.current_class,
            status=Enrollment.STATUS_PENDING,
            is_active=False,
            credit_report=credit,
        )

        # Mettre à jour department si changement de classe
        if new_class.program and new_class.program.department:
            student.user.__class__.objects.filter(pk=student.user.pk).update(
                department=new_class.program.department
            )

        if suspended_enrollment and credit:
            messages.success(
                request,
                f"Réinscription de « {student.full_name} » en « {new_class.name} » "
                f"({new_year.name}) créée en attente de validation. "
                f"Crédit reporté de l'année de suspension ({suspended_enrollment.academic_year}) : "
                f"{int(credit):,} FCFA — pris en compte automatiquement à la validation.".replace(',', ' ')
            )
        else:
            messages.success(
                request,
                f"Réinscription de « {student.full_name} » en « {new_class.name} » "
                f"({new_year.name}) créée en attente de validation."
            )
        return redirect('students:list')


# ─────────────────────────────────────────────────────────────────────────────
# Changement de filière
# ─────────────────────────────────────────────────────────────────────────────

class ChangementFiliereView(ReinscriptionView):
    """
    Permet à un étudiant inscrit dans une classe d'une filière d'être réinscrit
    dans une classe d'une AUTRE filière. Suit exactement le même cycle de
    validation que la réinscription : l'inscription est créée en attente,
    l'étudiant reste "en attente" (compte non touché mais plus dans aucune
    classe active) tant que le trésorier général n'a pas validé le changement
    via la liste de validation des inscriptions.
    """
    template_name = 'students/changement_filiere.html'
    scope_all_departments = False

    def get(self, request):
        ctx = self._context_base(request)
        query = request.GET.get('q', '').strip()
        student_id = request.GET.get('student_id', '').strip()

        ctx['query'] = query
        ctx['search_results'] = []
        ctx['selected_student'] = None

        if query:
            ctx['search_results'] = self._search_students(request, query)

        if student_id:
            student = Student.objects.select_related(
                'user', 'current_class__level', 'current_class__program__department',
                'current_class__academic_year', 'partenaire_bourse',
            ).filter(pk=student_id).first()
            if student:
                ctx['selected_student'] = student
                ctx['current_year'] = AcademicYear.objects.filter(is_current=True).first()
                ctx['current_enrollment'] = (
                    student.enrollments
                    .filter(is_active=True)
                    .select_related('academic_year', 'class_group')
                    .order_by('-enrollment_date')
                    .first()
                )

        return render(request, self.template_name, ctx)

    def post(self, request):
        student_id = request.POST.get('student_id')
        class_id   = request.POST.get('class_group')
        year_id    = request.POST.get('academic_year')
        reason     = request.POST.get('reason', '').strip()

        student = get_object_or_404(Student, pk=student_id)
        try:
            new_class = Class.objects.get(pk=class_id)
            new_year  = AcademicYear.objects.get(pk=year_id)
        except (Class.DoesNotExist, AcademicYear.DoesNotExist):
            messages.error(request, "Classe ou année académique invalide.")
            return redirect('students:changement_filiere')

        old_class = student.current_class
        if old_class and old_class.program_id and new_class.program_id == old_class.program_id:
            messages.error(
                request,
                "La nouvelle classe doit appartenir à une filière différente de la filière actuelle. "
                "Pour rester dans la même filière, utilisez plutôt la réinscription."
            )
            return redirect(f"{reverse('students:changement_filiere')}?student_id={student.pk}")

        existing = Enrollment.objects.filter(
            student=student,
            academic_year=new_year,
            class_group=new_class,
        ).first()
        if existing:
            messages.warning(
                request,
                f"« {student.full_name} » est déjà inscrit(e) dans « {new_class.name} » "
                f"pour l'année {new_year.name} (statut : {existing.get_status_display()})."
            )
            return redirect('students:changement_filiere')

        # Inscription active actuelle (avant désactivation) — sert de base au
        # report du crédit déjà réglé dans l'ancienne filière.
        active_enrollment = student.enrollments.filter(is_active=True).order_by('-enrollment_date').first()

        # Désactiver l'ancien enrollment actif : l'étudiant disparaît de toutes
        # les listes de classe tant que le changement n'est pas validé.
        Enrollment.objects.filter(student=student, is_active=True).update(is_active=False)

        # Report automatique des frais déjà réglés dans l'ancienne filière
        # (montant d'inscription + mensualités déjà payées), même mécanisme que
        # pour une réinscription depuis une inscription suspendue.
        credit = active_enrollment.total_paid_amount if active_enrollment else 0

        enrollment = Enrollment.objects.create(
            student=student,
            class_group=new_class,
            academic_year=new_year,
            enrollment_type=Enrollment.TYPE_CHANGE_FILIERE,
            previous_class=old_class,
            status=Enrollment.STATUS_PENDING,
            is_active=False,
            credit_report=credit,
            notes=reason,
        )

        # Mettre à jour le département si la nouvelle filière en dépend un autre
        if new_class.program and new_class.program.department:
            student.user.__class__.objects.filter(pk=student.user.pk).update(
                department=new_class.program.department
            )

        request.session['changement_filiere_pk'] = enrollment.pk
        messages.success(
            request,
            f"Changement de filière de « {student.full_name} » vers « {new_class.name} » "
            f"({new_year.name}) créé en attente de validation par le trésorier général."
        )
        return redirect('students:changement_filiere_confirm')


@login_required
def changement_filiere_confirm(request):
    """Confirmation après création d'une demande de changement de filière : permet
    d'imprimer/télécharger la fiche à transmettre au trésorier général."""
    pk = request.session.pop('changement_filiere_pk', None)
    if not pk:
        return redirect('students:list')
    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__program__department', 'previous_class__program',
            'academic_year',
        ),
        pk=pk,
    )
    return render(request, 'students/changement_filiere_confirm.html', {'enrollment': enrollment})


@login_required
def fiche_changement_filiere_pdf(request, pk):
    """Génère la fiche de changement de filière PDF à transmettre au trésorier général."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from academic_core.pdf_utils import logo_image as _logo_img_fn, senegal_flag as _flag, get_institut_config_for_request as _gcfr, watermark_canvas
    _logo_img = lambda **kw: _logo_img_fn(config=_gcfr(request), **kw)  # noqa: E731
    from datetime import date as dt

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'student__partenaire_bourse',
            'class_group__program__department', 'class_group__level',
            'previous_class__program__department', 'previous_class__level', 'academic_year',
        ),
        pk=pk,
    )
    student = enrollment.student
    # Inscription quittée dans l'ancienne filière (désactivée lors de la création
    # de ce changement) : sert à afficher le récapitulatif financier au trésorier.
    old_enrollment = (
        student.enrollments
        .filter(class_group=enrollment.previous_class)
        .exclude(pk=enrollment.pk)
        .select_related('academic_year')
        .order_by('-enrollment_date')
        .first()
    ) if enrollment.previous_class_id else None

    if not (request.user.can_manage_dept() or request.user.is_admin()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=1*cm, bottomMargin=1*cm,
    )

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')

    ss = getSampleStyleSheet()
    sc = ParagraphStyle

    W = 17.4*cm  # largeur utile

    s_ctr  = sc('c',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl  = sc('t',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=13, fontName='Helvetica-Bold', textColor=navy, spaceAfter=0)
    s_sub  = sc('s',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=8, textColor=grey, spaceAfter=0)
    s_lbl  = sc('l',  parent=ss['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=navy)
    s_val  = sc('v',  parent=ss['Normal'], fontSize=8)
    s_sec  = sc('sec',parent=ss['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=colors.white)
    s_warn = sc('w',  parent=ss['Normal'], fontSize=8, textColor=colors.HexColor('#92400e'), alignment=TA_CENTER)
    s_sgn  = sc('sg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=8, fontName='Helvetica-Bold', textColor=navy)
    s_foot = sc('ft', parent=ss['Normal'], alignment=TA_CENTER, fontSize=6.5, textColor=grey)

    _flag_el = _flag(width=2*cm, height=1.3*cm)
    _logo_el = _logo_img(width=2*cm, height=1.3*cm) or Paragraph(
        'ISI', sc('lb', parent=s_ctr, fontSize=8, fontName='Helvetica-Bold', textColor=navy)
    )
    _hdr_tbl = Table(
        [[_flag_el,
          Paragraph(
            '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="7">Un Peuple — Un But — Une Foi</font>'
            '<br/><font size="11"><b>GROUPE ISI</b></font><br/>'
            "<font size='8'>Institut Supérieur d'Informatique</font>",
            sc('rh', parent=ss['Normal'], alignment=TA_CENTER, leading=12),
          ),
          _logo_el]],
        colWidths=[2.5*cm, 12.4*cm, 2.5*cm],
    )
    _hdr_tbl.setStyle(TableStyle([
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
    ]))

    def section_header(title):
        tbl = Table([[Paragraph(f"<b>{title}</b>", s_sec)]], colWidths=[W])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), navy),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ]))
        return tbl

    def info_table(rows, col1=5*cm):
        tbl = Table(rows, colWidths=[col1, W - col1])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (0, -1), light),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',     (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
            ('LEFTPADDING',    (0, 0), (-1, -1), 6),
        ]))
        return tbl

    old_class = enrollment.previous_class
    new_class = enrollment.class_group
    gender_display = 'Masculin' if student.gender == 'M' else ('Féminin' if student.gender == 'F' else '—')

    story = [
        _hdr_tbl,
        Spacer(1, .15*cm),
        HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=4),
        Paragraph("FICHE DE CHANGEMENT DE FILIÈRE", s_ttl),
        Paragraph("À transmettre au Trésorier Général pour validation", s_sub),
        Spacer(1, .15*cm),
        HRFlowable(width='40%', thickness=1, color=gold, hAlign='CENTER'),
        Spacer(1, .2*cm),

        Table(
            [[Paragraph(
                "<b>IMPORTANT :</b> Tant que le Trésorier Général n'a pas validé ce changement de filière, "
                "l'étudiant reste en attente et n'apparaît dans aucune classe.",
                s_warn
            )]],
            colWidths=[W],
            style=[
                ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#FEF3C7')),
                ('BOX',           (0, 0), (-1, -1), 1, colors.HexColor('#F59E0B')),
                ('TOPPADDING',    (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING',   (0, 0), (-1, -1), 8),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ]
        ),
        Spacer(1, .25*cm),

        # Section 1 — Informations personnelles
        section_header("1. Informations personnelles"),
        info_table([
            [Paragraph("<b>Matricule</b>", s_lbl),            Paragraph(student.matricule, s_val)],
            [Paragraph("<b>Nom &amp; Prénom(s)</b>", s_lbl),  Paragraph(student.full_name, s_val)],
            [Paragraph("<b>Date de naissance</b>", s_lbl),    Paragraph(student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '—', s_val)],
            [Paragraph("<b>Lieu de naissance</b>", s_lbl),    Paragraph(student.place_of_birth or '—', s_val)],
            [Paragraph("<b>Genre</b>", s_lbl),                Paragraph(gender_display, s_val)],
            [Paragraph("<b>Téléphone</b>", s_lbl),            Paragraph(student.phone or '—', s_val)],
            [Paragraph("<b>Adresse</b>", s_lbl),              Paragraph(student.address or '—', s_val)],
            [Paragraph("<b>Email</b>", s_lbl),                Paragraph(student.email or '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 2 — Informations sur la Bourse
        section_header("2. Informations sur la Bourse"),
        info_table([
            [Paragraph("<b>Boursier</b>", s_lbl), Paragraph("Oui" if student.is_boursier else "Non", s_val)],
            [Paragraph("<b>Partenaire de bourse</b>", s_lbl),
             Paragraph(str(student.partenaire_bourse) if student.is_boursier and student.partenaire_bourse else '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 3 — Personne à contacter
        section_header("3. Personne à contacter (Tuteur / Parent)"),
        info_table([
            [Paragraph("<b>Prénom &amp; Nom</b>", s_lbl),  Paragraph(f"{student.guardian_first_name} {student.guardian_last_name}".strip() or '—', s_val)],
            [Paragraph("<b>Téléphone</b>", s_lbl),          Paragraph(student.guardian_phone or '—', s_val)],
            [Paragraph("<b>Email</b>", s_lbl),              Paragraph(student.guardian_email or '—', s_val)],
            [Paragraph("<b>Adresse</b>", s_lbl),            Paragraph(student.guardian_address or '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 4 — Filière actuelle (avant changement) + situation financière
        section_header("4. Filière actuelle (avant changement)"),
        info_table([
            [Paragraph("<b>Classe</b>", s_lbl),       Paragraph(old_class.name if old_class else '—', s_val)],
            [Paragraph("<b>Filière</b>", s_lbl),       Paragraph(old_class.program.name if old_class and old_class.program else '—', s_val)],
            [Paragraph("<b>Département</b>", s_lbl),  Paragraph(old_class.program.department.name if old_class and old_class.program and old_class.program.department else '—', s_val)],
            [Paragraph("<b>Niveau</b>", s_lbl),        Paragraph(old_class.level.name if old_class and old_class.level else '—', s_val)],
            [Paragraph("<b>Année académique</b>", s_lbl), Paragraph(str(old_enrollment.academic_year) if old_enrollment else '—', s_val)],
            [Paragraph("<b>Statut inscription</b>", s_lbl), Paragraph(old_enrollment.get_status_display() if old_enrollment else '—', s_val)],
            [Paragraph("<b>Montant versé</b>", s_lbl), Paragraph(f"{old_enrollment.payment_amount:,.0f} FCFA".replace(',', ' ') if old_enrollment and old_enrollment.payment_amount else '—', s_val)],
            [Paragraph("<b>Référence paiement</b>", s_lbl), Paragraph(old_enrollment.payment_reference if old_enrollment and old_enrollment.payment_reference else '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 5 — Nouvelle filière demandée
        section_header("5. Nouvelle filière demandée"),
        info_table([
            [Paragraph("<b>Classe</b>", s_lbl),       Paragraph(new_class.name, s_val)],
            [Paragraph("<b>Filière</b>", s_lbl),       Paragraph(new_class.program.name if new_class.program else '—', s_val)],
            [Paragraph("<b>Département</b>", s_lbl),  Paragraph(new_class.program.department.name if new_class.program and new_class.program.department else '—', s_val)],
            [Paragraph("<b>Niveau</b>", s_lbl),        Paragraph(new_class.level.name if new_class.level else '—', s_val)],
            [Paragraph("<b>Année académique</b>", s_lbl), Paragraph(str(enrollment.academic_year), s_val)],
            [Paragraph("<b>Crédit reporté de l'ancienne filière</b>", s_lbl),
             Paragraph(f"{enrollment.credit_report:,.0f} FCFA".replace(',', ' ') if enrollment.credit_report else '0 FCFA', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 6 — Motif
        section_header("6. Motif du changement de filière"),
        info_table([
            [Paragraph("<b>Motif</b>", s_lbl), Paragraph(enrollment.notes or '—', s_val)],
        ]),
        Spacer(1, .2*cm),

        # Section 7 — Réservé au Trésorier Général
        section_header("7. Réservé au Trésorier Général"),
        Table(
            [
                [Paragraph("<b>Décision</b>", s_lbl), Paragraph('☐ Validé     ☐ Rejeté', s_val)],
                [Paragraph("<b>Date</b>", s_lbl),     Paragraph('', s_val)],
            ],
            colWidths=[4.5*cm, 12.9*cm],
            style=TableStyle([
                ('BACKGROUND',     (0, 0), (0, -1), light),
                ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
                ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',     (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING',  (0, 0), (-1, -1), 8),
                ('LEFTPADDING',    (0, 0), (-1, -1), 6),
            ])
        ),
        Spacer(1, .5*cm),

        # Signature
        Table(
            [[Paragraph("Dakar, le _____ / _____ / _______", sc('dl', parent=ss['Normal'], fontSize=8)),
              Paragraph("Signature &amp; Cachet du Trésorier Général", s_sgn)]],
            colWidths=[9*cm, 8.4*cm],
            style=[('VALIGN', (0, 0), (-1, -1), 'TOP')],
        ),
        Spacer(1, .6*cm),
        HRFlowable(width='100%', thickness=0.5, color=grey),
        Spacer(1, .1*cm),
        Paragraph(
            f"Fiche générée le {dt.today().strftime('%d/%m/%Y')}  —  Institut Supérieur d'Informatique - ISI  —  Dakar, Sénégal",
            s_foot
        ),
    ]

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="changement_filiere_{student.matricule}.pdf"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Carte étudiant PDF
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def student_card_pdf(request, pk):
    """Génère la carte d'étudiant au format PDF (format carte de crédit)."""
    student = get_object_or_404(Student.objects.select_related('user'), pk=pk)

    is_self = student.user_id == request.user.pk
    if not (is_self or request.user.can_manage_dept() or request.user.is_admin()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    enrollment = student.current_enrollment()
    if not enrollment or enrollment.status != Enrollment.STATUS_VALIDATED:
        messages.warning(request, "La carte n'est disponible qu'après validation de l'inscription par la comptabilité.")
        return redirect('students:detail', pk=pk)

    from .qr_utils import generate_student_card_pdf
    from academic_core.apps.academic_structure.models import InstitutConfig
    base_url = request.build_absolute_uri('/')[:-1]
    # Récupérer le logo ET les coordonnées de l'institut réel de l'étudiant
    # (jamais celles d'un autre institut) depuis sa config.
    inst_logo = None
    inst_config = None
    try:
        dept = getattr(enrollment.class_group.program, 'department', None)
        faculty = getattr(dept, 'faculty', None) if dept else None
        if faculty:
            inst_config = InstitutConfig.objects.using('default').filter(faculty=faculty).first()
            if inst_config and inst_config.logo:
                inst_logo = inst_config.logo.path
    except Exception:
        pass
    pdf_bytes = generate_student_card_pdf(student, enrollment, base_url, inst_logo=inst_logo, inst_config=inst_config)

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="carte_{student.matricule}.pdf"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Ma carte Présence — QR code personnel de l'étudiant
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def my_presence_card(request):
    """Page 'Ma carte Présence' — affiche le QR code personnel de l'étudiant
    contenant son matricule. L'enseignant scanne ce QR pour valider la présence."""
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, "Cette page est réservée aux étudiants.")
        return redirect('dashboard:index')

    enrollment = (
        student.enrollments.filter(is_active=True)
        .select_related('class_group', 'academic_year')
        .order_by('-academic_year__start_date')
        .first()
    )

    from .qr_utils import presence_card_payload, qr_image_to_base64
    payload = presence_card_payload(student)
    qr_b64  = qr_image_to_base64(payload, size_px=350)

    return render(request, 'students/my_presence_card.html', {
        'student':    student,
        'enrollment': enrollment,
        'qr_b64':     qr_b64,
    })


# Vérification du statut de paiement via QR étudiant
# ─────────────────────────────────────────────────────────────────────────────

def payment_status_check(request, student_pk):
    """
    Endpoint public (accessible par scan de QR code) affichant le statut de paiement
    mensuel de l'étudiant. Retourne une page HTML avec bande verte/rouge.
    """
    from django.utils import timezone
    from .models import PaymentInstallment

    student = get_object_or_404(Student.objects.select_related('user'), pk=student_pk)
    today = timezone.now().date()
    enrollment = student.current_enrollment()

    status_info = {
        'student': student,
        'enrollment': enrollment,
        'is_paid': False,
        'last_paid_label': None,
        'current_month': today.strftime('%B %Y'),
    }

    if enrollment:
        current_inst = enrollment.installments.filter(
            due_date__year=today.year,
            due_date__month=today.month,
        ).first()
        if current_inst and current_inst.is_paid:
            status_info['is_paid'] = True
        else:
            last_inst = enrollment.installments.filter(is_paid=True).order_by('-due_date').first()
            if last_inst:
                status_info['last_paid_label'] = last_inst.due_date.strftime('%B %Y')

    return render(request, 'students/payment_status.html', status_info)


# Photo update view
@login_required
def update_student_photo(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if not (request.user.can_manage_dept() or request.user.is_admin()):
        messages.error(request, 'Accès refusé.')
        return redirect('students:detail', pk=pk)
    if request.method != 'POST':
        return redirect('students:detail', pk=pk)
    photo_file = request.FILES.get('photo') or _webcam_b64_to_file(request.POST.get('photo_webcam', ''), student.matricule)
    if photo_file:
        if student.photo:
            try:
                student.photo.delete(save=False)
            except Exception:
                pass
        student.photo.save(photo_file.name, photo_file, save=True)
        messages.success(request, 'Photo mise a jour avec succes.')
    else:
        messages.warning(request, 'Aucune photo recue.')
    return redirect('students:detail', pk=pk)


# ── Contrôle DAF : scanner les cartes étudiantes ─────────────────────────────

_CONTROLE_ROLES = (
    'ADMIN', 'INST_ADMIN', 'SI_ADMIN', 'ASSISTANTE_DG',
    'ADMIN_DIRECTION', 'ADMIN_DE', 'ADMIN_DAF', 'ADMIN_COM', 'ADMIN_RH',
    'ASSISTANTE_DIRECTION', 'ASSISTANTE_DE',
    'CONTROLEUR', 'CIAQ',
    'COMPTABLE', 'TRESORIER_GENERAL', 'CAISSIER',
    'CONTROLE_ACCUEIL',
)


@login_required
def controle_scan(request):
    """
    Contrôle Accueil : affiche automatiquement le QR Code du jour — chaque
    étudiant ou membre du personnel le scanne avec SON PROPRE téléphone
    (page hr:ma_carte_pointage) pour se pointer lui-même, sans intervention
    de l'agent d'accueil. Même principe que le QR de séance affiché par
    l'enseignant, et même jeton/QR que hr:accueil_qr_display (un seul QR sert
    les deux publics — hr:accueil_self_checkin branche selon le rôle).
    La Saisie manuelle (recherche par matricule/nom, contrôle_scan_lookup)
    reste disponible en secours pour les personnes sans téléphone.
    """
    if not (request.user.role and request.user.role.name in _CONTROLE_ROLES):
        messages.error(request, "Accès refusé : permissions insuffisantes.")
        return redirect('dashboard:index')

    import qrcode, base64, io
    from django.utils import timezone as _tz
    from academic_core.apps.hr.checkin_views import daily_accueil_token
    from academic_core.apps.attendance.views import _get_accessible_base_url

    token       = daily_accueil_token()
    base_url    = _get_accessible_base_url(request)
    checkin_url = f"{base_url.rstrip('/')}/hr/pointer-auth/{token}/"

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H,
                        box_size=8, border=2)
    qr.add_data(checkin_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#0d2244', back_color='#ffffff')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return render(request, 'students/controle_scan.html', {
        'qr_b64':      qr_b64,
        'checkin_url': checkin_url,
        'today':       _tz.localdate(),
    })


@login_required
def controle_scan_poll(request):
    """
    Polling léger de l'écran d'accueil (voir controle_scan ci-dessus) : renvoie
    le dernier résultat de pointage self-service (étudiant ou personnel),
    peu importe qui a scanné — le QR affiché est unique pour la journée/
    institut, donc tout scan récent est pertinent pour l'écran affiché.
    `after` (optionnel) : id du dernier évènement déjà affiché côté client,
    pour ne renvoyer un évènement que s'il est plus récent.
    """
    if not (request.user.role and request.user.role.name in _CONTROLE_ROLES):
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    from academic_core.apps.hr.models import AccueilScanEvent

    after_id = request.GET.get('after', '0')
    try:
        after_id = int(after_id)
    except (TypeError, ValueError):
        after_id = 0

    event = AccueilScanEvent.objects.order_by('-pk').first()
    if not event or event.pk <= after_id:
        return JsonResponse({'ok': True, 'event': None})

    return JsonResponse({
        'ok': True,
        'event': {
            'id':   event.pk,
            'type': event.scan_type,
            'data': event.payload,
            'scanned_at': timezone.localtime(event.created_at).strftime('%H:%M:%S'),
        },
    })


@login_required
@require_http_methods(["POST"])
def controle_scan_lookup(request):
    """
    AJAX endpoint pour le contrôle DAF.
    Body JSON: {"qr_data": "..."} ou {"matricule": "..."}
    Retourne JSON avec infos étudiant + statut de paiement du mois courant.
    """
    if not (request.user.role and request.user.role.name in _CONTROLE_ROLES):
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Corps JSON invalide'}, status=400)

    student = None
    qr_data = body.get('qr_data', '').strip()
    matricule_input = body.get('matricule', '').strip()

    if qr_data:
        # Essayer de parser le payload JSON du QR
        try:
            payload = json.loads(qr_data)
            if payload.get('type') in ('student', 'presence'):
                student_id = payload.get('id')
                mat = payload.get('mat', '')
                if student_id:
                    student = Student.objects.select_related('user', 'current_class').filter(pk=student_id).first()
                if not student and mat:
                    student = Student.objects.select_related('user', 'current_class').filter(matricule=mat).first()
        except (json.JSONDecodeError, ValueError):
            # QR non-JSON : traiter comme matricule brut
            student = Student.objects.select_related('user', 'current_class').filter(matricule=qr_data).first()
    elif matricule_input:
        student = Student.objects.select_related('user', 'current_class').filter(
            Q(matricule__iexact=matricule_input) |
            Q(user__first_name__icontains=matricule_input) |
            Q(user__last_name__icontains=matricule_input)
        ).first()

    if not student:
        # ── Chercher un membre du personnel (non-étudiant, non-vacataire) ──
        # Résolution + pointage (arrivée/départ) délégués à hr.services pour
        # rester cohérents avec accueil_staff_lookup et pointage_self_checkin
        # (reconnaît aussi l'URL /hr/pointer/<token>/ encodée sur la carte).
        from academic_core.apps.hr.services import resolve_and_checkin_staff

        raw = qr_data or matricule_input
        result = resolve_and_checkin_staff(raw, actor=request.user)

        if not result['found']:
            return JsonResponse({'found': False, 'message': result['message'] or 'Aucune personne trouvée avec cette référence.'})

        staff_user = result['staff_user']
        presence   = result['presence']

        avatar_url = None
        if staff_user.avatar:
            try:
                avatar_url = staff_user.avatar.url
            except Exception:
                pass

        return JsonResponse({
            'found': True,
            'type': 'staff',
            'staff': {
                'nom': staff_user.get_full_name(),
                'role': staff_user.role.get_name_display() if staff_user.role else '—',
                'email': staff_user.email,
                'avatar': avatar_url,
            },
            'presence': {
                'action': result['action'],
                'nouvelle': result['created'],
                'statut': presence.statut,
                'statut_label': presence.get_statut_display(),
                'statut_color': presence.statut_color,
                'heure_arrivee': presence.heure_arrivee.strftime('%H:%M') if presence.heure_arrivee else None,
                'heure_depart': presence.heure_depart.strftime('%H:%M') if presence.heure_depart else None,
                'date': presence.date.strftime('%d/%m/%Y'),
            },
        })

    from .services import build_student_card_status
    card = build_student_card_status(student)
    return JsonResponse({'found': True, 'type': 'student', **card})


# ─────────────────────────────────────────────────────────────────────────────
# Dossier complet étudiant (parcours de la première à la dernière inscription)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def dossier_etudiant(request, pk):
    """
    Vue consolidée du parcours académique complet d'un étudiant :
    - Toutes les inscriptions (chronologiques)
    - Bulletins / moyennes semestrielles par année
    - Taux de présence par semestre
    - Paiements (caisse + échéanciers)
    """
    student = get_object_or_404(
        Student.objects.select_related('user', 'current_class', 'partenaire_bourse'),
        pk=pk,
    )

    from academic_core.apps.grades.models import Bulletin, SemesterAverage
    from academic_core.apps.attendance.models import StudentAttendance
    from academic_core.apps.accounting.models import CaissePayment

    # ── Toutes les inscriptions triées de la plus ancienne à la plus récente ──
    enrollments = (
        student.enrollments
        .select_related('class_group', 'academic_year', 'class_group__program',
                        'class_group__program__department', 'validated_by')
        .prefetch_related('installments')
        .order_by('academic_year__start_date', 'enrollment_date')
    )

    # ── Bulletins groupés par inscription (via académique year + class_group) ──
    bulletins = (
        Bulletin.objects
        .filter(student=student)
        .select_related('semester', 'semester__academic_year', 'class_group')
        .prefetch_related('ue_results__ec_results')
        .order_by('semester__academic_year__start_date', 'semester__number')
    )
    bulletins_by_year = {}
    for b in bulletins:
        year_pk = b.semester.academic_year_id
        bulletins_by_year.setdefault(year_pk, []).append(b)

    # ── Moyennes semestrielles ──
    sem_averages = (
        SemesterAverage.objects
        .filter(student=student)
        .select_related('semester', 'semester__academic_year')
        .order_by('semester__academic_year__start_date', 'semester__number')
    )
    sem_avg_by_year = {}
    for sa in sem_averages:
        sem_avg_by_year.setdefault(sa.semester.academic_year_id, []).append(sa)

    # ── Présences par semestre ──
    attendances = (
        StudentAttendance.objects
        .filter(student=student)
        .select_related(
            'attendance_sheet__timetable_entry__semester',
            'attendance_sheet__timetable_entry__semester__academic_year',
        )
        .values(
            'status',
            'attendance_sheet__timetable_entry__semester__id',
            'attendance_sheet__timetable_entry__semester__number',
            'attendance_sheet__timetable_entry__semester__academic_year__id',
        )
    )
    # Agréger : total séances + absences par (année, semestre)
    presence_stats = {}  # {(year_id, sem_id): {'total': n, 'absent': n, 'sem_number': n}}
    for a in attendances:
        year_id = a['attendance_sheet__timetable_entry__semester__academic_year__id']
        sem_id  = a['attendance_sheet__timetable_entry__semester__id']
        sem_num = a['attendance_sheet__timetable_entry__semester__number']
        if year_id is None or sem_id is None:
            continue
        key = (year_id, sem_id)
        if key not in presence_stats:
            presence_stats[key] = {'total': 0, 'absent': 0, 'sem_number': sem_num}
        presence_stats[key]['total'] += 1
        if a['status'] in ('ABSENT', 'A'):
            presence_stats[key]['absent'] += 1

    # Regrouper présences par année
    presence_by_year = {}
    for (year_id, sem_id), stats in presence_stats.items():
        total = stats['total']
        absent = stats['absent']
        taux = round((total - absent) / total * 100, 1) if total else None
        presence_by_year.setdefault(year_id, []).append({
            'sem_id': sem_id,
            'sem_number': stats['sem_number'],
            'total': total,
            'absent': absent,
            'present': total - absent,
            'taux': taux,
        })
    for year_id in presence_by_year:
        presence_by_year[year_id].sort(key=lambda x: x['sem_number'])

    # ── Paiements caisse ──
    caisse_payments = (
        CaissePayment.objects
        .filter(student=student)
        .select_related('academic_year', 'enrollment')
        .order_by('academic_year__start_date', 'payment_date')
    )
    payments_by_year = {}
    for cp in caisse_payments:
        year_pk = cp.academic_year_id if cp.academic_year_id else 0
        payments_by_year.setdefault(year_pk, []).append(cp)

    # ── Construire la timeline par inscription ──
    timeline = []
    for enr in enrollments:
        year_pk = enr.academic_year_id
        timeline.append({
            'enrollment': enr,
            'bulletins': bulletins_by_year.get(year_pk, []),
            'sem_averages': sem_avg_by_year.get(year_pk, []),
            'presences': presence_by_year.get(year_pk, []),
            'payments': payments_by_year.get(year_pk, []),
        })

    # Totaux globaux
    total_years = len(timeline)
    total_paid_global = sum(
        cp.amount for cps in payments_by_year.values() for cp in cps
    )

    # Accès aux différents documents/reçus — répliqués exactement des vues
    # cibles (accounting.views) pour n'afficher un lien que si la personne
    # connectée pourra effectivement l'ouvrir (pas de clic vers un refus/404).
    user = request.user
    can_carte = user.can_manage_dept() or user.is_admin()
    can_inscription_docs = user.is_admin() or user.is_responsable()
    can_reussite = user.is_admin() or user.is_responsable() or user.is_comptable()
    can_recu = (
        user.is_admin() or user.is_controleur() or user.is_comptable()
        or getattr(user, 'role_name', '') in ('ASSISTANTE', 'RESPONSABLE', 'CIAQ')
    )
    can_mensualite_recu = user.is_admin() or user.is_responsable()

    return render(request, 'students/dossier.html', {
        'student': student,
        'timeline': timeline,
        'total_years': total_years,
        'total_paid_global': total_paid_global,
        'can_carte': can_carte,
        'can_inscription_docs': can_inscription_docs,
        'can_reussite': can_reussite,
        'can_recu': can_recu,
        'can_mensualite_recu': can_mensualite_recu,
    })


# ─── Vue : Dossiers étudiants (filtre classe uniquement) ─────────────────────

@login_required
def dossier_list_by_class(request):
    """Liste des étudiants filtrée par classe uniquement, avec lien vers leur dossier complet."""
    user    = request.user
    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    classes_qs = Class.objects.select_related('program__department', 'level').order_by('name')
    if dept:
        classes_qs = classes_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)

    # Année académique : par défaut l'année en cours — "Toutes les années"
    # (year=all) reste disponible pour consulter l'historique.
    from academic_core.apps.academic_structure.models import AcademicYear
    fac_for_years = faculty or (dept.faculty if dept else None)
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=fac_for_years) if fac_for_years else academic_years
    year_param = request.GET.get('year', '')
    if year_param == 'all':
        pass
    elif year_param:
        classes_qs = classes_qs.filter(academic_year_id=year_param)
    else:
        current_year = academic_years.filter(is_current=True).first()
        if current_year:
            classes_qs = classes_qs.filter(academic_year=current_year)

    class_id = request.GET.get('class_id')
    selected_class = None
    students = []

    if class_id:
        selected_class = classes_qs.filter(pk=class_id).first()
        if selected_class:
            students = (
                Student.objects
                .filter(enrollments__class_group=selected_class)
                .select_related('user', 'current_class')
                .distinct()
                .order_by('user__last_name', 'user__first_name')
            )

    return render(request, 'students/dossier_list.html', {
        'all_classes':    classes_qs,
        'academic_years': academic_years,
        'selected_class': selected_class,
        'class_id':       class_id or '',
        'year_param':     year_param,
        'students':       students,
    })
