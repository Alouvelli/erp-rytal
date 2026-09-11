from django import forms
from django.forms import inlineformset_factory
from .models import CoursePlan, CoursePlanSession


class CoursePlanSessionForm(forms.ModelForm):
    class Meta:
        model = CoursePlanSession
        # duree_heures n'est volontairement pas un champ du formulaire : elle
        # est calculée automatiquement côté serveur à partir de la durée
        # réelle de la séance dans l'emploi du temps (TimetableEntry.duration_hours)
        # et ne doit jamais être modifiable par l'enseignant — voir
        # attendance/views.py::course_plan_edit.
        fields = ['numero', 'titre', 'objectif', 'contenu_prevu']
        widgets = {
            'numero': forms.NumberInput(attrs={'class': 'form-control text-center fw-bold', 'min': 1}),
            'titre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex. : Introduction aux limites de fonctions'}),
            'objectif': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4, 'style': 'resize:vertical;min-height:100px;',
                'placeholder': "Ce que les étudiants doivent être capables de faire à l'issue de la séance…",
            }),
            'contenu_prevu': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4, 'style': 'resize:vertical;min-height:100px;',
                'placeholder': 'Notions, thèmes, exercices prévus pour cette séance…',
            }),
        }


CoursePlanSessionFormSet = inlineformset_factory(
    CoursePlan, CoursePlanSession,
    form=CoursePlanSessionForm,
    extra=1, can_delete=True,
)
