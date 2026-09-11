from datetime import date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .models import PlanningHoliday, TimetableEntry
from academic_core.apps.academic_structure.models import Class


def _get_dept_classes(request):
    dept  = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    qs = Class.objects.select_related('program__department')
    if dept:
        qs = qs.filter(program__department=dept)
    elif faculty:
        qs = qs.filter(program__department__faculty=faculty)

    # Seules les classes de l'année académique en cours peuvent être
    # suspendues — une classe d'une année précédente n'a plus de planning
    # actif à mettre en pause.
    fac_for_years = faculty or (dept.faculty if dept else None)
    if fac_for_years:
        from academic_core.apps.academic_structure.models import AcademicYear
        current_year = AcademicYear.objects.filter(faculty=fac_for_years, is_current=True).first()
        if current_year:
            qs = qs.filter(academic_year=current_year)
    return qs.order_by('name')


@login_required
def holiday_list(request):
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé aux administrateurs de département.")
        return redirect('dashboard:index')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    qs = PlanningHoliday.objects.select_related('class_group', 'created_by')
    if dept:
        qs = qs.filter(class_group__program__department=dept)
    elif faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)

    today  = date.today()
    active   = [h for h in qs if h.start_date <= today <= h.end_date]
    upcoming = [h for h in qs if h.start_date > today]
    expired  = [h for h in qs if h.end_date < today]

    classes = _get_dept_classes(request)

    return render(request, 'timetable/holiday_list.html', {
        'active':   active,
        'upcoming': upcoming,
        'expired':  expired,
        'classes':  classes,
        'today':    today,
    })


@login_required
def holiday_create(request):
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé aux administrateurs de département.")
        return redirect('dashboard:index')

    classes = _get_dept_classes(request)

    if request.method == 'POST':
        class_ids  = request.POST.getlist('class_group_ids')
        start_date = request.POST.get('start_date')
        end_date   = request.POST.get('end_date')
        reason     = request.POST.get('reason', '').strip()

        errors = []
        if not class_ids:
            errors.append("Sélectionnez au moins une classe.")
        if not start_date or not end_date:
            errors.append("Les dates de début et de fin sont obligatoires.")
        else:
            try:
                sd = date.fromisoformat(start_date)
                ed = date.fromisoformat(end_date)
                if ed < sd:
                    errors.append("La date de fin doit être postérieure à la date de début.")
            except ValueError:
                errors.append("Format de date invalide.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'timetable/holiday_form.html', {
                'classes':           classes,
                'selected_ids':      request.POST.getlist('class_group_ids'),
                'form_start_date':   request.POST.get('start_date', ''),
                'form_end_date':     request.POST.get('end_date', ''),
                'form_reason':       request.POST.get('reason', ''),
                'title': 'Nouvelle suspension',
            })

        created = 0
        for cid in class_ids:
            try:
                cg = Class.objects.get(pk=cid)
                PlanningHoliday.objects.create(
                    class_group=cg,
                    start_date=sd,
                    end_date=ed,
                    reason=reason,
                    created_by=request.user,
                )
                created += 1
            except Class.DoesNotExist:
                pass

        messages.success(request, f"{created} suspension(s) créée(s) avec succès.")
        return redirect('timetable:holiday_list')

    return render(request, 'timetable/holiday_form.html', {
        'classes':         classes,
        'selected_ids':    [],
        'form_start_date': '',
        'form_end_date':   '',
        'form_reason':     '',
        'title': 'Nouvelle suspension',
    })


@login_required
def holiday_edit(request, pk):
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé aux administrateurs de département.")
        return redirect('dashboard:index')

    holiday = get_object_or_404(PlanningHoliday, pk=pk)
    classes = _get_dept_classes(request)

    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date   = request.POST.get('end_date')
        reason     = request.POST.get('reason', '').strip()

        try:
            sd = date.fromisoformat(start_date)
            ed = date.fromisoformat(end_date)
            if ed < sd:
                messages.error(request, "La date de fin doit être postérieure à la date de début.")
                raise ValueError
            holiday.start_date = sd
            holiday.end_date   = ed
            holiday.reason     = reason
            holiday.save()
            messages.success(request, "Suspension modifiée.")
            return redirect('timetable:holiday_list')
        except ValueError:
            pass

    return render(request, 'timetable/holiday_form.html', {
        'classes': classes,
        'holiday': holiday,
        'title': 'Modifier la suspension',
    })


@login_required
def holiday_delete(request, pk):
    if not request.user.can_manage_dept():
        return JsonResponse({'error': 'Accès refusé'}, status=403)
    holiday = get_object_or_404(PlanningHoliday, pk=pk)
    if request.method == 'POST':
        holiday.delete()
        messages.success(request, "Suspension supprimée.")
    return redirect('timetable:holiday_list')


# ── API : vérifier si un enseignant est déjà planifié sur une plage ──────────

@login_required
def teacher_conflicts_api(request):
    """
    GET ?teacher_id=X&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    Retourne les conflits de l'enseignant sur la période.
    """
    teacher_id = request.GET.get('teacher_id')
    start_date = request.GET.get('start_date')
    end_date   = request.GET.get('end_date')

    if not (teacher_id and start_date and end_date):
        return JsonResponse({'conflicts': []})

    try:
        sd = date.fromisoformat(start_date)
        ed = date.fromisoformat(end_date)
    except ValueError:
        return JsonResponse({'conflicts': []})

    # Jours de la semaine touchés par la plage
    from datetime import timedelta
    days_in_range = set()
    cur = sd
    while cur <= ed:
        days_in_range.add(cur.isoweekday())
        cur += timedelta(days=1)

    entries = TimetableEntry.objects.filter(
        teacher_id=teacher_id,
        is_active=True,
        day_of_week__in=days_in_range,
    ).select_related('subject', 'class_group', 'semester').exclude(
        recurrence=TimetableEntry.RECURRENCE_ONCE
    )

    conflicts = []
    for e in entries:
        conflicts.append({
            'subject':     str(e.subject),
            'class_group': str(e.class_group),
            'day':         e.get_day_of_week_display(),
            'time':        f"{e.start_time.strftime('%H:%M')}–{e.end_time.strftime('%H:%M')}",
        })

    return JsonResponse({'conflicts': conflicts})
