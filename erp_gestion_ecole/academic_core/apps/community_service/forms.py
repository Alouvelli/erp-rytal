from django import forms
from .models import CommunityServiceActivity


class CommunityServiceActivityForm(forms.ModelForm):
    class Meta:
        model = CommunityServiceActivity
        fields = [
            'titre', 'categorie', 'description',
            'date_debut', 'date_fin', 'lieu',
            'beneficiaires', 'nombre_participants', 'partenaires',
            'responsable', 'statut', 'resultats',
        ]
        widgets = {
            'titre':               forms.TextInput(attrs={'class': 'form-control'}),
            'categorie':           forms.Select(attrs={'class': 'form-select'}),
            'description':         forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'date_debut':          forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_fin':            forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'lieu':                forms.TextInput(attrs={'class': 'form-control'}),
            'beneficiaires':       forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : Écoles primaires du quartier'}),
            'nombre_participants': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'partenaires':         forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : ONG XYZ, Mairie...'}),
            'responsable':         forms.Select(attrs={'class': 'form-select'}),
            'statut':              forms.Select(attrs={'class': 'form-select'}),
            'resultats':           forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'nombre_participants': 'Nombre de participants',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        self.fields['responsable'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['responsable'].required = False
        self.fields['responsable'].empty_label = '— Non assigné —'
        self.fields['date_fin'].required = False

    def clean(self):
        cleaned = super().clean()
        debut = cleaned.get('date_debut')
        fin = cleaned.get('date_fin')
        if debut and fin and fin < debut:
            self.add_error('date_fin', "La date de fin doit être postérieure à la date de début.")
        return cleaned
