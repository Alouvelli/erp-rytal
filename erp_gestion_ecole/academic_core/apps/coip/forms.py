from django import forms

from .models import (
    Activity, ActivityParticipant, Alumni, AlumniCareerEvent, Archive,
    ArchiveVersion, CollaborationHistory, EducationalVisit, Internship,
    InternshipOffer, JobApplication, Opportunity, OrientationSession,
    Partner, PartnerContact, Partnership, RecommendationRequest, Report,
)


class AlumniForm(forms.ModelForm):
    class Meta:
        model = Alumni
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'promotion', 'diplome', 'filiere', 'annee_obtention',
            'entreprise_actuelle', 'poste_occupe', 'secteur_activite', 'is_employed',
            'pays', 'ville', 'linkedin', 'photo',
        ]
        widgets = {
            'first_name':           forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':            forms.TextInput(attrs={'class': 'form-control'}),
            'email':                forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':                forms.TextInput(attrs={'class': 'form-control'}),
            'promotion':            forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : 2022'}),
            'diplome':              forms.TextInput(attrs={'class': 'form-control'}),
            'filiere':              forms.Select(attrs={'class': 'form-select'}),
            'annee_obtention':      forms.NumberInput(attrs={'class': 'form-control', 'min': '1990', 'max': '2100'}),
            'entreprise_actuelle':  forms.TextInput(attrs={'class': 'form-control'}),
            'poste_occupe':         forms.TextInput(attrs={'class': 'form-control'}),
            'secteur_activite':     forms.Select(attrs={'class': 'form-select'}),
            'is_employed':          forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'pays':                 forms.TextInput(attrs={'class': 'form-control'}),
            'ville':                forms.TextInput(attrs={'class': 'form-control'}),
            'linkedin':             forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://linkedin.com/in/...'}),
            'photo':                forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import Program
        self.fields['filiere'].queryset = Program.objects.order_by('name')
        self.fields['filiere'].required = False
        self.fields['filiere'].empty_label = '— Non renseignée —'


class AlumniCareerEventForm(forms.ModelForm):
    class Meta:
        model = AlumniCareerEvent
        fields = ['date', 'entreprise', 'poste', 'description']
        widgets = {
            'date':        forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'entreprise':  forms.TextInput(attrs={'class': 'form-control'}),
            'poste':       forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class PartnerForm(forms.ModelForm):
    class Meta:
        model = Partner
        fields = [
            'raison_sociale', 'type_partenaire', 'secteur',
            'adresse', 'ville', 'pays', 'email', 'phone', 'site_web', 'logo', 'is_active',
        ]
        widgets = {
            'raison_sociale': forms.TextInput(attrs={'class': 'form-control'}),
            'type_partenaire': forms.Select(attrs={'class': 'form-select'}),
            'secteur':        forms.TextInput(attrs={'class': 'form-control'}),
            'adresse':        forms.TextInput(attrs={'class': 'form-control'}),
            'ville':          forms.TextInput(attrs={'class': 'form-control'}),
            'pays':           forms.TextInput(attrs={'class': 'form-control'}),
            'email':          forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':          forms.TextInput(attrs={'class': 'form-control'}),
            'site_web':       forms.URLInput(attrs={'class': 'form-control'}),
            'logo':           forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'is_active':      forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PartnerContactForm(forms.ModelForm):
    class Meta:
        model = PartnerContact
        fields = ['nom', 'poste', 'email', 'phone', 'is_primary']
        widgets = {
            'nom':        forms.TextInput(attrs={'class': 'form-control'}),
            'poste':      forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control'}),
            'is_primary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PartnershipForm(forms.ModelForm):
    class Meta:
        model = Partnership
        fields = [
            'partner', 'intitule', 'description', 'date_signature', 'date_expiration',
            'status', 'document', 'responsable',
        ]
        widgets = {
            'partner':         forms.Select(attrs={'class': 'form-select'}),
            'intitule':        forms.TextInput(attrs={'class': 'form-control'}),
            'description':     forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'date_signature':  forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_expiration': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status':          forms.Select(attrs={'class': 'form-select'}),
            'document':        forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'responsable':     forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        self.fields['responsable'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['responsable'].required = False
        self.fields['responsable'].empty_label = '— Non assigné —'
        self.fields['date_expiration'].required = False

    def clean(self):
        cleaned = super().clean()
        debut = cleaned.get('date_signature')
        fin = cleaned.get('date_expiration')
        if debut and fin and fin < debut:
            self.add_error('date_expiration', "La date d'expiration doit être postérieure à la date de signature.")
        return cleaned


class CollaborationHistoryForm(forms.ModelForm):
    class Meta:
        model = CollaborationHistory
        fields = ['date', 'type_collaboration', 'description']
        widgets = {
            'date':               forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'type_collaboration': forms.TextInput(attrs={'class': 'form-control'}),
            'description':        forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class InternshipOfferForm(forms.ModelForm):
    class Meta:
        model = InternshipOffer
        fields = [
            'partner', 'titre', 'description', 'type_stage', 'filiere_cible',
            'duree', 'date_debut', 'date_fin', 'status', 'remunere', 'montant_remuneration',
        ]
        widgets = {
            'partner':              forms.Select(attrs={'class': 'form-select'}),
            'titre':                forms.TextInput(attrs={'class': 'form-control'}),
            'description':          forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'type_stage':           forms.Select(attrs={'class': 'form-select'}),
            'filiere_cible':        forms.Select(attrs={'class': 'form-select'}),
            'duree':                forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : 3 mois'}),
            'date_debut':           forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_fin':             forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status':               forms.Select(attrs={'class': 'form-select'}),
            'remunere':             forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'montant_remuneration': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import Program
        self.fields['filiere_cible'].queryset = Program.objects.order_by('name')
        self.fields['filiere_cible'].required = False
        self.fields['filiere_cible'].empty_label = '— Toutes filières —'
        self.fields['date_debut'].required = False
        self.fields['date_fin'].required = False


class InternshipForm(forms.ModelForm):
    class Meta:
        model = Internship
        fields = [
            'student', 'offer', 'partner', 'titre', 'encadreur_entreprise', 'encadreur_isi',
            'date_debut', 'date_fin', 'status', 'rapport', 'note', 'appreciation',
        ]
        widgets = {
            'student':              forms.Select(attrs={'class': 'form-select'}),
            'offer':                forms.Select(attrs={'class': 'form-select'}),
            'partner':              forms.Select(attrs={'class': 'form-select'}),
            'titre':                forms.TextInput(attrs={'class': 'form-control'}),
            'encadreur_entreprise': forms.TextInput(attrs={'class': 'form-control'}),
            'encadreur_isi':        forms.Select(attrs={'class': 'form-select'}),
            'date_debut':           forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_fin':             forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status':               forms.Select(attrs={'class': 'form-select'}),
            'rapport':              forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'note':                 forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '20'}),
            'appreciation':         forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        from academic_core.apps.students.models import Student
        self.fields['student'].queryset = Student.objects.select_related('user').order_by('user__last_name')
        self.fields['offer'].required = False
        self.fields['offer'].empty_label = '— Aucune offre liée —'
        self.fields['encadreur_isi'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['encadreur_isi'].required = False
        self.fields['encadreur_isi'].empty_label = '— Non assigné —'
        self.fields['date_fin'].required = False


class OrientationSessionForm(forms.ModelForm):
    class Meta:
        model = OrientationSession
        fields = [
            'student', 'conseiller', 'type_session', 'date_session', 'duree_minutes',
            'observations', 'recommandations', 'objectifs_fixes',
        ]
        widgets = {
            'student':          forms.Select(attrs={'class': 'form-select'}),
            'conseiller':       forms.Select(attrs={'class': 'form-select'}),
            'type_session':     forms.Select(attrs={'class': 'form-select'}),
            'date_session':     forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'duree_minutes':    forms.NumberInput(attrs={'class': 'form-control', 'min': '5'}),
            'observations':     forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'recommandations':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'objectifs_fixes':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        from academic_core.apps.students.models import Student
        self.fields['student'].queryset = Student.objects.select_related('user').order_by('user__last_name')
        self.fields['conseiller'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['conseiller'].required = False
        self.fields['conseiller'].empty_label = '— Non assigné —'


class RecommendationRequestForm(forms.ModelForm):
    """Formulaire de saisie étudiant — motif/destinataire uniquement, le
    statut et l'assignation restent du ressort du staff COIP."""
    class Meta:
        model = RecommendationRequest
        fields = ['motif', 'destinataire', 'programme_concerne', 'observations_etudiant']
        widgets = {
            'motif':                forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'destinataire':         forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Ex : Service des admissions, Université X"}),
            'programme_concerne':   forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : Master en Data Science'}),
            'observations_etudiant': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class RecommendationStatusForm(forms.Form):
    status = forms.ChoiceField(choices=RecommendationRequest.STATUT_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    assigned_to = forms.ModelChoiceField(queryset=None, required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['assigned_to'].empty_label = '— Non assigné —'


class OpportunityForm(forms.ModelForm):
    class Meta:
        model = Opportunity
        fields = [
            'titre', 'type_opportunite', 'description', 'partner', 'lieu',
            'remuneration', 'date_limite', 'filiere_cible', 'niveau_cible', 'status',
        ]
        widgets = {
            'titre':            forms.TextInput(attrs={'class': 'form-control'}),
            'type_opportunite': forms.Select(attrs={'class': 'form-select'}),
            'description':      forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'partner':          forms.Select(attrs={'class': 'form-select'}),
            'lieu':             forms.TextInput(attrs={'class': 'form-control'}),
            'remuneration':     forms.TextInput(attrs={'class': 'form-control'}),
            'date_limite':      forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'filiere_cible':    forms.Select(attrs={'class': 'form-select'}),
            'niveau_cible':     forms.Select(attrs={'class': 'form-select'}),
            'status':           forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import Level, Program
        self.fields['partner'].required = False
        self.fields['partner'].empty_label = '— Non applicable —'
        self.fields['filiere_cible'].queryset = Program.objects.order_by('name')
        self.fields['filiere_cible'].required = False
        self.fields['filiere_cible'].empty_label = '— Toutes filières —'
        self.fields['niveau_cible'].queryset = Level.objects.order_by('order')
        self.fields['niveau_cible'].required = False
        self.fields['niveau_cible'].empty_label = '— Tous niveaux —'
        self.fields['date_limite'].required = False


class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ['lettre_motivation', 'cv']
        widgets = {
            'lettre_motivation': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'cv':                forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class JobApplicationStatusForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ['status', 'notes']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes':  forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = [
            'titre', 'type_activite', 'description', 'objectifs', 'date_debut', 'date_fin',
            'lieu', 'budget', 'responsable', 'partenaires', 'status', 'programme', 'compte_rendu',
        ]
        widgets = {
            'titre':        forms.TextInput(attrs={'class': 'form-control'}),
            'type_activite': forms.Select(attrs={'class': 'form-select'}),
            'description':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'objectifs':    forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'date_debut':   forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'date_fin':     forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'lieu':         forms.TextInput(attrs={'class': 'form-control'}),
            'budget':       forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'responsable':  forms.Select(attrs={'class': 'form-select'}),
            'partenaires':  forms.SelectMultiple(attrs={'class': 'form-select'}),
            'status':       forms.Select(attrs={'class': 'form-select'}),
            'programme':    forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'compte_rendu': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        self.fields['responsable'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['responsable'].required = False
        self.fields['responsable'].empty_label = '— Non assigné —'
        self.fields['date_fin'].required = False


class EducationalVisitForm(forms.ModelForm):
    class Meta:
        model = EducationalVisit
        fields = [
            'intitule', 'lieu', 'date_depart', 'date_retour', 'responsable', 'budget',
            'objectifs', 'transport', 'nombre_places', 'status', 'rapport',
        ]
        widgets = {
            'intitule':      forms.TextInput(attrs={'class': 'form-control'}),
            'lieu':          forms.TextInput(attrs={'class': 'form-control'}),
            'date_depart':   forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'date_retour':   forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'responsable':   forms.Select(attrs={'class': 'form-select'}),
            'budget':        forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'objectifs':     forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'transport':     forms.TextInput(attrs={'class': 'form-control'}),
            'nombre_places': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'status':        forms.Select(attrs={'class': 'form-select'}),
            'rapport':       forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounts.models import User
        self.fields['responsable'].queryset = User.objects.filter(is_active=True).order_by('last_name')
        self.fields['responsable'].required = False
        self.fields['responsable'].empty_label = '— Non assigné —'
        self.fields['date_retour'].required = False


class ReportGenerateForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ['titre', 'type_rapport', 'format_fichier', 'periode_debut', 'periode_fin']
        widgets = {
            'titre':          forms.TextInput(attrs={'class': 'form-control'}),
            'type_rapport':   forms.Select(attrs={'class': 'form-select'}),
            'format_fichier': forms.Select(attrs={'class': 'form-select'}),
            'periode_debut':  forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'periode_fin':    forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        debut = cleaned.get('periode_debut')
        fin = cleaned.get('periode_fin')
        if debut and fin and fin < debut:
            self.add_error('periode_fin', "La fin de période doit être postérieure au début.")
        return cleaned


class ArchiveForm(forms.ModelForm):
    class Meta:
        model = Archive
        fields = ['titre', 'categorie', 'description', 'fichier', 'version', 'tags']
        widgets = {
            'titre':       forms.TextInput(attrs={'class': 'form-control'}),
            'categorie':   forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'fichier':     forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'version':     forms.TextInput(attrs={'class': 'form-control'}),
            'tags':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : convention, 2025, partenaire-x'}),
        }


class ArchiveVersionForm(forms.ModelForm):
    class Meta:
        model = ArchiveVersion
        fields = ['fichier', 'version', 'commentaire']
        widgets = {
            'fichier':     forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'version':     forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : 1.1'}),
            'commentaire': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
