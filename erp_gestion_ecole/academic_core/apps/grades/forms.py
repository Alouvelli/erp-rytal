import json
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Evaluation, Grade, EvaluationType
from academic_core.apps.subjects.models import Subject
from academic_core.apps.academic_structure.models import Semester, Class
from academic_core.apps.teachers.models import Teacher


class EvaluationForm(forms.ModelForm):
    class Meta:
        model  = Evaluation
        fields = [
            'title', 'evaluation_type', 'subject', 'class_group',
            'semester', 'date', 'duration_minutes', 'room',
            'max_score', 'coefficient', 'instructions',
        ]
        widgets = {
            'title':            forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Ex: Devoir n°1 — Algorithmique"}),
            'evaluation_type':  forms.Select(attrs={'class': 'form-select'}),
            'subject':          forms.Select(attrs={'class': 'form-select'}),
            'class_group':      forms.Select(attrs={'class': 'form-select'}),
            'semester':         forms.Select(attrs={'class': 'form-select'}),
            'date':             forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'duration_minutes': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '90', 'min': 15}),
            'room':             forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Amphi A, Salle 101…'}),
            'max_score':        forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': 1}),
            'coefficient':      forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': 0.5}),
            'instructions':     forms.Textarea(attrs={'class': 'form-control', 'rows': 3,
                                                      'placeholder': "Documents autorisés, calculatrice, consignes particulières…"}),
        }

    def __init__(self, *args, teacher_user=None, department=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Matières de l'enseignant : responsable ET/OU affecté dans l'emploi du temps
        if teacher_user and hasattr(teacher_user, 'teacher_profile'):
            from django.db.models import Q
            from academic_core.apps.timetable.models import TimetableEntry
            teacher = teacher_user.teacher_profile
            timetable_subject_ids = TimetableEntry.objects.filter(
                teacher=teacher
            ).values_list('subject_id', flat=True).distinct()
            subject_qs = Subject.objects.filter(
                Q(responsible_teacher=teacher) | Q(id__in=timetable_subject_ids)
            )
            if department:
                subject_qs = subject_qs.filter(program__department=department)
            self.fields['subject'].queryset = subject_qs.order_by('code')
        elif department:
            self.fields['subject'].queryset = Subject.objects.filter(
                program__department=department
            ).order_by('code')
        else:
            self.fields['subject'].queryset = Subject.objects.order_by('code')

        if department:
            self.fields['class_group'].queryset = Class.objects.filter(
                program__department=department
            ).order_by('name')
        else:
            self.fields['class_group'].queryset = Class.objects.order_by('name')

        # La classe est obligatoire : sans elle, les notes saisies ne peuvent pas
        # être rattachées à un EC précis dans Examens & Concours / la gestion des
        # bulletins (le modèle autorise null pour compatibilité avec d'anciennes
        # données, mais toute nouvelle évaluation doit désigner une classe).
        self.fields['class_group'].required = True

        # Semestres : inclure TOUS les semestres des modules disponibles
        # (pas uniquement is_active=True, pour ne pas bloquer des modules valides)
        final_subject_qs = self.fields['subject'].queryset
        semester_ids_from_subjects = set(
            final_subject_qs.exclude(semester__isnull=True)
                            .values_list('semester_id', flat=True)
        )
        self.fields['semester'].queryset = Semester.objects.filter(
            id__in=semester_ids_from_subjects
        ).select_related('academic_year').order_by('-academic_year__start_date', 'number')

        # Si aucun semestre trouvé via les modules, fallback sur is_active=True
        if not self.fields['semester'].queryset.exists():
            self.fields['semester'].queryset = Semester.objects.filter(
                is_active=True
            ).select_related('academic_year').order_by('-academic_year__start_date', 'number')

        # Si l'enseignant crée l'éval, masquer le champ teacher
        if teacher_user:
            self.teacher_user = teacher_user

        # Labels français
        self.fields['title'].label            = "Intitulé de l'évaluation"
        self.fields['evaluation_type'].label  = "Type"
        self.fields['subject'].label          = "Module"
        self.fields['semester'].label         = "Semestre"
        self.fields['class_group'].label      = "Classe concernée"
        self.fields['duration_minutes'].label = "Durée (minutes)"
        self.fields['room'].label             = "Lieu / Salle"
        self.fields['max_score'].label        = "Note maximale"
        self.fields['coefficient'].label      = "Coefficient"
        self.fields['instructions'].label     = "Consignes pour les étudiants"

        # Injecter les maps sur le widget Module pour le JS auto-fill
        sem_map   = {str(s.pk): s.semester_id for s in final_subject_qs if s.semester_id}
        coeff_map = {str(s.pk): float(s.coefficient) for s in final_subject_qs if s.coefficient is not None}
        self.fields['subject'].widget.attrs['data-sem-map']   = json.dumps(sem_map)
        self.fields['subject'].widget.attrs['data-coeff-map'] = json.dumps(coeff_map)


class GradeBulkForm(forms.Form):
    """Formulaire dynamique pour la saisie en masse des notes."""

    def __init__(self, *args, evaluation=None, students=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.evaluation = evaluation
        if students:
            for student in students:
                existing = None
                if evaluation:
                    try:
                        existing = Grade.objects.get(student=student, evaluation=evaluation)
                    except Grade.DoesNotExist:
                        pass
                self.fields[f'score_{student.pk}'] = forms.DecimalField(
                    label=student.full_name,
                    max_digits=5, decimal_places=2,
                    min_value=0,
                    max_value=float(evaluation.max_score) if evaluation else 20,
                    required=False,
                    initial=existing.score if existing else None,
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control form-control-sm grade-input',
                        'step': '0.25',
                        'data-max': str(evaluation.max_score) if evaluation else '20',
                        'data-student': student.pk,
                        'autocomplete': 'off',
                    })
                )
                self.fields[f'comment_{student.pk}'] = forms.CharField(
                    required=False,
                    initial=existing.comment if existing else '',
                    widget=forms.TextInput(attrs={
                        'class': 'form-control form-control-sm',
                        'placeholder': _('Commentaire optionnel'),
                    })
                )
