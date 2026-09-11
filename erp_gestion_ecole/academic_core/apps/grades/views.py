import io
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.generic import ListView, CreateView
from django.urls import reverse_lazy, reverse
from django.db import transaction, models as db_models
from django.http import HttpResponse, JsonResponse
from decimal import Decimal, InvalidOperation

from .models import (
    Evaluation, Grade, SubjectAverage, SemesterAverage, EvaluationType,
    UniteEnseignement, Bulletin, BulletinUEResult, BulletinECResult, ECValidation,
)
from .forms import EvaluationForm, GradeBulkForm
from .services import compute_bulletin_data, save_bulletin, compute_ec_grade
from academic_core.apps.students.models import Student, Enrollment
from academic_core.apps.subjects.models import Subject, natural_sort_key
from academic_core.apps.academic_structure.models import Semester, Program, Class, BulletinConfig
from academic_core.apps.notifications.utils import notify_users, notify_class_students
from academic_core.apps.accounting.services import check_bulletin_payment_clearance
from academic_core.apps.accounts.models import Role


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _can_edit_grades(user):
    """Seul l'enseignant propriétaire peut saisir des notes."""
    return user.is_enseignant()

def _can_view_only(user):
    """Admin et Responsable : lecture seule."""
    return user.can_manage_dept()


# ─── Liste des évaluations ────────────────────────────────────────────────────

class EvaluationListView(LoginRequiredMixin, ListView):
    model = Evaluation
    template_name = 'grades/evaluation_list.html'
    context_object_name = 'evaluations'

    def _resolve_selected_year(self, fac_for_years):
        from academic_core.apps.academic_structure.models import AcademicYear
        academic_years = AcademicYear.objects.order_by('-start_date')
        academic_years = academic_years.filter(faculty=fac_for_years) if fac_for_years else academic_years.none()

        year_param = self.request.GET.get('year')
        if year_param == 'all':
            return academic_years, None
        if year_param:
            return academic_years, academic_years.filter(pk=year_param).first()
        return academic_years, academic_years.filter(is_current=True).first()

    def get_queryset(self):
        from django.db.models import Count
        qs = Evaluation.objects.select_related(
            'subject__semester', 'semester', 'evaluation_type', 'teacher__user', 'class_group'
        ).annotate(
            grades_count=Count('grades')
        ).order_by('subject__semester__number', 'subject__semester__label', '-date')

        user    = self.request.user
        dept    = getattr(self.request, 'active_department', None)
        faculty = getattr(self.request, 'active_faculty', None)

        if user.is_etudiant():
            # Sélecteur d'année propre à l'étudiant (session persistée) —
            # la classe suit l'inscription de l'année choisie, pas
            # student.current_class (dénormalisé, reflète seulement l'année
            # en cours et deviendrait faux dès qu'une année passée est
            # sélectionnée, ou après une réinscription dans une autre classe).
            from academic_core.apps.students.utils import resolve_student_year
            student = getattr(user, 'student_profile', None)
            if student:
                selected_year, academic_years, enrollment = resolve_student_year(self.request, student)
                self._selected_year  = selected_year
                self._academic_years = academic_years
                qs = qs.filter(class_group=enrollment.class_group) if enrollment else qs.none()
            else:
                qs = qs.none()
                self._selected_year, self._academic_years = None, []
        elif user.is_enseignant():
            qs = qs.filter(teacher__user=user)
        elif dept:
            qs = qs.filter(class_group__program__department=dept)
        elif faculty:
            qs = qs.filter(class_group__program__department__faculty=faculty)
        else:
            qs = qs.none()

        # Année académique : par défaut l'année en cours (les évaluations
        # d'une année précédente ne doivent pas s'afficher mélangées avec
        # l'année en cours) — "Toutes les années" reste disponible pour
        # consulter l'historique. Pour l'étudiant, l'année a déjà été résolue
        # ci-dessus par son propre sélecteur.
        if not user.is_etudiant():
            fac_for_years = faculty or (dept.faculty if dept else None)
            self._academic_years, self._selected_year = self._resolve_selected_year(fac_for_years)
        if self._selected_year:
            qs = qs.filter(semester__academic_year=self._selected_year)

        class_id   = self.request.GET.get('class_id')
        semester_id = self.request.GET.get('semester_id')
        subject_id  = self.request.GET.get('subject_id')
        if class_id:
            qs = qs.filter(class_group_id=class_id)
        if semester_id:
            qs = qs.filter(semester_id=semester_id)
        if subject_id:
            qs = qs.filter(subject_id=subject_id)

        # Auto-transition SCHEDULED → ONGOING quand la date est dépassée
        today = timezone.now().date()
        qs.filter(
            status=Evaluation.STATUS_SCHEDULED,
            date__lte=today,
        ).update(status=Evaluation.STATUS_ONGOING)

        return qs

    def get_context_data(self, **kwargs):
        from collections import defaultdict
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx['can_create'] = user.is_enseignant()
        ctx['view_only']  = _can_view_only(user)

        # Filtres Année académique / Classe / Semestre / EC (masqués pour les
        # étudiants et enseignants, qui n'ont de toute façon accès qu'à leur
        # propre périmètre déjà filtré ci-dessus).
        if not user.is_etudiant() and not user.is_enseignant():
            dept    = getattr(self.request, 'active_department', None)
            faculty = getattr(self.request, 'active_faculty', None)
            selected_year = self._selected_year

            classes_qs = Class.objects.select_related('program').order_by('name')
            semesters_qs = Semester.objects.select_related('academic_year').order_by(
                '-academic_year__start_date', 'number'
            )
            subjects_qs = Subject.objects.select_related('program').order_by('code')
            if dept:
                classes_qs = classes_qs.filter(program__department=dept)
                semesters_qs = semesters_qs.filter(academic_year__faculty=dept.faculty)
                subjects_qs = subjects_qs.filter(program__department=dept)
            elif faculty:
                classes_qs = classes_qs.filter(program__department__faculty=faculty)
                semesters_qs = semesters_qs.filter(academic_year__faculty=faculty)
                subjects_qs = subjects_qs.filter(program__department__faculty=faculty)
            if selected_year:
                classes_qs = classes_qs.filter(academic_year=selected_year)
                semesters_qs = semesters_qs.filter(academic_year=selected_year)
                subjects_qs = subjects_qs.filter(semester__academic_year=selected_year)

            ctx['academic_years'] = self._academic_years
            ctx['selected_year_param'] = self.request.GET.get('year', '')
            ctx['filter_classes']   = classes_qs
            ctx['filter_semesters'] = semesters_qs
            ctx['filter_subjects']  = subjects_qs.distinct()
            ctx['selected_class_id']    = self.request.GET.get('class_id', '')
            ctx['selected_semester_id'] = self.request.GET.get('semester_id', '')
            ctx['selected_subject_id']  = self.request.GET.get('subject_id', '')

        ctx['is_student_view'] = user.is_etudiant()

        # Pour l'étudiant : annoter chaque évaluation avec sa propre note
        if user.is_etudiant():
            ctx['available_years'] = self._academic_years
            ctx['selected_year']   = self._selected_year
            student = getattr(user, 'student_profile', None)
            if student:
                from .models import Grade
                grades_map = {
                    g['evaluation_id']: g
                    for g in Grade.objects.filter(student=student).values('evaluation_id', 'score', 'comment')
                }
                for ev in ctx['evaluations']:
                    ev.my_grade = grades_map.get(ev.pk)

        # Grouper par semestre → UE → EC (Subject) → [evaluations]
        # Structure : { sem: { ue: { subject: [ev, ...] } } }
        by_sem_ue_subj = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        no_sem_ue_subj = defaultdict(lambda: defaultdict(list))

        for ev in ctx['evaluations']:
            subj = ev.subject
            sem  = getattr(subj, 'semester', None) if subj else None
            ue   = getattr(subj, 'ue', None)       if subj else None
            if sem:
                by_sem_ue_subj[sem][ue][subj].append(ev)
            else:
                no_sem_ue_subj[ue][subj].append(ev)

        def _dedup_evs(evs):
            """Vue étudiant : masquer DEVOIR2 si sa note == DEVOIR1."""
            if not user.is_etudiant():
                return sorted(evs, key=lambda e: e.date or e.pk)

            sorted_evs = sorted(evs, key=lambda e: e.date or e.pk)

            def _type_str(ev):
                return str(ev.evaluation_type).strip().upper()

            def _score(ev):
                g = getattr(ev, 'my_grade', None)
                return g['score'] if g else None

            devoir1_score = next((_score(e) for e in sorted_evs if _type_str(e) == 'DEVOIR1'), None)
            devoir2_score = next((_score(e) for e in sorted_evs if _type_str(e) == 'DEVOIR2'), None)
            hide_devoir2  = (
                devoir1_score is not None
                and devoir2_score is not None
                and devoir1_score == devoir2_score
            )
            return [ev for ev in sorted_evs if not (hide_devoir2 and _type_str(ev) == 'DEVOIR2')]

        def _build_ue_groups(ue_dict):
            """
            ue_dict : { ue_or_None: { subj: [ev, ...] } }
            Retourne : [ (ue_or_None, [ (subj, [ev, ...]), ... ]), ... ]
            """
            result = []
            for ue in sorted(ue_dict.keys(), key=lambda u: (getattr(u, 'order', 0), getattr(u, 'code', '') or '') if u else (9999, '')):
                subj_groups = [
                    (subj, _dedup_evs(evs))
                    for subj, evs in sorted(ue_dict[ue].items(), key=lambda x: getattr(x[0], 'code', '') or '')
                ]
                result.append((ue, subj_groups))
            return result

        # Trier par numéro de semestre
        semester_groups = []
        for sem in sorted(by_sem_ue_subj.keys(), key=lambda s: (s.number, s.label)):
            semester_groups.append((sem, _build_ue_groups(by_sem_ue_subj[sem])))
        if no_sem_ue_subj:
            semester_groups.append((None, _build_ue_groups(no_sem_ue_subj)))

        ctx['semester_groups'] = semester_groups

        # Évaluations programmées à venir (rappel enseignant)
        if user.is_enseignant():
            from django.utils import timezone as _tz
            today = _tz.now().date()
            upcoming = [
                ev for sem_group in semester_groups
                for ue_group in sem_group[1]
                for subj_group in ue_group[1]
                for ev in subj_group[1]
                if getattr(ev, 'status', None) == 'SCHEDULED'
                and ev.date and ev.date >= today
            ]
            upcoming.sort(key=lambda e: e.date)
            ctx['upcoming_evals'] = upcoming

        return ctx


# ─── Créer une évaluation (enseignant uniquement) ────────────────────────────

@login_required
def evaluation_create_view(request):
    user = request.user
    if not user.is_enseignant():
        messages.error(request, "Seul un enseignant peut programmer une évaluation.")
        return redirect('grades:evaluation_list')

    dept = getattr(request, 'active_department', None)
    form = EvaluationForm(
        request.POST or None,
        teacher_user=user,
        department=dept,
    )

    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            evaluation = form.save(commit=False)
            evaluation.teacher = user.teacher_profile
            evaluation.status  = Evaluation.STATUS_SCHEDULED
            evaluation.save()

            # ── Notification aux étudiants de la classe ──────────────────────
            if evaluation.class_group:
                notify_class_students(
                    class_group=evaluation.class_group,
                    notification_type='EVALUATION',
                    title=f"📅 Évaluation programmée — {evaluation.subject.code} : {evaluation.subject.title}",
                    message=(
                        f"{evaluation.evaluation_type} : « {evaluation.title} »\n"
                        f"📆 Date : {evaluation.date.strftime('%d/%m/%Y')}"
                        + (f" | ⏱ Durée : {evaluation.duration_minutes} min" if evaluation.duration_minutes else "")
                        + (f" | 📍 {evaluation.room}" if evaluation.room else "")
                        + (f"\n\n{evaluation.instructions}" if evaluation.instructions else "")
                    ),
                    priority='HIGH',
                    link=f"/grades/",
                )
                evaluation.notification_sent = True
                evaluation.save(update_fields=['notification_sent'])

        messages.success(request,
            f"Évaluation « {evaluation.title} » programmée. "
            f"{'Les étudiants ont été notifiés.' if evaluation.notification_sent else ''}"
        )
        return redirect('grades:grade_entry', pk=evaluation.pk)

    return render(request, 'grades/evaluation_form.html', {
        'form': form,
        'title': "Programmer une évaluation",
    })


# ─── Saisie des notes (enseignant propriétaire uniquement) ────────────────────

@login_required
def grade_entry_view(request, pk):
    evaluation = get_object_or_404(
        Evaluation.objects.select_related(
            'subject', 'semester', 'teacher__user', 'class_group', 'evaluation_type'
        ), pk=pk
    )
    user = request.user

    # Lecture seule pour admin/responsable
    if _can_view_only(user):
        return redirect('grades:evaluation_detail', pk=pk)

    if not user.is_enseignant():
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')

    # L'enseignant ne peut saisir que ses propres évals
    if evaluation.teacher and evaluation.teacher.user != user:
        messages.error(request, "Cette évaluation ne vous appartient pas.")
        return redirect('grades:evaluation_list')

    if evaluation.is_locked:
        messages.warning(request, "Cette évaluation est verrouillée. Consultation uniquement.")
        return redirect('grades:evaluation_detail', pk=pk)

    # Vérifier si le semestre est verrouillé par le contrôleur interne
    if evaluation.semester.is_locked:
        messages.warning(request, evaluation.semester.lock_message)
        return redirect('grades:evaluation_detail', pk=pk)

    # Vérifier si la session normale est clôturée pour ce semestre
    if evaluation.semester.session_normale_closed:
        eval_type_code = evaluation.evaluation_type.code if evaluation.evaluation_type else ''
        if eval_type_code != 'RATTRAPAGE':
            messages.warning(request, "La session normale est clôturée pour ce semestre. Consultation uniquement.")
            return redirect('grades:evaluation_detail', pk=pk)

    # Récupérer les étudiants de la classe
    if evaluation.class_group:
        enrollments = Enrollment.objects.filter(
            class_group=evaluation.class_group,
            status=Enrollment.STATUS_VALIDATED,
        ).select_related('student__user').order_by('student__user__last_name')
    else:
        enrollments = Enrollment.objects.filter(
            class_group__program=evaluation.subject.program if hasattr(evaluation.subject, 'program') else None,
            academic_year=evaluation.semester.academic_year,
            status=Enrollment.STATUS_VALIDATED,
        ).select_related('student__user').order_by('student__user__last_name')

    students = [e.student for e in enrollments]
    form = GradeBulkForm(
        request.POST or None,
        evaluation=evaluation,
        students=students,
    )

    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            count = 0
            for student in students:
                score   = form.cleaned_data.get(f'score_{student.pk}')
                comment = form.cleaned_data.get(f'comment_{student.pk}', '')
                if score is not None:
                    Grade.objects.update_or_create(
                        student=student,
                        evaluation=evaluation,
                        defaults={'score': score, 'comment': comment, 'entered_by': user}
                    )
                    count += 1

            # Mise à jour du statut
            evaluation.status = Evaluation.STATUS_GRADED
            evaluation.save(update_fields=['status'])

            # Notification aux étudiants
            notify_users(
                recipients=[s.user for s in students],
                notification_type='NEW_GRADE',
                title=f"📊 Notes disponibles — {evaluation.subject.code}",
                message=f"Vos notes pour « {evaluation.title} » du {evaluation.date.strftime('%d/%m/%Y')} sont disponibles.",
                link="/grades/student/",
            )

        messages.success(request, f"{count} note(s) enregistrée(s). Les étudiants ont été notifiés.")
        return redirect('grades:evaluation_list')

    existing_qs = Grade.objects.filter(evaluation=evaluation).values('student_id', 'score', 'comment')
    existing_map = {g['student_id']: g for g in existing_qs}
    students_data = [
        {
            'student': s,
            'score':   existing_map.get(s.pk, {}).get('score', ''),
            'comment': existing_map.get(s.pk, {}).get('comment', ''),
        }
        for s in students
    ]
    return render(request, 'grades/grade_entry.html', {
        'evaluation':   evaluation,
        'students_data': students_data,
        'grades_count': len(existing_map),
    })


# ─── Détail (lecture seule — admin/responsable) ───────────────────────────────

@login_required
def evaluation_detail_view(request, pk):
    evaluation = get_object_or_404(
        Evaluation.objects.select_related(
            'subject', 'semester', 'teacher__user', 'class_group', 'evaluation_type'
        ), pk=pk
    )
    if evaluation.class_group:
        enrollments = Enrollment.objects.filter(
            class_group=evaluation.class_group, status=Enrollment.STATUS_VALIDATED
        ).select_related('student__user').order_by('student__user__last_name')
    else:
        enrollments = []

    students_with_grades = []
    for enr in enrollments:
        try:
            grade = Grade.objects.get(student=enr.student, evaluation=evaluation)
        except Grade.DoesNotExist:
            grade = None
        students_with_grades.append({'student': enr.student, 'grade': grade})

    grades_qs = Grade.objects.filter(evaluation=evaluation)
    total = grades_qs.count()
    avg   = None
    if total:
        s = sum(float(g.score) for g in grades_qs)
        avg = round(s / total, 2)

    return render(request, 'grades/evaluation_detail.html', {
        'evaluation':          evaluation,
        'students_with_grades': students_with_grades,
        'total_graded':        total,
        'class_size':          len(students_with_grades),
        'average':             avg,
        'view_only':           _can_view_only(request.user),
    })


# ─── Anonymisation des modèles de feuille de notes ───────────────────────────
# Un enseignant qui voit "DIOP Awa" en remplissant une note peut être
# (in)consciemment influencé par l'identité de l'étudiant. Les 3 générateurs de
# modèle Excel de saisie/import (download_grade_template, download_notes_template,
# examens_concours_ec_template) proposent donc, en plus du modèle nominatif
# habituel, une variante où les colonnes Nom/Prénom sont remplacées par un
# pseudonyme — SANS toucher à la colonne Matricule, qui reste la seule clé
# utilisée par les imports (import_grades, import_notes_csv,
# examens_concours_ec_import ne lisent jamais Nom/Prénom, voir leurs
# `Student.objects.get(matricule=...)`) : aucune correspondance à maintenir
# séparément, le pseudonyme n'est qu'un habillage d'affichage.
def _is_anon_requested(request):
    return request.GET.get('anon') in ('1', 'true', 'yes')


def _name_cells(anon, index, last_name, first_name):
    """Retourne (nom, prenom) à écrire dans le modèle — pseudonymisé si `anon`."""
    if anon:
        return 'ÉTUDIANT', f"{index:03d}"
    return last_name, first_name


# ─── Télécharger le modèle Excel ─────────────────────────────────────────────

@login_required
def download_grade_template(request, pk):
    evaluation = get_object_or_404(Evaluation, pk=pk)
    user = request.user

    is_owner   = user.is_enseignant() and evaluation.teacher and evaluation.teacher.user == user
    is_manager = user.can_manage_dept() or user.is_admin()

    if not (is_owner or is_manager):
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')
    # L'enseignant ne peut télécharger que ses propres évaluations
    if user.is_enseignant() and not is_owner:
        messages.error(request, "Cette évaluation ne vous appartient pas.")
        return redirect('grades:evaluation_list')

    if evaluation.class_group:
        enrollments = Enrollment.objects.filter(
            class_group=evaluation.class_group, status=Enrollment.STATUS_VALIDATED
        ).select_related('student__user').order_by('student__user__last_name')
    else:
        enrollments = []

    anon = _is_anon_requested(request)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        messages.error(request, "openpyxl non installé. Lancez : pip install openpyxl")
        return redirect('grades:grade_entry', pk=pk)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notes"

    # ── Styles ────────────────────────────────────────────────────────────────
    navy_fill   = PatternFill("solid", fgColor="003D82")
    gold_fill   = PatternFill("solid", fgColor="F0A500")
    light_fill  = PatternFill("solid", fgColor="EFF6FF")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1'),
    )

    # ── En-tête informations ──────────────────────────────────────────────────
    title_row = "MODÈLE DE SAISIE DES NOTES (ANONYME)" if anon else "MODÈLE DE SAISIE DES NOTES — Institut Supérieur d'Informatique - ISI"
    info_rows = [
        (title_row, ),
        (f"Évaluation :", evaluation.title),
        (f"Module (EC) :", evaluation.subject.title if evaluation.subject else "—"),
        (f"Classe :", evaluation.class_group.name if evaluation.class_group else "—"),
        (f"Type :", str(evaluation.evaluation_type)),
        (f"Date :", evaluation.date.strftime("%d/%m/%Y")),
        (f"Note max :", float(evaluation.max_score)),
        ("⚠ NE PAS MODIFIER les colonnes A, B, C, D. Remplir uniquement la colonne E (Note).", ),
    ]
    for r, row in enumerate(info_rows, 1):
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=val)
            if r == 1:
                cell.font = Font(name='Calibri', bold=True, size=13, color='FFFFFF')
                cell.fill = navy_fill
                cell.alignment = Alignment(horizontal='center')
            elif r == 8:
                cell.font = Font(name='Calibri', bold=True, size=10, color='92400E')
                cell.fill = PatternFill("solid", fgColor="FDE68A")
            elif c == 1:
                cell.font = Font(name='Calibri', bold=True, size=10, color='003D82')

    ws.merge_cells('A1:F1')
    ws.merge_cells('A8:F8')
    ws.row_dimensions[1].height = 28

    # ── En-tête tableau (ligne 10) ───────────────────────────────────────────
    headers = ["N°", "Matricule", "Nom", "Prénom", f"Note /{float(evaluation.max_score)}", "Commentaire"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=10, column=c, value=h)
        cell.font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border
    ws.row_dimensions[10].height = 22

    # ── Données étudiants ────────────────────────────────────────────────────
    for i, enr in enumerate(enrollments, 1):
        student = enr.student
        row_num = 10 + i
        fill = light_fill if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        try:
            existing = Grade.objects.get(student=student, evaluation=evaluation)
            score = float(existing.score)
            comment = existing.comment
        except Grade.DoesNotExist:
            score = None
            comment = ""

        nom, prenom = _name_cells(anon, i, student.user.last_name.upper(), student.user.first_name.title())
        row_data = [
            i,
            student.matricule,
            nom,
            prenom,
            score,
            comment,
        ]
        for c, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=c, value=val)
            cell.fill = fill
            cell.border = thin_border
            cell.font = Font(name='Calibri', size=10)
            if c == 5:  # Note
                cell.font = Font(name='Calibri', size=11, bold=True, color='003D82')
                cell.alignment = Alignment(horizontal='center')
            elif c in (1, 2):
                cell.alignment = Alignment(horizontal='center')

    # ── Largeurs colonnes ────────────────────────────────────────────────────
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 22
    ws.column_dimensions['D'].width = 22
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 35

    # ── Feuille de référence (IDs cachés, ne pas modifier) ───────────────────
    ws_ref = wb.create_sheet("_ref_ids")
    ws_ref.sheet_state = 'hidden'
    ws_ref.cell(1, 1, "evaluation_id")
    ws_ref.cell(1, 2, evaluation.pk)
    ws_ref.cell(2, 1, "max_score")
    ws_ref.cell(2, 2, float(evaluation.max_score))
    for i, enr in enumerate(enrollments, 1):
        ws_ref.cell(10 + i, 1, enr.student.pk)

    # ── Réponse ──────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    import re
    def _slug(s):
        """Convertit une chaîne en slug sans accents ni espaces."""
        import unicodedata
        s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
        return re.sub(r'[^\w]', '_', s).strip('_')

    subj_slug    = _slug(evaluation.subject.title if evaluation.subject else evaluation.subject.code if evaluation.subject else 'Module')
    teacher_slug = _slug(evaluation.teacher.user.get_full_name() if evaluation.teacher else 'Enseignant')
    class_slug   = _slug(evaluation.class_group.name if evaluation.class_group else 'Classe')
    anon_suffix  = '_ANONYME' if anon else ''
    filename     = f"Notes_{subj_slug}_{teacher_slug}_{class_slug}{anon_suffix}.xlsx"

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─── Importer les notes depuis Excel ─────────────────────────────────────────

@login_required
def import_grades(request, pk):
    evaluation = get_object_or_404(Evaluation, pk=pk)
    user = request.user

    if not user.is_enseignant():
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')
    if evaluation.teacher and evaluation.teacher.user != user:
        messages.error(request, "Cette évaluation ne vous appartient pas.")
        return redirect('grades:evaluation_list')
    if evaluation.is_locked:
        messages.error(request, "Cette évaluation est verrouillée.")
        return redirect('grades:evaluation_detail', pk=pk)
    if evaluation.semester.is_locked:
        messages.error(request, evaluation.semester.lock_message)
        return redirect('grades:evaluation_detail', pk=pk)
    eval_type_code = evaluation.evaluation_type.code if evaluation.evaluation_type else ''
    if evaluation.semester.session_normale_closed and eval_type_code != 'RATTRAPAGE':
        messages.error(request, "Session normale clôturée pour ce semestre. Import refusé.")
        return redirect('grades:evaluation_detail', pk=pk)

    if request.method != 'POST':
        return redirect('grades:grade_entry', pk=pk)

    uploaded = request.FILES.get('excel_file')
    if not uploaded:
        messages.error(request, "Aucun fichier sélectionné.")
        return redirect('grades:grade_entry', pk=pk)

    try:
        import openpyxl
    except ImportError:
        messages.error(request, "openpyxl non installé.")
        return redirect('grades:grade_entry', pk=pk)

    try:
        wb = openpyxl.load_workbook(uploaded, data_only=True)
        ws = wb.active

        errors = []
        saved  = 0

        with transaction.atomic():
            for row in ws.iter_rows(min_row=11, values_only=True):
                num, matricule, nom, prenom, score_raw, comment = (
                    row[0], row[1], row[2], row[3], row[4], row[5] if len(row) > 5 else ""
                )
                if not matricule:
                    continue
                try:
                    student = Student.objects.get(matricule=str(matricule).strip())
                except Student.DoesNotExist:
                    errors.append(f"Matricule introuvable : {matricule}")
                    continue

                if score_raw is None or str(score_raw).strip() == '':
                    continue  # pas de note renseignée → on saute

                try:
                    score = Decimal(str(score_raw))
                except InvalidOperation:
                    errors.append(f"{matricule} : note invalide « {score_raw} »")
                    continue

                if score < 0 or score > evaluation.max_score:
                    errors.append(
                        f"{matricule} : note {score} hors plage [0 – {evaluation.max_score}]"
                    )
                    continue

                Grade.objects.update_or_create(
                    student=student, evaluation=evaluation,
                    defaults={
                        'score': score,
                        'comment': str(comment or '').strip(),
                        'entered_by': user,
                    }
                )
                saved += 1

            if saved:
                evaluation.status = Evaluation.STATUS_GRADED
                evaluation.save(update_fields=['status'])

        if errors:
            for err in errors[:5]:  # max 5 erreurs affichées
                messages.warning(request, err)

        if saved:
            messages.success(request, f"{saved} note(s) importée(s) avec succès.")
            # Notifier les étudiants
            if evaluation.class_group:
                notify_class_students(
                    class_group=evaluation.class_group,
                    notification_type='NEW_GRADE',
                    title=f"📊 Notes disponibles — {evaluation.subject.code}",
                    message=f"Vos notes pour « {evaluation.title} » du {evaluation.date.strftime('%d/%m/%Y')} sont disponibles.",
                    link="/grades/student/",
                )
        else:
            messages.warning(request, "Aucune note importée. Vérifiez le fichier.")

    except Exception as e:
        messages.error(request, f"Erreur lors de l'import : {e}")

    return redirect('grades:grade_entry', pk=pk)


# ─── Verrouiller (admin/responsable) ─────────────────────────────────────────

@login_required
def lock_evaluation(request, pk):
    evaluation = get_object_or_404(Evaluation, pk=pk)
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')
    if request.method == 'POST':
        evaluation.is_locked = True
        evaluation.locked_at = timezone.now()
        evaluation.locked_by = request.user
        evaluation.status    = Evaluation.STATUS_LOCKED
        evaluation.save(update_fields=['is_locked', 'locked_at', 'locked_by', 'status'])
        messages.success(request, "Évaluation verrouillée — aucune modification possible.")
    return redirect('grades:evaluation_detail', pk=pk)


# ─── Marquer les notes comme saisies (ONGOING → GRADED) ─────────────────────

@login_required
def mark_grades_entered(request, pk):
    """L'enseignant confirme que les notes sont saisies → status GRADED."""
    evaluation = get_object_or_404(Evaluation, pk=pk)
    user = request.user

    if not user.is_enseignant():
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')
    if evaluation.teacher and evaluation.teacher.user != user:
        messages.error(request, "Cette évaluation ne vous appartient pas.")
        return redirect('grades:evaluation_list')
    if evaluation.status not in (Evaluation.STATUS_ONGOING, Evaluation.STATUS_SCHEDULED):
        messages.warning(request, "L'évaluation n'est pas en cours de correction.")
        return redirect('grades:evaluation_list')

    if request.method == 'POST':
        evaluation.status = Evaluation.STATUS_GRADED
        evaluation.save(update_fields=['status'])
        messages.success(request, f"Notes de « {evaluation.title} » marquées comme saisies.")

    return redirect('grades:evaluation_list')


# ─── Supprimer une évaluation ────────────────────────────────────────────────

@login_required
def evaluation_delete_view(request, pk):
    evaluation = get_object_or_404(Evaluation, pk=pk)
    user = request.user

    # Seuls l'enseignant propriétaire, les admins et responsables peuvent supprimer
    is_owner = evaluation.teacher and evaluation.teacher.user == user
    can_manage = user.can_manage_dept()
    if not (is_owner or can_manage):
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')

    if evaluation.is_locked:
        messages.error(request, "Impossible de supprimer une évaluation verrouillée.")
        return redirect('grades:evaluation_list')

    if request.method == 'POST':
        titre = evaluation.title
        evaluation.delete()
        messages.success(request, f"Évaluation « {titre} » supprimée.")
        return redirect('grades:evaluation_list')

    return redirect('grades:evaluation_list')


# ─── Notes étudiant (lecture seule) ──────────────────────────────────────────

@login_required
def student_grades_view(request):
    user = request.user
    if not user.is_etudiant():
        messages.error(request, "Vue réservée aux étudiants.")
        return redirect('dashboard:index')

    from academic_core.apps.students.utils import resolve_student_year
    student     = get_object_or_404(Student, user=user)
    selected_year, available_years, enrollment = resolve_student_year(request, student)
    grades      = Grade.objects.filter(
        student=student, evaluation__semester__academic_year=selected_year,
    ).select_related(
        'evaluation__subject', 'evaluation__evaluation_type',
        'evaluation__semester', 'evaluation__class_group'
    ).order_by('evaluation__semester__number', 'evaluation__subject__code')
    sem_avgs    = SemesterAverage.objects.filter(
        student=student, semester__academic_year=selected_year,
    ).select_related('semester')

    return render(request, 'grades/student_grades.html', {
        'student':         student,
        'grades':          grades,
        'semester_avgs':   sem_avgs,
        'enrollment':      enrollment,
        'selected_year':   selected_year,
        'available_years': available_years,
    })


# ─── Calcul des moyennes ──────────────────────────────────────────────────────

@login_required
def compute_averages(request, semester_id):
    from academic_core.apps.academic_structure.models import Semester
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('grades:evaluation_list')

    semester    = get_object_or_404(Semester, pk=semester_id)
    enrollments = Enrollment.objects.filter(
        academic_year=semester.academic_year, status=Enrollment.STATUS_VALIDATED
    ).select_related('student')

    with transaction.atomic():
        for enrollment in enrollments:
            student = enrollment.student
            weighted_total = Decimal('0')
            total_coeff    = Decimal('0')

            evals = Evaluation.objects.filter(semester=semester)
            subjects_done = set()
            for ev in evals:
                subj = ev.subject
                if subj.pk in subjects_done:
                    continue
                grades = Grade.objects.filter(student=student, evaluation__subject=subj, evaluation__semester=semester)
                if not grades.exists():
                    continue
                total_w = sum(g.evaluation.evaluation_type.weight for g in grades)
                if total_w > 0:
                    subj_score = sum(g.score * g.evaluation.evaluation_type.weight for g in grades) / total_w
                    coeff      = getattr(subj, 'coefficient', Decimal('1'))
                    SubjectAverage.objects.update_or_create(
                        student=student, subject=subj, semester=semester,
                        defaults={'average': round(subj_score, 2)}
                    )
                    weighted_total += subj_score * coeff
                    total_coeff    += coeff
                subjects_done.add(subj.pk)

            if total_coeff > 0:
                SemesterAverage.objects.update_or_create(
                    student=student, semester=semester,
                    defaults={'average': round(weighted_total / total_coeff, 2)}
                )

        avgs  = SemesterAverage.objects.filter(semester=semester).order_by('-average')
        total = avgs.count()
        for rank, avg in enumerate(avgs, 1):
            mention = "Insuffisant"
            if avg.average >= 16:   mention = "Très Bien"
            elif avg.average >= 14: mention = "Bien"
            elif avg.average >= 12: mention = "Assez Bien"
            elif avg.average >= 10: mention = "Passable"
            avg.rank = rank; avg.total_students = total; avg.mention = mention
            avg.save(update_fields=['rank', 'total_students', 'mention'])

    messages.success(request, f"Moyennes calculées pour {semester}.")
    return redirect('grades:evaluation_list')


# ═══════════════════════════════════════════════════════════════════════════════
# LMD — MAQUETTES (Gestion des UE/EC)
# ═══════════════════════════════════════════════════════════════════════════════

def _admin_required(request):
    return request.user.can_manage_dept() or request.user.is_charge_examens_concours()


@login_required
def maquette_list(request):
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import AcademicYear

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    programs = Program.objects.all()
    if dept:
        programs = programs.filter(department=dept)
    elif faculty:
        programs = programs.filter(department__faculty=faculty)
    else:
        programs = programs.none()

    # Années académiques de l'institut — la maquette se choisit d'abord par
    # année, pour ne pas mélanger les semestres de plusieurs années dans un
    # même sélecteur (une même Filière peut avoir des maquettes différentes
    # d'une année sur l'autre).
    fac_for_years = faculty or (dept.faculty if dept else None)
    academic_years = AcademicYear.objects.all().order_by('-start_date')
    if fac_for_years:
        academic_years = academic_years.filter(faculty=fac_for_years)
    else:
        academic_years = academic_years.none()

    year_id = request.GET.get('year')
    selected_year = None
    if year_id:
        selected_year = academic_years.filter(pk=year_id).first()
    if not selected_year and not year_id:
        # Par défaut : toujours l'année académique en cours, même si elle n'a
        # pas encore de semestres/maquettes — la page doit automatiquement
        # suivre l'année marquée "en cours" dans Gestion de la Scolarité,
        # plutôt que de retomber silencieusement sur une année plus ancienne.
        selected_year = academic_years.filter(is_current=True).first() or academic_years.first()

    # Année précédente (la plus récente avant celle sélectionnée) ayant des
    # maquettes déjà définies — utilisée pour proposer la duplication.
    previous_year_with_maquettes = None
    if selected_year and fac_for_years:
        previous_year_with_maquettes = (
            academic_years
            .filter(start_date__lt=selected_year.start_date, semesters__unites_enseignement__isnull=False)
            .exclude(pk=selected_year.pk)
            .distinct()
            .order_by('-start_date')
            .first()
        )
    has_maquettes_for_selected_year = False
    if selected_year:
        has_maquettes_for_selected_year = UniteEnseignement.objects.filter(
            semester__academic_year=selected_year
        ).exists()

    semesters = Semester.objects.select_related('academic_year').order_by('-academic_year__start_date', 'number')
    if selected_year:
        semesters = semesters.filter(academic_year=selected_year)
    elif fac_for_years:
        semesters = semesters.filter(academic_year__faculty=fac_for_years)
    else:
        semesters = semesters.none()
    selected_program = None
    selected_semester = None
    ues = []

    prog_id = request.GET.get('program')
    sem_id = request.GET.get('semester')

    totals = None
    if prog_id and sem_id:
        try:
            selected_program = programs.get(pk=prog_id)
            selected_semester = Semester.objects.get(pk=sem_id)
            ues = list(UniteEnseignement.objects.filter(
                program=selected_program, semester=selected_semester
            ).prefetch_related('subjects').order_by('order', 'code'))

            from decimal import Decimal as _D
            t = {'cm': _D(0), 'td': _D(0), 'tp': _D(0), 'tpe': _D(0),
                 'volume_hours': _D(0), 'volume_total_ue': _D(0), 'coeff': _D(0), 'credits': 0}
            for ue in ues:
                ue_credits = 0
                ue_vol_h = _D(0)
                for s in ue.subjects.all():
                    t['cm']      += s.volume_cm    or _D(0)
                    t['td']      += s.volume_td    or _D(0)
                    t['tp']      += s.volume_tp    or _D(0)
                    t['tpe']     += s.volume_tpe   or _D(0)
                    t['coeff']   += s.coefficient  or _D(0)
                    t['credits'] += s.credits or 0
                    t['volume_hours']    += s.volume_hours    or _D(0)
                    t['volume_total_ue'] += s.volume_total_ue or _D(0)
                    ue_credits   += s.credits or 0
                    ue_vol_h     += s.volume_hours or _D(0)
                ue.computed_credits = ue_credits
                ue.computed_volume_hours = ue_vol_h
            totals = t
        except (Program.DoesNotExist, Semester.DoesNotExist):
            pass

    return render(request, 'grades/maquette_list.html', {
        'programs': programs,
        'semesters': semesters,
        'academic_years': academic_years,
        'selected_year': selected_year,
        'previous_year_with_maquettes': previous_year_with_maquettes,
        'has_maquettes_for_selected_year': has_maquettes_for_selected_year,
        'selected_program': selected_program,
        'selected_semester': selected_semester,
        'ues': ues,
        'totals': totals,
    })


@login_required
def maquette_ue_create(request):
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('grades:maquette_list')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    if dept:
        programs = Program.objects.filter(department=dept)
    elif faculty:
        programs = Program.objects.filter(department__faculty=faculty)
    else:
        programs = Program.objects.none()
    semesters = Semester.objects.select_related('academic_year').order_by('-academic_year__start_date', 'number')
    if faculty:
        semesters = semesters.filter(academic_year__faculty=faculty)
    elif dept:
        semesters = semesters.filter(academic_year__faculty=dept.faculty)
    else:
        semesters = semesters.none()

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        title = request.POST.get('title', '').strip()
        program_id = request.POST.get('program')
        semester_id = request.POST.get('semester')
        credits = request.POST.get('credits', 6)
        order = request.POST.get('order', 1)

        if not (code and title and program_id and semester_id):
            messages.error(request, "Tous les champs sont obligatoires.")
        else:
            try:
                program = Program.objects.get(pk=program_id)
                semester = Semester.objects.get(pk=semester_id)
                ue = UniteEnseignement.objects.create(
                    code=code, title=title, program=program, semester=semester,
                    credits=int(credits), order=int(order)
                )
                messages.success(request, f"UE {ue.code} créée. Affectez maintenant les modules (EC).")
                return redirect(reverse('grades:maquette_assign_subjects', kwargs={'pk': ue.pk}))
            except Exception as e:
                messages.error(request, f"Erreur : {e}")

    return render(request, 'grades/maquette_ue_form.html', {
        'programs': programs,
        'semesters': semesters,
        'form_title': 'Créer une UE',
        'prog_id': request.GET.get('program'),
        'sem_id': request.GET.get('semester'),
    })


@login_required
def maquette_ue_edit(request, pk):
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('grades:maquette_list')

    ue = get_object_or_404(UniteEnseignement, pk=pk)
    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    if dept:
        programs = Program.objects.filter(department=dept)
    elif faculty:
        programs = Program.objects.filter(department__faculty=faculty)
    else:
        programs = Program.objects.none()
    semesters = Semester.objects.select_related('academic_year').order_by('-academic_year__start_date', 'number')
    if faculty:
        semesters = semesters.filter(academic_year__faculty=faculty)
    elif dept:
        semesters = semesters.filter(academic_year__faculty=dept.faculty)
    else:
        semesters = semesters.none()

    if request.method == 'POST':
        ue.code = request.POST.get('code', ue.code).strip()
        ue.title = request.POST.get('title', ue.title).strip()
        ue.credits = int(request.POST.get('credits', ue.credits))
        ue.order = int(request.POST.get('order', ue.order))
        ue.save()
        messages.success(request, f"UE {ue.code} mise à jour.")
        return redirect(f"{'/grades/maquette/list/'}?program={ue.program_id}&semester={ue.semester_id}")

    return render(request, 'grades/maquette_ue_form.html', {
        'ue': ue,
        'programs': programs,
        'semesters': semesters,
        'form_title': f'Modifier UE — {ue.code}',
    })


@login_required
def maquette_ue_delete(request, pk):
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('grades:maquette_list')
    ue = get_object_or_404(UniteEnseignement, pk=pk)
    prog_id = ue.program_id
    sem_id = ue.semester_id
    ue.delete()
    messages.success(request, "UE supprimée.")
    return redirect(f"/grades/maquette/list/?program={prog_id}&semester={sem_id}")


def _unique_subject_code(base_code, year_label):
    """Génère un code de module (EC) unique (Subject.code est unique platforme-wide)."""
    candidate = f"{base_code}-{year_label}"
    if not Subject.objects.filter(code=candidate).exists():
        return candidate
    i = 2
    while Subject.objects.filter(code=f"{candidate}-{i}").exists():
        i += 1
    return f"{candidate}-{i}"


@login_required
def maquette_duplicate(request):
    """
    Duplique le Référentiel des Maquettes (UE + modules EC) d'une année
    académique précédente vers une année académique cible (en général
    l'année en cours), en faisant correspondre les semestres des deux années
    par (niveau, numéro). Ne touche ni aux notes, ni aux bulletins, ni au
    cahier de texte — uniquement la structure du programme.
    """
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('grades:maquette_list')

    from academic_core.apps.academic_structure.models import AcademicYear

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    fac_for_years = faculty or (dept.faculty if dept else None)

    target_year_id = request.GET.get('year') or request.POST.get('year')
    source_year_id = request.GET.get('source') or request.POST.get('source')

    academic_years = AcademicYear.objects.all().order_by('-start_date')
    academic_years = academic_years.filter(faculty=fac_for_years) if fac_for_years else academic_years.none()

    target_year = academic_years.filter(pk=target_year_id).first()
    source_year = academic_years.filter(pk=source_year_id).first()

    if not target_year or not source_year:
        messages.error(request, "Année académique cible ou source introuvable.")
        return redirect('grades:maquette_list')
    if target_year.pk == source_year.pk:
        messages.error(request, "L'année source et l'année cible doivent être différentes.")
        return redirect(f"/grades/maquette/list/?year={target_year.pk}")

    programs = Program.objects.all()
    if dept:
        programs = programs.filter(department=dept)
    elif faculty:
        programs = programs.filter(department__faculty=faculty)
    else:
        programs = programs.none()

    # Correspondance des semestres source → cible, par (niveau, numéro) :
    # le numéro est attribué automatiquement par niveau à la création d'un
    # semestre (cf. _lmd_base_offset), donc stable d'une année sur l'autre
    # tant que les semestres sont recréés dans le même ordre par niveau.
    source_semesters = Semester.objects.filter(academic_year=source_year).select_related('level')
    target_semesters = Semester.objects.filter(academic_year=target_year).select_related('level')
    target_by_key = {(s.level_id, s.number): s for s in target_semesters}

    preview_rows = []
    for sem in source_semesters.order_by('level__order', 'number'):
        ues = UniteEnseignement.objects.filter(
            semester=sem, program__in=programs
        ).select_related('program').prefetch_related('subjects').order_by('program__name', 'order', 'code')
        target_sem = target_by_key.get((sem.level_id, sem.number))
        for ue in ues:
            preview_rows.append({
                'source_semester': sem,
                'target_semester': target_sem,
                'ue': ue,
                'subject_count': ue.subjects.count(),
                'already_exists': (
                    target_sem is not None and
                    UniteEnseignement.objects.filter(code=ue.code, program=ue.program, semester=target_sem).exists()
                ),
            })

    if request.method == 'POST':
        created_ue = created_subjects = skipped_existing = skipped_no_semester = 0
        with transaction.atomic():
            for row in preview_rows:
                ue = row['ue']
                target_sem = row['target_semester']
                if not target_sem:
                    skipped_no_semester += 1
                    continue
                if row['already_exists']:
                    skipped_existing += 1
                    continue
                new_ue = UniteEnseignement.objects.create(
                    code=ue.code, title=ue.title, program=ue.program,
                    semester=target_sem, credits=ue.credits, order=ue.order,
                )
                created_ue += 1
                for subj in ue.subjects.all():
                    Subject.objects.create(
                        code=_unique_subject_code(subj.code, target_year.label),
                        title=subj.title, program=subj.program,
                        semester=target_sem, subject_type=subj.subject_type,
                        coefficient=subj.coefficient,
                        volume_cm=subj.volume_cm, volume_td=subj.volume_td,
                        volume_tp=subj.volume_tp, volume_tpe=subj.volume_tpe,
                        ue=new_ue, description=subj.description,
                    )
                    created_subjects += 1

        msg = f"{created_ue} UE et {created_subjects} module(s) (EC) dupliqués depuis {source_year.label} vers {target_year.label}."
        if skipped_existing:
            msg += f" {skipped_existing} UE déjà existante(s) ignorée(s)."
        if skipped_no_semester:
            msg += (
                f" {skipped_no_semester} UE ignorée(s) : semestre correspondant non créé "
                f"dans {target_year.label} (à créer d'abord dans Gestion de la Scolarité)."
            )
        messages.success(request, msg)
        return redirect(f"/grades/maquette/list/?year={target_year.pk}")

    return render(request, 'grades/maquette_duplicate.html', {
        'source_year': source_year,
        'target_year': target_year,
        'preview_rows': preview_rows,
    })


@login_required
def maquette_assign_subjects(request, pk):
    """Assign/unassign subjects (ECs) to a UE."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('grades:maquette_list')

    ue = get_object_or_404(
        UniteEnseignement.objects.select_related('program', 'semester'),
        pk=pk
    )
    # Subjects belonging to same program/semester
    available = sorted(
        Subject.objects.filter(program=ue.program, semester=ue.semester),
        key=lambda s: natural_sort_key(s.code),
    )

    if request.method == 'POST':
        selected_ids = request.POST.getlist('subjects')
        # Clear current assignments for this UE
        Subject.objects.filter(ue=ue).update(ue=None)
        # Assign selected
        if selected_ids:
            Subject.objects.filter(pk__in=selected_ids).update(ue=ue)
        # Auto-compute UE credits = sum of EC volume_hours / 20, arrondi au supérieur
        import math
        ec_total_hours = Subject.objects.filter(ue=ue).aggregate(
            total=db_models.Sum('volume_hours')
        )['total'] or 0
        ue.credits = max(1, math.ceil(float(ec_total_hours) / 20)) if ec_total_hours > 0 else 0
        ue.save(update_fields=['credits'])
        messages.success(request, f"{len(selected_ids)} module(s) (EC) assigné(s) à {ue.code}. Crédits UE recalculés : {ue.credits}.")
        return redirect(f"/grades/maquette/list/?program={ue.program_id}&semester={ue.semester_id}")

    assigned_ids = {s.pk for s in available if s.ue_id == ue.pk}

    return render(request, 'grades/maquette_assign_subjects.html', {
        'ue': ue,
        'available': available,
        'assigned_ids': assigned_ids,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# LMD — BULLETINS
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def bulletin_class_list(request):
    """Admin: choose a class to view/generate bulletins."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('dashboard:index')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    from academic_core.apps.academic_structure.models import AcademicYear, Level
    years = AcademicYear.objects.all().order_by('-start_date')
    selected_year = None
    level_groups = []

    year_id = request.GET.get('year')
    if year_id:
        try:
            selected_year = years.get(pk=year_id)
            classes_qs = Class.objects.filter(
                academic_year=selected_year
            ).select_related('program__department', 'level')
            if dept:
                classes_qs = classes_qs.filter(program__department=dept)
            elif faculty:
                classes_qs = classes_qs.filter(program__department__faculty=faculty)
            else:
                classes_qs = classes_qs.none()
            classes = list(classes_qs.order_by('name'))

            # Un semestre n'est pertinent pour une classe que s'il partage son
            # niveau (numérotation LMD par cycle : L1/M1 -> S1/S2, L2/M2 ->
            # S3/S4, L3 -> S5/S6) — sans ce filtre, toutes les classes
            # affichaient tous les semestres de l'année, quel que soit leur niveau.
            semesters_by_level = {}
            for sem in selected_year.semesters.select_related('level').order_by('number'):
                semesters_by_level.setdefault(sem.level_id, []).append(sem)
            for cls in classes:
                cls.relevant_semesters = semesters_by_level.get(cls.level_id, [])

            # Regrouper par niveau LMD (Licence 1, Licence 2, Licence 3,
            # Master 1, Master 2...) — seuls les niveaux ayant au moins une
            # classe avec des étudiants inscrits sont affichés (une classe
            # sans étudiant n'a aucun bulletin à gérer).
            classes_by_level = {}
            for cls in classes:
                if cls.student_count > 0:
                    classes_by_level.setdefault(cls.level_id, []).append(cls)
            for level in Level.objects.order_by('order'):
                lvl_classes = classes_by_level.get(level.pk, [])
                if lvl_classes:
                    level_groups.append({
                        'level': level,
                        'classes': lvl_classes,
                    })
            # Classes sans niveau renseigné (cas résiduel) en dernier groupe.
            orphan_classes = classes_by_level.get(None, [])
            if orphan_classes:
                level_groups.append({'level': None, 'classes': orphan_classes})
        except Exception:
            pass

    return render(request, 'grades/bulletin_class_list.html', {
        'years': years,
        'selected_year': selected_year,
        'level_groups': level_groups,
    })


@login_required
def bulletin_list(request, class_id, semester_id):
    """Admin: list of students in a class with bulletin status."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user').order_by('student__user__last_name')

    enrollment_map = {e.student_id: e for e in enrollments}
    students = [e.student for e in enrollments]

    # Map existing bulletins
    bulletin_map = {
        b.student_id: b
        for b in Bulletin.objects.filter(
            student__in=students, semester=semester
        )
    }

    student_rows = []
    for s in students:
        saved = bulletin_map.get(s.pk)
        # Toujours calculer en live pour avoir les détails UE/EC
        live = compute_bulletin_data(s, semester, class_group)
        if saved:
            row_data = {
                'semester_average':       saved.semester_average,
                'mention':                saved.mention,
                'total_credits_obtained': saved.total_credits_obtained,
                'total_credits_possible': saved.total_credits_possible,
            }
        elif live:
            row_data = {
                'semester_average':       live['semester_average'],
                'mention':                live['mention'],
                'total_credits_obtained': live['total_credits_obtained'],
                'total_credits_possible': live['total_credits_possible'],
            }
        else:
            row_data = {
                'semester_average': None, 'mention': '',
                'total_credits_obtained': None, 'total_credits_possible': None,
            }

        enr = enrollment_map.get(s.pk)
        payment_validated = enr is not None and enr.status == Enrollment.STATUS_VALIDATED

        # Détail UE/EC depuis compute_bulletin_data
        ue_data_list = live['ue_list'] if live else []
        # Toutes UEs validées ?
        all_ues_validated = bool(ue_data_list) and all(ud['is_validated'] for ud in ue_data_list)

        # Vérification comptable des mensualités
        acad_year = enr.academic_year if enr else class_group.academic_year
        pay_status = check_bulletin_payment_clearance(s, acad_year)

        student_rows.append({
            'student':            s,
            'enrollment':         enr,
            'bulletin':           saved,
            'data':               row_data,
            'payment_validated':  payment_validated,
            'ue_data_list':       ue_data_list,
            'all_ues_validated':  all_ues_validated,
            # Statut affiché ("Actif"/"INACTIF") : basé sur la validation de
            # CETTE inscription précise (class_group + statut VALIDATED, déjà
            # garanti par la requête `enrollments` ci-dessus), PAS sur
            # `Enrollment.is_active` — ce flag global est mis à False par une
            # réinscription ultérieure (voir ReinscriptionView.post), y
            # compris sur les inscriptions passées déjà validées. Sans ce
            # correctif, un étudiant réinscrit apparaît "INACTIF" dans la
            # liste de sa classe/année d'origine alors que son bulletin y est
            # bien validé et doit rester pleinement accessible.
            'is_active':          payment_validated,
            'pay_status':         pay_status,
        })

    # Available semesters for navigation — uniquement ceux du même niveau LMD
    # que la classe (cf. bulletin_class_list) : sans ce filtre, une L1
    # affichait aussi les semestres S3/S4/S5/S6 d'autres niveaux.
    semesters = Semester.objects.filter(
        academic_year=class_group.academic_year, level=class_group.level,
    ).order_by('number')

    return render(request, 'grades/bulletin_list.html', {
        'class_group': class_group,
        'semester': semester,
        'semesters': semesters,
        'student_rows': student_rows,
    })


@login_required
def enrollment_toggle_active(request, class_id, semester_id, enrollment_id):
    """
    Désactive un étudiant de la liste de délibération : équivaut à un abandon
    (inscrit sur la liste des abandons, compte désactivé, disparaît de toutes
    les listes de classe). Réintégrable depuis la liste des abandons.
    """
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)

    enr = get_object_or_404(Enrollment.objects.select_related('student__user'), pk=enrollment_id)
    student = enr.student

    if enr.is_active:
        # Désactivation = abandon (même mécanisme que la liste des abandons)
        enr.status            = Enrollment.STATUS_ABANDONED
        enr.is_active          = False
        enr.status_changed_at  = timezone.now()
        enr.status_changed_by  = request.user
        enr.status_reason      = "Désactivé(e) depuis la liste de délibération (Gestion des Bulletins)."
        enr.save(update_fields=[
            'status', 'is_active', 'status_changed_at', 'status_changed_by', 'status_reason',
        ])
        student.user.__class__.objects.filter(pk=student.user_id).update(is_active=False)
        messages.success(
            request,
            f"Étudiant {student.full_name} désactivé et inscrit sur la liste des abandons. "
            f"Réintégrable depuis « Abandons »."
        )
    else:
        # Réactivation : annule l'abandon (même mécanisme que la liste des abandons)
        enr.status            = Enrollment.STATUS_VALIDATED
        enr.is_active          = True
        enr.status_changed_at  = None
        enr.status_changed_by  = None
        enr.status_reason      = ''
        enr.save(update_fields=[
            'status', 'is_active', 'status_changed_at', 'status_changed_by', 'status_reason',
        ])
        student.user.__class__.objects.filter(pk=student.user_id).update(is_active=True)
        messages.success(request, f"Étudiant {student.full_name} réactivé avec succès.")

    return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)


@login_required
def bulletin_generate_class(request, class_id, semester_id):
    """Generate/refresh all bulletins for a class/semester."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)

    if request.method != 'POST':
        return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student')

    count = 0
    for enr in enrollments:
        b = save_bulletin(enr.student, semester, class_group, request.user)
        if b:
            count += 1

    messages.success(request, f"{count} bulletin(s) générés pour {class_group.name} — {semester}.")
    return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)


@login_required
def bulletin_detail(request, pk):
    """View a single bulletin (from saved data)."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    bulletin = get_object_or_404(
        Bulletin.objects.select_related(
            'student__user', 'semester__academic_year', 'class_group__program__department'
        ), pk=pk
    )
    ue_results = list(bulletin.ue_results.prefetch_related(
        'ec_results__subject'
    ).select_related('ue').order_by('order'))
    # Tri naturel des EC par code (EC2 < EC10, pas l'inverse comme le
    # donnerait un tri alphabétique) — le Meta.ordering du modèle ne peut
    # trier qu'alphabétiquement au niveau SQL, donc on retrie ici et on
    # réinjecte dans le cache de prefetch pour que le template (qui appelle
    # ur.ec_results.all) voie directement l'ordre corrigé.
    for _ur in ue_results:
        _sorted_ecs = sorted(_ur.ec_results.all(), key=lambda ec: natural_sort_key(ec.subject.code))
        _ur._prefetched_objects_cache['ec_results'] = _sorted_ecs

    # Cross-semester annual recap — même niveau LMD que la classe du bulletin,
    # sinon on pouvait récupérer le semestre d'un tout autre niveau.
    from .services import _get_saved_sem_data, _mention
    other_sem = Semester.objects.filter(
        academic_year=bulletin.semester.academic_year,
        level=bulletin.class_group.level,
    ).exclude(pk=bulletin.semester.pk).order_by('number').first()

    s1_credits_obtained = s1_credits_possible = s1_average = None
    s2_credits_obtained = s2_credits_possible = s2_average = None

    # S1/S3/S5 (numéro impair) = premier semestre de la paire de son niveau ;
    # S2/S4/S6 (numéro pair) = second — cf. pdf_bulletin.py::is_first_of_pair.
    is_first_of_pair = bulletin.semester.number % 2 == 1
    own_num  = bulletin.semester.number
    peer_num = other_sem.number if other_sem else (own_num + 1 if is_first_of_pair else own_num - 1)
    s1_num, s2_num = (own_num, peer_num) if is_first_of_pair else (peer_num, own_num)

    if bulletin.semester.number % 2 == 1:
        s1_credits_obtained = bulletin.total_credits_obtained
        s1_credits_possible = bulletin.total_credits_possible
        s1_average = bulletin.semester_average
        if other_sem:
            d = _get_saved_sem_data(bulletin.student, other_sem)
            if d:
                s2_credits_obtained = d['credits_obtained']
                s2_credits_possible = d['credits_possible']
                s2_average = d['average']
    else:
        s2_credits_obtained = bulletin.total_credits_obtained
        s2_credits_possible = bulletin.total_credits_possible
        s2_average = bulletin.semester_average
        if other_sem:
            d = _get_saved_sem_data(bulletin.student, other_sem)
            if d:
                s1_credits_obtained = d['credits_obtained']
                s1_credits_possible = d['credits_possible']
                s1_average = d['average']
            # Si bulletin S1 non sauvegardé, calculer à la volée
            if s1_credits_obtained is None:
                from .services import compute_bulletin_data as _cbd
                _s1 = _cbd(bulletin.student, other_sem, bulletin.class_group)
                if _s1:
                    s1_credits_obtained = _s1['total_credits_obtained']
                    s1_credits_possible = _s1['total_credits_possible']
                    s1_average = _s1['semester_average']

    from decimal import Decimal
    annual_credits_obtained = annual_credits_possible = annual_average = None
    annual_mention = ''
    if s1_credits_obtained is not None and s2_credits_obtained is not None:
        annual_credits_obtained = s1_credits_obtained + s2_credits_obtained
        annual_credits_possible = (s1_credits_possible or 0) + (s2_credits_possible or 0)
        if s1_average and s2_average and annual_credits_possible:
            s1_w = Decimal(str(s1_average)) * Decimal(str(s1_credits_possible or 0))
            s2_w = Decimal(str(s2_average)) * Decimal(str(s2_credits_possible or 0))
            from decimal import ROUND_HALF_UP
            annual_average = (s1_w + s2_w) / Decimal(str(annual_credits_possible))
            annual_average = annual_average.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            annual_mention = _mention(annual_average)

    return render(request, 'grades/bulletin_detail.html', {
        'bulletin': bulletin,
        'ue_results': ue_results,
        'is_first_of_pair': is_first_of_pair,
        's1_num': s1_num,
        's2_num': s2_num,
        's1_credits_obtained': s1_credits_obtained,
        's1_credits_possible': s1_credits_possible,
        's1_average': s1_average,
        's2_credits_obtained': s2_credits_obtained,
        's2_credits_possible': s2_credits_possible,
        's2_average': s2_average,
        'annual_credits_obtained': annual_credits_obtained,
        'annual_credits_possible': annual_credits_possible,
        'annual_average': annual_average,
        'annual_mention': annual_mention,
    })


@login_required
def _build_preview_context(request, data, student, semester, class_group, is_sr=False, **extra):
    """Enrichit le contexte preview avec les mêmes données que le PDF."""
    from academic_core.apps.academic_structure.models import BulletinConfig
    from academic_core.pdf_utils import get_institut_config_for_request
    from .models import Bulletin as _Bul
    from academic_core.apps.academic_structure.models import Semester as _Sem
    from academic_core.apps.attendance.models import StudentAttendance as _SA

    # Absences (identique PDF)
    try:
        absence_count = _SA.objects.filter(
            student=student,
            status__in=['ABSENT', 'JUSTIFIED'],
            attendance_sheet__timetable_entry__semester=semester,
        ).count()
    except Exception:
        absence_count = 0

    # BulletinConfig (titre/nom directeur)
    bulletin_config = BulletinConfig.get()

    # Bulletin du semestre pair (pour récap croisé S1/S2)
    peer_bul = None
    peer_sem = None
    s1_ue_list = []
    s2_ue_list = []
    s1_cr_obt = s1_cr_pos = s1_avg = None
    s2_cr_obt = s2_cr_pos = s2_avg = None
    # Cf. pdf_bulletin.py::peer_sem — recherche par niveau, pas par numéro
    # littéral 1/2 (numérotation à plat sur tout le cursus).
    try:
        peer_sem = _Sem.objects.filter(
            academic_year=semester.academic_year,
            level=semester.level,
        ).exclude(pk=semester.pk).order_by('number').first()
        if peer_sem:
            peer_bul = _Bul.objects.filter(student=student, semester=peer_sem).first()
    except Exception:
        pass

    # Cf. pdf_bulletin.py::is_first_of_pair / own_num / peer_num.
    is_first_of_pair = semester.number % 2 == 1
    own_num  = semester.number
    peer_num = peer_sem.number if peer_sem else (own_num + 1 if is_first_of_pair else own_num - 1)
    s1_num, s2_num = (own_num, peer_num) if is_first_of_pair else (peer_num, own_num)

    if is_first_of_pair:
        s1_cr_obt = data['total_credits_obtained']
        s1_cr_pos = data['total_credits_possible']
        s1_avg    = data['semester_average']
        s1_ue_list = data['ue_list']
        if peer_bul:
            s2_cr_obt = peer_bul.total_credits_obtained
            s2_cr_pos = peer_bul.total_credits_possible
            s2_avg    = peer_bul.semester_average
            try:
                s2_ue_list = list(peer_bul.ue_results.all().order_by('order'))
            except Exception:
                pass
    else:
        s2_cr_obt = data['total_credits_obtained']
        s2_cr_pos = data['total_credits_possible']
        s2_avg    = data['semester_average']
        s2_ue_list = data['ue_list']
        if peer_bul:
            s1_cr_obt = peer_bul.total_credits_obtained
            s1_cr_pos = peer_bul.total_credits_possible
            s1_avg    = peer_bul.semester_average
            try:
                s1_ue_list = list(peer_bul.ue_results.all().order_by('order'))
            except Exception:
                pass
        if not s1_ue_list and peer_sem:
            try:
                _s1 = compute_bulletin_data(student, peer_sem, class_group)
                if _s1:
                    s1_ue_list = _s1['ue_list']
                    if s1_cr_obt is None:
                        s1_cr_obt = _s1['total_credits_obtained']
                        s1_cr_pos = _s1['total_credits_possible']
                        s1_avg    = _s1['semester_average']
            except Exception:
                pass

    # Moyenne générale : (S1 + S2) / 2 (identique PDF)
    moy_gen = None
    if s1_avg is not None and s2_avg is not None:
        moy_gen = round((float(s1_avg) + float(s2_avg)) / 2, 2)

    total_cr_obt_global = (s1_cr_obt or 0) + (s2_cr_obt or 0)

    inst_cfg = get_institut_config_for_request(request)
    ctx = {
        'data': data,
        'student': student,
        'semester': semester,
        'is_first_of_pair': is_first_of_pair,
        's1_num': s1_num,
        's2_num': s2_num,
        'class_group': class_group,
        'is_sr': is_sr,
        'institut_config': inst_cfg,
        'absence_count': absence_count,
        'bulletin_config': bulletin_config,
        'peer_bul': peer_bul,
        's1_ue_list': s1_ue_list,
        's2_ue_list': s2_ue_list,
        's1_cr_obt': s1_cr_obt,
        's1_cr_pos': s1_cr_pos,
        's2_cr_obt': s2_cr_obt,
        's2_cr_pos': s2_cr_pos,
        's1_avg': s1_avg,
        's2_avg': s2_avg,
        'moy_gen': moy_gen,
        'total_cr_obt_global': total_cr_obt_global,
        'total_cr_pos_global': (s1_cr_pos or 0) + (s2_cr_pos or 0),
    }
    ctx.update(extra)
    return ctx


def bulletin_preview(request, class_id, semester_id, student_id):
    """Compute and display bulletin on-the-fly (not saved)."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    student = get_object_or_404(Student, pk=student_id)

    # Vérification comptable
    enr = student.enrollments.filter(class_group=class_group, status=Enrollment.STATUS_VALIDATED).first()
    acad_year = enr.academic_year if enr else class_group.academic_year
    pay_status = check_bulletin_payment_clearance(student, acad_year)
    if not pay_status.is_cleared:
        months_str = ', '.join(pay_status.unpaid_month_labels)
        messages.error(
            request,
            f"Bulletin bloqué — {student.user.get_full_name()} n'a pas réglé "
            f"les mensualités suivantes : {months_str}. "
            f"Montant dû : {pay_status.total_due:,.0f} FCFA."
        )
        return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)

    data = compute_bulletin_data(student, semester, class_group)
    if data is None:
        messages.error(request, "Impossible de calculer le bulletin. Vérifiez la maquette de formation.")
        return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)

    ctx = _build_preview_context(request, data, student, semester, class_group, is_sr=False)
    return render(request, 'grades/bulletin_preview.html', ctx)


@login_required
def bulletin_pdf(request, class_id, semester_id, student_id):
    """Generate bulletin PDF for a student."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    student = get_object_or_404(Student, pk=student_id)

    # Vérification comptable
    enr = student.enrollments.filter(class_group=class_group, status=Enrollment.STATUS_VALIDATED).first()
    acad_year = enr.academic_year if enr else class_group.academic_year
    pay_status = check_bulletin_payment_clearance(student, acad_year)
    if not pay_status.is_cleared:
        months_str = ', '.join(pay_status.unpaid_month_labels)
        messages.error(
            request,
            f"Impression impossible — {student.user.get_full_name()} a des mensualités impayées : "
            f"{months_str}. Montant dû : {pay_status.total_due:,.0f} FCFA."
        )
        return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)

    data = compute_bulletin_data(student, semester, class_group)
    if data is None:
        messages.error(request, "Maquette de formation introuvable.")
        return redirect('grades:bulletin_list', class_id=class_id, semester_id=semester_id)

    from .pdf_bulletin import generate_bulletin_pdf
    from academic_core.pdf_utils import get_institut_config_for_request
    is_sr = request.GET.get('sr', '0') == '1'
    inst_cfg = get_institut_config_for_request(request)
    pdf_bytes = generate_bulletin_pdf(data, is_sr=is_sr, institut_config=inst_cfg)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    student_name = f"{student.user.last_name}_{student.user.first_name}"
    response['Content-Disposition'] = (
        f'attachment; filename="bulletin_{student_name}_S{semester.number}.pdf"'
    )
    return response


@login_required
def bulletin_publish(request, pk):
    """Toggle bulletin status DRAFT -> PUBLISHED."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    bulletin = get_object_or_404(Bulletin, pk=pk)
    if request.method == 'POST':
        if bulletin.status == Bulletin.STATUS_DRAFT:
            bulletin.status = Bulletin.STATUS_PUBLISHED
            messages.success(request, "Bulletin publié.")
        elif bulletin.status == Bulletin.STATUS_PUBLISHED:
            bulletin.status = Bulletin.STATUS_LOCKED
            messages.success(request, "Bulletin verrouillé définitivement.")
        bulletin.save(update_fields=['status'])
    return redirect('grades:bulletin_detail', pk=pk)


# ═══════════════════════════════════════════════════════════════════════════════
# IMPORT CSV NOTES
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def get_ecs_for_import(request):
    """Retourne en JSON la liste des ECs pour une classe+semestre donnés."""
    class_id = request.GET.get('class_id')
    sem_id   = request.GET.get('semester_id')
    if not class_id or not sem_id:
        return JsonResponse({'ecs': []})
    try:
        class_group = Class.objects.get(pk=class_id)
        semester    = Semester.objects.get(pk=sem_id)
    except (Class.DoesNotExist, Semester.DoesNotExist):
        return JsonResponse({'ecs': []})

    program = class_group.program
    ues = UniteEnseignement.objects.filter(
        program=program, semester=semester
    ).prefetch_related('subjects').order_by('order', 'code')

    ecs = []
    for ue in ues:
        for subj in sorted(ue.subjects.all(), key=lambda s: natural_sort_key(s.code)):
            ecs.append({
                'id':    subj.pk,
                'code':  subj.code,
                'title': subj.title,
                'ue':    f'{ue.code} — {ue.title}',
            })
    return JsonResponse({'ecs': ecs})


@login_required
def download_notes_template(request):
    """
    Télécharge un modèle Excel (.xlsx) pour un EC précis — même forme et mêmes
    colonnes de saisie que le modèle par EC de la page Examens & Concours
    (bandeau d'information sur 5 lignes, colonnes Devoir 1 / Devoir 2 / TP /
    Examen saisies brutes, sans moyenne pré-calculée par formule).
    La colonne « Code EC » est conservée en plus (lecture seule) car ce modèle
    générique peut être importé sans présélectionner l'EC (voir import_notes_csv).
    """
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    class_id   = request.GET.get('class_id')
    sem_id     = request.GET.get('semester_id')
    subject_id = request.GET.get('subject_id')

    class_group = get_object_or_404(Class,    pk=class_id)   if class_id   else None
    semester    = get_object_or_404(Semester, pk=sem_id)     if sem_id     else None
    subject     = get_object_or_404(Subject,  pk=subject_id) if subject_id else None

    if not subject or not class_group or not semester:
        messages.error(request, "Veuillez sélectionner la classe, le semestre et l'EC.")
        return redirect('grades:import_notes_csv')

    anon = _is_anon_requested(request)

    wb = Workbook()
    ws = wb.active
    ws.title = subject.code[:31]

    NAVY_HEX   = '003D82'
    BORDER_HEX = 'CBD5E1'

    def _border():
        s = Side(style='thin', color=BORDER_HEX)
        return Border(left=s, right=s, top=s, bottom=s)

    navy_fill  = PatternFill('solid', fgColor=NAVY_HEX)
    light_fill = PatternFill('solid', fgColor='EFF6FF')
    white_fill = PatternFill('solid', fgColor='FFFFFF')

    # ── Bandeau d'information (5 lignes) ────────────────────────────────────────
    # Seules les lignes 1 (titre) et 5 (avertissement) sont fusionnées A:H : les
    # lignes 2-4 gardent deux cellules distinctes (libellé + valeur) — les fusionner
    # aurait effacé la valeur de la 2e cellule (seule la cellule haut-gauche d'une
    # plage fusionnée conserve sa valeur dans openpyxl).
    info_rows = [
        ("MODÈLE D'IMPORT DES NOTES (ANONYME)" if anon else "MODÈLE D'IMPORT DES NOTES",),
        ("Module (EC) :", f"{subject.code} — {subject.title}"),
        ("Classe :", class_group.name),
        ("Semestre :", str(semester)),
        ("⚠ Ne modifiez pas la colonne Matricule ni Code EC. Remplissez les colonnes Devoir 1 / Devoir 2 / TP / Examen (sur 20).",),
    ]
    for r, row in enumerate(info_rows, 1):
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=val)
            if r == 1:
                cell.font = Font(name='Calibri', bold=True, size=13, color='FFFFFF')
                cell.fill = navy_fill
                cell.alignment = Alignment(horizontal='center')
            elif r == 5:
                cell.font = Font(name='Calibri', bold=True, size=10, color='92400E')
                cell.fill = PatternFill('solid', fgColor='FDE68A')
            elif c == 1:
                cell.font = Font(name='Calibri', bold=True, size=10, color=NAVY_HEX)
        if r in (1, 5):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    ws.row_dimensions[1].height = 26

    # ── Ligne 7 : en-têtes colonnes ──────────────────────────────────────────────
    header_row_num = 7
    col_headers = ['Matricule', 'Nom', 'Prénom', 'Code EC', 'Devoir 1', 'Devoir 2', 'TP', 'Examen']
    for col_idx, hdr in enumerate(col_headers, start=1):
        c = ws.cell(row=header_row_num, column=col_idx, value=hdr)
        c.font      = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
        c.fill      = navy_fill
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border    = _border()
    ws.row_dimensions[header_row_num].height = 22

    # ── Lignes étudiants ────────────────────────────────────────────────────────
    enrollments = list(
        Enrollment.objects.filter(
            class_group=class_group,
            academic_year=semester.academic_year,
            status=Enrollment.STATUS_VALIDATED,
        ).select_related('student__user').order_by('student__user__last_name')
    )

    note_num_fmt = '0.00'
    for i, enr in enumerate(enrollments, start=1):
        student = enr.student
        row_idx = header_row_num + i
        bg = white_fill if i % 2 == 0 else light_fill

        nom, prenom = _name_cells(anon, i, student.user.last_name.upper(), student.user.first_name.title())
        data = [
            student.matricule or '',
            nom,
            prenom,
            subject.code,
        ]
        for col_idx, val in enumerate(data, start=1):
            c = ws.cell(row=row_idx, column=col_idx, value=val)
            c.fill      = bg
            c.border    = _border()
            c.alignment = Alignment(vertical='center')
            if col_idx == 4:  # code_ec en lecture seule visuellement
                c.font = Font(color='64748B')

        # Devoir 1 / Devoir 2 / TP / Examen (col 5-8) — saisie manuelle, fond jaune
        for col_idx in (5, 6, 7, 8):
            c = ws.cell(row=row_idx, column=col_idx, value=None)
            c.fill           = PatternFill('solid', fgColor='FFFBEB')
            c.border         = _border()
            c.number_format  = note_num_fmt
            c.alignment      = Alignment(horizontal='center', vertical='center')

        ws.row_dimensions[row_idx].height = 18

    # ── Validation données notes (0-20) — colonnes Devoir 1, Devoir 2, TP, Examen ──
    n_students = len(enrollments) or 100
    last_data_row = header_row_num + n_students
    dv = DataValidation(
        type='decimal',
        operator='between',
        formula1='0',
        formula2='20',
        showErrorMessage=True,
        errorTitle='Note invalide',
        error='La note doit être comprise entre 0 et 20.',
    )
    ws.add_data_validation(dv)
    dv.add(f'E{header_row_num + 1}:H{last_data_row}')

    # ── Largeurs colonnes ──────────────────────────────────────────────────────
    col_widths = [16, 20, 20, 14, 12, 12, 12, 12]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = f'A{header_row_num + 1}'

    # ── Réponse HTTP ──────────────────────────────────────────────────────────
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    import re, unicodedata
    def _slug(s):
        s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
        return re.sub(r'[^\w]', '_', s).strip('_')

    anon_suffix = '_ANONYME' if anon else ''
    filename = f"Modele_Notes_{_slug(subject.title)}_{_slug(class_group.name)}_S{semester.number}{anon_suffix}.xlsx"

    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@transaction.atomic
def import_notes_csv(request):
    """
    Import des notes depuis un fichier Excel (.xlsx) — même format que le modèle
    par EC de la page Examens & Concours : bandeau d'information de hauteur
    variable au-dessus, puis une ligne d'en-tête de colonnes (repérée en
    cherchant la colonne « Matricule »). Colonnes attendues (insensible à la
    casse, ordre libre) : Matricule | Nom | Prénom | Code EC | Devoir 1 |
    Devoir 2 | TP | Examen. La colonne Code EC reste nécessaire ici (contrairement
    au modèle par EC de la page Examens & Concours) car ce formulaire générique
    n'impose pas de présélectionner l'EC : celui-ci est déterminé ligne par ligne,
    ce qui permet même d'importer plusieurs EC en une fois (un onglet par EC).
    """
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    # Année académique : par défaut l'année en cours — l'import de notes ne
    # doit pas proposer des classes/semestres d'une année précédente mélangés
    # avec l'année en cours. "Toutes les années" (year=all) reste disponible.
    from academic_core.apps.academic_structure.models import AcademicYear
    fac_for_years = faculty or (dept.faculty if dept else None)
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=fac_for_years) if fac_for_years else academic_years.none()
    year_param = request.GET.get('year')
    if year_param == 'all':
        selected_year = None
    elif year_param:
        selected_year = academic_years.filter(pk=year_param).first()
    else:
        selected_year = academic_years.filter(is_current=True).first()

    semesters = Semester.objects.select_related('academic_year').order_by(
        '-academic_year__start_date', 'number'
    )
    if faculty:
        semesters = semesters.filter(academic_year__faculty=faculty)
    classes = Class.objects.select_related('program').order_by('name')
    if dept:
        classes = classes.filter(program__department=dept)
    elif faculty:
        classes = classes.filter(program__department__faculty=faculty)
    if selected_year:
        semesters = semesters.filter(academic_year=selected_year)
        classes = classes.filter(academic_year=selected_year)

    context = {
        'semesters': semesters, 'classes': classes,
        'academic_years': academic_years,
        'selected_year_param': year_param or '',
    }

    if request.method != 'POST':
        return render(request, 'grades/import_notes.html', context)

    class_id   = request.POST.get('class_id')
    sem_id     = request.POST.get('semester_id')
    xlsx_file  = request.FILES.get('csv_file')

    if not class_id or not sem_id or not xlsx_file:
        messages.error(request, "Veuillez sélectionner la classe, le semestre et le fichier Excel.")
        return render(request, 'grades/import_notes.html', context)

    class_group = get_object_or_404(Class,    pk=class_id)
    semester    = get_object_or_404(Semester, pk=sem_id)

    if semester.is_locked:
        messages.error(request, semester.lock_message)
        return render(request, 'grades/import_notes.html', context)

    import datetime
    from openpyxl import load_workbook

    errors  = []
    created = 0
    updated = 0
    skipped = 0

    _students_cache   = {}
    _subjects_cache   = {}
    _eval_types_cache = {et.code: et for et in EvaluationType.objects.all()}
    _evals_cache      = {}
    today = datetime.date.today()

    def _save_grade(row_no, matricule, code_ec, type_key, note_raw):
        note_str = str(note_raw).strip() if note_raw is not None else ''
        if note_str in ('', 'None'):
            return 'skip'
        try:
            note_val = Decimal(str(note_raw).replace(',', '.'))
            note_max = Decimal('20')
        except Exception:
            errors.append(f"Ligne {row_no} : note invalide « {note_raw} »")
            return 'error'
        if note_val < 0 or note_val > note_max:
            errors.append(f"Ligne {row_no} : note {note_val} hors plage [0, 20]")
            return 'error'

        if matricule not in _students_cache:
            try:
                _students_cache[matricule] = Student.objects.get(matricule=matricule)
            except Student.DoesNotExist:
                errors.append(f"Ligne {row_no} : matricule introuvable « {matricule} »")
                _students_cache[matricule] = None
        student = _students_cache[matricule]
        if student is None:
            return 'error'

        if code_ec not in _subjects_cache:
            try:
                _subjects_cache[code_ec] = Subject.objects.get(code=code_ec)
            except Subject.DoesNotExist:
                errors.append(f"Ligne {row_no} : EC introuvable « {code_ec} »")
                _subjects_cache[code_ec] = None
        subject = _subjects_cache[code_ec]
        if subject is None:
            return 'error'

        eval_type = _eval_types_cache.get(type_key)
        if eval_type is None:
            # Créer à la volée si le type n'existe pas encore
            eval_type, _ = EvaluationType.objects.get_or_create(
                code=type_key,
                defaults={'label': type_key, 'weight': Decimal('1.00')},
            )
            _eval_types_cache[type_key] = eval_type

        eval_key = (subject.pk, eval_type.pk, semester.pk, class_group.pk)
        if eval_key not in _evals_cache:
            evaluation, _ = Evaluation.objects.get_or_create(
                subject=subject,
                evaluation_type=eval_type,
                semester=semester,
                class_group=class_group,
                defaults={
                    'title':     f'{type_key} - {subject.code} (import Excel)',
                    'date':      today,
                    'max_score': note_max,
                },
            )
            _evals_cache[eval_key] = evaluation
        evaluation = _evals_cache[eval_key]

        _, created_flag = Grade.objects.update_or_create(
            student=student,
            evaluation=evaluation,
            defaults={'score': note_val},
        )
        return 'created' if created_flag else 'updated'

    try:
        wb = load_workbook(filename=io.BytesIO(xlsx_file.read()), read_only=True, data_only=True)
    except Exception as e:
        messages.error(request, f"Impossible de lire le fichier Excel : {e}")
        return render(request, 'grades/import_notes.html', context)

    def _col(header_row, keywords):
        for kw in keywords:
            for i, h in enumerate(header_row):
                if kw in h:
                    return i
        return None

    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            continue

        # Recherche de la ligne d'en-tête (contient « matricule ») parmi les
        # premières lignes — tolère un bandeau d'information de hauteur
        # variable au-dessus, comme dans le modèle téléchargeable.
        header_idx = None
        col_mat = col_ec = col_d1 = col_d2 = col_tp = col_cc = col_exam = None
        for i, row in enumerate(rows[:10]):
            candidate = [str(c).strip().lower() if c else '' for c in row]
            non_empty = [c for c in candidate if c]
            if len(non_empty) < 2:
                continue
            mat_idx = None
            for ci, h in enumerate(candidate):
                if h == 'matricule' or (len(h) <= 20 and 'matricule' in h):
                    mat_idx = ci
                    break
            if mat_idx is not None:
                header_idx = i
                col_mat  = mat_idx
                col_ec   = _col(candidate, ['code ec', 'code_ec'])
                col_d1   = _col(candidate, ['devoir 1', 'devoir1', 'd1'])
                col_d2   = _col(candidate, ['devoir 2', 'devoir2', 'd2'])
                col_tp   = _col(candidate, ['tp'])
                col_cc   = _col(candidate, ['note cc', 'note_cc', 'cc (calculé)', 'cc'])
                col_exam = _col(candidate, ['note exam', 'note_exam', 'examen', 'exam'])
                break

        if header_idx is None or col_ec is None:
            errors.append(f"Feuille « {sheet.title} » : colonnes Matricule ou Code EC introuvables.")
            continue

        # Si le fichier contient Devoir 1 / Devoir 2 / TP, on importe ces types
        # bruts (comme le modèle par EC de la page Examens & Concours). Sinon,
        # compatibilité ascendante : on importe la colonne CC directement.
        has_devoirs = col_d1 is not None or col_d2 is not None or col_tp is not None

        for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            mat = str(row[col_mat]).strip() if col_mat is not None and col_mat < len(row) and row[col_mat] else ''
            ec  = str(row[col_ec]).strip()  if col_ec  is not None and col_ec  < len(row) and row[col_ec]  else ''

            if not mat or not ec or mat == 'None' or ec == 'None':
                skipped += 1
                continue

            if has_devoirs:
                grade_cols = [('DEVOIR1', col_d1), ('DEVOIR2', col_d2), ('TP', col_tp), ('EXAM', col_exam)]
            else:
                grade_cols = [('CC', col_cc), ('EXAM', col_exam)]

            for type_key, col_idx in grade_cols:
                if col_idx is None:
                    continue
                raw_val = row[col_idx] if col_idx < len(row) else None
                result  = _save_grade(row_idx, mat, ec, type_key, raw_val)
                if result == 'created':
                    created += 1
                elif result == 'updated':
                    updated += 1
                elif result == 'skip':
                    skipped += 1

    if errors and not created and not updated:
        messages.error(request, f"{len(errors)} erreur(s) — aucune note importée.")
    else:
        msg = f"Import terminé : {created} note(s) créée(s), {updated} mise(s) à jour, {skipped} ligne(s) ignorée(s)."
        if errors:
            msg += f" {len(errors)} avertissement(s)."
        messages.success(request, msg)

    context['errors']      = errors
    context['created']     = created
    context['updated']     = updated
    context['skipped']     = skipped
    context['class_group'] = class_group
    context['semester']    = semester
    return render(request, 'grades/import_notes.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE GRADE UPDATE  (AJAX)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def grade_inline_update(request):
    """
    AJAX POST — modifie ou supprime une note (CC / EXAM / RATTRAPAGE) pour un
    étudiant/EC/semestre.  Retourne les valeurs recalculées en JSON.
    """
    import json
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    student_id  = body.get('student_id')
    subject_id  = body.get('subject_id')
    semester_id = body.get('semester_id')
    class_id    = body.get('class_id')
    grade_type  = (body.get('grade_type') or 'CC').upper()
    score_raw   = body.get('score')

    # Saisie de rattrapage : ouverte aux mêmes rôles que la page
    # grades:rattrapage_list (CIAQ, Contrôleur Interne...), un sur-ensemble de
    # _admin_required — mais uniquement pour ce type de note, pas pour
    # CC/EXAM/DEVOIR qui restent réservés à _admin_required.
    is_authorized = (
        _admin_required(request)
        or (grade_type == 'RATTRAPAGE' and _rattrapage_required(request))
    )
    if not is_authorized:
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    try:
        student     = Student.objects.get(pk=student_id)
        subject     = Subject.objects.get(pk=subject_id)
        semester    = Semester.objects.get(pk=semester_id)
        class_group = Class.objects.get(pk=class_id)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=404)

    # Bloquer les modifications si le semestre est verrouillé par le contrôleur interne
    if semester.is_locked:
        return JsonResponse({'error': semester.lock_message}, status=403)

    # Bloquer les modifications de session normale si clôturée
    if semester.session_normale_closed and grade_type != 'RATTRAPAGE':
        return JsonResponse(
            {'error': 'Session normale clôturée. Seules les notes de rattrapage peuvent être modifiées.'},
            status=403
        )

    # Récupérer l'ancienne note avant modification
    _old_grade = Grade.objects.filter(
        student=student,
        evaluation__subject=subject,
        evaluation__semester=semester,
        evaluation__evaluation_type__code=grade_type,
        evaluation__class_group=class_group,
    ).select_related('evaluation').first()
    old_score = float(_old_grade.score) if _old_grade else None

    if score_raw in (None, ''):
        # Supprimer la note existante
        Grade.objects.filter(
            student=student,
            evaluation__subject=subject,
            evaluation__semester=semester,
            evaluation__evaluation_type__code=grade_type,
            evaluation__class_group=class_group,
        ).delete()
        _audit_action = 'DELETE'
        _new_score = None
    else:
        try:
            score = Decimal(str(score_raw).replace(',', '.'))
            if not (Decimal('0') <= score <= Decimal('20')):
                return JsonResponse({'error': 'Note doit être entre 0 et 20'}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({'error': 'Note invalide'}, status=400)

        eval_type = EvaluationType.objects.filter(code=grade_type).first()
        if not eval_type:
            eval_type, _ = EvaluationType.objects.get_or_create(
                code=grade_type,
                defaults={'label': grade_type, 'weight': Decimal('1.00')},
            )

        evaluation, _ = Evaluation.objects.get_or_create(
            subject=subject,
            semester=semester,
            class_group=class_group,
            evaluation_type=eval_type,
            defaults={
                'title': f'{grade_type} — {subject.code}',
                'date': timezone.now().date(),
                'max_score': Decimal('20'),
                'status': Evaluation.STATUS_GRADED,
            },
        )

        Grade.objects.update_or_create(
            student=student,
            evaluation=evaluation,
            defaults={'score': score, 'entered_by': request.user},
        )
        _audit_action = 'UPDATE'
        _new_score = float(score)

    # ── Audit log détaillé ────────────────────────────────────────────────────
    try:
        from academic_core.apps.accounts.models import AuditLog
        student_name = student.user.get_full_name() or student.user.username
        subject_label = f"{subject.code} — {subject.name}"
        _type_labels = {
            'DEVOIR1': 'Devoir 1', 'DEVOIR2': 'Devoir 2',
            'CC': 'CC', 'EXAM': 'Examen', 'RATTRAPAGE': 'Rattrapage',
            'TP': 'TP', 'PROJECT': 'Projet',
        }
        type_label = _type_labels.get(grade_type, grade_type)
        if _audit_action == 'DELETE':
            _desc = f"Suppression note {type_label} de {student_name} ({subject.code})"
        elif old_score is None:
            _desc = f"Saisie note {type_label} : {_new_score}/20 — {student_name} ({subject.code})"
        else:
            _desc = f"Modification note {type_label} : {old_score} → {_new_score}/20 — {student_name} ({subject.code})"

        AuditLog.objects.create(
            user=request.user,
            action=_audit_action,
            model_name='Grade',
            object_repr=f"{student_name} — {subject_label} — {type_label}",
            details=_desc[:500],
            url=request.path[:500],
            ip_address=getattr(request, 'real_ip', None) or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            changes={
                'etudiant':       student_name,
                'etudiant_id':    student.pk,
                'matricule':      getattr(student, 'matricule', ''),
                'matiere':        subject_label,
                'matiere_id':     subject.pk,
                'type_note':      type_label,
                'semestre':       semester.label,
                'classe':         class_group.name,
                'ancienne_note':  old_score,
                'nouvelle_note':  _new_score,
            },
        )
    except Exception:
        pass

    # Répercuter automatiquement la modification dans le bulletin de l'étudiant
    # (même mécanisme que le bouton "Valider"/"Revalider cet EC" des Examens &
    # Concours, mais limité à ce seul étudiant) — évite qu'un EC déjà validé
    # affiche un bulletin obsolète après une note modifiée ici.
    try:
        from .services import save_bulletin as _save_bulletin
        _save_bulletin(student, semester, class_group, request.user)
    except Exception:
        pass

    # Recalcul EC
    from .services import compute_ec_grade, _round2
    ec = compute_ec_grade(student, subject, semester)

    # Recalcul UE
    program = class_group.program
    ue = UniteEnseignement.objects.filter(
        program=program, semester=semester, subjects=subject
    ).first()

    ue_avg = None
    ue_validated = False
    if ue:
        weighted = Decimal('0')
        coeff_sum = Decimal('0')
        for subj in ue.subjects.all():
            ec2 = compute_ec_grade(student, subj, semester)
            f = ec2['final_average']
            c = subj.coefficient or Decimal('1')
            coeff_sum += c
            if f is not None:
                weighted += f * c
        if coeff_sum > 0:
            ue_avg = _round2(weighted / coeff_sum)
            ue_validated = ue_avg >= Decimal('10')

    def _f(v):
        return float(v) if v is not None else None

    final = ec['final_average']

    # Appréciation UE recalculée — même règle que compute_bulletin_data() :
    # l'UE est validée dès que sa moyenne pondérée est >= 10, quelles que
    # soient les moyennes des EC qui la composent (un EC "Non Validé" isolé
    # ne doit plus invalider l'UE, seul un EC "A faire" la laisse en attente).
    ue_appreciation = None
    ue_validated_by_rattrapage = False
    if ue:
        ec_apprs = []
        ec_ratt_flags = []
        for subj in ue.subjects.all():
            ec2 = compute_ec_grade(student, subj, semester)
            ec_apprs.append(ec2['appreciation'])
            ec_ratt_flags.append(ec2['validated_by_rattrapage'])
        if 'A faire' in ec_apprs:
            ue_appreciation = 'EC à composer'
        elif ue_avg is not None and ue_avg >= Decimal('10'):
            ue_appreciation = 'Validée'
        else:
            ue_appreciation = 'Non Validée'
        ue_validated = ue_appreciation == 'Validée'
        ue_validated_by_rattrapage = ue_validated and any(ec_ratt_flags)

    return JsonResponse({
        'd1':                       _f(ec['d1_score']),
        'd2':                       _f(ec['d2_score']),
        'cc':                       _f(ec['cc_average']),
        'exam':                     _f(ec['exam_score']),
        'ratt':                     _f(ec['rattrapage_score']),
        'final':                    _f(final),
        'appreciation':             ec['appreciation'],
        'validated_by_rattrapage':  ec['validated_by_rattrapage'],
        'ue_avg':                   _f(ue_avg),
        'ue_id':                    ue.pk if ue else None,
        'ue_validated':             ue_validated,
        'ue_validated_by_rattrapage': ue_validated_by_rattrapage,
        'ue_appreciation':          ue_appreciation,
        'ec_validated':             ec['is_validated'],
    })


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT NOTES — EXCEL
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def export_grades_excel(request, class_id, semester_id):
    """Export de toutes les notes d'une classe/semestre en fichier Excel."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('grades:bulletin_class_list')

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    class_group = get_object_or_404(Class,    pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)

    students = Student.objects.filter(
        enrollments__class_group=class_group,
        enrollments__academic_year=semester.academic_year,
        enrollments__status=Enrollment.STATUS_VALIDATED,
    ).select_related('user').order_by('user__last_name', 'user__first_name')

    program = class_group.program
    ues = list(UniteEnseignement.objects.filter(
        program=program, semester=semester
    ).prefetch_related('subjects').order_by('order', 'code'))

    wb = Workbook()
    ws = wb.active
    ws.title = f'Notes S{semester.number}'

    NAVY   = PatternFill('solid', fgColor='003D82')
    UE_BG  = PatternFill('solid', fgColor='DBEAFE')
    SUM_BG = PatternFill('solid', fgColor='EFF6FF')
    thin   = Side(style='thin', color='CBD5E1')
    brd    = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left   = Alignment(horizontal='left',   vertical='center')
    white_bold = Font(bold=True, color='FFFFFF', size=9)
    navy_bold  = Font(bold=True, color='003D82', size=9)

    # Titre
    total_data_cols = 4 + sum(len(list(ue.subjects.all())) * 4 for ue in ues) + 3
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_data_cols)
    title_cell = ws.cell(row=1, column=1,
        value=f'RELEVÉ DE NOTES — {class_group.name} — Semestre {semester.number} — {semester.academic_year}')
    title_cell.font = Font(bold=True, size=12, color='003D82')
    title_cell.alignment = center
    title_cell.fill = PatternFill('solid', fgColor='EFF6FF')
    ws.row_dimensions[1].height = 22

    # Ligne 2 : en-têtes groupes UE
    ws.cell(row=2, column=1, value='').fill = NAVY
    ws.cell(row=2, column=2, value='').fill = NAVY
    ws.cell(row=2, column=3, value='').fill = NAVY
    ws.cell(row=2, column=4, value='').fill = NAVY

    col = 5
    ue_col_ranges = []
    for ue in ues:
        subjects = sorted(ue.subjects.all(), key=lambda s: natural_sort_key(s.code))
        if not subjects:
            continue
        span = len(subjects) * 4
        ue_col_ranges.append((ue, col, col + span - 1))
        if span > 1:
            ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + span - 1)
        c = ws.cell(row=2, column=col, value=f'{ue.code} — {ue.title}')
        c.fill = NAVY
        c.font = white_bold
        c.alignment = center
        c.border = brd
        for ci in range(col + 1, col + span):
            ws.cell(row=2, column=ci).fill = NAVY
        col += span

    sum_start = col
    ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 2)
    c = ws.cell(row=2, column=col, value='Récapitulatif')
    c.fill = NAVY; c.font = white_bold; c.alignment = center; c.border = brd
    for ci in range(col + 1, col + 3):
        ws.cell(row=2, column=ci).fill = NAVY

    # Ligne 3 : sous-en-têtes
    for j, lbl in enumerate(['N°', 'Matricule', 'Nom', 'Prénom'], 1):
        c = ws.cell(row=3, column=j, value=lbl)
        c.fill = NAVY; c.font = white_bold; c.alignment = center; c.border = brd

    subject_col_map = []  # (subject, col, type_label)
    col = 5
    for ue in ues:
        subjects = sorted(ue.subjects.all(), key=lambda s: natural_sort_key(s.code))
        for subj in subjects:
            for lbl, gtype in [('CC (40%)', 'CC'), ('Examen (60%)', 'EXAM'), ('Rattrap.', 'RATT'), ('Moy EC', 'FINAL')]:
                c = ws.cell(row=3, column=col, value=lbl)
                c.fill = NAVY; c.font = white_bold; c.alignment = center; c.border = brd
                subject_col_map.append((subj, col, gtype))
                col += 1

    for lbl in ['Moy. S.', 'Crédits', 'Mention']:
        c = ws.cell(row=3, column=col, value=lbl)
        c.fill = NAVY; c.font = white_bold; c.alignment = center; c.border = brd
        col += 1

    ws.row_dimensions[2].height = 28
    ws.row_dimensions[3].height = 20
    ws.freeze_panes = 'E4'

    # Largeurs de colonnes
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 16
    for ci in range(5, col):
        ws.column_dimensions[get_column_letter(ci)].width = 10

    # Données
    from .services import compute_ec_grade, compute_bulletin_data, _round2
    for row_idx, student in enumerate(students, 1):
        row = row_idx + 3
        ws.cell(row=row, column=1, value=row_idx).alignment = center
        ws.cell(row=row, column=2, value=student.matricule).alignment = left
        ws.cell(row=row, column=3, value=student.user.last_name.upper()).alignment = left
        ws.cell(row=row, column=4, value=student.user.first_name.title()).alignment = left

        ec_cache = {}
        for subj, scol, gtype in subject_col_map:
            if subj.pk not in ec_cache:
                ec_cache[subj.pk] = compute_ec_grade(student, subj, semester)
            ec = ec_cache[subj.pk]
            val = {
                'CC':    ec['cc_average'],
                'EXAM':  ec['exam_score'],
                'RATT':  ec['rattrapage_score'],
                'FINAL': ec['final_average'],
            }.get(gtype)
            c = ws.cell(row=row, column=scol)
            c.value = float(val) if val is not None else None
            c.number_format = '0.00'
            c.alignment = center
            c.border = brd
            if val is not None:
                is_good = float(val) >= 10
                if gtype == 'FINAL':
                    c.font = Font(bold=True, color='166534' if is_good else 'DC2626', size=9)
                else:
                    c.font = Font(color='166534' if is_good else 'DC2626', size=9)

        bdata = compute_bulletin_data(student, semester, class_group)
        avg  = bdata['semester_average'] if bdata else None
        cred = bdata['total_credits_obtained'] if bdata else 0
        ment = bdata['mention'] if bdata else ''

        c = ws.cell(row=row, column=sum_start)
        c.value = float(avg) if avg is not None else None
        c.number_format = '0.00'
        c.alignment = center; c.border = brd
        c.font = Font(bold=True, size=10,
                      color='166534' if avg and float(avg) >= 10 else 'DC2626')

        c2 = ws.cell(row=row, column=sum_start + 1, value=cred)
        c2.alignment = center; c2.border = brd
        c2.font = Font(bold=True, size=9)

        c3 = ws.cell(row=row, column=sum_start + 2, value=ment)
        c3.alignment = center; c3.border = brd
        c3.font = Font(size=9)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = f'notes_{class_group.name}_S{semester.number}.xlsx'.replace(' ', '_')
    resp = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHIVE BULLETINS — ZIP DE PDFs
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_fname_part(part):
    """Nettoie un composant de nom de fichier (espaces → _, caractères interdits retirés)."""
    import re
    part = re.sub(r'\s+', '_', str(part).strip())
    return re.sub(r'[\\/:*?"<>|]', '', part)


@login_required
def archive_bulletins_zip(request, class_id, semester_id):
    """Génère un ZIP contenant les bulletins PDF de tous les étudiants d'une classe."""
    if not _admin_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('grades:bulletin_class_list')

    import zipfile
    from .pdf_bulletin import generate_bulletin_pdf
    from academic_core.pdf_utils import get_institut_config_for_request
    inst_cfg = get_institut_config_for_request(request)

    class_group = get_object_or_404(Class,    pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)

    students = Student.objects.filter(
        enrollments__class_group=class_group,
        enrollments__academic_year=semester.academic_year,
        enrollments__status=Enrollment.STATUS_VALIDATED,
    ).select_related('user').order_by('user__last_name', 'user__first_name')

    class_code = _safe_fname_part(class_group.code or class_group.name)
    annee      = _safe_fname_part(semester.academic_year)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for student in students:
            data = compute_bulletin_data(student, semester, class_group)
            if not data:
                continue
            try:
                pdf_bytes = generate_bulletin_pdf(data, institut_config=inst_cfg)
                full_name = _safe_fname_part(f'{student.user.first_name}_{student.user.last_name}')
                fname = f'Bulletin_S{semester.number}_{class_code}_{full_name}_{annee}.pdf'
                zf.writestr(fname, pdf_bytes)
            except Exception:
                pass

    zip_buf.seek(0)
    fname = f'bulletins_{class_group.name}_S{semester.number}.zip'.replace(' ', '_')
    resp = HttpResponse(zip_buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION BULLETIN
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def bulletin_config_edit(request):
    """Édition de la configuration du bulletin (signataire, titre) — ce réglage
    définit le signataire officiel de tous les bulletins de l'institut, pas une
    simple préférence de département. Accessible aux rôles ayant tous les
    droits (Administrateur, Administrateur d'institut, Administrateurs de
    direction, Contrôleur interne)."""
    if not (request.user.is_admin() or request.user.is_inst_admin()):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    config = BulletinConfig.get()

    if request.method == 'POST':
        director_title = request.POST.get('director_title', '').strip()
        director_name  = request.POST.get('director_name',  '').strip()
        if not director_title:
            messages.error(request, "Le titre du signataire est obligatoire.")
        else:
            config.director_title = director_title
            config.director_name  = director_name
            config.updated_by     = request.user
            config.save()
            messages.success(request, "Configuration du bulletin mise à jour.")
            return redirect('grades:bulletin_config_edit')

    return render(request, 'grades/bulletin_config.html', {'config': config})


# ═══════════════════════════════════════════════════════════════════════════════
# RATTRAPAGES
# ═══════════════════════════════════════════════════════════════════════════════

def _rattrapage_required(request):
    """Accessible aux admins, CIAQ, Contrôleur Interne et Chargé des Examens & Concours."""
    u = request.user
    return u.can_manage_dept() or u.is_ciaq() or u.is_controleur() or u.is_charge_examens_concours()


def _student_needs_rattrapage(student, semester, class_group):
    """
    Retourne (needs_rattrapage, data, ues_non_validees) pour un étudiant.
    Seules les UEs avec appreciation == 'Non Validée' déclenchent le rattrapage.
    'EC à composer' = notes pas encore saisies, pas un cas de rattrapage.
    """
    data = compute_bulletin_data(student, semester, class_group)
    if data is None:
        return False, None, []
    ues_non_validees = [
        ue for ue in data.get('ue_list', [])
        if ue.get('appreciation', '') == 'Non Validée'
    ]
    return len(ues_non_validees) > 0, data, ues_non_validees


@login_required
def rattrapage_class_list(request):
    """Sélection classe/année pour les rattrapages."""
    if not _rattrapage_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    from academic_core.apps.academic_structure.models import AcademicYear, Level
    years = AcademicYear.objects.all().order_by('-start_date')
    if faculty:
        years = years.filter(faculty=faculty)
    selected_year = None
    level_groups = []

    year_id = request.GET.get('year')
    if year_id:
        try:
            selected_year = years.get(pk=year_id)
            classes_qs = Class.objects.filter(
                academic_year=selected_year
            ).select_related('program__department', 'level')
            if dept:
                classes_qs = classes_qs.filter(program__department=dept)
            elif faculty:
                classes_qs = classes_qs.filter(program__department__faculty=faculty)
            else:
                classes_qs = classes_qs.none()
            classes = list(classes_qs.order_by('name'))

            # Cf. bulletin_class_list : ne montrer que les semestres du même
            # niveau LMD que la classe.
            semesters_by_level = {}
            for sem in selected_year.semesters.select_related('level').order_by('number'):
                semesters_by_level.setdefault(sem.level_id, []).append(sem)
            for cls in classes:
                cls.relevant_semesters = semesters_by_level.get(cls.level_id, [])

            # Regrouper par niveau LMD, même présentation que bulletin_class_list
            # (seuls les niveaux ayant au moins une classe avec des étudiants
            # inscrits sont affichés).
            classes_by_level = {}
            for cls in classes:
                if cls.student_count > 0:
                    classes_by_level.setdefault(cls.level_id, []).append(cls)
            for level in Level.objects.order_by('order'):
                lvl_classes = classes_by_level.get(level.pk, [])
                if lvl_classes:
                    level_groups.append({
                        'level': level,
                        'classes': lvl_classes,
                    })
            orphan_classes = classes_by_level.get(None, [])
            if orphan_classes:
                level_groups.append({'level': None, 'classes': orphan_classes})
        except Exception:
            pass

    return render(request, 'grades/rattrapage_class_list.html', {
        'years': years,
        'selected_year': selected_year,
        'level_groups': level_groups,
    })


@login_required
def rattrapage_list(request, class_id, semester_id):
    """Liste des étudiants nécessitant un rattrapage pour une classe/semestre."""
    if not _rattrapage_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user').order_by('student__user__last_name')

    # Uniquement les semestres du même niveau LMD que la classe (cf.
    # bulletin_class_list) — sinon d'autres niveaux apparaissaient aussi.
    semesters = Semester.objects.filter(
        academic_year=class_group.academic_year, level=class_group.level,
    ).order_by('number')

    student_rows = []
    all_count = 0
    for enr in enrollments:
        all_count += 1
        data = compute_bulletin_data(enr.student, semester, class_group)
        if data is None:
            continue
        ue_list = data.get('ue_list', [])
        # Une UE nécessite la session de rattrapage dès qu'elle n'est pas validée,
        # que ce soit parce qu'elle a été explicitement échouée ("Non Validée")
        # ou parce qu'aucune note n'a jamais été saisie ("EC à composer") — dans
        # les deux cas l'étudiant doit composer en rattrapage.
        ues_non_validees = [ue for ue in ue_list if not ue.get('is_validated')]
        ues_validees_sr  = [ue for ue in ue_list if ue.get('validated_by_rattrapage')]
        # Inclure l'étudiant s'il a des UEs non validées OU des UEs validées en SR
        if ues_non_validees or ues_validees_sr:
            student_rows.append({
                'student':         enr.student,
                'ues_non_validees': ues_non_validees,
                'ues_validees_sr':  ues_validees_sr,
                'ues_count':       len(ue_list),
                'all_validated_sr': not ues_non_validees and bool(ues_validees_sr),
                'data':            data,
            })

    return render(request, 'grades/rattrapage_list.html', {
        'class_group': class_group,
        'semester': semester,
        'semesters': semesters,
        'student_rows': student_rows,
        'all_count': all_count,
    })


@login_required
def rattrapage_preview(request, class_id, semester_id, student_id):
    """Aperçu du bulletin en session de rattrapage."""
    if not _rattrapage_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    student = get_object_or_404(Student, pk=student_id)

    data = compute_bulletin_data(student, semester, class_group)
    if data is None:
        messages.error(request, "Impossible de calculer le bulletin. Vérifiez la maquette.")
        return redirect('grades:rattrapage_list', class_id=class_id, semester_id=semester_id)

    back_url = reverse('grades:rattrapage_list', kwargs={'class_id': class_id, 'semester_id': semester_id})
    pdf_url  = reverse('grades:rattrapage_pdf',  kwargs={'class_id': class_id, 'semester_id': semester_id, 'student_id': student_id})

    ctx = _build_preview_context(request, data, student, semester, class_group, is_sr=True,
                                  back_url=back_url, pdf_url=pdf_url)
    return render(request, 'grades/bulletin_preview.html', ctx)


@login_required
def rattrapage_pdf(request, class_id, semester_id, student_id):
    """Génère le PDF du bulletin rattrapage (is_sr=True)."""
    if not _rattrapage_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    student = get_object_or_404(Student, pk=student_id)

    data = compute_bulletin_data(student, semester, class_group)
    if data is None:
        messages.error(request, "Maquette introuvable.")
        return redirect('grades:rattrapage_list', class_id=class_id, semester_id=semester_id)

    from .pdf_bulletin import generate_bulletin_pdf
    from academic_core.pdf_utils import get_institut_config_for_request
    inst_cfg = get_institut_config_for_request(request)
    pdf_bytes = generate_bulletin_pdf(data, is_sr=True, institut_config=inst_cfg)

    student_name = f"{student.user.last_name}_{student.user.first_name}"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="rattrapage_{student_name}_S{semester.number}.pdf"'
    )
    return response


@login_required
def rattrapage_archive_zip(request, class_id, semester_id):
    """ZIP des bulletins rattrapages de tous les étudiants concernés."""
    if not _rattrapage_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    import zipfile, io
    from .pdf_bulletin import generate_bulletin_pdf
    from academic_core.pdf_utils import get_institut_config_for_request
    inst_cfg = get_institut_config_for_request(request)

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user')

    class_code = _safe_fname_part(class_group.code or class_group.name)
    annee      = _safe_fname_part(semester.academic_year)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for enr in enrollments:
            needs, data, _ = _student_needs_rattrapage(enr.student, semester, class_group)
            if not needs or data is None:
                continue
            try:
                pdf_bytes = generate_bulletin_pdf(data, is_sr=True, institut_config=inst_cfg)
                full_name = _safe_fname_part(f'{enr.student.user.first_name}_{enr.student.user.last_name}')
                fname = f'Bulletin_Rattrapage_S{semester.number}_{class_code}_{full_name}_{annee}.pdf'
                zf.writestr(fname, pdf_bytes)
            except Exception:
                pass

    zip_buf.seek(0)
    fname = f'rattrapages_{class_group.name}_S{semester.number}.zip'.replace(' ', '_')
    resp = HttpResponse(zip_buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# CLÔTURE DE SESSION (Contrôleur interne)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def gestion_cloture(request):
    """
    Page de gestion des clôtures de session pour le contrôleur interne.
    Liste les semestres actifs avec leur état de session.
    """
    if not request.user.is_controleur():
        messages.error(request, "Accès réservé au contrôleur interne.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import AcademicYear, Class
    faculty = getattr(request, 'active_faculty', None)
    current_year_qs = AcademicYear.objects.filter(is_current=True)
    semesters = Semester.objects.filter(
        academic_year__is_current=True
    ).select_related('academic_year', 'level', 'session_normale_closed_by').order_by('level__order', 'number')
    if faculty:
        current_year_qs = current_year_qs.filter(faculty=faculty)
        semesters = semesters.filter(academic_year__faculty=faculty)
    current_year = current_year_qs.first()

    # Regrouper par (année académique, niveau, semestre) et ne garder que les
    # classes du niveau ayant des étudiants inscrits — un semestre sans
    # aucune classe inscrite n'a rien à clôturer et n'est pas affiché.
    # NB: Class.student_count exige en plus status='VALIDATED', un critère
    # administratif plus strict que celui utilisé par bulletin_list/
    # rattrapage_list (Enrollment.is_active seul) — l'utiliser ici masquerait
    # à tort des classes ayant de vrais étudiants avec notes à clôturer.
    semester_groups = []
    for sem in semesters:
        if not sem.level_id:
            continue
        classes = list(
            Class.objects.filter(academic_year=sem.academic_year, level=sem.level)
            .order_by('name')
        )
        classes_with_students = []
        for c in classes:
            count = Enrollment.objects.filter(class_group=c, status=Enrollment.STATUS_VALIDATED).count()
            if count > 0:
                c.enrolled_count = count
                classes_with_students.append(c)
        if not classes_with_students:
            continue
        semester_groups.append({
            'semester': sem,
            'classes':  classes_with_students,
        })

    return render(request, 'grades/gestion_cloture.html', {
        'semester_groups': semester_groups,
        'current_year':    current_year,
    })


@login_required
def close_session_normale(request, semester_id):
    """
    Clôture la session normale d'un semestre :
    - Verrouille toutes les évaluations non-RATTRAPAGE du semestre
    - Verrouille tous les bulletins du semestre (DRAFT/PUBLISHED → LOCKED)
    - Active la session de rattrapage
    Réservé au contrôleur interne.
    """
    if not request.user.is_controleur():
        messages.error(request, "Accès réservé au contrôleur interne.")
        return redirect('dashboard:index')

    semester = get_object_or_404(Semester, pk=semester_id)

    if semester.session_normale_closed:
        messages.warning(request, f"La session normale du {semester} est déjà clôturée.")
        return redirect('grades:gestion_cloture')

    if request.method != 'POST':
        return redirect('grades:gestion_cloture')

    now = timezone.now()

    with transaction.atomic():
        # 1. Verrouiller toutes les évaluations de session normale (non-RATTRAPAGE)
        evals_to_lock = Evaluation.objects.filter(
            semester=semester, is_locked=False
        ).exclude(evaluation_type__code='RATTRAPAGE')

        locked_count = evals_to_lock.count()
        evals_to_lock.update(
            is_locked=True,
            locked_at=now,
            locked_by=request.user,
            status=Evaluation.STATUS_LOCKED,
        )

        # 2. Verrouiller tous les bulletins non encore verrouillés
        bulletins_to_lock = Bulletin.objects.filter(
            semester=semester
        ).exclude(status=Bulletin.STATUS_LOCKED)

        bulletins_count = bulletins_to_lock.count()
        bulletins_to_lock.update(status=Bulletin.STATUS_LOCKED)

        # 3. Marquer le semestre : session normale clôturée, rattrapage activé
        semester.session_normale_closed    = True
        semester.session_normale_closed_at = now
        semester.session_normale_closed_by = request.user
        semester.session_rattrapage_active = True
        semester.save(update_fields=[
            'session_normale_closed',
            'session_normale_closed_at',
            'session_normale_closed_by',
            'session_rattrapage_active',
        ])

    messages.success(
        request,
        f"Session normale du {semester} clôturée. "
        f"{locked_count} évaluation(s) et {bulletins_count} bulletin(s) verrouillé(s). "
        f"Session de rattrapage activée."
    )
    return redirect('grades:gestion_cloture')


@login_required
def reopen_session_normale(request, semester_id):
    """
    Réouvre la session normale d'un semestre (annule la clôture) :
    - Déverrouille les évaluations non-RATTRAPAGE verrouillées lors de la clôture
    - Déverrouille les bulletins (LOCKED → PUBLISHED si notes saisies, sinon DRAFT)
    - Désactive la session de rattrapage
    Réservé au contrôleur interne.
    """
    if not request.user.is_controleur():
        messages.error(request, "Accès réservé au contrôleur interne.")
        return redirect('dashboard:index')

    semester = get_object_or_404(Semester, pk=semester_id)

    if not semester.session_normale_closed:
        messages.warning(request, f"La session normale du {semester} n'est pas clôturée.")
        return redirect('grades:gestion_cloture')

    if request.method != 'POST':
        return redirect('grades:gestion_cloture')

    with transaction.atomic():
        # 1. Déverrouiller les évaluations non-RATTRAPAGE verrouillées
        evals_unlocked = Evaluation.objects.filter(
            semester=semester, is_locked=True
        ).exclude(evaluation_type__code='RATTRAPAGE').update(
            is_locked=False,
            locked_at=None,
            locked_by=None,
            status=Evaluation.STATUS_GRADED,
        )

        # 2. Déverrouiller les bulletins (LOCKED → PUBLISHED)
        bulletins_unlocked = Bulletin.objects.filter(
            semester=semester, status=Bulletin.STATUS_LOCKED
        ).update(status=Bulletin.STATUS_PUBLISHED)

        # 3. Réinitialiser les champs de clôture du semestre
        semester.session_normale_closed    = False
        semester.session_normale_closed_at = None
        semester.session_normale_closed_by = None
        semester.session_rattrapage_active = False
        semester.save(update_fields=[
            'session_normale_closed',
            'session_normale_closed_at',
            'session_normale_closed_by',
            'session_rattrapage_active',
        ])

    messages.success(
        request,
        f"Session normale du {semester} réouverte. "
        f"{evals_unlocked} évaluation(s) et {bulletins_unlocked} bulletin(s) déverrouillé(s). "
        f"Session de rattrapage désactivée."
    )
    return redirect('grades:gestion_cloture')


@login_required
def lock_semester(request, semester_id):
    """
    Verrouille l'accès à un semestre : verrouille en même temps le semestre,
    la session normale ET la session de rattrapage — plus aucune modification
    (notes, évaluations, bulletins, cahier de texte, présences...) n'y sera
    autorisée, y compris les notes de rattrapage. Ouvre automatiquement tous
    les autres semestres de la même année académique. Réservé au contrôleur
    interne — seul un déverrouillage par ses soins permet à nouveau les
    modifications.
    """
    if not request.user.is_controleur():
        messages.error(request, "Accès réservé au contrôleur interne.")
        return redirect('dashboard:index')

    semester = get_object_or_404(Semester, pk=semester_id)

    if request.method != 'POST':
        return redirect('grades:gestion_cloture')

    now = timezone.now()

    with transaction.atomic():
        semester.is_locked = True
        semester.locked_at = now
        semester.locked_by = request.user
        # Verrouiller aussi la session normale et la session de rattrapage :
        # un semestre verrouillé doit être totalement figé.
        semester.session_normale_closed    = True
        semester.session_normale_closed_at = semester.session_normale_closed_at or now
        semester.session_normale_closed_by = semester.session_normale_closed_by or request.user
        semester.session_rattrapage_active = True
        semester.save(update_fields=[
            'is_locked', 'locked_at', 'locked_by',
            'session_normale_closed', 'session_normale_closed_at', 'session_normale_closed_by',
            'session_rattrapage_active',
        ])

        # Verrouiller TOUTES les évaluations du semestre, y compris celles de
        # rattrapage (contrairement à la simple clôture de session normale qui
        # les exempte) : aucune saisie de note n'est plus possible.
        evals_to_lock = Evaluation.objects.filter(semester=semester, is_locked=False)
        locked_count = evals_to_lock.count()
        evals_to_lock.update(
            is_locked=True, locked_at=now, locked_by=request.user,
            status=Evaluation.STATUS_LOCKED,
        )

        # Verrouiller tous les bulletins du semestre
        bulletins_to_lock = Bulletin.objects.filter(semester=semester).exclude(status=Bulletin.STATUS_LOCKED)
        bulletins_count = bulletins_to_lock.count()
        bulletins_to_lock.update(status=Bulletin.STATUS_LOCKED)

        # Ouvre automatiquement les autres semestres de la même année académique
        Semester.objects.filter(
            academic_year=semester.academic_year, is_locked=True
        ).exclude(pk=semester.pk).update(
            is_locked=False, locked_at=None, locked_by=None,
        )

    messages.success(
        request,
        f"Le semestre « {semester} » est désormais entièrement verrouillé (semestre, session normale et "
        f"session de rattrapage). {locked_count} évaluation(s) et {bulletins_count} bulletin(s) verrouillé(s). "
        f"Seul le semestre ouvert accepte les modifications pour l'année {semester.academic_year}."
    )
    return redirect('grades:gestion_cloture')


@login_required
def unlock_semester(request, semester_id):
    """
    Déverrouille un semestre précédemment verrouillé : rouvre en même temps le
    semestre, la session normale et la session de rattrapage (déverrouille les
    évaluations et bulletins figés lors du verrouillage). N'affecte pas les
    autres semestres : s'ils étaient déjà ouverts, tous les semestres restent
    ouverts. Réservé au contrôleur interne.
    """
    if not request.user.is_controleur():
        messages.error(request, "Accès réservé au contrôleur interne.")
        return redirect('dashboard:index')

    semester = get_object_or_404(Semester, pk=semester_id)

    if not semester.is_locked:
        messages.warning(request, f"Le semestre « {semester} » n'est pas verrouillé.")
        return redirect('grades:gestion_cloture')

    if request.method != 'POST':
        return redirect('grades:gestion_cloture')

    with transaction.atomic():
        semester.is_locked = False
        semester.locked_at = None
        semester.locked_by = None
        semester.session_normale_closed    = False
        semester.session_normale_closed_at = None
        semester.session_normale_closed_by = None
        semester.session_rattrapage_active = False
        semester.save(update_fields=[
            'is_locked', 'locked_at', 'locked_by',
            'session_normale_closed', 'session_normale_closed_at', 'session_normale_closed_by',
            'session_rattrapage_active',
        ])

        evals_unlocked = Evaluation.objects.filter(semester=semester, is_locked=True).update(
            is_locked=False, locked_at=None, locked_by=None,
            status=Evaluation.STATUS_GRADED,
        )
        bulletins_unlocked = Bulletin.objects.filter(semester=semester, status=Bulletin.STATUS_LOCKED).update(
            status=Bulletin.STATUS_PUBLISHED,
        )

    messages.success(
        request,
        f"Le semestre « {semester} » est déverrouillé (semestre, session normale et session de rattrapage). "
        f"{evals_unlocked} évaluation(s) et {bulletins_unlocked} bulletin(s) déverrouillé(s). "
        f"Il reste ouvert aux côtés des autres semestres non verrouillés."
    )
    return redirect('grades:gestion_cloture')


# ═══════════════════════════════════════════════════════════════════════════════
# EXAMENS & CONCOURS — Validation des notes par la Direction des Études
# ═══════════════════════════════════════════════════════════════════════════════

def _examens_concours_required(request):
    """Accès réservé à la Direction des Études (+ profils de gestion habituels)."""
    return request.user.can_manage_dept() or request.user.is_charge_examens_concours()


def _ec_note_counts(class_group, semester, subject, student_ids):
    """
    Retourne un dict {'DEVOIR1': 1|0, 'DEVOIR2': 1|0, 'TP': 1|0, 'EXAM': 1|0}
    = 1 si au moins une note de ce type a été saisie pour cet EC, sinon 0.
    """
    codes = ('DEVOIR1', 'DEVOIR2', 'TP', 'EXAM')
    present = {code: 0 for code in codes}
    used_codes = Grade.objects.filter(
        student_id__in=student_ids,
        evaluation__subject=subject,
        evaluation__semester=semester,
        evaluation__class_group=class_group,
        evaluation__evaluation_type__code__in=codes,
    ).values_list('evaluation__evaluation_type__code', flat=True).distinct()
    for code in used_codes:
        present[code] = 1
    return present


def _semester_numbers_for_level(level_name):
    """Retourne les numéros de semestres à afficher selon le niveau."""
    if not level_name:
        return None
    import re as _re
    n = level_name.lower()
    if _re.search(r'licence\s*1|l\s*1\b|^l1$', n):
        return {1, 2}
    if _re.search(r'licence\s*2|l\s*2\b|^l2$', n):
        return {3, 4}
    if _re.search(r'licence\s*3|l\s*3\b|^l3$', n):
        return {5, 6}
    if _re.search(r'master\s*1|m\s*1\b|^m1$', n):
        return {1, 2}
    if _re.search(r'master\s*2|m\s*2\b|^m2$', n):
        return {3, 4}
    return None


@login_required
def examens_concours_class_list(request):
    """Direction des Études : choisir une classe/semestre à valider."""
    if not _examens_concours_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    from academic_core.apps.academic_structure.models import AcademicYear
    from collections import defaultdict
    years = AcademicYear.objects.all().order_by('-start_date')
    selected_year = None
    levels_data = []

    year_id = request.GET.get('year')
    if year_id:
        try:
            selected_year = years.get(pk=year_id)
            semesters_all = list(
                selected_year.semesters.all().order_by('number')
            )
            classes_qs = Class.objects.filter(
                academic_year=selected_year
            ).select_related('program__department', 'level')
            if dept:
                classes_qs = classes_qs.filter(program__department=dept)
            elif faculty:
                classes_qs = classes_qs.filter(program__department__faculty=faculty)
            else:
                classes_qs = classes_qs.none()

            # Group by level (preserve level.order)
            level_map = {}
            for cls in classes_qs.order_by('level__order', 'name'):
                level_obj = cls.level
                level_key = level_obj.pk if level_obj else None
                if level_key not in level_map:
                    level_map[level_key] = {
                        'level': level_obj,
                        'level_name': level_obj.name if level_obj else 'Sans niveau',
                        'level_order': level_obj.order if level_obj else 9999,
                        'classes': [],
                    }
                # Filtrage par la vraie relation Semester.level (fiable, ne
                # dépend pas d'un heuristique sur le champ number — cf.
                # _semester_numbers_for_level, conservé pour compatibilité
                # mais plus utilisé ici).
                filtered_sems = [s for s in semesters_all if s.level_id == level_key]
                level_map[level_key]['classes'].append({
                    'cls': cls,
                    'semesters': filtered_sems,
                })

            levels_data = sorted(level_map.values(), key=lambda x: x['level_order'])
        except Exception:
            pass

    return render(request, 'grades/examens_concours_class_list.html', {
        'years': years,
        'selected_year': selected_year,
        'levels_data': levels_data,
    })


@login_required
def examens_concours_detail(request, class_id, semester_id):
    """Liste, par UE puis EC, l'état des notes (D1/D2/TP/Exam) et permet la validation."""
    if not _examens_concours_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)

    student_ids = list(Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).values_list('student_id', flat=True))

    ues = UniteEnseignement.objects.filter(
        program=class_group.program, semester=semester
    ).prefetch_related('subjects__responsible_teacher__user').order_by('order', 'code')

    validations = {
        v.subject_id: v for v in ECValidation.objects.filter(
            class_group=class_group, semester=semester
        )
    }

    ue_rows = []
    for ue in ues:
        ec_rows = []
        for subj in sorted(ue.subjects.all(), key=lambda s: natural_sort_key(s.code)):
            teachers = list(Evaluation.objects.filter(
                subject=subj, semester=semester, class_group=class_group, teacher__isnull=False
            ).values_list('teacher__user__first_name', 'teacher__user__last_name').distinct())
            if teachers:
                teacher_label = ', '.join(f"{fn} {ln}".strip() for fn, ln in teachers)
            elif subj.responsible_teacher:
                teacher_label = subj.responsible_teacher.user.get_full_name()
            else:
                teacher_label = '—'

            ec_rows.append({
                'subject':    subj,
                'teacher':    teacher_label,
                'counts':     _ec_note_counts(class_group, semester, subj, student_ids),
                'validation': validations.get(subj.pk),
            })
        ue_rows.append({'ue': ue, 'ec_rows': ec_rows})

    semesters = Semester.objects.filter(
        academic_year=class_group.academic_year, level=class_group.level,
    ).order_by('number')

    return render(request, 'grades/examens_concours_detail.html', {
        'class_group': class_group,
        'semester': semester,
        'semesters': semesters,
        'ue_rows': ue_rows,
        'total_students': len(student_ids),
    })


@login_required
def examens_concours_ec_notes(request, class_id, semester_id, subject_id):
    """Détail des notes saisies par l'enseignant pour un EC (classe/semestre) — lecture seule."""
    if not _examens_concours_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    subject = get_object_or_404(Subject, pk=subject_id)

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user').order_by('student__user__last_name')

    raw_grades = Grade.objects.filter(
        student__in=[e.student_id for e in enrollments],
        evaluation__subject=subject,
        evaluation__semester=semester,
        evaluation__class_group=class_group,
    ).select_related('evaluation__evaluation_type')

    raw_by_student = {}
    for g in raw_grades:
        max_score = g.evaluation.max_score or Decimal('20')
        normalized = (g.score / max_score) * Decimal('20')
        raw_by_student.setdefault(g.student_id, {})[g.evaluation.evaluation_type.code] = normalized

    student_rows = []
    for e in enrollments:
        raw = raw_by_student.get(e.student_id, {})
        ec = compute_ec_grade(e.student, subject, semester)
        student_rows.append({
            'student':  e.student,
            'devoir1':  raw.get('DEVOIR1'),
            'devoir2':  raw.get('DEVOIR2'),
            'tp':       raw.get('TP'),
            'examen':   raw.get('EXAM'),
            'final_average': ec['final_average'],
            'appreciation':  ec['appreciation'],
        })

    teachers = list(Evaluation.objects.filter(
        subject=subject, semester=semester, class_group=class_group, teacher__isnull=False
    ).values_list('teacher__user__first_name', 'teacher__user__last_name').distinct())
    if teachers:
        teacher_label = ', '.join(f"{fn} {ln}".strip() for fn, ln in teachers)
    else:
        # Repli : aucune évaluation ne porte encore de professeur (ex. notes
        # importées depuis Excel) — on retrouve l'enseignant via l'emploi du
        # temps, puis via le professeur responsable de la matière.
        from academic_core.apps.timetable.models import TimetableEntry
        entry = TimetableEntry.objects.filter(
            subject=subject, semester=semester, class_group=class_group, teacher__isnull=False
        ).select_related('teacher__user').first()
        fallback_teacher = entry.teacher if entry else subject.responsible_teacher
        teacher_label = fallback_teacher.user.get_full_name() if fallback_teacher else '—'

    validation = ECValidation.objects.filter(
        subject=subject, class_group=class_group, semester=semester
    ).first()

    return render(request, 'grades/examens_concours_ec_notes.html', {
        'class_group':   class_group,
        'semester':      semester,
        'subject':       subject,
        'teacher_label': teacher_label,
        'student_rows':  student_rows,
        'validation':    validation,
    })


@login_required
def examens_concours_ec_template(request, class_id, semester_id, subject_id):
    """
    Génère le modèle Excel (.xlsx) à remplir pour l'import direct des notes
    d'un EC — pré-rempli avec les étudiants inscrits et leurs notes déjà
    saisies (Devoir 1 / Devoir 2 / TP / Examen), pour cette classe/semestre.
    """
    if not _examens_concours_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    subject = get_object_or_404(Subject, pk=subject_id)

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user').order_by('student__user__last_name')

    raw_grades = Grade.objects.filter(
        student__in=[e.student_id for e in enrollments],
        evaluation__subject=subject,
        evaluation__semester=semester,
        evaluation__class_group=class_group,
    ).select_related('evaluation__evaluation_type')

    raw_by_student = {}
    for g in raw_grades:
        max_score = g.evaluation.max_score or Decimal('20')
        normalized = (g.score / max_score) * Decimal('20')
        raw_by_student.setdefault(g.student_id, {})[g.evaluation.evaluation_type.code] = float(normalized)

    anon = _is_anon_requested(request)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        messages.error(request, "openpyxl non installé. Lancez : pip install openpyxl")
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notes"

    navy_fill  = PatternFill("solid", fgColor="003D82")
    light_fill = PatternFill("solid", fgColor="EFF6FF")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'), right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'), bottom=Side(style='thin', color='CBD5E1'),
    )

    # ── Bandeau d'information ───────────────────────────────────────────────
    info_rows = [
        ("MODÈLE D'IMPORT DES NOTES (ANONYME)" if anon else "MODÈLE D'IMPORT DES NOTES — Institut Supérieur d'Informatique - ISI",),
        ("Module (EC) :", f"{subject.code} — {subject.title}"),
        ("Classe :", class_group.name),
        ("Semestre :", str(semester)),
        ("⚠ Ne modifiez pas la colonne Matricule. Remplissez les colonnes Devoir 1 / Devoir 2 / TP / Examen (sur 20).",),
    ]
    for r, row in enumerate(info_rows, 1):
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=val)
            if r == 1:
                cell.font = Font(name='Calibri', bold=True, size=13, color='FFFFFF')
                cell.fill = navy_fill
                cell.alignment = Alignment(horizontal='center')
            elif r == 5:
                cell.font = Font(name='Calibri', bold=True, size=10, color='92400E')
                cell.fill = PatternFill("solid", fgColor="FDE68A")
            elif c == 1:
                cell.font = Font(name='Calibri', bold=True, size=10, color='003D82')
    ws.merge_cells('A1:G1')
    ws.merge_cells('A5:G5')
    ws.row_dimensions[1].height = 26

    # ── En-tête du tableau (ligne 7) ─────────────────────────────────────────
    header_row_num = 7
    headers = ["Matricule", "Nom", "Prénom", "Devoir 1", "Devoir 2", "TP", "Examen"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row_num, column=c, value=h)
        cell.font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border
    ws.row_dimensions[header_row_num].height = 22

    # ── Données étudiants ────────────────────────────────────────────────────
    for i, enr in enumerate(enrollments, 1):
        student = enr.student
        raw = raw_by_student.get(student.pk, {})
        row_num = header_row_num + i
        fill = light_fill if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        nom, prenom = _name_cells(anon, i, student.user.last_name.upper(), student.user.first_name.title())
        row_data = [
            student.matricule,
            nom,
            prenom,
            raw.get('DEVOIR1'),
            raw.get('DEVOIR2'),
            raw.get('TP'),
            raw.get('EXAM'),
        ]
        for c, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=c, value=val)
            cell.fill = fill
            cell.border = thin_border
            cell.font = Font(name='Calibri', size=10)
            if c >= 4:
                cell.alignment = Alignment(horizontal='center')

    ws.column_dimensions['A'].width = 16
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 20
    for col in ('D', 'E', 'F', 'G'):
        ws.column_dimensions[col].width = 12

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    import re, unicodedata
    def _slug(s):
        s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
        return re.sub(r'[^\w]', '_', s).strip('_')

    anon_suffix = '_ANONYME' if anon else ''
    filename = f"Modele_Notes_{_slug(subject.title)}_{_slug(class_group.name)}_S{semester.number}{anon_suffix}.xlsx"
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def examens_concours_ec_import(request, class_id, semester_id, subject_id):
    """
    Importe directement depuis un fichier Excel (.xlsx) les notes Devoir 1 /
    Devoir 2 / TP / Examen d'un EC pour une classe/semestre — sans avoir à
    ressaisir la classe, le semestre ou le code EC (déjà déterminés par la
    page). Colonnes attendues (insensible à la casse, ordre libre) :
    Matricule | Devoir 1 | Devoir 2 | TP | Examen.
    """
    if not _examens_concours_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    subject = get_object_or_404(Subject, pk=subject_id)

    if request.method != 'POST':
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    if semester.is_locked:
        messages.error(request, semester.lock_message)
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    xlsx_file = request.FILES.get('excel_file')
    if not xlsx_file:
        messages.error(request, "Veuillez sélectionner un fichier Excel.")
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    import datetime
    from openpyxl import load_workbook

    try:
        wb = load_workbook(filename=io.BytesIO(xlsx_file.read()), read_only=True, data_only=True)
    except Exception as e:
        messages.error(request, f"Impossible de lire le fichier Excel : {e}")
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    enrolled_matricules = set(
        Enrollment.objects.filter(class_group=class_group, status=Enrollment.STATUS_VALIDATED)
        .values_list('student__matricule', flat=True)
    )

    eval_types = {et.code: et for et in EvaluationType.objects.all()}
    evals_cache = {}

    def _get_evaluation(type_key):
        if type_key not in evals_cache:
            eval_type = eval_types.get(type_key)
            if eval_type is None:
                eval_type, _ = EvaluationType.objects.get_or_create(
                    code=type_key, defaults={'label': type_key, 'weight': Decimal('1.00')},
                )
                eval_types[type_key] = eval_type
            evaluation, _ = Evaluation.objects.get_or_create(
                subject=subject, evaluation_type=eval_type, semester=semester, class_group=class_group,
                defaults={
                    'title': f'{type_key} - {subject.code} (import Excel)',
                    'date': datetime.date.today(),
                    'max_score': Decimal('20'),
                },
            )
            evals_cache[type_key] = evaluation
        return evals_cache[type_key]

    errors  = []
    created = 0
    updated = 0
    skipped = 0

    sheet = wb.worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        messages.error(request, "Le fichier Excel est vide.")
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    def _col(header_row, keywords):
        for kw in keywords:
            for i, h in enumerate(header_row):
                if kw in h:
                    return i
        return None

    # Recherche de la ligne d'en-tête (contient "matricule") parmi les
    # premières lignes — tolère un éventuel bandeau d'information au-dessus,
    # comme dans le modèle téléchargeable. On exige que la cellule "matricule"
    # soit un libellé court (colonne dédiée) et que la ligne comporte plusieurs
    # colonnes renseignées, pour ne pas confondre avec une phrase d'info qui
    # mentionnerait ces mots en texte libre (ex. le bandeau d'avertissement).
    header_idx = None
    col_mat = col_d1 = col_d2 = col_tp = col_exam = None
    for i, row in enumerate(rows[:10]):
        candidate = [str(c).strip().lower() if c else '' for c in row]
        non_empty = [c for c in candidate if c]
        if len(non_empty) < 2:
            continue
        mat_idx = None
        for ci, h in enumerate(candidate):
            if h == 'matricule' or (len(h) <= 20 and 'matricule' in h):
                mat_idx = ci
                break
        if mat_idx is not None:
            header_idx = i
            col_mat  = mat_idx
            col_d1   = _col(candidate, ['devoir 1', 'devoir1', 'd1'])
            col_d2   = _col(candidate, ['devoir 2', 'devoir2', 'd2'])
            col_tp   = _col(candidate, ['tp'])
            col_exam = _col(candidate, ['examen', 'exam'])
            break

    if header_idx is None:
        messages.error(request, "Colonne « Matricule » introuvable dans le fichier Excel.")
        return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)

    grade_cols = [
        ('DEVOIR1', col_d1),
        ('DEVOIR2', col_d2),
        ('TP',      col_tp),
        ('EXAM',    col_exam),
    ]

    for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        mat = str(row[col_mat]).strip() if col_mat < len(row) and row[col_mat] else ''
        if not mat or mat == 'None':
            skipped += 1
            continue

        try:
            student = Student.objects.get(matricule=mat)
        except Student.DoesNotExist:
            errors.append(f"Ligne {row_idx} : matricule introuvable « {mat} »")
            continue

        if mat not in enrolled_matricules:
            errors.append(f"Ligne {row_idx} : « {mat} » n'est pas inscrit(e) dans « {class_group.name} »")
            continue

        for type_key, col_idx in grade_cols:
            if col_idx is None or col_idx >= len(row):
                continue
            note_raw = row[col_idx]
            note_str = str(note_raw).strip() if note_raw is not None else ''
            if note_str in ('', 'None'):
                continue
            try:
                note_val = Decimal(str(note_raw).replace(',', '.'))
            except Exception:
                errors.append(f"Ligne {row_idx} : note « {type_key} » invalide « {note_raw} »")
                continue
            if note_val < 0 or note_val > 20:
                errors.append(f"Ligne {row_idx} : note « {type_key} » {note_val} hors plage [0, 20]")
                continue

            evaluation = _get_evaluation(type_key)
            _, created_flag = Grade.objects.update_or_create(
                student=student, evaluation=evaluation, defaults={'score': note_val},
            )
            if created_flag:
                created += 1
            else:
                updated += 1

    if errors and not created and not updated:
        detail = " | ".join(errors[:5])
        if len(errors) > 5:
            detail += f" (+{len(errors) - 5} autre(s))"
        messages.error(request, f"{len(errors)} erreur(s) — aucune note importée. {detail}")
    else:
        msg = f"Import Excel terminé : {created} note(s) créée(s), {updated} mise(s) à jour, {skipped} ligne(s) ignorée(s)."
        if errors:
            msg += f" {len(errors)} avertissement(s) : " + " | ".join(errors[:5])
            if len(errors) > 5:
                msg += f" (+{len(errors) - 5} autre(s))"
        messages.success(request, msg)

    return redirect('grades:examens_concours_ec_notes', class_id=class_id, semester_id=semester_id, subject_id=subject_id)


@login_required
@transaction.atomic
def examens_concours_ec_validate(request, class_id, semester_id, subject_id):
    """
    Valide les notes d'un EC pour une classe/semestre : marque la validation
    et importe automatiquement les notes dans la gestion des bulletins
    (recalcul + sauvegarde du bulletin de chaque étudiant de la classe).
    """
    if not _examens_concours_required(request):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('grades:examens_concours_detail', class_id=class_id, semester_id=semester_id)

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    subject = get_object_or_404(Subject, pk=subject_id)

    if semester.is_locked:
        messages.error(request, semester.lock_message)
        return redirect('grades:examens_concours_detail', class_id=class_id, semester_id=semester_id)

    ECValidation.objects.update_or_create(
        subject=subject, class_group=class_group, semester=semester,
        defaults={
            'is_validated': True,
            'validated_by': request.user,
            'validated_at': timezone.now(),
        }
    )

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student')

    count = 0
    for enr in enrollments:
        b = save_bulletin(enr.student, semester, class_group, request.user)
        if b:
            count += 1

    messages.success(
        request,
        f"Notes de « {subject.title} » validées pour {class_group.name} — {semester}. "
        f"{count} bulletin(s) mis à jour."
    )
    return redirect('grades:examens_concours_detail', class_id=class_id, semester_id=semester_id)
