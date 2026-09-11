"""
Rapport Annuel de la Direction Pédagogique — vue de restitution.
"""
import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, FileResponse
from django.shortcuts import render, redirect, get_object_or_404

from .conseil_views import _can_access
from .annual_report_services import compute_annual_department_report
from .class_results_services import compute_class_results_table


@login_required
def rapport_annuel_direction(request):
    if not _can_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import AcademicYear, Department, Semester

    faculty = getattr(request, 'active_faculty', None)

    # Pas de select_related('faculty') : Faculty est un modèle maître (toujours
    # en base 'default'), Department est routé par tenant — un JOIN vers la
    # table locale 'faculties' (toujours vide côté tenant) ferait disparaître
    # tous les départements, quel que soit le filtre (piège déjà documenté
    # ailleurs, ex. academic_structure/views.py, accounts/views.py).
    departments = Department.objects.order_by('name')
    if faculty:
        departments = departments.filter(faculty=faculty)

    academic_years = AcademicYear.objects.order_by('-start_date')
    if faculty:
        academic_years = academic_years.filter(faculty=faculty)

    year_param = request.GET.get('year')
    if year_param:
        selected_year = academic_years.filter(pk=year_param).first()
    else:
        selected_year = academic_years.filter(is_current=True).first()

    dept_param = request.GET.get('department')
    selected_department = departments.filter(pk=dept_param).first() if dept_param else None

    semesters = Semester.objects.filter(
        academic_year=selected_year
    ).select_related('level').order_by('level__order', 'number') if selected_year else Semester.objects.none()

    semester_param = request.GET.get('semester')
    selected_semester = semesters.filter(pk=semester_param).first() if semester_param else None

    context = {
        'departments': departments,
        'academic_years': academic_years,
        'selected_year': selected_year,
        'selected_department': selected_department,
        'semesters': semesters,
        'selected_semester': selected_semester,
        'department_summaries': [],
        'detail': None,
        'class_results': None,
    }

    if not selected_year:
        return render(request, 'grades/rapport_annuel_direction.html', context)

    if selected_department:
        detail = compute_annual_department_report(selected_department, selected_year)
        context['detail'] = detail
        context['gender_labels_json'] = json.dumps(list(detail['summary']['by_gender'].keys()))
        context['gender_totals_json'] = json.dumps(
            [v['total'] for v in detail['summary']['by_gender'].values()]
        )
        context['nationality_labels_json'] = json.dumps(list(detail['summary']['by_nationality'].keys()))
        context['nationality_totals_json'] = json.dumps(
            [v['total'] for v in detail['summary']['by_nationality'].values()]
        )

        if selected_semester:
            context['class_results'] = compute_class_results_table(
                selected_department, selected_year, selected_semester
            )
    else:
        # Pas de département choisi : vue d'ensemble, un résumé par département
        # de la faculté active (chacun cliquable pour le détail par classe).
        for dept in departments:
            report = compute_annual_department_report(dept, selected_year)
            context['department_summaries'].append({
                'department': dept,
                'semester': report['semester'],
                **report['summary'],
            })

    return render(request, 'grades/rapport_annuel_direction.html', context)


def _resolve_department_year(request):
    from academic_core.apps.academic_structure.models import AcademicYear, Department
    department = get_object_or_404(Department, pk=request.GET.get('department'))
    academic_year = get_object_or_404(AcademicYear, pk=request.GET.get('year'))
    return department, academic_year


@login_required
def rapport_annuel_pdf(request):
    if not _can_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.pdf_utils import get_institut_config_for_request
    from academic_core.apps.reports.pdf_generator import generate_rapport_annuel_pdf

    department, academic_year = _resolve_department_year(request)
    detail = compute_annual_department_report(department, academic_year)
    config = get_institut_config_for_request(request)
    buf = generate_rapport_annuel_pdf(detail, config=config)
    filename = f"rapport_annuel_{department.code}_{academic_year.label}.pdf".replace(' ', '_')
    return FileResponse(buf, as_attachment=True, filename=filename, content_type='application/pdf')


@login_required
def rapport_annuel_excel(request):
    if not _can_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.pdf_utils import get_institut_config_for_request
    from academic_core.apps.reports.excel_generator import generate_rapport_annuel_excel

    department, academic_year = _resolve_department_year(request)
    detail = compute_annual_department_report(department, academic_year)
    config = get_institut_config_for_request(request)
    buf = generate_rapport_annuel_excel(detail, config=config)
    filename = f"rapport_annuel_{department.code}_{academic_year.label}.xlsx".replace(' ', '_')
    return HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def _resolve_department_year_semester(request):
    from academic_core.apps.academic_structure.models import AcademicYear, Department, Semester
    department = get_object_or_404(Department, pk=request.GET.get('department'))
    academic_year = get_object_or_404(AcademicYear, pk=request.GET.get('year'))
    semester = get_object_or_404(Semester, pk=request.GET.get('semester'))
    return department, academic_year, semester


_CLASS_RESULTS_SESSIONS = ('normale', 'normale_reclamation', 'rattrapage', 'rattrapage_reclamation')


def _resolve_sessions(request):
    """Export par rubrique : ?section=normale|normale_reclamation|rattrapage|
    rattrapage_reclamation n'exporte qu'une session ; sans ce paramètre (ou
    une valeur invalide), les 4."""
    section = request.GET.get('section')
    if section in _CLASS_RESULTS_SESSIONS:
        return (section,)
    return _CLASS_RESULTS_SESSIONS


@login_required
def class_results_excel(request):
    if not _can_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.pdf_utils import get_institut_config_for_request
    from academic_core.apps.reports.excel_generator import generate_class_results_excel

    department, academic_year, semester = _resolve_department_year_semester(request)
    sessions = _resolve_sessions(request)
    data = compute_class_results_table(department, academic_year, semester)
    config = get_institut_config_for_request(request)
    buf = generate_class_results_excel(data, config=config, sessions=sessions)
    filename = f"resultats_classes_{department.code}_{semester.label}.xlsx".replace(' ', '_')
    return HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@login_required
def class_results_pdf(request):
    if not _can_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.pdf_utils import get_institut_config_for_request
    from academic_core.apps.reports.pdf_generator import generate_class_results_pdf

    department, academic_year, semester = _resolve_department_year_semester(request)
    sessions = _resolve_sessions(request)
    data = compute_class_results_table(department, academic_year, semester)
    config = get_institut_config_for_request(request)
    buf = generate_class_results_pdf(data, config=config, sessions=sessions)
    filename = f"resultats_classes_{department.code}_{semester.label}.pdf".replace(' ', '_')
    return FileResponse(buf, as_attachment=True, filename=filename, content_type='application/pdf')


@login_required
def class_results_word(request):
    if not _can_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.pdf_utils import get_institut_config_for_request
    from .word_class_results import generate_class_results_word

    department, academic_year, semester = _resolve_department_year_semester(request)
    sessions = _resolve_sessions(request)
    data = compute_class_results_table(department, academic_year, semester)
    config = get_institut_config_for_request(request)
    buf = generate_class_results_word(data, config=config, sessions=sessions)
    filename = f"resultats_classes_{department.code}_{semester.label}.docx".replace(' ', '_')
    return HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
