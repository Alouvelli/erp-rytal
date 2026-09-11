"""
Suivi des réclamations de notes traitées — alimente le compteur
"Nb réclamations traitées" du Rapport Annuel de la Direction
(voir class_results_services.py).
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .conseil_views import _can_access
from .models import GradeComplaint, Semester
from academic_core.apps.academic_structure.models import Class
from academic_core.apps.students.models import Enrollment, Student


@login_required
def reclamation_class_list(request):
    """Sélection classe/année pour le suivi des réclamations (même présentation que rattrapages)."""
    if not _can_access(request.user):
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

            semesters_by_level = {}
            for sem in selected_year.semesters.select_related('level').order_by('number'):
                semesters_by_level.setdefault(sem.level_id, []).append(sem)
            for cls in classes:
                cls.relevant_semesters = semesters_by_level.get(cls.level_id, [])

            classes_by_level = {}
            for cls in classes:
                if cls.student_count > 0:
                    classes_by_level.setdefault(cls.level_id, []).append(cls)
            for level in Level.objects.order_by('order'):
                lvl_classes = classes_by_level.get(level.pk, [])
                if lvl_classes:
                    level_groups.append({'level': level, 'classes': lvl_classes})
            orphan_classes = classes_by_level.get(None, [])
            if orphan_classes:
                level_groups.append({'level': None, 'classes': orphan_classes})
        except Exception:
            pass

    return render(request, 'grades/reclamation_class_list.html', {
        'years': years,
        'selected_year': selected_year,
        'level_groups': level_groups,
    })


@login_required
def reclamation_list(request, class_id, semester_id):
    """Liste + enregistrement des réclamations de notes traitées pour une classe/semestre."""
    if not _can_access(request.user):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    class_group = get_object_or_404(Class, pk=class_id)
    semester = get_object_or_404(Semester, pk=semester_id)

    if request.method == 'POST':
        student_id = request.POST.get('student')
        description = request.POST.get('description', '').strip()
        student = Student.objects.filter(pk=student_id).first()
        if not student:
            messages.error(request, "Étudiant introuvable — merci de le choisir dans la liste proposée.")
        elif not description:
            messages.error(request, "Le motif de la réclamation est obligatoire.")
        else:
            GradeComplaint.objects.create(
                student=student, class_group=class_group, semester=semester,
                description=description, processed_by=request.user,
            )
            messages.success(request, f"Réclamation de {student.user.get_full_name()} enregistrée.")
        return redirect('grades:reclamation_list', class_id=class_id, semester_id=semester_id)

    enrolled_students = [
        e.student for e in Enrollment.objects.filter(
            class_group=class_group, status=Enrollment.STATUS_VALIDATED
        ).select_related('student__user').order_by('student__user__last_name')
    ]

    complaints = GradeComplaint.objects.filter(
        class_group=class_group, semester=semester,
    ).select_related('student__user', 'processed_by').order_by('-processed_at')

    already_processed_ids = set(complaints.values_list('student_id', flat=True))

    return render(request, 'grades/reclamation_list.html', {
        'class_group': class_group,
        'semester': semester,
        'enrolled_students': enrolled_students,
        'complaints': complaints,
        'already_processed_ids': already_processed_ids,
    })


@login_required
def reclamation_delete(request, pk):
    """Annule (supprime) une réclamation enregistrée par erreur."""
    if not _can_access(request.user):
        messages.error(request, "Accès réservé.")
        return redirect('dashboard:index')

    complaint = get_object_or_404(GradeComplaint, pk=pk)
    class_id, semester_id = complaint.class_group_id, complaint.semester_id
    if request.method == 'POST':
        complaint.delete()
        messages.success(request, "Réclamation supprimée.")
    return redirect('grades:reclamation_list', class_id=class_id, semester_id=semester_id)
