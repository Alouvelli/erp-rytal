from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from .models import TimetableEntry
from academic_core.apps.academic_structure.models import Class, Semester
from academic_core.apps.subjects.models import Subject
from academic_core.apps.teachers.models import Teacher
from academic_core.apps.rooms.models import Room


class TimetableEntryForm(forms.ModelForm):
    # Champ hors modèle : le taux horaire n'est pas stocké sur TimetableEntry
    # mais sur accounting.HourlyRate (clé département × niveau × année
    # académique, dérivée de class_group) — voir
    # timetable/views.py::_apply_taux_horaire. Facultatif : laissé vide, le
    # taux existant (le cas échéant) n'est pas modifié.
    taux_horaire = forms.DecimalField(
        required=False, min_value=0, max_digits=10, decimal_places=2,
        label='Taux horaire (FCFA/heure)',
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0',
            'placeholder': '— sélectionnez une classe —',
        }),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        exclude_pk = self.instance.pk if self.instance and self.instance.pk else None

        # Tous les semestres créés doivent être sélectionnables ici (planifier une
        # séance sur un semestre pas encore actif, ou consulter/modifier un
        # semestre passé, doit rester possible), mais uniquement ceux créés
        # dans l'institut courant (Gestion de la Scolarité).
        dept    = getattr(request, 'active_department', None)
        faculty = getattr(request, 'active_faculty', None)
        # Le Chef de Département (RESPONSABLE) et son Assistante ont les mêmes
        # droits sur tout l'institut : ils doivent pouvoir affecter un module
        # de leur département à un enseignant créé dans un autre département
        # du même institut, donc ne pas être bridés au seul département actif.
        dept_head = bool(request) and getattr(request.user, 'is_responsable', lambda: False)()
        semester_qs = Semester.objects.select_related('academic_year').order_by(
            '-academic_year__start_date', 'number'
        )
        if faculty:
            semester_qs = semester_qs.filter(academic_year__faculty=faculty)
        self.fields['semester'].queryset = semester_qs

        # Enseignant : même périmètre que la liste des enseignants (Ajouter
        # Enseignant) — département actif en priorité, sinon faculté — pour ne
        # pas proposer ici des enseignants absents de cette liste. On garde
        # l'enseignant déjà affecté à l'instance en édition même s'il sort de
        # ce périmètre (changement de département depuis), pour ne pas le
        # faire disparaître silencieusement du formulaire.
        teacher_qs = Teacher.objects.select_related('user').order_by('user__last_name')
        if dept and not dept_head:
            teacher_qs = teacher_qs.filter(user__department=dept)
        elif faculty:
            teacher_qs = teacher_qs.filter(user__department__faculty=faculty)
        if self.instance and self.instance.teacher_id and not teacher_qs.filter(pk=self.instance.teacher_id).exists():
            teacher_qs = Teacher.objects.select_related('user').filter(
                Q(pk__in=teacher_qs.values_list('pk', flat=True)) | Q(pk=self.instance.teacher_id)
            ).order_by('user__last_name')
        self.fields['teacher'].queryset = teacher_qs

        # Classe : même périmètre que la liste des enseignants/salles ci-dessus
        # (département actif en priorité, sinon faculté) — ce champ n'était
        # jusqu'ici filtré ni par département, ni même par institut. On garde
        # la classe déjà affectée à l'instance en édition même si elle sort de
        # ce périmètre, pour ne pas la faire disparaître silencieusement.
        class_qs = Class.objects.select_related('program__department', 'academic_year').order_by('name')
        if dept and not dept_head:
            class_qs = class_qs.filter(program__department=dept)
        elif faculty:
            class_qs = class_qs.filter(program__department__faculty=faculty)
        if self.instance and self.instance.class_group_id and not class_qs.filter(pk=self.instance.class_group_id).exists():
            class_qs = Class.objects.select_related('program__department', 'academic_year').filter(
                Q(pk__in=class_qs.values_list('pk', flat=True)) | Q(pk=self.instance.class_group_id)
            ).order_by('name')
        self.fields['class_group'].queryset = class_qs

        # Source des valeurs : POST soumis ou instance existante (mode édition)
        data = args[0] if args else kwargs.get('data')
        if data:
            day   = data.get('day_of_week')
            start = data.get('start_time')
            end   = data.get('end_time')
        elif self.instance and self.instance.pk:
            day   = self.instance.day_of_week
            start = self.instance.start_time
            end   = self.instance.end_time
        else:
            day = start = end = None

        if day and start and end:
            occupied_qs = TimetableEntry.objects.filter(
                day_of_week=day,
                start_time__lt=end,
                end_time__gt=start,
                is_active=True,
                room__isnull=False,
            )
            if exclude_pk:
                occupied_qs = occupied_qs.exclude(pk=exclude_pk)
            occupied_ids = list(occupied_qs.values_list('room_id', flat=True))
            self.fields['room'].queryset = (
                Room.objects.filter(is_available=True).exclude(pk__in=occupied_ids).order_by('name')
            )
            # Mémoriser les IDs occupées pour info dans le template
            self._occupied_room_ids = occupied_ids
        else:
            self.fields['room'].queryset = Room.objects.filter(is_available=True).order_by('name')
            self._occupied_room_ids = []

    class Meta:
        model = TimetableEntry
        fields = [
            'semester', 'class_group', 'subject', 'teacher', 'room',
            'day_of_week', 'start_time', 'end_time', 'recurrence',
            'specific_date', 'color',
        ]
        labels = {
            'semester':      'Semestre',
            'class_group':   'Classe',
            'subject':       'Module (EC)',
            'teacher':       'Enseignant',
            'room':          'Salle',
            'day_of_week':   'Jour de la semaine',
            'start_time':    'Heure de début',
            'end_time':      'Heure de fin',
            'recurrence':    'Récurrence',
            'specific_date': 'Date spécifique (si ponctuel)',
            'color':         'Couleur',
        }
        widgets = {
            'semester':     forms.Select(attrs={'class': 'form-select'}),
            'class_group':  forms.Select(attrs={'class': 'form-select'}),
            'subject':      forms.Select(attrs={'class': 'form-select'}),
            'teacher':      forms.Select(attrs={'class': 'form-select'}),
            'room':         forms.Select(attrs={'class': 'form-select'}),
            'day_of_week':  forms.Select(attrs={'class': 'form-select'}),
            'start_time':   forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'end_time':     forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'recurrence':   forms.Select(attrs={'class': 'form-select'}),
            'specific_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'color':        forms.TextInput(attrs={'class': 'form-control form-control-color', 'type': 'color'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end   = cleaned.get('end_time')
        if start and end and start >= end:
            raise forms.ValidationError(_("L'heure de début doit être avant l'heure de fin."))
        return cleaned


class TimetableFilterForm(forms.Form):
    semester    = forms.ModelChoiceField(
        queryset=Semester.objects.filter(is_active=True),
        required=False, empty_label=_("Tous les semestres"),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    class_group = forms.ModelChoiceField(
        queryset=Class.objects.all(), required=False,
        empty_label=_("Toutes les classes"),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    teacher     = forms.ModelChoiceField(
        queryset=Teacher.objects.select_related('user').all(),
        required=False, empty_label=_("Tous les enseignants"),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    room        = forms.ModelChoiceField(
        queryset=Room.objects.all(), required=False,
        empty_label=_("Toutes les salles"),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        faculty = getattr(request, 'active_faculty', None)
        if faculty:
            self.fields['semester'].queryset = self.fields['semester'].queryset.filter(
                academic_year__faculty=faculty
            )
