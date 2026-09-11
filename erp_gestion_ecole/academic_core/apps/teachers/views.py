import random
import string

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView, View
from django.urls import reverse_lazy
from django.db.models import Q
from .models import Teacher, Grade, ContratEnseignant
from .forms import TeacherForm, TeacherUserForm, TeacherCivilInfoForm, ContratEnseignantForm
from academic_core.apps.accounts.models import User, Role

# Préfixe distinctif des matricules générés au nouveau format — sert à repérer
# les enseignants déjà migrés lors de la régénération en masse (idempotence).
TEACHER_MATRICULE_PREFIX = 'Ens_'


def _generate_teacher_matricule(db_alias=None, max_tries=20):
    """
    Génère un matricule enseignant unique au format :
      Ens_{YY}_{4 chiffres aléatoires}/{sigle institut}
    YY = 2 derniers chiffres de l'année académique en cours de l'institut.
    """
    from academic_core.db_router import get_current_db
    from academic_core.apps.academic_structure.models import AcademicYear, InstitutConfig

    alias = db_alias or get_current_db() or 'default'

    sigle = ''
    try:
        cfg = InstitutConfig.objects.using('default').filter(db_alias=alias).first()
        sigle = (cfg.sigle or '').strip() if cfg else ''
    except Exception:
        pass
    suffix = f'/{sigle}' if sigle else ''

    year = (
        AcademicYear.objects.using(alias).filter(is_current=True).order_by('-start_date').first()
        or AcademicYear.objects.using(alias).order_by('-start_date').first()
    )
    year_digits = '00'
    if year:
        end = getattr(year, 'end_date', None) or getattr(year, 'start_date', None)
        if end:
            year_digits = str(end.year)[-2:]

    for _ in range(max_tries):
        rand4 = ''.join(random.choices(string.digits, k=4))
        candidate = f'{TEACHER_MATRICULE_PREFIX}{year_digits}_{rand4}{suffix}'
        if not Teacher.objects.using(alias).filter(matricule=candidate).exists():
            return candidate
    rand6 = ''.join(random.choices(string.digits, k=6))
    return f'{TEACHER_MATRICULE_PREFIX}{year_digits}_{rand6}{suffix}'


class _AdminResponsableMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_manage_dept()


# ── Grades des enseignants ────────────────────────────────────────────────────
class GradeListView(_AdminResponsableMixin, ListView):
    model = Grade
    template_name = 'teachers/grades.html'
    context_object_name = 'grades'

    def get_queryset(self):
        return Grade.objects.prefetch_related('teachers').order_by('order', 'code')

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'create':
            code  = request.POST.get('code', '').strip().upper()
            label = request.POST.get('label', '').strip()
            order = request.POST.get('order', 1)
            if not code or not label:
                messages.error(request, "Code et libellé sont obligatoires.")
            elif Grade.objects.filter(code=code).exists():
                messages.error(request, f"Le code « {code} » existe déjà.")
            else:
                Grade.objects.create(code=code, label=label, order=int(order))
                messages.success(request, f"Grade « {label} » créé.")
        elif action == 'edit':
            g = get_object_or_404(Grade, pk=request.POST.get('pk'))
            g.code  = request.POST.get('code', g.code).strip().upper()
            g.label = request.POST.get('label', g.label).strip()
            g.order = int(request.POST.get('order', g.order))
            g.save()
            messages.success(request, f"Grade « {g.label} » modifié.")
        elif action == 'delete':
            g = get_object_or_404(Grade, pk=request.POST.get('pk'))
            if g.teachers.exists():
                messages.error(request, f"Impossible de supprimer « {g.label} » : des enseignants y sont rattachés.")
            else:
                label = g.label
                g.delete()
                messages.success(request, f"Grade « {label} » supprimé.")
        return redirect('teachers:grades')


# ── Enseignants ───────────────────────────────────────────────────────────────
class TeacherListView(_AdminResponsableMixin, ListView):
    model = Teacher
    template_name = 'teachers/list.html'
    context_object_name = 'teachers'
    paginate_by = 25

    def get_queryset(self):
        from django.db.models import Q
        qs = Teacher.objects.select_related('user', 'grade', 'user__department').order_by('user__last_name')
        dept     = getattr(self.request, 'active_department', None)
        faculty  = getattr(self.request, 'active_faculty', None)
        is_super = self.request.user.is_super_admin()

        # Le Chef de Département (RESPONSABLE) et son Assistante ont les mêmes
        # droits sur tout l'institut, pas seulement sur leur département
        # d'affectation : ils doivent voir les enseignants de tous les
        # départements pour pouvoir leur affecter des modules cross-département.
        if dept and not self.request.user.is_responsable():
            qs = qs.filter(user__department=dept)
        elif faculty:
            # Pas de filtre supplémentaire par faculté : Teacher est routé par
            # tenant, donc `qs` est déjà scopé à la bonne base par le routeur
            # DB (activé via `active_faculty` dans le middleware). Filtrer en
            # plus par `user__department__faculty` exclurait à tort tout
            # enseignant sans département assigné (INNER JOIN sur une valeur
            # NULL ne matche jamais).
            pass
        else:
            qs = qs.none()

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(matricule__icontains=q) |
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q) |
                Q(specialty__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['dept_required'] = (
            not self.request.user.is_super_admin() and
            not getattr(self.request, 'active_department', None) and
            not getattr(self.request, 'active_faculty', None)
        )
        from academic_core.apps.academic_structure.models import Department
        faculty = getattr(self.request, 'active_faculty', None)
        dept_qs = Department.objects.filter(is_active=True).order_by('name')
        ctx['dept_qs'] = dept_qs.filter(faculty=faculty) if faculty else dept_qs
        return ctx


class TeacherAssignDepartmentHeadView(_AdminResponsableMixin, View):
    """
    Nomme un enseignant existant chef de département (RESPONSABLE) et
    l'assigne à ce département — action rapide depuis la liste des
    enseignants, pour ne pas avoir à recréer un compte (qui buterait sur un
    email déjà utilisé) juste pour le promouvoir.
    """

    def post(self, request, pk):
        from academic_core.apps.academic_structure.models import Department
        from academic_core.apps.academic_structure.services import assign_department_head

        teacher = get_object_or_404(Teacher.objects.select_related('user'), pk=pk)
        department = get_object_or_404(Department, pk=request.POST.get('department_id'))

        faculty = getattr(request, 'active_faculty', None)
        if faculty and department.faculty_id != faculty.pk and not request.user.is_super_admin():
            messages.error(request, "Ce département n'appartient pas à votre institut.")
            return redirect('teachers:list')

        assign_department_head(department, teacher.user)
        messages.success(
            request,
            f"{teacher.full_name} est désormais Chef de Département de « {department.name} »."
        )
        return redirect('teachers:list')


class TeacherDetailView(LoginRequiredMixin, DetailView):
    model = Teacher
    template_name = 'teachers/detail.html'
    context_object_name = 'teacher'


def _activate_institut_db(institut_config):
    """
    Active la base de données de l'institut sélectionné dans le thread courant.
    Retourne l'alias utilisé, ou 'default' si aucun alias n'est trouvé.
    """
    from academic_core.db_router import set_current_db, get_current_db
    if not institut_config:
        return get_current_db()
    alias = getattr(institut_config, 'db_alias', '') or ''
    if not alias:
        set_current_db('default')
        return 'default'
    from academic_core.tenant_databases import register_tenant_db
    alias = register_tenant_db(alias)
    if not alias:
        set_current_db('default')
        return 'default'
    set_current_db(alias)
    return alias


def _get_current_db():
    from academic_core.db_router import get_current_db
    return get_current_db()


@login_required
def ajax_generate_teacher_matricule(request):
    """
    AJAX GET — génère un matricule enseignant unique et le retourne en JSON.
    Param optionnel : institut_id (pk d'InstitutConfig) — utile depuis le
    formulaire de création, où l'institut cible peut être choisi avant
    l'enregistrement (l'unicité est vérifiée dans la base de CET institut).
    """
    institut_id = request.GET.get('institut_id')
    db_alias = None
    if institut_id:
        from academic_core.apps.academic_structure.models import InstitutConfig
        cfg = InstitutConfig.objects.using('default').filter(pk=institut_id).first()
        if cfg:
            db_alias = _activate_institut_db(cfg)
    matricule = _generate_teacher_matricule(db_alias)
    return JsonResponse({'matricule': matricule})


@login_required
def regenerate_all_teacher_matricules(request):
    """
    Régénère le matricule (nouveau format Ens_YY_NNNN/SIGLE) de tous les
    enseignants de l'institut courant qui n'en ont pas déjà un dans ce format
    — action groupée, idempotente (relancer ne rechange pas ceux déjà migrés).
    """
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé à la direction pédagogique.")
        return redirect('teachers:list')
    if request.method != 'POST':
        return redirect('teachers:list')

    to_update = Teacher.objects.exclude(matricule__startswith=TEACHER_MATRICULE_PREFIX)
    count = 0
    for t in to_update:
        t.matricule = _generate_teacher_matricule()
        t.save(update_fields=['matricule'])
        count += 1

    if count:
        messages.success(request, f"{count} matricule(s) enseignant(s) régénéré(s) au nouveau format.")
    else:
        messages.info(request, "Tous les enseignants ont déjà un matricule au nouveau format.")
    return redirect('teachers:list')


class TeacherCreateView(_AdminResponsableMixin, View):
    template_name = 'teachers/form.html'

    def get(self, request, *args, **kwargs):
        form = TeacherUserForm(requester=request.user)
        return render(request, self.template_name, {
            'form': form,
            'is_create': True,
        })

    def post(self, request, *args, **kwargs):
        form = TeacherUserForm(request.POST, requester=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_create': True})

        cd = form.cleaned_data

        # ── Activer la base de l'institut choisi ──────────────────────────
        target_cfg = cd.get('target_institut')
        db_alias   = _activate_institut_db(target_cfg)

        try:
            role = Role.objects.using(db_alias).get(name=Role.ENSEIGNANT)
        except Role.DoesNotExist:
            # Fallback : chercher dans default
            try:
                role = Role.objects.get(name=Role.ENSEIGNANT)
            except Role.DoesNotExist:
                messages.error(request, "Le rôle ENSEIGNANT n'existe pas. Vérifiez la base de données.")
                return render(request, self.template_name, {'form': form, 'is_create': True})

        plain_password = cd['password']
        dept = cd.get('department') or getattr(request, 'active_department', None)

        user = User.objects.using(db_alias).create(
            first_name=cd['first_name'],
            last_name=cd['last_name'],
            email=cd['email'],
            phone=cd['phone'],
            username=cd['username'],
            password=make_password(plain_password),
            role=role,
            department=dept,
            must_change_password=True,
        )
        Teacher.objects.using(db_alias).create(
            user=user,
            matricule=cd['matricule'],
            grade=cd.get('grade'),
            specialty=cd['specialty'],
            statut=cd['statut'],
            contractual_hours=cd['contractual_hours'],
            hire_date=cd.get('hire_date'),
            bio=cd.get('bio', ''),
        )
        request.session['created_credentials'] = {
            'type':      'enseignant',
            'full_name': user.get_full_name(),
            'username':  cd['username'],
            'password':  plain_password,
            'institut':  getattr(target_cfg, 'nom', ''),
        }
        return redirect('teachers:credentials_created')


class TeacherCredentialsView(_AdminResponsableMixin, View):
    """Affiche les identifiants générés juste après la création d'un enseignant."""
    def get(self, request, *args, **kwargs):
        creds = request.session.pop('created_credentials', None)
        if not creds:
            return redirect('teachers:list')
        return render(request, 'teachers/credentials_created.html', {'creds': creds})


class TeacherUpdateView(_AdminResponsableMixin, View):
    template_name = 'teachers/form.html'

    def _user_initial(self, teacher):
        u = teacher.user
        return {
            'first_name': u.first_name,
            'last_name':  u.last_name,
            'email':      u.email,
            'phone':      u.phone,
            'username':   u.username,
            'department': u.department_id,
        }

    def get(self, request, pk):
        teacher = get_object_or_404(Teacher, pk=pk)
        form = TeacherForm(instance=teacher, initial=self._user_initial(teacher))
        return render(request, self.template_name, {'form': form, 'is_create': False, 'teacher': teacher})

    def post(self, request, pk):
        teacher = get_object_or_404(Teacher, pk=pk)
        form = TeacherForm(request.POST, instance=teacher)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'is_create': False, 'teacher': teacher})

        form.save()

        # Sauvegarder les champs utilisateur (identité + identifiant de connexion)
        cd = form.cleaned_data
        u = teacher.user
        u.first_name = cd['first_name']
        u.last_name  = cd['last_name']
        u.email      = cd['email']
        u.phone      = cd['phone']
        u.username   = cd['username']
        u.department = cd.get('department')
        u.save(update_fields=['first_name', 'last_name', 'email', 'phone', 'username', 'department'])

        # Réinitialisation du mot de passe (optionnelle) — sauvegarde séparée
        # (voir StudentUpdateView.post pour l'explication de la synchro mot
        # de passe vers la copie 'default').
        new_pwd = cd.get('new_password', '')
        if new_pwd:
            u.set_password(new_pwd)
            u.must_change_password = True
            u.save(update_fields=['password', 'must_change_password'])

        messages.success(request, f"Les informations de « {teacher.full_name} » ont été mises à jour avec succès.")
        return redirect('teachers:list')


class TeacherDeleteView(_AdminResponsableMixin, DeleteView):
    model = Teacher
    template_name = 'teachers/confirm_delete.html'
    success_url = reverse_lazy('teachers:list')

    def delete(self, request, *args, **kwargs):
        teacher = self.get_object()
        messages.success(request, f"Enseignant « {teacher.full_name} » supprimé.")
        return super().delete(request, *args, **kwargs)


@login_required
def my_honoraires(request):
    """Tableau de bord honoraires de l enseignant connecte."""
    from django.utils import timezone
    from decimal import Decimal
    from collections import defaultdict
    from academic_core.apps.accounting.models import TeacherHonoraire

    teacher = getattr(request.user, 'teacher_profile', None)
    if not teacher:
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    # Backfill : créer les honoraires manquants pour les feuilles déjà validées
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.accounting.services import record_honoraire
    for sheet in AttendanceSheet.objects.filter(
        timetable_entry__teacher=teacher, status='VALIDATED'
    ).select_related('timetable_entry__class_group__level',
                     'timetable_entry__semester__academic_year'):
        try:
            _ = sheet.honoraire
        except Exception:
            record_honoraire(sheet, validated_by=sheet.validated_by)

    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))

    # Honoraires du mois sélectionné — tous départements confondus
    month_qs = TeacherHonoraire.objects.filter(
        teacher=teacher,
        session_date__year=year,
        session_date__month=month,
    ).select_related('department', 'academic_year', 'attendance_sheet__timetable_entry__subject',
                     'attendance_sheet__timetable_entry__class_group').order_by('session_date')

    # Regroupement par département
    by_dept = defaultdict(lambda: {'rows': [], 'subtotal': Decimal(0), 'subtotal_impots': Decimal(0), 'subtotal_net': Decimal(0)})
    total_month = Decimal(0)
    total_impots = Decimal(0)
    total_net    = Decimal(0)
    for h in month_qs:
        key = h.department.name
        by_dept[key]['dept'] = h.department
        by_dept[key]['rows'].append(h)
        by_dept[key]['subtotal']        += h.amount
        by_dept[key]['subtotal_impots'] += h.impots
        by_dept[key]['subtotal_net']    += h.net_a_payer
        total_month  += h.amount
        total_impots += h.impots
        total_net    += h.net_a_payer

    # Historique mensuel (12 derniers mois)
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth
    history = (
        TeacherHonoraire.objects
        .filter(teacher=teacher)
        .annotate(month=TruncMonth('session_date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('-month')[:12]
    )

    months_fr = {
        1: 'Janvier', 2: 'Février', 3: 'Mars', 4: 'Avril',
        5: 'Mai', 6: 'Juin', 7: 'Juillet', 8: 'Août',
        9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre',
    }
    months = [(i, months_fr[i]) for i in range(1, 13)]

    return render(request, 'teachers/my_honoraires.html', {
        'teacher':      teacher,
        'by_dept':      dict(by_dept),
        'total_month':  total_month,
        'total_impots': total_impots,
        'total_net':    total_net,
        'history':      history,
        'year':         year,
        'month':        month,
        'month_name':   months_fr.get(month, ''),
        'months':       months,
        'years':        range(today.year - 3, today.year + 2),
    })


# ── Contrats enseignants ──────────────────────────────────────────────────────

@login_required
def contrat_list(request):
    """Liste des contrats enseignants, groupés par département (Direction Pédagogique)."""
    from collections import defaultdict

    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé à la direction pédagogique.")
        return redirect('dashboard:index')

    contrats = (
        ContratEnseignant.objects
        .select_related('teacher__user', 'department', 'academic_year')
        .order_by('department__name', 'teacher__user__last_name')
    )

    by_dept = defaultdict(list)
    for c in contrats:
        by_dept[c.department.name].append(c)

    return render(request, 'teachers/contrat_list.html', {
        'by_dept': dict(by_dept),
    })


@login_required
def contrat_modele(request):
    """
    Modèle de contrat (texte modifiable par institut) : titre, introduction de
    l'Article 1, paragraphe "cahier de charge", et articles numérotés (2 à N).
    Le PDF généré (contrat_pdf) lit ce texte en direct — voir teachers/pdf_contrat.py.
    """
    from academic_core.apps.academic_structure.models import (
        InstitutConfig, ContratArticle, seed_default_contrat_articles,
    )

    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé à la direction pédagogique.")
        return redirect('dashboard:index')

    faculty = getattr(request, 'active_faculty', None)
    if not faculty:
        messages.error(request, "Aucun institut actif.")
        return redirect('teachers:contrat_list')

    config = get_object_or_404(InstitutConfig.objects.using('default'), faculty=faculty)
    seed_default_contrat_articles(config)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_intro':
            config.contrat_titre = request.POST.get('contrat_titre', '').strip() or config.contrat_titre
            config.contrat_article1_texte = request.POST.get('contrat_article1_texte', '').strip()
            config.contrat_cahier_charge_texte = request.POST.get('contrat_cahier_charge_texte', '').strip()
            config.updated_by = request.user
            config.save(update_fields=[
                'contrat_titre', 'contrat_article1_texte', 'contrat_cahier_charge_texte', 'updated_by',
            ])
            messages.success(request, "Texte d'introduction du contrat mis à jour.")

        elif action == 'save_article':
            article = get_object_or_404(
                ContratArticle.objects.using('default'), pk=request.POST.get('article_id'), config=config,
            )
            texte = request.POST.get('texte', '').strip()
            if texte:
                article.texte = texte
                article.save(update_fields=['texte'])
                messages.success(request, f"Article {article.numero} mis à jour.")
            else:
                messages.error(request, "Le texte de l'article ne peut pas être vide.")

        elif action == 'toggle_article':
            article = get_object_or_404(
                ContratArticle.objects.using('default'), pk=request.POST.get('article_id'), config=config,
            )
            article.actif = not article.actif
            article.save(update_fields=['actif'])
            messages.success(request, f"Article {article.numero} {'réactivé' if article.actif else 'désactivé'}.")

        elif action == 'delete_article':
            article = get_object_or_404(
                ContratArticle.objects.using('default'), pk=request.POST.get('article_id'), config=config,
            )
            numero = article.numero
            article.delete()
            messages.success(request, f"Article {numero} supprimé.")

        elif action == 'add_article':
            numero_raw = request.POST.get('numero', '').strip()
            texte = request.POST.get('texte', '').strip()
            if not numero_raw.isdigit() or not texte:
                messages.error(request, "Numéro et texte requis pour ajouter un article.")
            elif ContratArticle.objects.using('default').filter(config=config, numero=numero_raw).exists():
                messages.error(request, f"Un article numéro {numero_raw} existe déjà.")
            else:
                ContratArticle.objects.using('default').create(config=config, numero=int(numero_raw), texte=texte)
                messages.success(request, f"Article {numero_raw} ajouté.")

        return redirect('teachers:contrat_modele')

    return render(request, 'teachers/contrat_modele.html', {
        'config': config,
        'articles': config.contrat_articles.order_by('numero'),
        'next_numero': (config.contrat_articles.order_by('-numero').values_list('numero', flat=True).first() or 1) + 1,
    })


@login_required
def contrat_edit(request, pk):
    """Formulaire modifiable : informations civiles de l'enseignant + signature du contrat."""
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé à la direction pédagogique.")
        return redirect('dashboard:index')

    contrat = get_object_or_404(
        ContratEnseignant.objects.select_related('teacher__user', 'department', 'academic_year'), pk=pk,
    )

    if request.method == 'POST':
        civil_form = TeacherCivilInfoForm(request.POST, instance=contrat.teacher)
        contrat_form = ContratEnseignantForm(request.POST, instance=contrat)
        if civil_form.is_valid() and contrat_form.is_valid():
            civil_form.save()
            contrat_form.save()
            messages.success(request, "Contrat mis à jour.")
            return redirect('teachers:contrat_list')
    else:
        civil_form = TeacherCivilInfoForm(instance=contrat.teacher)
        contrat_form = ContratEnseignantForm(instance=contrat)

    return render(request, 'teachers/contrat_edit.html', {
        'contrat': contrat,
        'civil_form': civil_form,
        'contrat_form': contrat_form,
        'modules_rows': contrat.modules_rows(),
    })


@login_required
def contrat_pdf(request, pk):
    """Génère et renvoie le PDF du contrat — accessible à la direction pédagogique et à l'enseignant concerné."""
    from django.http import HttpResponse
    from .pdf_contrat import generate_contrat_pdf

    # Pas de select_related('department__faculty') : Faculty est un modèle
    # maître, ContratEnseignant/Department sont routés par tenant — le hop
    # __faculty forcerait un INNER JOIN chaîné sur la table locale
    # `faculties` (toujours vide côté tenant), faisant échouer get_object_or_404
    # pour TOUT contrat valide.
    contrat = get_object_or_404(
        ContratEnseignant.objects.select_related('teacher__user', 'department', 'academic_year'), pk=pk,
    )

    teacher_profile = getattr(request.user, 'teacher_profile', None)
    is_owner = teacher_profile is not None and teacher_profile.pk == contrat.teacher_id
    if not (is_owner or request.user.can_manage_dept()):
        messages.error(request, "Accès non autorisé à ce contrat.")
        return redirect('dashboard:index')

    pdf_bytes = generate_contrat_pdf(contrat)
    filename = f"contrat_{contrat.teacher.matricule}_{contrat.department.code}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


@login_required
def mes_contrats(request):
    """Contrats de l'enseignant connecté — un par département où il intervient."""
    from academic_core.apps.academic_structure.models import AcademicYear

    teacher = getattr(request.user, 'teacher_profile', None)
    if not teacher:
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    from .services import sync_contracts_for_teacher
    sync_contracts_for_teacher(teacher)

    contrats = (
        ContratEnseignant.objects
        .filter(teacher=teacher)
        .select_related('department', 'academic_year')
        .order_by('department__name')
    )
    current_year = AcademicYear.objects.filter(is_current=True).first()
    if current_year:
        contrats = contrats.filter(academic_year=current_year)

    return render(request, 'teachers/mes_contrats.html', {
        'contrats': contrats,
    })
