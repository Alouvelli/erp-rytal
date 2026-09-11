"""
Cahier de Texte Numérique — vues enseignant + administrateur.
"""
from datetime import date, timedelta
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse

from .models import TimetableEntry, SessionLog


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_occurrences(entry, start, end):
    """
    Retourne les dates de toutes les occurrences d'un créneau entre start et end (inclus).
    """
    if not entry.is_active:
        return []

    today = date.today()
    end   = min(end, today)   # on n'affiche pas les séances futures

    if entry.recurrence == TimetableEntry.RECURRENCE_ONCE:
        d = entry.specific_date
        if d and start <= d <= end:
            return [d]
        return []

    # Trouver le premier lundi (day_of_week 1=lun, …, 7=dim en isoweekday)
    # TimetableEntry.day_of_week : 1=lun … 6=sam
    target_iso = entry.day_of_week  # 1=lun … 6=sam correspond à isoweekday
    d = start
    while d.isoweekday() != target_iso:
        d += timedelta(days=1)
    if d > end:
        return []

    step   = 7 if entry.recurrence == TimetableEntry.RECURRENCE_WEEKLY else 14
    dates  = []
    while d <= end:
        dates.append(d)
        d += timedelta(days=step)
    return dates


def _build_session_list(entries, semester, db_alias='default'):
    """
    À partir d'une liste de TimetableEntry et d'un Semester,
    retourne une liste de dicts :
    { entry, date, log_or_None, is_filled, attendance_sheet_or_None }
    triée par date décroissante.
    Auto-synchronise SessionLog depuis AttendanceSheet quand un log n'existe pas encore.
    """
    from academic_core.apps.attendance.models import AttendanceSheet

    sem_start = semester.start_date
    sem_end   = semester.end_date
    today     = date.today()
    cap       = min(sem_end, today)   # borne pour les occurrences planifiées

    entry_pks = [e.pk for e in entries]

    # Pré-charger logs existants (sans borne de date : inclut séances hors période)
    logs    = SessionLog.objects.using(db_alias).filter(
        timetable_entry_id__in=entry_pks,
    )
    log_map = {(l.timetable_entry_id, l.session_date): l for l in logs}

    # Pré-charger les feuilles d'émargement signées/validées (sans borne de date)
    sheets    = AttendanceSheet.objects.using(db_alias).filter(
        timetable_entry_id__in=entry_pks,
        status__in=['SIGNED', 'VALIDATED'],
    )
    sheet_map = {(s.timetable_entry_id, s.session_date): s for s in sheets}

    # Auto-sync : créer SessionLog depuis AttendanceSheet si absent
    to_create = []
    for (eid, d_), sheet in sheet_map.items():
        if (eid, d_) not in log_map:
            to_create.append(SessionLog(
                timetable_entry_id=eid,
                session_date=d_,
                objectives=sheet.lesson_objectives or sheet.lesson_content,
                content=sheet.lesson_content,
                remarks=sheet.teacher_comment or '',
            ))
    if to_create:
        SessionLog.objects.using(db_alias).bulk_create(to_create, ignore_conflicts=True)
        # Recharger la map après création
        logs    = SessionLog.objects.using(db_alias).filter(
            timetable_entry_id__in=entry_pks,
        )
        log_map = {(l.timetable_entry_id, l.session_date): l for l in logs}

    # Construire les sessions : uniquement celles ayant une feuille d'émargement validée
    entry_map = {e.pk: e for e in entries}
    planned_keys = set()
    sessions = []
    for entry in entries:
        for d in _get_occurrences(entry, sem_start, sem_end):
            planned_keys.add((entry.pk, d))
            sheet = sheet_map.get((entry.pk, d))
            if not sheet:
                continue  # ignorer les séances sans émargement validé
            log = log_map.get((entry.pk, d))
            sessions.append({
                'entry':            entry,
                'date':             d,
                'log':              log,
                'is_filled':        log is not None,
                'attendance_sheet': sheet,
            })

    # Inclure aussi les séances hors planning ayant une feuille validée
    for (eid, d_), sheet in sheet_map.items():
        if (eid, d_) not in planned_keys:
            entry = entry_map.get(eid)
            if entry:
                log = log_map.get((eid, d_))
                sessions.append({
                    'entry':            entry,
                    'date':             d_,
                    'log':              log,
                    'is_filled':        log is not None,
                    'attendance_sheet': sheet,
                })

    sessions.sort(key=lambda s: s['date'], reverse=True)
    return sessions


# ── Vue enseignant : liste de ses séances ─────────────────────────────────────

def _build_grouped_for_semester(teacher, semester, db_alias='default'):
    """
    Retourne (grouped, total_sessions, filled_sessions) pour un semestre donné.
    """
    from academic_core.apps.attendance.models import AttendanceSheet

    entries = TimetableEntry.objects.filter(
        teacher=teacher, semester=semester, is_active=True
    ).select_related('subject__ue', 'class_group', 'semester', 'room')

    sessions = _build_session_list(list(entries), semester, db_alias=db_alias)

    entry_pks = [e.pk for e in entries]
    signed_keys = set(
        AttendanceSheet.objects.using(db_alias).filter(
            timetable_entry_id__in=entry_pks,
        ).values_list('timetable_entry_id', 'session_date')
    )
    sessions = [s for s in sessions if (s['entry'].pk, s['date']) in signed_keys]

    tree_data = {}
    for s in sessions:
        cg   = s['entry'].class_group
        subj = s['entry'].subject
        if cg not in tree_data:
            tree_data[cg] = {}
        if subj not in tree_data[cg]:
            tree_data[cg][subj] = []
        tree_data[cg][subj].append(s)

    grouped = []
    for cg in sorted(tree_data.keys(), key=lambda c: c.name):
        subj_list = []
        for subj in sorted(tree_data[cg].keys(), key=lambda x: x.code or ''):
            s_list = sorted(tree_data[cg][subj], key=lambda x: x['date'], reverse=True)
            total  = len(s_list)
            filled = sum(1 for s in s_list if s['is_filled'])
            subj_list.append({
                'subject': subj,
                'sessions': s_list,
                'total':   total,
                'filled':  filled,
                'pct':     round(filled / total * 100) if total else 0,
            })
        cg_total  = sum(x['total']  for x in subj_list)
        cg_filled = sum(x['filled'] for x in subj_list)
        grouped.append({
            'class_group': cg,
            'subjects':    subj_list,
            'total':       cg_total,
            'filled':      cg_filled,
            'pct':         round(cg_filled / cg_total * 100) if cg_total else 0,
        })

    total_sessions  = len(sessions)
    filled_sessions = sum(1 for s in sessions if s['is_filled'])
    return grouped, total_sessions, filled_sessions


@login_required
def mes_seances(request):
    """Enseignant : liste de toutes ses séances avec statut cahier de texte."""
    if not request.user.is_enseignant():
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    teacher = request.user.teacher_profile

    from academic_core.apps.academic_structure.models import Semester
    from academic_core.db_router import get_current_db

    semesters = Semester.objects.select_related('academic_year').order_by(
        '-academic_year__start_date', 'number'
    )
    faculty = getattr(request, 'active_faculty', None) or (
        request.user.department.faculty if request.user.department_id else None
    )
    if faculty:
        semesters = semesters.filter(academic_year__faculty=faculty)
    sem_id   = request.GET.get('semester')  # None = tous les semestres
    semester = None
    if sem_id:
        semester = semesters.filter(pk=sem_id).first()

    _db = get_current_db() or 'default'

    if semester:
        # Vue filtrée : un seul semestre
        grouped, total_sessions, filled_sessions = _build_grouped_for_semester(
            teacher, semester, db_alias=_db
        )
        semester_groups = None
    else:
        # Vue par défaut : tous les semestres
        semester_groups = []
        total_sessions  = 0
        filled_sessions = 0
        for sem in semesters:
            grp, tot, fil = _build_grouped_for_semester(teacher, sem, db_alias=_db)
            if not grp:
                continue  # semestre sans séances : on le saute
            total_sessions  += tot
            filled_sessions += fil
            semester_groups.append({
                'semester': sem,
                'grouped':  grp,
                'total':    tot,
                'filled':   fil,
                'pct':      round(fil / tot * 100) if tot else 0,
            })
        grouped = []

    return render(request, 'timetable/mes_seances.html', {
        'semesters':        semesters,
        'semester':         semester,
        'semester_groups':  semester_groups,   # None si filtre actif
        'grouped':          grouped,
        'total_sessions':   total_sessions,
        'filled_sessions':  filled_sessions,
    })


# ── Vue enseignant : remplir / modifier le log d'une séance ──────────────────

@login_required
def session_log_edit(request, entry_pk, session_date_str):
    """Enseignant : saisir/modifier les objectifs et le contenu d'une séance."""
    if not request.user.is_enseignant():
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    teacher = request.user.teacher_profile
    entry   = get_object_or_404(TimetableEntry, pk=entry_pk, teacher=teacher)

    try:
        from datetime import date as _date
        session_date = _date.fromisoformat(session_date_str)
    except ValueError:
        messages.error(request, "Date invalide.")
        return redirect('timetable:mes_seances')

    # Vérifier que la date est une vraie occurrence
    sem_start = entry.semester.start_date
    sem_end   = entry.semester.end_date
    occurrences = _get_occurrences(entry, sem_start, sem_end)
    if session_date not in occurrences:
        messages.error(request, "Cette date ne correspond pas à une séance planifiée.")
        return redirect('timetable:mes_seances')

    log, _ = SessionLog.objects.get_or_create(
        timetable_entry=entry, session_date=session_date,
        defaults={'objectives': '', 'content': '', 'remarks': ''},
    )

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST' and entry.semester.is_locked:
        if is_ajax:
            return JsonResponse({'error': entry.semester.lock_message}, status=403)
        messages.error(request, entry.semester.lock_message)
        return redirect('timetable:mes_seances')

    if request.method == 'POST' and log.is_validated:
        error_msg = "Ce cahier de texte a été validé et ne peut plus être modifié."
        if is_ajax:
            return JsonResponse({'error': error_msg}, status=403)
        messages.error(request, error_msg)
        return redirect('timetable:mes_seances')

    if request.method == 'POST':
        objectives = request.POST.get('objectives', '').strip()
        content    = request.POST.get('content', '').strip()
        remarks    = request.POST.get('remarks', '').strip()

        if not objectives:
            if is_ajax:
                return JsonResponse({'error': "Les objectifs sont obligatoires."}, status=400)
            messages.error(request, "Les objectifs de la séance sont obligatoires.")
        else:
            log.objectives = objectives
            log.content    = content
            log.remarks    = remarks
            log.save()
            if is_ajax:
                return JsonResponse({
                    'ok':         True,
                    'objectives': log.objectives,
                    'content':    log.content,
                    'remarks':    log.remarks or '',
                })
            messages.success(request, "Cahier de texte mis à jour.")
            from django.urls import reverse as _rev
            next_url = request.POST.get('next') or f"{_rev('timetable:mes_seances')}?semester={entry.semester_id}"
            return redirect(next_url)

    # GET : renvoyer JSON si AJAX (pour pré-remplir le modal)
    if is_ajax:
        return JsonResponse({
            'objectives':   log.objectives or '',
            'content':      log.content    or '',
            'remarks':      log.remarks    or '',
            'entry_pk':     entry.pk,
            'date_str':     session_date_str,
            'subject':      f"{entry.subject.code} — {entry.subject.title}",
            'class_name':   entry.class_group.name,
            'date_fr':      session_date.strftime('%d/%m/%Y'),
            'horaire':      f"{entry.start_time.strftime('%Hh%M')} – {entry.end_time.strftime('%Hh%M')}",
            'is_validated': log.is_validated,
        })

    from django.urls import reverse as _rev
    back_url = request.GET.get('next') or f"{_rev('timetable:mes_seances')}?semester={entry.semester_id}"
    return render(request, 'timetable/session_log_form.html', {
        'entry':        entry,
        'session_date': session_date,
        'log':          log,
        'back_url':     back_url,
    })


# ── Vue admin : sélecteur classe + semestre ───────────────────────────────────

@login_required
def cahier_texte_list(request):
    """Admin/responsable : arbre Semestre → Classe avec accès direct au cahier."""
    user = request.user
    if not (user.can_manage_dept() or user.is_admin() or user.is_responsable_classe()):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Class, Semester
    from academic_core.apps.subjects.models import Subject

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    classes_qs = Class.objects.select_related('level', 'program__department').order_by('name')
    if user.is_responsable_classe():
        # Un Responsable/Adjoint de classe (personnel ou étudiant nommé) ne voit que sa classe.
        rep_class_id = user.get_class_rep_class_id()
        classes_qs = classes_qs.filter(pk=rep_class_id) if rep_class_id else classes_qs.none()
    elif dept:
        classes_qs = classes_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)

    semesters_qs = Semester.objects.select_related('academic_year').order_by(
        '-academic_year__start_date', 'number'
    )
    if faculty:
        semesters_qs = semesters_qs.filter(academic_year__faculty=faculty)

    # Année académique : par défaut l'année en cours — le cahier de texte
    # d'une année précédente ne doit pas apparaître mélangé avec l'année en
    # cours. "Toutes les années" (year=all) reste disponible pour consulter
    # l'historique.
    from academic_core.apps.academic_structure.models import AcademicYear
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=faculty) if faculty else academic_years.none()
    year_param = request.GET.get('year')
    if year_param == 'all':
        selected_year = None
    elif year_param:
        selected_year = academic_years.filter(pk=year_param).first()
    else:
        selected_year = academic_years.filter(is_current=True).first()

    if selected_year:
        classes_qs   = classes_qs.filter(academic_year=selected_year)
        semesters_qs = semesters_qs.filter(academic_year=selected_year)

    # Redirect direct si form soumis
    class_id    = request.GET.get('class_id')
    semester_id = request.GET.get('semester_id')
    if class_id and semester_id:
        return redirect('timetable:cahier_texte_view',
                        class_id=int(class_id), semester_id=int(semester_id))

    # Construire l'arbre Semestre → [Classe → [Matières count]]
    class_pks = list(classes_qs.values_list('pk', flat=True))
    entries_qs = (
        TimetableEntry.objects
        .filter(class_group_id__in=class_pks, is_active=True)
        .select_related('subject__ue', 'class_group', 'semester__academic_year')
        .order_by('semester__academic_year__start_date', 'semester__number', 'class_group__name')
    )
    if selected_year:
        entries_qs = entries_qs.filter(semester__academic_year=selected_year)

    # tree : { semester: { class_group: set(subjects) } }
    tree_data = {}
    for entry in entries_qs:
        sem = entry.semester
        if sem not in tree_data:
            tree_data[sem] = {}
        cg = entry.class_group
        if cg not in tree_data[sem]:
            tree_data[sem][cg] = set()
        if entry.subject_id:
            tree_data[sem][cg].add(entry.subject_id)

    # Transformer en liste triée
    tree = []
    for sem in sorted(tree_data.keys(),
                      key=lambda s: (-s.academic_year.start_date.year, s.number)):
        classes_list = []
        for cg in sorted(tree_data[sem].keys(), key=lambda c: c.name):
            subject_count = len(tree_data[sem][cg])
            classes_list.append({
                'class_group':    cg,
                'subject_count':  subject_count,
            })
        tree.append({
            'semester': sem,
            'classes':  classes_list,
        })

    return render(request, 'timetable/cahier_texte_list.html', {
        'tree':      tree,
        'classes':   classes_qs,
        'semesters': semesters_qs,
        'academic_years': academic_years,
        'selected_year_param': year_param or '',
    })


# ── Vue admin : cahier de texte par classe + semestre ─────────────────────────

@login_required
def cahier_texte_view(request, class_id, semester_id):
    """Admin/responsable : cahier de texte complet pour une classe+semestre."""
    user = request.user
    from academic_core.apps.academic_structure.models import Class, Semester
    from academic_core.apps.grades.models import UniteEnseignement

    class_group = get_object_or_404(Class, pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)

    if user.is_responsable_classe():
        if user.get_class_rep_class_id() != class_group.pk:
            messages.error(request, "Accès non autorisé : cette classe ne vous est pas assignée.")
            return redirect('dashboard:index')
    elif not (user.can_manage_dept() or user.is_admin()):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    entries = TimetableEntry.objects.filter(
        class_group=class_group, semester=semester, is_active=True
    ).select_related('subject__ue', 'teacher__user', 'room').order_by(
        'subject__ue__order', 'subject__ue__code', 'subject__code'
    )

    from academic_core.db_router import get_current_db
    _db = get_current_db() or 'default'
    sessions = _build_session_list(list(entries), semester, db_alias=_db)

    # Grouper : UE → EC (subject) → sessions
    # Structure : { ue: { subject: [sessions] } }
    ue_groups = defaultdict(lambda: defaultdict(list))
    no_ue_group = defaultdict(list)

    for s in sessions:
        subj = s['entry'].subject
        ue   = getattr(subj, 'ue', None)
        if ue:
            ue_groups[ue][subj].append(s)
        else:
            no_ue_group[subj].append(s)

    # Convertir en liste triée
    def _sort_key_ue(u):
        return (getattr(u, 'order', 0) or 0, getattr(u, 'code', '') or '')

    grouped = []
    for ue in sorted(ue_groups.keys(), key=_sort_key_ue):
        subj_list = []
        for subj in sorted(ue_groups[ue].keys(), key=lambda x: x.code or ''):
            s_list = ue_groups[ue][subj]
            total  = len(s_list)
            filled = sum(1 for s in s_list if s['is_filled'])
            subj_list.append({
                'subject':  subj,
                'sessions': s_list,
                'total':    total,
                'filled':   filled,
                'pct':      round(filled / total * 100) if total else 0,
            })
        total_ue  = sum(x['total']  for x in subj_list)
        filled_ue = sum(x['filled'] for x in subj_list)
        grouped.append({
            'ue':       ue,
            'subjects': subj_list,
            'total':    total_ue,
            'filled':   filled_ue,
            'pct':      round(filled_ue / total_ue * 100) if total_ue else 0,
        })

    if no_ue_group:
        subj_list = []
        for subj in sorted(no_ue_group.keys(), key=lambda x: x.code or ''):
            s_list = no_ue_group[subj]
            total  = len(s_list)
            filled = sum(1 for s in s_list if s['is_filled'])
            subj_list.append({
                'subject':  subj,
                'sessions': s_list,
                'total':    total,
                'filled':   filled,
                'pct':      round(filled / total * 100) if total else 0,
            })
        total_ue  = sum(x['total']  for x in subj_list)
        filled_ue = sum(x['filled'] for x in subj_list)
        grouped.append({
            'ue':       None,
            'subjects': subj_list,
            'total':    total_ue,
            'filled':   filled_ue,
            'pct':      round(filled_ue / total_ue * 100) if total_ue else 0,
        })

    grand_total  = sum(g['total']  for g in grouped)
    grand_filled = sum(g['filled'] for g in grouped)

    return render(request, 'timetable/cahier_texte_view.html', {
        'class_group':   class_group,
        'semester':      semester,
        'grouped':       grouped,
        'grand_total':   grand_total,
        'grand_filled':  grand_filled,
        'grand_pct':     round(grand_filled / grand_total * 100) if grand_total else 0,
        'class_id':      class_id,
        'semester_id':   semester_id,
        'can_validate':  user.can_validate_session_log(class_group),
    })


# ── Admin : modifier un SessionLog (AJAX POST) ────────────────────────────────

@login_required
def cahier_session_edit(request, log_pk):
    if not (request.user.can_manage_dept() or request.user.is_admin()):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    log = get_object_or_404(SessionLog, pk=log_pk)
    if log.timetable_entry.semester.is_locked:
        return JsonResponse({'error': log.timetable_entry.semester.lock_message}, status=403)
    if log.is_validated:
        return JsonResponse({'error': "Ce cahier de texte a été validé et ne peut plus être modifié."}, status=403)

    objectives = request.POST.get('objectives', '').strip()
    content    = request.POST.get('content', '').strip()
    remarks    = request.POST.get('remarks', '').strip()

    if not objectives:
        return JsonResponse({'error': 'Les objectifs sont obligatoires.'}, status=400)

    log.objectives = objectives
    log.content    = content
    log.remarks    = remarks
    log.save()

    return JsonResponse({
        'ok':         True,
        'objectives': log.objectives,
        'content':    log.content,
        'remarks':    log.remarks,
    })


# ── Admin : supprimer un SessionLog (AJAX POST) ───────────────────────────────

@login_required
def cahier_session_delete(request, log_pk):
    if not (request.user.can_manage_dept() or request.user.is_admin()):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    log = get_object_or_404(SessionLog, pk=log_pk)
    if log.timetable_entry.semester.is_locked:
        return JsonResponse({'error': log.timetable_entry.semester.lock_message}, status=403)
    if log.is_validated:
        return JsonResponse({'error': "Ce cahier de texte a été validé et ne peut plus être supprimé."}, status=403)

    log.delete()
    return JsonResponse({'ok': True})


# ── Admin : créer un SessionLog (AJAX POST) ───────────────────────────────────

@login_required
def cahier_session_create(request):
    if not (request.user.can_manage_dept() or request.user.is_admin()):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    entry_pk     = request.POST.get('entry_pk', '').strip()
    session_date = request.POST.get('session_date', '').strip()
    objectives   = request.POST.get('objectives', '').strip()
    content      = request.POST.get('content', '').strip()
    remarks      = request.POST.get('remarks', '').strip()

    if not objectives:
        return JsonResponse({'error': 'Les objectifs sont obligatoires.'}, status=400)

    try:
        from datetime import date as _date
        entry = TimetableEntry.objects.get(pk=entry_pk)
        d     = _date.fromisoformat(session_date)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    if entry.semester.is_locked:
        return JsonResponse({'error': entry.semester.lock_message}, status=403)

    existing = SessionLog.objects.filter(timetable_entry=entry, session_date=d).first()
    if existing and existing.is_validated:
        return JsonResponse({'error': "Ce cahier de texte a été validé et ne peut plus être modifié."}, status=403)

    log, created = SessionLog.objects.update_or_create(
        timetable_entry=entry,
        session_date=d,
        defaults={'objectives': objectives, 'content': content, 'remarks': remarks},
    )
    return JsonResponse({'ok': True, 'pk': log.pk, 'created': created})


# ── Responsable de classe / Chef de Département : valider un SessionLog ───────

@login_required
def validate_session_log(request, log_pk):
    """
    Valide le cahier de texte d'une séance (Responsable de classe pour sa
    classe, Chef de Département pour son département, ou Super Admin /
    Administrateur d'institut).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    log = get_object_or_404(SessionLog, pk=log_pk)
    class_group = log.timetable_entry.class_group

    if not request.user.can_validate_session_log(class_group):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if log.timetable_entry.semester.is_locked:
        return JsonResponse({'error': log.timetable_entry.semester.lock_message}, status=403)
    if not log.objectives:
        return JsonResponse({'error': "Impossible de valider un cahier de texte non renseigné."}, status=400)

    from django.utils import timezone
    log.is_validated = True
    log.validated_at = timezone.now()
    log.validated_by = request.user
    log.save(update_fields=['is_validated', 'validated_at', 'validated_by'])

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse({
            'ok': True,
            'validated_by': request.user.get_full_name() or request.user.username,
            'validated_at': log.validated_at.strftime('%d/%m/%Y %H:%M'),
        })
    messages.success(request, "Cahier de texte validé.")
    return redirect(request.POST.get('next') or 'timetable:cahier_texte_list')


# ── Responsable de classe / Chef de Département : dévalider un SessionLog ─────

@login_required
def unvalidate_session_log(request, log_pk):
    """Annule la validation d'un cahier de texte pour permettre sa correction."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    log = get_object_or_404(SessionLog, pk=log_pk)
    class_group = log.timetable_entry.class_group

    if not request.user.can_validate_session_log(class_group):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if log.timetable_entry.semester.is_locked:
        return JsonResponse({'error': log.timetable_entry.semester.lock_message}, status=403)

    log.is_validated = False
    log.validated_at = None
    log.validated_by = None
    log.save(update_fields=['is_validated', 'validated_at', 'validated_by'])

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse({'ok': True})
    messages.success(request, "Validation annulée — le cahier de texte est de nouveau modifiable.")
    return redirect(request.POST.get('next') or 'timetable:cahier_texte_list')


# ── Admin : export Word (HTML-in-DOC) du cahier de texte ─────────────────────

@login_required
def cahier_texte_word(request, class_id, semester_id):
    """Génère un fichier .doc (HTML enrichi ouvert par Word) pour une classe+semestre."""
    from django.http import HttpResponse
    from academic_core.apps.academic_structure.models import Class, Semester

    if not (request.user.can_manage_dept() or request.user.is_admin()):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    class_group = get_object_or_404(Class, pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)

    entries = TimetableEntry.objects.filter(
        class_group=class_group, semester=semester, is_active=True
    ).select_related('subject__ue', 'teacher__user', 'room').order_by(
        'subject__ue__order', 'subject__ue__code', 'subject__code'
    )
    from academic_core.db_router import get_current_db
    _db = get_current_db() or 'default'
    sessions = _build_session_list(list(entries), semester, db_alias=_db)

    ue_groups   = defaultdict(lambda: defaultdict(list))
    no_ue_group = defaultdict(list)
    for s in sessions:
        subj = s['entry'].subject
        ue   = getattr(subj, 'ue', None)
        if ue:
            ue_groups[ue][subj].append(s)
        else:
            no_ue_group[subj].append(s)

    def _sort_key_ue(u):
        return (getattr(u, 'order', 0) or 0, getattr(u, 'code', '') or '')

    grouped = []
    for ue in sorted(ue_groups.keys(), key=_sort_key_ue):
        subj_list = [{'subject': s, 'sessions': ue_groups[ue][s]}
                     for s in sorted(ue_groups[ue].keys(), key=lambda x: x.code or '')]
        grouped.append({'ue': ue, 'subjects': subj_list})
    if no_ue_group:
        subj_list = [{'subject': s, 'sessions': no_ue_group[s]}
                     for s in sorted(no_ue_group.keys(), key=lambda x: x.code or '')]
        grouped.append({'ue': None, 'subjects': subj_list})

    # ── Infos institut pour page de garde ─────────────────────────────────────
    from academic_core.pdf_utils import get_institut_config_for_request, get_logo_path
    config       = get_institut_config_for_request(request)
    faculty      = getattr(request, 'active_faculty', None)
    inst_name    = ''
    if config and getattr(config, 'name', None):
        inst_name = config.name
    elif faculty:
        inst_name = getattr(faculty, 'name', '') or getattr(faculty, 'full_name', '') or str(faculty)

    logo_path = get_logo_path(config)
    logo_b64  = ''
    if logo_path:
        import base64
        try:
            with open(logo_path, 'rb') as _f:
                _ext = logo_path.rsplit('.', 1)[-1].lower()
                _mime = 'image/png' if _ext == 'png' else 'image/jpeg'
                logo_b64 = f'data:{_mime};base64,' + base64.b64encode(_f.read()).decode()
        except Exception:
            pass

    # Drapeau sénégalais en HTML (3 bandes verticales + étoile via CSS)
    flag_html = '''
<div style="display:inline-block;width:90px;height:60px;position:relative;border:1px solid #ddd;border-radius:3px;overflow:hidden;vertical-align:middle;">
  <div style="position:absolute;left:0;top:0;width:30px;height:60px;background:#00853F;"></div>
  <div style="position:absolute;left:30px;top:0;width:30px;height:60px;background:#FDEF42;"></div>
  <div style="position:absolute;left:60px;top:0;width:30px;height:60px;background:#E31B23;"></div>
  <div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);font-size:16px;color:#00853F;line-height:1;">&#9733;</div>
</div>'''

    logo_img_html = f'<img src="{logo_b64}" style="height:70px;max-width:130px;object-fit:contain;" />' if logo_b64 else ''

    cover_html = f'''
<div style="page-break-after:always;text-align:center;padding:60px 40px;font-family:Calibri,Arial,sans-serif;">
  <div style="margin-bottom:24px;">{flag_html}</div>
  <p style="font-size:12pt;font-weight:bold;color:#1e3a5f;margin:0 0 6px;">
    MINISTÈRE DE L'ENSEIGNEMENT SUPÉRIEUR,<br>DE LA RECHERCHE ET DE L'INNOVATION
  </p>
  <p style="font-size:10pt;color:#374151;margin:0 0 32px;">Direction de l'Enseignement Supérieur Privé</p>
  <hr style="border:none;border-top:2px solid #7c3aed;margin:0 auto 32px;width:60%;"/>
  <p style="font-size:14pt;font-weight:bold;color:#7c3aed;margin:0 0 20px;">{inst_name}</p>
  {f'<div style="margin-bottom:24px;">{logo_img_html}</div>' if logo_img_html else ''}
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:0 auto 32px;width:60%;"/>
  <p style="font-size:13pt;font-weight:bold;color:#1e3a5f;margin:0 0 10px;">CAHIER DE TEXTE NUMÉRIQUE</p>
  <p style="font-size:11pt;color:#475569;margin:0 0 4px;"><strong>Classe :</strong> {class_group.name}</p>
  <p style="font-size:11pt;color:#475569;margin:0 0 2px;"><strong>Semestre :</strong> Semestre {semester.number}</p>
  <p style="font-size:10pt;color:#64748b;margin:0;">{semester.academic_year}</p>
</div>
'''

    # Construire le HTML du document Word (même structure que la vue web)
    body_html = ''
    for grp in grouped:
        ue      = grp['ue']
        ue_credits = f" — {ue.credits} crédits" if ue and getattr(ue, 'credits', None) else ''
        ue_label = f"{ue.code} — {ue.title}{ue_credits}" if ue else "Sans UE"

        body_html += f'''
<div style="margin-bottom:20px;">
  <!-- En-tête UE -->
  <div style="background:#7c3aed;color:white;font-weight:bold;font-size:11pt;
              padding:8px 14px;border-radius:6px 6px 0 0;margin-bottom:0;">
    {ue_label}
  </div>'''

        for ec_grp in grp['subjects']:
            subj    = ec_grp['subject']
            ec_label = f"{subj.code} — {subj.title}"

            sessions = ec_grp['sessions']
            n_rows   = len(sessions)
            if not sessions:
                continue
            teacher_name = sessions[0]['entry'].teacher.user.get_full_name()

            body_html += f'''
  <!-- En-tête EC -->
  <div style="background:#e0f2fe;color:#0369a1;font-weight:bold;font-size:10pt;
              padding:6px 14px;border-left:3px solid #06b6d4;margin-bottom:0;">
    {ec_label}
  </div>
  <!-- Tableau séances -->
  <table style="width:100%;border-collapse:collapse;font-size:9pt;margin-bottom:8px;">
    <tr style="background:#f0f9ff;">
      <th style="padding:5px 8px;border:1px solid #cbd5e1;text-align:left;white-space:nowrap;">Enseignant</th>
      <th style="padding:5px 8px;border:1px solid #cbd5e1;text-align:left;white-space:nowrap;">Date de séance</th>
      <th style="padding:5px 8px;border:1px solid #cbd5e1;text-align:center;white-space:nowrap;">Statut</th>
      <th style="padding:5px 8px;border:1px solid #cbd5e1;text-align:left;">Objectifs</th>
      <th style="padding:5px 8px;border:1px solid #cbd5e1;text-align:left;">Contenu réalisé</th>
    </tr>'''

            for idx, s in enumerate(sessions):
                d      = s['date']
                log    = s['log']
                dstr   = d.strftime('%d/%m/%Y')
                day_fr = d.strftime('%A')
                horo   = f"{s['entry'].start_time.strftime('%Hh%M')}–{s['entry'].end_time.strftime('%Hh%M')}"
                statut = '✔ Renseigné' if log else '✘ Non renseigné'
                scolor = '#166534' if log else '#dc2626'
                obj_txt = (log.objectives or '—') if log else '—'
                cnt_txt = (log.content    or '—') if log else '—'
                row_bg  = '#ffffff' if idx % 2 == 0 else '#f8fafc'
                # Cellule enseignant : rowspan sur la première ligne uniquement
                ens_cell = (
                    f'<td rowspan="{n_rows}" style="padding:8px 10px;border:1px solid #e2e8f0;'
                    f'vertical-align:middle;background:#f8fdff;border-right:2px solid #e0f2fe;'
                    f'font-weight:bold;color:#1e3a5f;">{teacher_name}'
                    f'<br><span style="font-size:8pt;color:#7c3aed;font-weight:normal;">{n_rows} séance{"s" if n_rows>1 else ""}</span></td>'
                ) if idx == 0 else ''

                body_html += f'''    <tr style="background:{row_bg};">
      {ens_cell}
      <td style="padding:5px 8px;border:1px solid #e2e8f0;white-space:nowrap;vertical-align:top;">
        <strong>{dstr}</strong><br>
        <span style="color:#94a3b8;font-size:8pt;">{day_fr}</span><br>
        <span style="color:#64748b;font-size:8pt;">{horo}</span>
      </td>
      <td style="padding:5px 8px;border:1px solid #e2e8f0;text-align:center;vertical-align:top;color:{scolor};font-weight:bold;">{statut}</td>
      <td style="padding:5px 8px;border:1px solid #e2e8f0;vertical-align:top;">{obj_txt}</td>
      <td style="padding:5px 8px;border:1px solid #e2e8f0;vertical-align:top;">{cnt_txt}</td>
    </tr>'''

            body_html += '  </table>'

        body_html += '</div>'

    html_content = f"""<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="UTF-8">
<style>
  body  {{ font-family: Calibri, Arial, sans-serif; font-size: 11pt; margin: 2cm; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ font-size: 9pt; vertical-align: top; }}
  @page {{ mso-footer: f1; }}
</style>
</head>
<body>
<div style="mso-element:footer;" id="f1">
  <p style="text-align:center;font-size:6pt;color:#94A3B8;margin:0;">ERP-RYTAL, App-GEST V1.0</p>
</div>
{cover_html}
<div style="text-align:center;margin-bottom:24px;">
  <p style="font-size:13pt;font-weight:bold;color:#1e3a5f;margin:0 0 4px;">
    {class_group.name} &mdash; Semestre {semester.number}
  </p>
  <p style="font-size:10pt;color:#64748b;margin:0;">{semester.academic_year}</p>
</div>
{body_html}
</body></html>"""

    safe_name = f"CahierTexte_{class_group.name}_{semester.label}".replace(' ', '_')
    response = HttpResponse(html_content, content_type='application/vnd.ms-word')
    response['Content-Disposition'] = f'attachment; filename="{safe_name}.doc"'
    return response


# ── Admin : PDF du cahier de texte complet ────────────────────────────────────

@login_required
def cahier_texte_pdf(request, class_id, semester_id):
    """Génère un PDF A4 du cahier de texte numérique pour une classe+semestre."""
    import io
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from academic_core.apps.academic_structure.models import Class, Semester
    from academic_core.pdf_utils import logo_image

    if not (request.user.can_manage_dept() or request.user.is_admin()):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    class_group = get_object_or_404(Class, pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)

    entries = TimetableEntry.objects.filter(
        class_group=class_group, semester=semester, is_active=True
    ).select_related('subject__ue', 'teacher__user', 'room').order_by(
        'subject__ue__order', 'subject__ue__code', 'subject__code'
    )
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.db_router import get_current_db as _gcdb
    _db2 = _gcdb() or 'default'
    sessions = _build_session_list(list(entries), semester, db_alias=_db2)

    # Restreindre aux séances émargées (cohérence avec la vue HTML)
    from academic_core.db_router import get_current_db
    entry_pks = [e.pk for e in entries]
    _db = get_current_db() or 'default'
    signed_keys = set(
        AttendanceSheet.objects.using(_db).filter(
            timetable_entry_id__in=entry_pks,
        ).values_list('timetable_entry_id', 'session_date')
    )
    sessions = [s for s in sessions if (s['entry'].pk, s['date']) in signed_keys]

    # Grouper UE → EC → sessions (même logique que cahier_texte_view)
    from collections import defaultdict
    ue_groups   = defaultdict(lambda: defaultdict(list))
    no_ue_group = defaultdict(list)
    for s in sessions:
        subj = s['entry'].subject
        ue   = getattr(subj, 'ue', None)
        if ue:
            ue_groups[ue][subj].append(s)
        else:
            no_ue_group[subj].append(s)

    def _sort_key_ue(u):
        return (getattr(u, 'order', 0) or 0, getattr(u, 'code', '') or '')

    grouped = []
    for ue in sorted(ue_groups.keys(), key=_sort_key_ue):
        subj_list = []
        for subj in sorted(ue_groups[ue].keys(), key=lambda x: x.code or ''):
            subj_list.append({'subject': subj, 'sessions': ue_groups[ue][subj]})
        grouped.append({'ue': ue, 'subjects': subj_list})
    if no_ue_group:
        subj_list = [{'subject': s, 'sessions': no_ue_group[s]}
                     for s in sorted(no_ue_group.keys(), key=lambda x: x.code or '')]
        grouped.append({'ue': None, 'subjects': subj_list})

    # ── Infos institut pour page de garde PDF ─────────────────────────────────
    from academic_core.pdf_utils import (get_institut_config_for_request as _gcfr,
                                         get_logo_path as _glp, senegal_flag,
                                         watermark_canvas)
    _config    = _gcfr(request)
    _faculty   = getattr(request, 'active_faculty', None)
    _inst_name = ''
    if _config and getattr(_config, 'name', None):
        _inst_name = _config.name
    elif _faculty:
        _inst_name = getattr(_faculty, 'name', '') or getattr(_faculty, 'full_name', '') or str(_faculty)

    # ── PDF ───────────────────────────────────────────────────────────────────
    pdf_buf = io.BytesIO()
    W, H    = A4
    doc = SimpleDocTemplate(pdf_buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    usable = W - 3.6*cm

    navy   = colors.HexColor('#1e3a5f')
    purple = colors.HexColor('#7c3aed')
    cyan   = colors.HexColor('#0e7490')
    green  = colors.HexColor('#16a34a')
    red    = colors.HexColor('#dc2626')
    grey   = colors.HexColor('#64748b')
    lgrey  = colors.HexColor('#f8fafc')
    border = colors.HexColor('#e2e8f0')
    yellow = colors.HexColor('#FDEF42')

    def ps(name, **kw):
        base = {'fontName': 'Helvetica', 'fontSize': 9, 'leading': 12, 'textColor': navy}
        base.update(kw)
        return ParagraphStyle(name, **base)

    s_title  = ps('T',  fontSize=14, fontName='Helvetica-Bold', alignment=TA_CENTER, leading=18)
    s_sub    = ps('S',  fontSize=9,  textColor=grey, alignment=TA_CENTER)
    s_ue     = ps('UE', fontSize=10, fontName='Helvetica-Bold', textColor=colors.white)
    s_ec     = ps('EC', fontSize=9,  fontName='Helvetica-Bold', textColor=cyan)
    s_cell   = ps('C',  fontSize=7.5, leading=10, textColor=navy)
    s_grey   = ps('G',  fontSize=7.5, leading=10, textColor=grey, fontName='Helvetica-Oblique')
    s_ok     = ps('OK', fontSize=7,  textColor=green, fontName='Helvetica-Bold')
    s_no     = ps('NO', fontSize=7,  textColor=red,   fontName='Helvetica-Bold')

    s_cover_min  = ps('CM',  fontSize=10, fontName='Helvetica-Bold',
                      textColor=navy, alignment=TA_CENTER, leading=15)
    s_cover_dir  = ps('CD',  fontSize=9, textColor=grey, alignment=TA_CENTER)
    s_cover_inst = ps('CI',  fontSize=13, fontName='Helvetica-Bold',
                      textColor=purple, alignment=TA_CENTER, leading=18)
    s_cover_doc  = ps('CDO', fontSize=14, fontName='Helvetica-Bold',
                      textColor=navy, alignment=TA_CENTER, leading=20)
    s_cover_info = ps('CIF', fontSize=10, textColor=grey, alignment=TA_CENTER)

    story = []

    # ── PAGE DE GARDE ─────────────────────────────────────────────────────────
    # Drapeau sénégalais centré (grand format)
    flag_w, flag_h = 5*cm, 3.3*cm
    flag_draw = senegal_flag(width=flag_w, height=flag_h)
    flag_tbl = Table([[flag_draw]], colWidths=[usable])
    flag_tbl.setStyle(TableStyle([
        ('ALIGN',  (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(Spacer(1, 2*cm))
    story.append(flag_tbl)
    story.append(Spacer(1, 1*cm))

    # Mentions officielles
    story.append(Paragraph(
        "MINISTÈRE DE L'ENSEIGNEMENT SUPÉRIEUR,<br/>DE LA RECHERCHE ET DE L'INNOVATION",
        s_cover_min))
    story.append(Spacer(1, .4*cm))
    story.append(Paragraph("Direction de l'Enseignement Supérieur Privé", s_cover_dir))
    story.append(Spacer(1, .8*cm))
    story.append(HRFlowable(width=usable * 0.6, thickness=1.5, color=purple,
                             hAlign='CENTER'))
    story.append(Spacer(1, .8*cm))

    # Nom de l'institut
    if _inst_name:
        story.append(Paragraph(_inst_name.upper(), s_cover_inst))
        story.append(Spacer(1, .5*cm))

    # Logo de l'institut
    _lpath = _glp(_config)
    if _lpath:
        try:
            from reportlab.platypus import Image as _Img
            _logo = _Img(_lpath, width=3.5*cm, height=2.5*cm, kind='proportional')
            _logo_tbl = Table([[_logo]], colWidths=[usable])
            _logo_tbl.setStyle(TableStyle([
                ('ALIGN',  (0,0), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ]))
            story.append(_logo_tbl)
            story.append(Spacer(1, .8*cm))
        except Exception:
            pass

    story.append(HRFlowable(width=usable * 0.4, thickness=0.5, color=border,
                             hAlign='CENTER'))
    story.append(Spacer(1, .8*cm))

    # Titre du document
    story.append(Paragraph("CAHIER DE TEXTE NUMÉRIQUE", s_cover_doc))
    story.append(Spacer(1, .5*cm))
    story.append(Paragraph(f"Classe : {class_group.name}", s_cover_info))
    story.append(Spacer(1, .2*cm))
    story.append(Paragraph(f"Semestre : Semestre {semester.number}", s_cover_info))
    story.append(Spacer(1, .1*cm))
    story.append(Paragraph(str(semester.academic_year),
                           ps('CY', fontSize=9, textColor=grey, alignment=TA_CENTER)))
    story.append(PageBreak())

    # ── CONTENU ───────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"{class_group.name}  —  Semestre {semester.number}", s_title))
    story.append(Spacer(1, .1*cm))
    story.append(Paragraph(str(semester.academic_year), s_sub))
    story.append(Spacer(1, .5*cm))
    story.append(HRFlowable(width=usable, thickness=1, color=border))
    story.append(Spacer(1, .4*cm))

    day_fr = {0:'Lun',1:'Mar',2:'Mer',3:'Jeu',4:'Ven',5:'Sam',6:'Dim'}

    col_ens  = 3.5*cm
    col_date = 2.4*cm
    col_stat = 2.0*cm
    rest     = usable - col_ens - col_date - col_stat
    col_obj  = rest * 0.50
    col_cont = rest * 0.50

    for grp in grouped:
        ue = grp['ue']
        # Bandeau UE
        ue_label = f"{ue.code} — {ue.title}" if ue else "Sans UE"
        ue_row = [[Paragraph(ue_label, s_ue)]]
        ue_table = Table(ue_row, colWidths=[usable])
        ue_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), purple),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        story.append(ue_table)
        story.append(Spacer(1, .15*cm))

        for ec_grp in grp['subjects']:
            subj = ec_grp['subject']
            # Sous-titre EC
            story.append(Paragraph(
                f"<b>{subj.code}</b>  {subj.title}",
                s_ec))
            story.append(Spacer(1, .1*cm))

            ec_sessions = ec_grp['sessions']
            if not ec_sessions:
                continue
            teacher_name = ec_sessions[0]['entry'].teacher.user.get_full_name()
            n_data_rows  = len(ec_sessions)

            # En-tête tableau
            _h = lambda t, align=TA_LEFT: Paragraph(
                f'<b>{t}</b>',
                ps('H', fontSize=7, textColor=grey, fontName='Helvetica-Bold', alignment=align))
            hdr = [_h('Enseignant'), _h('Date de séance'), _h('Statut', TA_CENTER),
                   _h('Objectifs'), _h('Contenu réalisé')]

            s_ens = ps('EN', fontSize=8, fontName='Helvetica-Bold', textColor=navy,
                       alignment=TA_CENTER, leading=11)
            s_ens_sub = ps('ES', fontSize=6.5, textColor=purple, alignment=TA_CENTER)

            rows = [hdr]
            for i, s in enumerate(ec_sessions):
                d       = s['date']
                log     = s['log']
                dstr    = f"{day_fr.get(d.weekday(),'')}\n{d.strftime('%d/%m/%Y')}\n{s['entry'].start_time.strftime('%Hh%M')}–{s['entry'].end_time.strftime('%Hh%M')}"
                stat    = Paragraph('✔ Renseigné', s_ok) if log else Paragraph('✘ Non renseigné', s_no)
                obj_txt = log.objectives[:300] if log and log.objectives else '—'
                cnt_txt = log.content[:300]    if log and log.content    else '—'
                # Cellule Enseignant : remplie seulement à la première ligne (sera spanée)
                ens_cell = Paragraph(
                    f'<b>{teacher_name}</b><br/>'
                    f'<font size="6" color="#7c3aed">{n_data_rows} séance{"s" if n_data_rows>1 else ""}</font>',
                    ps('ENC', fontSize=8, fontName='Helvetica-Bold', textColor=navy,
                       alignment=TA_CENTER, leading=11)
                ) if i == 0 else Paragraph('', s_cell)
                rows.append([
                    ens_cell,
                    Paragraph(dstr,    s_cell),
                    stat,
                    Paragraph(obj_txt, s_cell if log else s_grey),
                    Paragraph(cnt_txt, s_cell if log else s_grey),
                ])

            tbl = Table(rows,
                        colWidths=[col_ens, col_date, col_stat, col_obj, col_cont],
                        repeatRows=1)
            style_cmds = [
                ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#f0f9ff')),
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 7.5),
                ('GRID',          (0,0), (-1,-1), 0.3, border),
                ('TOPPADDING',    (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ('LEFTPADDING',   (0,0), (-1,-1), 4),
                ('VALIGN',        (0,0), (-1,-1), 'TOP'),
                ('VALIGN',        (0,1), (0,-1),  'MIDDLE'),
                ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, lgrey]),
                ('ALIGN',         (2,0), (2,-1),  'CENTER'),
                ('ALIGN',         (0,1), (0,-1),  'CENTER'),
                ('BACKGROUND',    (0,1), (0,-1),  colors.HexColor('#f8fdff')),
                ('LINEAFTER',     (0,0), (0,-1),  1, colors.HexColor('#bae6fd')),
            ]
            # Fusionner la cellule Enseignant sur toutes les lignes de données
            if n_data_rows > 1:
                style_cmds.append(('SPAN', (0,1), (0, n_data_rows)))
            tbl.setStyle(TableStyle(style_cmds))
            story.append(tbl)
            story.append(Spacer(1, .3*cm))

        story.append(Spacer(1, .2*cm))

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf_buf.seek(0)

    safe = f"CahierTexte_{class_group.name}_{semester.label}".replace(' ', '_')
    response = HttpResponse(pdf_buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{safe}.pdf"'
    return response
