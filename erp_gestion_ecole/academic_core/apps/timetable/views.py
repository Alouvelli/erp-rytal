import json
from datetime import date, timedelta
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from .models import TimetableEntry
from .forms import TimetableEntryForm, TimetableFilterForm
from academic_core.apps.accounts.decorators import responsable_required
from academic_core.apps.academic_structure.models import Semester, Class
from academic_core.apps.teachers.models import Teacher
from academic_core.apps.rooms.models import Room


class TimetableIndexView(LoginRequiredMixin, ListView):
    model = TimetableEntry
    template_name = 'timetable/index.html'
    context_object_name = 'entries'

    def _resolve_selected_year(self, faculty):
        """
        Année académique sélectionnée pour les filtres de cette page : par
        défaut l'année en cours, sauf si l'utilisateur choisit explicitement
        une autre année (ou "Toutes les années" pour consulter l'historique).
        """
        from academic_core.apps.academic_structure.models import AcademicYear
        academic_years = AcademicYear.objects.order_by('-start_date')
        academic_years = academic_years.filter(faculty=faculty) if faculty else academic_years.none()

        year_param = self.request.GET.get('year')
        if year_param == 'all':
            return academic_years, None
        if year_param:
            return academic_years, academic_years.filter(pk=year_param).first()
        return academic_years, academic_years.filter(is_current=True).first()

    def get_queryset(self):
        qs = TimetableEntry.objects.select_related(
            'class_group', 'subject', 'teacher__user', 'room', 'semester'
        ).filter(is_active=True)

        user = self.request.user
        faculty = getattr(self.request, 'active_faculty', None)
        self._student_enrollment = None
        if user.is_etudiant():
            student = getattr(user, 'student_profile', None)
            if student:
                from academic_core.apps.students.utils import resolve_student_year
                self._selected_year, self._academic_years, self._student_enrollment = \
                    resolve_student_year(self.request, student, param='year')
                qs = qs.filter(class_group=self._student_enrollment.class_group) if self._student_enrollment else qs.none()
            else:
                qs = qs.none()
                self._selected_year, self._academic_years = None, []
        elif user.is_enseignant():
            qs = qs.filter(teacher__user=user)
            self._academic_years, self._selected_year = self._resolve_selected_year(faculty)
        else:
            if faculty:
                qs = qs.filter(class_group__program__department__faculty=faculty)
            self._academic_years, self._selected_year = self._resolve_selected_year(faculty)

        if self._selected_year:
            qs = qs.filter(semester__academic_year=self._selected_year)

        semester_id = self.request.GET.get('semester')
        class_id    = self.request.GET.get('class_group')
        teacher_id  = self.request.GET.get('teacher')
        room_id     = self.request.GET.get('room')
        if semester_id:
            qs = qs.filter(semester_id=semester_id)
        if class_id and not user.is_etudiant():
            qs = qs.filter(class_group_id=class_id)
        if teacher_id and (user.can_manage_dept()):
            qs = qs.filter(teacher_id=teacher_id)
        if room_id and (user.can_manage_dept()):
            qs = qs.filter(room_id=room_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        faculty = getattr(self.request, 'active_faculty', None)
        ctx['filter_form'] = TimetableFilterForm(self.request.GET or None, request=self.request)

        # Grille hebdomadaire (planning) : uniquement pertinente quand un axe
        # unique est sélectionné (une classe, un enseignant ou une salle),
        # sinon plusieurs séances pourraient se chevaucher dans une même case.
        from .planning_views import build_planning_grid
        user = self.request.user
        has_axis = (
            self.request.GET.get('class_group') or self.request.GET.get('teacher') or
            self.request.GET.get('room') or user.is_enseignant() or user.is_etudiant()
        )
        ctx['planning_grid'] = build_planning_grid(self.object_list) if has_axis else None

        # Libellé de l'axe affiché (pour l'en-tête d'impression de la grille)
        ctx['axis_label'] = None
        ctx['axis_name']  = None
        if ctx['planning_grid']:
            class_id   = self.request.GET.get('class_group')
            teacher_id = self.request.GET.get('teacher')
            room_id    = self.request.GET.get('room')
            def _classe_label(cls):
                if not cls:
                    return ''
                filiere_name = cls.program.name if getattr(cls, 'program', None) else ''
                return f"{filiere_name} - {cls.name}" if filiere_name else cls.name

            if class_id and not user.is_etudiant():
                obj = Class.objects.select_related('program').filter(pk=class_id).first()
                ctx['axis_label'], ctx['axis_name'] = 'Classe', _classe_label(obj)
            elif teacher_id and user.can_manage_dept():
                obj = Teacher.objects.select_related('user').filter(pk=teacher_id).first()
                ctx['axis_label'], ctx['axis_name'] = 'Enseignant', (obj.full_name if obj else '')
            elif room_id and user.can_manage_dept():
                obj = Room.objects.filter(pk=room_id).first()
                ctx['axis_label'], ctx['axis_name'] = 'Salle', (obj.name if obj else '')
            elif user.is_enseignant():
                tp = getattr(user, 'teacher_profile', None)
                ctx['axis_label'], ctx['axis_name'] = 'Enseignant', (tp.full_name if tp else '')
            elif user.is_etudiant():
                ctx['axis_label'] = 'Classe'
                ctx['axis_name']  = _classe_label(self._student_enrollment.class_group) if self._student_enrollment else ''
        # Filtre Semestre/Classe : par défaut, seuls ceux de l'année académique
        # en cours sont proposés — l'option "Toutes les années" (year=all)
        # reste disponible pour consulter/planifier un semestre passé ou pas
        # encore actif, contrairement au formulaire d'ajout de séance
        # (TimetableEntryForm) qui, lui, ne propose que les semestres actifs.
        academic_years, selected_year = self._academic_years, self._selected_year
        semesters_qs = Semester.objects.select_related('academic_year').order_by(
            '-academic_year__start_date', 'number'
        )
        classes_qs  = Class.objects.select_related('academic_year').order_by('name')
        teachers_qs = Teacher.objects.select_related('user').order_by('user__last_name')
        rooms_qs    = Room.objects.order_by('name')
        if faculty:
            semesters_qs = semesters_qs.filter(academic_year__faculty=faculty)
            classes_qs  = classes_qs.filter(program__department__faculty=faculty)
            teachers_qs = teachers_qs.filter(user__department__faculty=faculty)
            rooms_qs    = rooms_qs.filter(building__faculty=faculty)
        if selected_year:
            semesters_qs = semesters_qs.filter(academic_year=selected_year)
            classes_qs   = classes_qs.filter(academic_year=selected_year)
        ctx['academic_years'] = academic_years
        ctx['selected_year']  = selected_year
        ctx['selected_year_param'] = self.request.GET.get('year', '')
        ctx['semesters'] = semesters_qs
        ctx['classes']  = classes_qs
        ctx['teachers'] = teachers_qs
        ctx['rooms']    = rooms_qs
        return ctx



def _class_level_map(request):
    """Retourne un dict JSON {class_id: {level_id, level_name, rate_per_hour}} pour
    le formulaire. Le taux horaire affiché est celui du département RÉEL de
    chaque classe (class.program.department, même résolution que
    accounting/services.py::record_honoraire) plutôt que du département
    "actif" de la requête — un Admin/Chef de Département qui gère plusieurs
    départements doit voir le taux propre à la classe choisie, pas celui de
    son département actuellement sélectionné dans l'UI."""
    from academic_core.apps.accounting.models import HourlyRate
    classes = Class.objects.select_related('level', 'academic_year', 'program__department').all()
    result = {}
    for c in classes:
        rate = None
        dept = c.program.department if c.program_id else None
        if c.level and dept:
            try:
                hr = HourlyRate.objects.get(
                    department=dept,
                    level=c.level,
                    academic_year=c.academic_year,
                )
                rate = float(hr.rate_per_hour)
            except Exception:
                pass
        result[c.pk] = {
            'level': str(c.level) if c.level else '',
            'level_id': c.level_id,
            'department_id': dept.pk if dept else None,
            'academic_year_id': c.academic_year_id,
            'rate': rate,
        }
    return result


def _apply_taux_horaire(entry, taux, user=None):
    """Applique le taux horaire soumis (facultatif) sur le formulaire de
    séance à HourlyRate(department, level, academic_year) — même clé que
    record_honoraire(). N'agit que si un montant a été saisi et que la classe
    a un niveau."""
    if taux is None or not entry.class_group_id or not entry.class_group.level_id:
        return
    from academic_core.apps.accounting.services import set_hourly_rate
    set_hourly_rate(
        department=entry.class_group.program.department,
        level=entry.class_group.level,
        academic_year=entry.class_group.academic_year,
        rate_value=taux,
        user=user,
    )


def _sync_subject_teacher(entry):
    """
    Synchronise Subject.responsible_teacher avec l'enseignant choisi pour cette
    séance : l'affectation d'un module à un enseignant peut se faire soit ici
    (création/modification d'une séance), soit depuis Modules (EC) — les deux
    doivent rester cohérents entre eux.
    """
    if entry.subject_id and entry.teacher_id and entry.subject.responsible_teacher_id != entry.teacher_id:
        entry.subject.responsible_teacher_id = entry.teacher_id
        entry.subject.save(update_fields=['responsible_teacher'])


class TimetableCreateView(LoginRequiredMixin, CreateView):
    model = TimetableEntry
    form_class = TimetableEntryForm
    template_name = 'timetable/entry_form.html'
    success_url = reverse_lazy('timetable:index')

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.can_manage_dept()):
            messages.error(request, "Accès refusé.")
            return redirect('timetable:index')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['class_level_map'] = json.dumps(_class_level_map(self.request))
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        entry = form.save(commit=False)
        conflicts = entry.check_conflicts()
        if conflicts:
            for c in conflicts:
                if 'salle' in c.lower() or 'room' in c.lower():
                    form.add_error('room', f"Salle déjà occupée sur ce créneau.")
                elif 'enseignant' in c.lower() or 'teacher' in c.lower():
                    form.add_error('teacher', f"Enseignant déjà occupé sur ce créneau.")
                elif 'classe' in c.lower() or 'class' in c.lower():
                    form.add_error('class_group', f"Classe déjà occupée sur ce créneau.")
                else:
                    form.add_error(None, f"Conflit détecté : {c}")
            return self.form_invalid(form)
        entry.save()
        _sync_subject_teacher(entry)
        _apply_taux_horaire(entry, form.cleaned_data.get('taux_horaire'), self.request.user)
        messages.success(self.request, "Séance ajoutée à l'emploi du temps.")
        return redirect(self.success_url)


class TimetableUpdateView(LoginRequiredMixin, UpdateView):
    model = TimetableEntry
    form_class = TimetableEntryForm
    template_name = 'timetable/entry_form.html'
    success_url = reverse_lazy('timetable:index')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.can_manage_dept():
            messages.error(request, "Accès refusé.")
            return redirect('timetable:index')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['class_level_map'] = json.dumps(_class_level_map(self.request))
        return ctx

    def form_valid(self, form):
        entry = form.save(commit=False)
        conflicts = entry.check_conflicts()
        if conflicts:
            for c in conflicts:
                if 'salle' in c.lower() or 'room' in c.lower():
                    form.add_error('room', f"Salle déjà occupée sur ce créneau.")
                elif 'enseignant' in c.lower() or 'teacher' in c.lower():
                    form.add_error('teacher', f"Enseignant déjà occupé sur ce créneau.")
                elif 'classe' in c.lower() or 'class' in c.lower():
                    form.add_error('class_group', f"Classe déjà occupée sur ce créneau.")
                else:
                    form.add_error(None, f"Conflit détecté : {c}")
            return self.form_invalid(form)
        entry.save()
        _sync_subject_teacher(entry)
        _apply_taux_horaire(entry, form.cleaned_data.get('taux_horaire'), self.request.user)
        messages.success(self.request, "Séance mise à jour.")
        return redirect(self.success_url)


class TimetableDeleteView(LoginRequiredMixin, DeleteView):
    model = TimetableEntry
    template_name = 'timetable/entry_confirm_delete.html'
    success_url = reverse_lazy('timetable:index')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.can_manage_dept():
            messages.error(request, "Accès refusé.")
            return redirect('timetable:index')
        return super().dispatch(request, *args, **kwargs)


@login_required
def timetable_events_api(request):
    """Endpoint JSON pour FullCalendar — supporte tous les filtres."""
    qs = TimetableEntry.objects.select_related(
        'class_group', 'subject', 'teacher__user', 'room', 'semester'
    ).filter(is_active=True)

    user = request.user
    faculty = getattr(request, 'active_faculty', None)
    if user.is_etudiant():
        sp = getattr(user, 'student_profile', None)
        if sp:
            current = sp.current_enrollment()
            if current:
                qs = qs.filter(class_group=current.class_group)
    elif user.is_enseignant():
        qs = qs.filter(teacher__user=user)
    elif faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)

    # Année académique : même filtre par défaut que la page (année en cours,
    # sauf "Toutes les années" explicitement choisi) — le calendrier doit
    # rester cohérent avec les filtres Semestre/Classe affichés au-dessus.
    year_param = request.GET.get('year')
    if year_param == 'all':
        pass
    elif year_param:
        qs = qs.filter(semester__academic_year_id=year_param)
    elif faculty:
        from academic_core.apps.academic_structure.models import AcademicYear
        current_year = AcademicYear.objects.filter(faculty=faculty, is_current=True).first()
        if current_year:
            qs = qs.filter(semester__academic_year=current_year)

    semester_id  = request.GET.get('semester')
    class_id     = request.GET.get('class_group')
    teacher_id   = request.GET.get('teacher')
    room_id      = request.GET.get('room')

    if semester_id:
        qs = qs.filter(semester_id=semester_id)
    if class_id and not user.is_etudiant():
        qs = qs.filter(class_group_id=class_id)
    if teacher_id and (user.can_manage_dept()):
        qs = qs.filter(teacher_id=teacher_id)
    if room_id and (user.can_manage_dept()):
        qs = qs.filter(room_id=room_id)

    # Récupère la semaine en cours (lundi)
    today  = date.today()
    monday = today - timedelta(days=today.weekday())

    # Pour les entrées hebdomadaires, on génère les occurrences sur 52 semaines
    events = []
    for entry in qs:
        day_offset = entry.day_of_week - 1  # 1=Lundi → offset 0
        if entry.recurrence == TimetableEntry.RECURRENCE_ONCE and entry.specific_date:
            # Séance ponctuelle : une seule occurrence à la date exacte
            events.append(_build_event(entry, entry.specific_date))
        else:
            # Hebdomadaire ou bi-hebdomadaire : 26 semaines en arrière + 26 en avant
            weeks = range(-4, 30) if entry.recurrence == TimetableEntry.RECURRENCE_WEEKLY else range(-4, 30, 2)
            for w in weeks:
                event_date = monday + timedelta(days=day_offset) + timedelta(weeks=w)
                events.append(_build_event(entry, event_date))

    return JsonResponse(events, safe=False)


@login_required
def room_swap_view(request):
    """
    Permutation de salles entre deux créneaux.
    POST: entry1_id, entry2_id → échange les salles si aucun conflit.
    GET : formulaire de sélection.
    """
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('timetable:index')

    entries_qs = TimetableEntry.objects.select_related(
        'subject', 'room', 'class_group__program__department',
        'class_group__level', 'teacher__user', 'semester',
    ).filter(is_active=True)

    # Périmètre institut + année académique en cours : permuter des salles
    # entre deux séances d'instituts ou d'années différents n'a pas de sens.
    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    if dept:
        entries_qs = entries_qs.filter(class_group__program__department=dept)
    elif faculty:
        entries_qs = entries_qs.filter(class_group__program__department__faculty=faculty)
    fac_for_years = faculty or (dept.faculty if dept else None)
    if fac_for_years:
        from academic_core.apps.academic_structure.models import AcademicYear
        current_year = AcademicYear.objects.filter(faculty=fac_for_years, is_current=True).first()
        if current_year:
            entries_qs = entries_qs.filter(semester__academic_year=current_year)

    if request.method == 'POST':
        id1 = request.POST.get('entry1_id')
        id2 = request.POST.get('entry2_id')
        try:
            e1 = entries_qs.get(pk=id1)
            e2 = entries_qs.get(pk=id2)
        except TimetableEntry.DoesNotExist:
            messages.error(request, "Créneau introuvable.")
            return redirect('timetable:room_swap')

        # Vérifier les conflits APRÈS la permutation
        room1, room2 = e1.room, e2.room
        # e1 prendrait room2 : y a-t-il un conflit ?
        def has_conflict(entry, new_room):
            if new_room is None:
                return False
            qs = TimetableEntry.objects.filter(
                semester=entry.semester,
                day_of_week=entry.day_of_week,
                room=new_room,
                is_active=True,
            ).exclude(pk=entry.pk)
            for e in qs:
                if e.start_time < entry.end_time and e.end_time > entry.start_time:
                    return True
            return False

        conflict1 = has_conflict(e1, room2)
        conflict2 = has_conflict(e2, room1)

        if conflict1 or conflict2:
            messages.error(request, "Permutation impossible : conflit de salle détecté.")
        else:
            e1.room, e2.room = room2, room1
            e1.save(update_fields=['room'])
            e2.save(update_fields=['room'])
            messages.success(
                request,
                f"Salles permutées : {e1.subject.code} ↔ {e2.subject.code}"
            )
            return redirect('timetable:index')

    # Grouper par département → semestre → classe
    from collections import OrderedDict
    dept_map = OrderedDict()
    for e in entries_qs.order_by(
        'class_group__program__department__name',
        'semester__number',
        'class_group__name',
        'day_of_week', 'start_time',
    ):
        dept = e.class_group.program.department
        sem  = e.semester
        cg   = e.class_group

        if dept.pk not in dept_map:
            dept_map[dept.pk] = {'dept': dept, 'semesters': OrderedDict()}
        sem_map = dept_map[dept.pk]['semesters']

        if sem.pk not in sem_map:
            sem_map[sem.pk] = {'semester': sem, 'classes': OrderedDict()}
        cls_map = sem_map[sem.pk]['classes']

        if cg.pk not in cls_map:
            cls_map[cg.pk] = {'class_group': cg, 'entries': []}
        cls_map[cg.pk]['entries'].append(e)

    # Aplatir en liste pour le template
    grouped_dept = []
    for d in dept_map.values():
        sems = []
        for s in d['semesters'].values():
            classes = list(s['classes'].values())
            sems.append({'semester': s['semester'], 'classes': classes})
        grouped_dept.append({'dept': d['dept'], 'semesters': sems})

    return render(request, 'timetable/room_swap.html', {
        'grouped_dept': grouped_dept,
        'all_entries':  entries_qs,
    })


@login_required
def subjects_by_semester_api(request):
    """Retourne les matières (JSON) filtrées par semestre et/ou programme de la classe."""
    semester_id    = request.GET.get('semester_id')
    class_group_id = request.GET.get('class_group_id')

    if not semester_id and not class_group_id:
        return JsonResponse([], safe=False)

    from academic_core.apps.subjects.models import Subject
    from academic_core.apps.academic_structure.models import Class as ClassGroup

    qs = Subject.objects.select_related('ue', 'responsible_teacher__user').order_by('ue__code', 'code')

    # Filtrer par programme de la classe (relation fiable)
    if class_group_id:
        try:
            cg = ClassGroup.objects.select_related('program').get(pk=class_group_id)
            qs = qs.filter(program=cg.program)
        except ClassGroup.DoesNotExist:
            pass

    # Affiner par semestre si disponible et si des matières ont un semestre assigné
    if semester_id:
        with_sem = qs.filter(semester_id=semester_id)
        # N'appliquer le filtre semestre que si des résultats existent
        if with_sem.exists():
            qs = with_sem

    data = [
        {
            'id':           s.pk,
            'code':         s.code,
            'title':        s.title,
            'ue':           s.ue.code if s.ue_id else '',
            'teacher_id':   s.responsible_teacher_id or '',
            'teacher_name': s.responsible_teacher.full_name if s.responsible_teacher_id else '',
        }
        for s in qs
    ]
    return JsonResponse(data, safe=False)


@login_required
def available_rooms_api(request):
    """Retourne les salles disponibles pour un créneau donné (jour + heure + semestre)."""
    day      = request.GET.get('day')
    start    = request.GET.get('start')
    end      = request.GET.get('end')
    semester = request.GET.get('semester')
    exclude  = request.GET.get('exclude')  # pk de l'entrée en cours de modification

    if not (day and start and end):
        faculty = getattr(request, 'active_faculty', None)
        rooms = Room.objects.filter(is_available=True).order_by('name')
        if faculty:
            rooms = rooms.filter(building__faculty=faculty)
        return JsonResponse([{'id': r.pk, 'name': str(r)} for r in rooms], safe=False)

    # Vérification globale : tous les plannings actifs, tous départements confondus
    occupied_qs = TimetableEntry.objects.filter(
        day_of_week=day,
        start_time__lt=end,
        end_time__gt=start,
        is_active=True,
        room__isnull=False,
    )
    if exclude:
        occupied_qs = occupied_qs.exclude(pk=exclude)

    occupied_room_ids = occupied_qs.values_list('room_id', flat=True)
    rooms = Room.objects.filter(is_available=True).order_by('name')
    result = [
        {'id': r.pk, 'name': str(r), 'occupied': r.pk in list(occupied_room_ids)}
        for r in rooms
    ]
    return JsonResponse(result, safe=False)


def _build_event(entry, event_date):
    return {
        'id':    f"{entry.pk}_{event_date}",
        'title': f"{entry.subject.code} - {entry.subject.title} — {entry.class_group.code if hasattr(entry.class_group, 'code') else entry.class_group.name}",
        'start': f"{event_date}T{entry.start_time}",
        'end':   f"{event_date}T{entry.end_time}",
        'color': entry.color,
        'extendedProps': {
            'teacher':         entry.teacher.full_name,
            'teacher_user_id': entry.teacher.user_id,
            'room':            entry.room.name if entry.room else '—',
            'subject':         entry.subject.title,
            'class_group':     entry.class_group.name,
            'semester':        entry.semester.label if entry.semester else '',
            'recurrence':      entry.get_recurrence_display(),
            'edit_url':        f"/timetable/{entry.pk}/edit/",
            'delete_url':      f"/timetable/{entry.pk}/delete/",
        },
    }
