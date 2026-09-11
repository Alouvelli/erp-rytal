import json
from collections import defaultdict
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from .models import Subject
from .forms import SubjectForm


def _program_semester_rate_maps(request):
    """Cartes JSON pour le formulaire EC : programme → département, semestre
    → {niveau, année}, et (département, niveau, année) → taux horaire connu —
    permet d'afficher/pré-remplir le taux horaire dès que filière + semestre
    sont choisis, même principe que timetable/views.py::_class_level_map."""
    from academic_core.apps.academic_structure.models import Program, Semester
    from academic_core.apps.accounting.models import HourlyRate

    faculty = getattr(request, 'active_faculty', None)
    programs = Program.objects.select_related('department')
    semesters = Semester.objects.select_related('level', 'academic_year')
    rates = HourlyRate.objects.all()
    if faculty:
        programs = programs.filter(department__faculty=faculty)
        semesters = semesters.filter(academic_year__faculty=faculty)
        rates = rates.filter(department__faculty=faculty)

    program_dept = {p.pk: p.department_id for p in programs}
    semester_info = {
        s.pk: {
            'level_id': s.level_id,
            'level_name': str(s.level) if s.level else '',
            'year_id': s.academic_year_id,
        }
        for s in semesters
    }
    rate_map = {
        f'{r.department_id}-{r.level_id}-{r.academic_year_id}': float(r.rate_per_hour)
        for r in rates
    }
    return program_dept, semester_info, rate_map


class _AdminResponsableMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_manage_dept()


class SubjectListView(_AdminResponsableMixin, ListView):
    model = Subject
    template_name = 'subjects/list.html'
    context_object_name = 'subjects'

    def _resolve_academic_years(self):
        from academic_core.apps.academic_structure.models import AcademicYear
        faculty = getattr(self.request, 'active_faculty', None)
        years = AcademicYear.objects.order_by('-start_date')
        years = years.filter(faculty=faculty) if faculty else years.none()

        year_id = self.request.GET.get('annee')
        selected = years.filter(pk=year_id).first() if year_id else None
        if not selected:
            selected = years.filter(is_current=True).first() or years.first()
        return years, selected

    def get_queryset(self):
        self.academic_years, self.selected_year = self._resolve_academic_years()

        qs = Subject.objects.select_related(
            'program', 'semester__level', 'semester__academic_year', 'responsible_teacher__user'
        ).order_by('semester__number', 'code')
        faculty = getattr(self.request, 'active_faculty', None)
        if faculty:
            qs = qs.filter(program__department__faculty=faculty)
        if self.selected_year:
            # Les modules sans semestre (semester=None) ne sont rattachables à aucune
            # année : on les garde toujours visibles (voir no_level_subjects) plutôt
            # que de les masquer selon l'année sélectionnée.
            qs = qs.filter(
                Q(semester__academic_year=self.selected_year) | Q(semester__isnull=True)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from academic_core.apps.academic_structure.models import Class, Semester

        subjects = list(ctx['subjects'])

        # Précharger les classes correspondant à chaque (programme, niveau, année académique)
        # d'une matière, pour dériver la classe concernée (Subject n'a pas de FK directe vers Class).
        combos = {
            (s.program_id, s.semester.level_id, s.semester.academic_year_id)
            for s in subjects if s.semester and s.semester.level_id
        }
        classes_by_combo = defaultdict(list)
        if combos:
            prog_ids  = {c[0] for c in combos}
            level_ids = {c[1] for c in combos}
            year_ids  = {c[2] for c in combos}
            classes_qs = Class.objects.filter(
                program_id__in=prog_ids, level_id__in=level_ids, academic_year_id__in=year_ids,
            ).select_related('level', 'program', 'academic_year')
            for c in classes_qs:
                classes_by_combo[(c.program_id, c.level_id, c.academic_year_id)].append(c)

        # Structure : { level_id: {'level':, 'classes': { class_id_or_None: {'class_group':, 'semesters': {sem_id: {'semester':, 'subjects':[]}}}}}}
        level_map = {}
        no_level_subjects = []

        for subj in subjects:
            level = subj.semester.level if subj.semester else None
            if not level:
                no_level_subjects.append(subj)
                continue

            if level.pk not in level_map:
                level_map[level.pk] = {'level': level, 'classes': {}}
            classes_map = level_map[level.pk]['classes']

            combo = (subj.program_id, level.pk, subj.semester.academic_year_id)
            matched_classes = classes_by_combo.get(combo) or [None]
            for cls in matched_classes:
                cls_key = cls.pk if cls else None
                if cls_key not in classes_map:
                    classes_map[cls_key] = {'class_group': cls, 'semesters': {}}
                sem_map = classes_map[cls_key]['semesters']
                sem_key = subj.semester_id
                if sem_key not in sem_map:
                    sem_map[sem_key] = {'semester': subj.semester, 'subjects': []}
                sem_map[sem_key]['subjects'].append(subj)

        # Tri : niveau (order), classe (nom), semestre (numéro)
        levels_sorted = sorted(level_map.values(), key=lambda lv: (lv['level'].order, lv['level'].name))
        for lv in levels_sorted:
            classes_sorted = sorted(
                lv['classes'].values(),
                key=lambda c: (c['class_group'].name if c['class_group'] else 'zzz')
            )
            for cg in classes_sorted:
                cg['semesters'] = sorted(cg['semesters'].values(), key=lambda s: s['semester'].number)
                cg['total'] = sum(len(s['subjects']) for s in cg['semesters'])
            lv['classes'] = classes_sorted
            lv['total'] = sum(c['total'] for c in classes_sorted)

        ctx['levels'] = levels_sorted
        ctx['no_level_subjects'] = no_level_subjects
        ctx['total_subjects'] = len(subjects)

        ctx['academic_years'] = self.academic_years
        ctx['selected_year'] = self.selected_year
        ctx['empty_semesters'] = []
        ctx['previous_year'] = None

        if self.selected_year:
            faculty = getattr(self.request, 'active_faculty', None)
            previous_year = self.academic_years.filter(
                start_date__lt=self.selected_year.start_date
            ).order_by('-start_date').first()
            ctx['previous_year'] = previous_year

            if previous_year:
                subject_count_by_semester = defaultdict(int)
                for subj in subjects:
                    if subj.semester_id and subj.semester.academic_year_id == self.selected_year.pk:
                        subject_count_by_semester[subj.semester_id] += 1

                year_semesters = Semester.objects.filter(
                    academic_year=self.selected_year
                ).select_related('level')
                if faculty:
                    year_semesters = year_semesters.filter(academic_year__faculty=faculty)

                empty_semesters = []
                for sem in year_semesters:
                    if subject_count_by_semester.get(sem.pk):
                        continue
                    source_sem = Semester.objects.filter(
                        academic_year=previous_year, level_id=sem.level_id, number=sem.number,
                    ).select_related('level').first()
                    if source_sem and Subject.objects.filter(semester=source_sem).exists():
                        empty_semesters.append({'semester': sem, 'source_semester': source_sem})

                empty_semesters.sort(
                    key=lambda row: (
                        row['semester'].level.order if row['semester'].level else 99,
                        row['semester'].number,
                    )
                )
                ctx['empty_semesters'] = empty_semesters

        return ctx


class _SubjectRateMixin:
    """Injecte les cartes JSON du taux horaire dans le contexte et applique
    le taux soumis (le cas échéant) à la sauvegarde — factorisé pour
    Create/Update (mêmes formulaire et template)."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        program_dept, semester_info, rate_map = _program_semester_rate_maps(self.request)
        ctx['program_dept_map'] = json.dumps(program_dept)
        ctx['semester_info_map'] = json.dumps(semester_info)
        ctx['rate_map'] = json.dumps(rate_map)
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        taux = form.cleaned_data.get('taux_horaire')
        subject = self.object
        if taux is not None and subject.program_id and subject.semester_id and subject.semester.level_id:
            from academic_core.apps.accounting.services import set_hourly_rate
            set_hourly_rate(
                department=subject.program.department,
                level=subject.semester.level,
                academic_year=subject.semester.academic_year,
                rate_value=taux,
                user=self.request.user,
            )
        return response


class SubjectCreateView(_SubjectRateMixin, _AdminResponsableMixin, CreateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'subjects/form.html'
    success_url = reverse_lazy('subjects:list')


class SubjectUpdateView(_SubjectRateMixin, _AdminResponsableMixin, UpdateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'subjects/form.html'
    success_url = reverse_lazy('subjects:list')


class SubjectDeleteView(_AdminResponsableMixin, DeleteView):
    model = Subject
    template_name = 'subjects/confirm_delete.html'
    success_url = reverse_lazy('subjects:list')

    def delete(self, request, *args, **kwargs):
        subject = self.get_object()
        messages.success(request, f"Module (EC) « {subject.title} » supprimé.")
        return super().delete(request, *args, **kwargs)


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
def semester_duplicate(request, pk):
    """
    Duplique les modules (EC) — avec ou sans UE — du semestre correspondant
    (même niveau, même numéro) de l'année académique précédente vers le
    semestre cible `pk`. Contrairement à grades.maquette_duplicate (qui ne
    couvre que les EC déjà rattachés à une UE), cette vue couvre tous les
    Subject du semestre source, puisque la page Modules (EC) les affiche tous.
    Les enseignants affectés et les syllabus ne sont pas copiés — propres à
    chaque année.
    """
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('subjects:list')

    from academic_core.apps.academic_structure.models import AcademicYear, Semester
    from academic_core.apps.grades.models import UniteEnseignement

    target_semester = get_object_or_404(Semester, pk=pk)
    faculty = getattr(request, 'active_faculty', None)

    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=faculty) if faculty else academic_years.none()

    source_semester = Semester.objects.filter(
        academic_year__in=academic_years.filter(start_date__lt=target_semester.academic_year.start_date),
        level_id=target_semester.level_id, number=target_semester.number,
    ).select_related('academic_year', 'level').order_by('-academic_year__start_date').first()

    if not source_semester:
        messages.error(request, "Aucun semestre correspondant trouvé dans une année académique précédente.")
        return redirect(f"/subjects/?annee={target_semester.academic_year_id}")

    source_subjects = Subject.objects.filter(semester=source_semester).select_related(
        'program', 'ue'
    ).order_by('program__name', 'code')
    if faculty:
        source_subjects = source_subjects.filter(program__department__faculty=faculty)

    existing_titles = set(
        Subject.objects.filter(semester=target_semester).values_list('program_id', 'title')
    )

    preview_rows = [
        {
            'subject': subj,
            'already_exists': (subj.program_id, subj.title) in existing_titles,
        }
        for subj in source_subjects
    ]

    if request.method == 'POST':
        created = skipped_existing = 0
        with transaction.atomic():
            for row in preview_rows:
                if row['already_exists']:
                    skipped_existing += 1
                    continue
                subj = row['subject']

                new_ue = None
                if subj.ue_id:
                    new_ue, _ = UniteEnseignement.objects.get_or_create(
                        code=subj.ue.code, program=subj.ue.program, semester=target_semester,
                        defaults={'title': subj.ue.title, 'credits': subj.ue.credits, 'order': subj.ue.order},
                    )

                Subject.objects.create(
                    code=_unique_subject_code(subj.code, target_semester.academic_year.label),
                    title=subj.title, program=subj.program,
                    semester=target_semester, subject_type=subj.subject_type,
                    coefficient=subj.coefficient,
                    volume_cm=subj.volume_cm, volume_td=subj.volume_td,
                    volume_tp=subj.volume_tp, volume_tpe=subj.volume_tpe,
                    ue=new_ue, description=subj.description,
                )
                created += 1

        msg = (
            f"{created} module(s) (EC) dupliqué(s) depuis {source_semester.academic_year.label} "
            f"vers {target_semester.academic_year.label}."
        )
        if skipped_existing:
            msg += f" {skipped_existing} module(s) déjà existant(s) ignoré(s)."
        messages.success(request, msg)
        return redirect(f"/subjects/?annee={target_semester.academic_year_id}")

    return render(request, 'subjects/semester_duplicate.html', {
        'source_semester': source_semester,
        'target_semester': target_semester,
        'preview_rows': preview_rows,
    })
