from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, FileResponse
from django.contrib import messages
from django.utils import timezone

from academic_core.apps.students.models import Student
from academic_core.apps.teachers.models import Teacher
from academic_core.apps.academic_structure.models import Semester, Class, AcademicYear


@login_required
def reports_index(request):
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        from django.shortcuts import redirect
        return redirect('dashboard:index')
    faculty      = getattr(request, 'active_faculty', None)
    semesters    = Semester.objects.select_related('academic_year').order_by('-academic_year__start_date')
    classes_qs   = Class.objects.select_related('program').order_by('code')
    academic_yrs = AcademicYear.objects.order_by('-start_date')
    if faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)
    return render(request, 'reports/index.html', {
        'semesters':    semesters,
        'classes':      classes_qs,
        'academic_yrs': academic_yrs,
    })


@login_required
def bulletin_pdf(request, student_id, semester_id):
    student  = get_object_or_404(Student, pk=student_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    # Students can only view their own bulletin
    if request.user.is_etudiant():
        sp = getattr(request.user, 'student_profile', None)
        if not sp or sp.pk != student.pk:
            messages.error(request, "Accès refusé.")
            from django.shortcuts import redirect
            return redirect('dashboard:index')
    from .pdf_generator import generate_bulletin
    from academic_core.pdf_utils import get_institut_config_for_request
    config   = get_institut_config_for_request(request)
    buf      = generate_bulletin(student, semester, config=config)
    filename = f"bulletin_{student.matricule}_{semester.label.replace(' ', '_')}.pdf"
    return FileResponse(buf, as_attachment=True, filename=filename, content_type='application/pdf')


@login_required
def teacher_report_pdf(request, teacher_id, year_id):
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        from django.shortcuts import redirect
        return redirect('dashboard:index')
    teacher      = get_object_or_404(Teacher, pk=teacher_id)
    academic_year = get_object_or_404(AcademicYear, pk=year_id)
    from .pdf_generator import generate_teacher_report
    from academic_core.pdf_utils import get_institut_config_for_request
    config       = get_institut_config_for_request(request)
    buf          = generate_teacher_report(teacher, academic_year, config=config)
    filename     = f"bilan_heures_{teacher.matricule}_{academic_year.label}.pdf"
    return FileResponse(buf, as_attachment=True, filename=filename, content_type='application/pdf')


@login_required
def absence_report_pdf(request, class_id, semester_id):
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        from django.shortcuts import redirect
        return redirect('dashboard:index')
    class_group = get_object_or_404(Class, pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)
    from .pdf_generator import generate_absence_report
    from academic_core.pdf_utils import get_institut_config_for_request
    config      = get_institut_config_for_request(request)
    buf         = generate_absence_report(class_group, semester, config=config)
    filename    = f"absences_{class_group.code}_{semester.label.replace(' ', '_')}.pdf"
    return FileResponse(buf, as_attachment=True, filename=filename, content_type='application/pdf')


@login_required
def grades_excel(request, class_id, semester_id):
    if not (request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        from django.shortcuts import redirect
        return redirect('dashboard:index')
    class_group = get_object_or_404(Class, pk=class_id)
    semester    = get_object_or_404(Semester, pk=semester_id)
    from .excel_generator import generate_grades_excel
    from academic_core.pdf_utils import get_institut_config_for_request
    config      = get_institut_config_for_request(request)
    buf         = generate_grades_excel(class_group, semester, config=config)
    filename    = f"notes_{class_group.code}_{semester.label.replace(' ', '_')}.xlsx"
    return HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@login_required
def timetable_excel(request, semester_id):
    semester    = get_object_or_404(Semester, pk=semester_id)
    class_id    = request.GET.get('class_id')
    teacher_id  = request.GET.get('teacher_id')
    class_group = Class.objects.filter(pk=class_id).first() if class_id else None
    teacher     = Teacher.objects.filter(pk=teacher_id).first() if teacher_id else None
    from .excel_generator import generate_timetable_excel
    from academic_core.pdf_utils import get_institut_config_for_request
    config      = get_institut_config_for_request(request)
    buf         = generate_timetable_excel(semester, class_group, teacher, config=config)
    filename    = f"emploi_du_temps_{semester.label.replace(' ', '_')}.xlsx"
    return HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
