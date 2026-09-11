from decimal import Decimal
from django import forms
from .models import HourlyRate, PartenaireBourse
from academic_core.apps.academic_structure.models import Level, AcademicYear


class PartenaireBourseForm(forms.ModelForm):
    class Meta:
        model = PartenaireBourse
        fields = ['code', 'intitule', 'is_active']
        widgets = {
            'code':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : ETAT-SN'}),
            'intitule':  forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Ex : État du Sénégal — Bourses d'excellence"}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        qs = PartenaireBourse.objects.filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ce code est déjà utilisé par un autre partenaire.")
        return code

PREDEFINED_RATES = [
    ('5000',  '5 000 FCFA / heure'),
    ('7000',  '7 000 FCFA / heure'),
    ('9000',  '9 000 FCFA / heure'),
    ('10000', '10 000 FCFA / heure'),
    ('12000', '12 000 FCFA / heure'),
    ('15000', '15 000 FCFA / heure'),
    ('custom', 'Autre montant personnalisé…'),
]


class HourlyRateForm(forms.ModelForm):
    rate_choice = forms.ChoiceField(
        choices=[('', '— Choisir un taux —')] + PREDEFINED_RATES,
        label='Taux horaire (FCFA/heure)',
        required=True,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'rate_choice'}),
    )
    custom_rate = forms.DecimalField(
        label='Montant personnalisé (FCFA/heure)',
        required=False,
        min_value=Decimal('0'),
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'placeholder': 'ex: 8500',
            'min': '0', 'step': '500', 'id': 'custom_rate',
        }),
    )

    class Meta:
        model = HourlyRate
        fields = ['level', 'academic_year']
        widgets = {
            'level': forms.Select(attrs={'class': 'form-select'}),
            'academic_year': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'level': 'Niveau',
            'academic_year': 'Année académique',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['academic_year'].queryset = AcademicYear.objects.order_by('-start_date')
        self.fields['level'].queryset = Level.objects.order_by('order')

        # Pré-remplir en mode édition
        if self.instance and self.instance.pk and self.instance.rate_per_hour:
            current = str(int(self.instance.rate_per_hour))
            predefined = [c[0] for c in PREDEFINED_RATES if c[0] != 'custom']
            if current in predefined:
                self.fields['rate_choice'].initial = current
            else:
                self.fields['rate_choice'].initial = 'custom'
                self.fields['custom_rate'].initial = self.instance.rate_per_hour

    def clean(self):
        cleaned = super().clean()
        choice = cleaned.get('rate_choice')
        if not choice:
            self.add_error('rate_choice', 'Veuillez choisir un taux horaire.')
        elif choice == 'custom':
            custom = cleaned.get('custom_rate')
            if not custom:
                self.add_error('custom_rate', 'Veuillez saisir un montant personnalisé.')
            else:
                cleaned['rate_per_hour'] = custom
        else:
            cleaned['rate_per_hour'] = Decimal(choice)
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.rate_per_hour = self.cleaned_data['rate_per_hour']
        if commit:
            instance.save()
        return instance
