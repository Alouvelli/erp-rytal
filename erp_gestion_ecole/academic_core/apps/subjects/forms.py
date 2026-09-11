from django import forms
from .models import Subject


class SubjectForm(forms.ModelForm):
    # Champ hors modèle : le taux horaire n'est pas stocké sur Subject mais
    # sur accounting.HourlyRate (clé département × niveau × année académique,
    # dérivée de program.department + semester.level/academic_year) — voir
    # SubjectCreateView/SubjectUpdateView.form_valid et
    # accounting/services.py::set_hourly_rate. Facultatif : laissé vide, le
    # taux existant (le cas échéant) n'est pas modifié.
    taux_horaire = forms.DecimalField(
        required=False, min_value=0, max_digits=10, decimal_places=2,
        label='Taux horaire (FCFA/heure)',
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0',
            'placeholder': '— sélectionnez filière + semestre —',
        }),
    )

    class Meta:
        model = Subject
        fields = [
            'code', 'title', 'program', 'semester',
            'coefficient',
            'volume_cm', 'volume_td', 'volume_tp', 'volume_tpe',
            'responsible_teacher', 'syllabus', 'description',
        ]
        widgets = {
            'code':                forms.TextInput(attrs={'class': 'form-control'}),
            'title':               forms.TextInput(attrs={'class': 'form-control'}),
            'program':             forms.Select(attrs={'class': 'form-select'}),
            'semester':            forms.Select(attrs={'class': 'form-select'}),
            'coefficient':         forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '0'}),
            'volume_cm':           forms.NumberInput(attrs={'class': 'form-control vol-input', 'step': '0.5', 'min': '0'}),
            'volume_td':           forms.NumberInput(attrs={'class': 'form-control vol-input', 'step': '0.5', 'min': '0'}),
            'volume_tp':           forms.NumberInput(attrs={'class': 'form-control vol-input', 'step': '0.5', 'min': '0'}),
            'volume_tpe':          forms.NumberInput(attrs={'class': 'form-control vol-input', 'step': '0.5', 'min': '0'}),
            'responsible_teacher': forms.Select(attrs={'class': 'form-select'}),
            'syllabus':            forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.doc,.docx'}),
            'description':         forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
