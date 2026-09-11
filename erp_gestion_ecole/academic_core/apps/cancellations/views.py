from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone
from django.shortcuts import render

from .models import CourseCancellation
from academic_core.apps.timetable.models import TimetableEntry
from academic_core.apps.rooms.models import Room
from academic_core.apps.notifications.utils import notify_class_students


# ─── helpers ──────────────────────────────────────────────────────────────────

def _week_bounds(offset=0):
    """Retourne (lundi, dimanche) de la semaine offset par rapport à aujourd'hui."""
    today  = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _can_act(user):
    """Enseignant, admin de département ou assistante."""
    return user.is_enseignant() or user.can_manage_dept()


# ─── vue principale ────────────────────────────────────────────────────────────

@login_required
def cancellation_dashboard(request):
    user = request.user
    if not _can_act(user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    # Navigation semaine
    try:
        week_offset = int(request.GET.get('week', 0))
    except ValueError:
        week_offset = 0
    monday, sunday = _week_bounds(week_offset)

    # Toutes les entrées actives de l'emploi du temps (semestre actif ou non),
    # mais uniquement de l'année académique en cours — une séance d'une année
    # précédente ne doit pas apparaître ici mélangée à la semaine courante.
    entries_qs = TimetableEntry.objects.filter(
        is_active=True,
    ).select_related('subject', 'class_group', 'teacher__user', 'room', 'semester')

    faculty = getattr(request, 'active_faculty', None)
    dept    = getattr(request, 'active_department', None)
    fac_for_years = faculty or (dept.faculty if dept else None)
    if fac_for_years:
        from academic_core.apps.academic_structure.models import AcademicYear
        current_year = AcademicYear.objects.filter(faculty=fac_for_years, is_current=True).first()
        if current_year:
            entries_qs = entries_qs.filter(semester__academic_year=current_year)

    if user.is_enseignant() and not user.can_manage_dept():
        entries_qs = entries_qs.filter(teacher__user=user)
    else:
        if dept:
            entries_qs = entries_qs.filter(class_group__program__department=dept)

    # Cancellations existantes sur la semaine (indexed by (entry_id, date))
    days = [monday + timedelta(days=i) for i in range(7)]
    cancellations_index = {}
    existing = CourseCancellation.objects.filter(
        timetable_entry__in=entries_qs,
        session_date__range=(monday, sunday),
    ).select_related('timetable_entry', 'requested_by')
    for c in existing:
        cancellations_index[(c.timetable_entry_id, c.session_date)] = c

    # Construire les données par classe (accordéon)
    DAY_NAMES = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    week_days = []
    for i, d in enumerate(days):
        dow = i + 1
        day_entries = [e for e in entries_qs if e.day_of_week == dow]
        day_entries.sort(key=lambda e: e.start_time)
        sessions = []
        for entry in day_entries:
            cancel = cancellations_index.get((entry.pk, d))
            sessions.append({'entry': entry, 'date': d, 'cancellation': cancel})
        week_days.append({
            'name':     DAY_NAMES[i],
            'date':     d,
            'is_today': d == date.today(),
            'sessions': sessions,
        })

    # Grouper par classe pour l'affichage accordéon
    from collections import OrderedDict
    classes_dict = OrderedDict()
    for day in week_days:
        for s in day['sessions']:
            cg = s['entry'].class_group
            if cg.pk not in classes_dict:
                classes_dict[cg.pk] = {
                    'class_group': cg,
                    'sessions': [],
                    'has_cancellation': False,
                }
            classes_dict[cg.pk]['sessions'].append({
                **s,
                'day_name': day['name'],
                'is_today': day['is_today'],
            })
            if s['cancellation']:
                classes_dict[cg.pk]['has_cancellation'] = True

    classes_list = list(classes_dict.values())

    # Historique (toutes les annulations de l'enseignant ou du dept)
    history_qs = CourseCancellation.objects.select_related(
        'timetable_entry__subject', 'timetable_entry__class_group',
        'timetable_entry__teacher__user', 'requested_by', 'reviewed_by',
    ).order_by('-session_date')
    if user.is_enseignant() and not user.can_manage_dept():
        history_qs = history_qs.filter(requested_by=user)
    else:
        dept = getattr(request, 'active_department', None)
        if dept:
            history_qs = history_qs.filter(
                timetable_entry__class_group__program__department=dept
            )

    rooms = Room.objects.all().order_by('name')

    return render(request, 'cancellations/dashboard.html', {
        'week_days':    week_days,
        'classes_list': classes_list,
        'week_offset':  week_offset,
        'monday':       monday,
        'sunday':       sunday,
        'history':      history_qs[:50],
        'rooms':        rooms,
        'is_admin':     user.can_manage_dept(),
    })


# ─── action annuler / reporter ─────────────────────────────────────────────────

@login_required
def cancel_or_postpone(request, entry_pk, session_date_str):
    """POST — annule ou reporte une séance et notifie les étudiants."""
    if request.method != 'POST':
        return redirect('cancellations:list')

    user = request.user
    if not _can_act(user):
        messages.error(request, "Accès refusé.")
        return redirect('cancellations:list')

    entry = get_object_or_404(TimetableEntry, pk=entry_pk)

    # Un enseignant ne peut agir que sur ses propres séances
    if user.is_enseignant() and not user.can_manage_dept():
        if entry.teacher.user != user:
            messages.error(request, "Vous ne pouvez agir que sur vos propres séances.")
            return redirect('cancellations:list')

    try:
        session_date = date.fromisoformat(session_date_str)
    except ValueError:
        messages.error(request, "Date invalide.")
        return redirect('cancellations:list')

    req_type = request.POST.get('request_type', CourseCancellation.TYPE_CANCELLATION)
    reason   = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, "Le motif est obligatoire.")
        return redirect('cancellations:list')

    # Éviter les doublons : mettre à jour si déjà existant
    cancel, created = CourseCancellation.objects.get_or_create(
        timetable_entry=entry,
        session_date=session_date,
        defaults={
            'request_type': req_type,
            'reason':        reason,
            'requested_by':  user,
            'status':        CourseCancellation.STATUS_APPROVED,
            'reviewed_by':   user,
            'reviewed_at':   timezone.now(),
        },
    )
    if not created:
        cancel.request_type  = req_type
        cancel.reason        = reason
        cancel.requested_by  = user
        cancel.status        = CourseCancellation.STATUS_APPROVED
        cancel.reviewed_by   = user
        cancel.reviewed_at   = timezone.now()
        cancel.review_comment = ''

    if req_type == CourseCancellation.TYPE_POSTPONEMENT:
        cancel.rescheduled_date  = request.POST.get('rescheduled_date') or None
        cancel.rescheduled_start = request.POST.get('rescheduled_start') or None
        cancel.rescheduled_end   = request.POST.get('rescheduled_end') or None
        room_pk = request.POST.get('rescheduled_room')
        cancel.rescheduled_room  = Room.objects.filter(pk=room_pk).first() if room_pk else None
    else:
        cancel.rescheduled_date  = None
        cancel.rescheduled_start = None
        cancel.rescheduled_end   = None
        cancel.rescheduled_room  = None

    cancel.save()

    # Notification aux étudiants
    _notify_students(cancel, entry)

    week_offset = request.POST.get('week_offset', '0')
    action_label = 'reportée' if req_type == CourseCancellation.TYPE_POSTPONEMENT else 'annulée'
    messages.success(request, f"Séance {action_label}. Les étudiants ont été notifiés.")
    return redirect(f"{request.build_absolute_uri('/cancellations/')}?week={week_offset}")


def _notify_students(cancel, entry):
    type_label = 'reporté' if cancel.request_type == CourseCancellation.TYPE_POSTPONEMENT else 'annulé'
    title = f"Cours {type_label} — {entry.subject.title}"
    msg   = (
        f"Le cours {entry.subject.title} "
        f"({entry.class_group.name}) "
        f"du {cancel.session_date.strftime('%A %d/%m/%Y')} "
        f"a été {type_label}."
    )
    if cancel.request_type == CourseCancellation.TYPE_POSTPONEMENT and cancel.rescheduled_date:
        msg += (
            f" Nouveau créneau : {cancel.rescheduled_date.strftime('%d/%m/%Y')}"
            + (f" à {cancel.rescheduled_start.strftime('%H:%M')}" if cancel.rescheduled_start else "")
            + (f" – {cancel.rescheduled_end.strftime('%H:%M')}" if cancel.rescheduled_end else "")
            + (f", salle {cancel.rescheduled_room.name}" if cancel.rescheduled_room else "")
            + "."
        )
    if cancel.reason:
        msg += f" Motif : {cancel.reason}"

    notify_class_students(
        class_group=entry.class_group,
        notification_type='COURSE_CANCELLED',
        title=title,
        message=msg,
        priority='HIGH',
        link='/cancellations/',
    )


# ─── annuler une annulation (rétablir la séance) ─────────────────────────────

@login_required
def restore_session(request, pk):
    """Supprime une annulation/report → la séance redevient normale."""
    cancel = get_object_or_404(CourseCancellation, pk=pk)
    user   = request.user

    if not _can_act(user):
        messages.error(request, "Accès refusé.")
        return redirect('cancellations:list')

    entry = cancel.timetable_entry
    if user.is_enseignant() and not user.can_manage_dept():
        if entry.teacher.user != user:
            messages.error(request, "Accès refusé.")
            return redirect('cancellations:list')

    week_offset = request.GET.get('week', '0')
    cancel.delete()
    messages.success(request, "La séance a été rétablie.")
    return redirect(f"/cancellations/?week={week_offset}")
