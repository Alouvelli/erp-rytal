from django import forms
from django.contrib.auth.hashers import make_password
from .models import Teacher, Grade, ContratEnseignant
from academic_core.apps.accounts.models import User, Role


class TeacherUserForm(forms.Form):
    """Formulaire combiné : création compte utilisateur + profil enseignant."""

    # ── Institut d'appartenance ────────────────────────────────────────────
    target_institut = forms.ModelChoiceField(
        queryset=None,
        label="Institut d'appartenance",
        empty_label="— Choisir un institut —",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_target_institut',
        }),
        help_text="Les données de l'enseignant seront enregistrées dans la base de cet institut.",
    )

    # ── Département ────────────────────────────────────────────────────────
    department = forms.ModelChoiceField(
        queryset=None,
        label="Département",
        required=False,
        empty_label="— Aucun département —",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_department'}),
    )

    # ── Compte utilisateur ────────────────────────────────────────────────
    first_name = forms.CharField(
        max_length=100, label="Prénom",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prénom'})
    )
    last_name = forms.CharField(
        max_length=100, label="Nom",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom'})
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@isi.sn'})
    )
    phone = forms.CharField(
        max_length=20, label="Téléphone",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '77 123 45 67'}),
        help_text="Requis pour les fiches et récapitulatifs d'honoraires.",
    )
    username = forms.CharField(
        max_length=150, label="Identifiant de connexion",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'ex : p.diallo ou PDiallo',
            'autocomplete': 'off',
        }),
        help_text="L'identifiant que l'enseignant utilisera pour se connecter."
    )
    password = forms.CharField(
        label="Mot de passe temporaire",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Mot de passe provisoire',
            'autocomplete': 'off',
        }),
        help_text="L'enseignant devra le changer à sa première connexion."
    )

    # ── Profil enseignant ─────────────────────────────────────────────────
    matricule = forms.CharField(
        max_length=30, label="Matricule",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    grade = forms.ModelChoiceField(
        queryset=Grade.objects.all(), label="Grade",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    specialty = forms.CharField(
        max_length=200, label="Spécialité",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    statut = forms.ChoiceField(
        choices=[('', '— Sélectionner —')] + list(Teacher.STATUT_CHOICES), label="Statut",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    contractual_hours = forms.DecimalField(
        max_digits=6, decimal_places=2, initial=0, label="Volume horaire contractuel",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'})
    )
    hire_date = forms.DateField(
        required=False, label="Date d'embauche",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    bio = forms.CharField(
        required=False, label="Biographie",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )

    def __init__(self, *args, requester=None, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import InstitutConfig, Department

        is_inst_admin = requester and getattr(requester, 'role_name', None) in (
            'INST_ADMIN', 'ASSISTANTE_DG'
        )
        is_super = requester and getattr(requester, 'role_name', None) == 'ADMIN'

        # Queryset instituts
        inst_qs = InstitutConfig.objects.select_related('faculty').order_by('nom')
        if is_inst_admin:
            cfg = getattr(requester, 'institut_config', None)
            if cfg:
                inst_qs = inst_qs.filter(pk=cfg.pk)
                self.fields['target_institut'].initial = cfg
                self.fields['target_institut'].widget.attrs['readonly'] = True
        self.fields['target_institut'].queryset = inst_qs

        # Queryset départements
        dept_qs = Department.objects.filter(is_active=True).order_by('name')
        if is_inst_admin:
            cfg = getattr(requester, 'institut_config', None)
            fac = cfg.faculty if cfg else None
            dept_qs = dept_qs.filter(faculty=fac) if fac else dept_qs.none()
        elif not is_super:
            fac = getattr(getattr(requester, 'department', None), 'faculty', None) if requester else None
            if fac:
                dept_qs = dept_qs.filter(faculty=fac)
        self.fields['department'].queryset = dept_qs

    def clean_statut(self):
        statut = self.cleaned_data.get('statut')
        if not statut:
            raise forms.ValidationError("Ce champ est obligatoire.")
        return statut

    def clean_email(self):
        from django.db.models import Q
        email = self.cleaned_data['email']
        # Vérification pinnée sur 'default' (base maître), pas sur get_current_db()
        # (base de l'institut actif) : tout compte créé avec succès y est dupliqué
        # (voir User.save()), donc c'est la seule base qui reflète TOUS les instituts.
        # Sans ce pin, un email déjà utilisé dans un autre institut passe inaperçu.
        qs = User.objects.using('default').filter(Q(email__iexact=email) | Q(username__iexact=email))
        if self.initial.get('user_pk'):
            qs = qs.exclude(pk=self.initial['user_pk'])
        if qs.exists():
            raise forms.ValidationError("Cet email est déjà utilisé par un compte existant (dans cet institut ou un autre).")
        return email

    def clean_username(self):
        from django.db.models import Q
        username = self.cleaned_data['username'].strip()
        qs = User.objects.using('default').filter(Q(username__iexact=username) | Q(email__iexact=username))
        if self.initial.get('user_pk'):
            qs = qs.exclude(pk=self.initial['user_pk'])
        if qs.exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé par un autre compte (dans cet institut ou un autre).")
        return username

    def clean_matricule(self):
        matricule = self.cleaned_data['matricule']
        qs = Teacher.objects.filter(matricule=matricule)
        if self.initial.get('teacher_pk'):
            qs = qs.exclude(pk=self.initial['teacher_pk'])
        if qs.exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé.")
        return matricule


class TeacherForm(forms.ModelForm):
    """Formulaire de mise à jour du profil enseignant + identifiants de connexion."""

    # Champs User (hors modèle Teacher) — identifiants de connexion.
    first_name = forms.CharField(max_length=100, label="Prénom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, label="Nom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Email (identifiant de connexion)",
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
        help_text="L'enseignant se connecte avec cette adresse email.")
    phone = forms.CharField(
        max_length=20, label="Téléphone",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '77 123 45 67'}),
        help_text="Requis pour les fiches et récapitulatifs d'honoraires.",
    )
    username = forms.CharField(max_length=150, label="Identifiant interne",
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
        help_text="Identifiant technique (non utilisé pour la connexion — la connexion se fait par email).")
    new_password = forms.CharField(
        label="Nouveau mot de passe", required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'Laisser vide pour ne pas changer',
            'autocomplete': 'new-password',
        }),
    )
    new_password_confirm = forms.CharField(
        label="Confirmer le mot de passe", required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    department = forms.ModelChoiceField(
        queryset=None, label="Département", required=False,
        empty_label="— Aucun département —",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Teacher
        fields = ['matricule', 'grade', 'specialty', 'statut', 'contractual_hours', 'hire_date', 'bio']
        widgets = {
            'matricule':         forms.TextInput(attrs={'class': 'form-control'}),
            'grade':             forms.Select(attrs={'class': 'form-select'}),
            'specialty':         forms.TextInput(attrs={'class': 'form-control'}),
            'statut':            forms.Select(attrs={'class': 'form-select'}),
            'contractual_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'hire_date':         forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'bio':               forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import Department
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('name')

    def clean_email(self):
        email = self.cleaned_data['email']
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk and hasattr(self.instance, 'user_id'):
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        qs = User.objects.filter(username=username)
        if self.instance and self.instance.pk and hasattr(self.instance, 'user_id'):
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password', '')
        p2 = cleaned.get('new_password_confirm', '')
        if p1:
            if len(p1) < 6:
                self.add_error('new_password', "Le mot de passe doit contenir au moins 6 caractères.")
            elif p1 != p2:
                self.add_error('new_password_confirm', "Les deux mots de passe ne correspondent pas.")
        return cleaned


class TeacherCivilInfoForm(forms.ModelForm):
    """Informations civiles de l'enseignant utilisées dans le contrat de prestation de service."""
    class Meta:
        model = Teacher
        fields = [
            'date_naissance', 'lieu_naissance', 'nationalite', 'num_cin_passeport',
            'situation_matrimoniale', 'adresse', 'lieu_residence', 'profession', 'ninea',
        ]
        widgets = {
            'date_naissance':         forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'lieu_naissance':         forms.TextInput(attrs={'class': 'form-control'}),
            'nationalite':            forms.TextInput(attrs={'class': 'form-control'}),
            'num_cin_passeport':      forms.TextInput(attrs={'class': 'form-control'}),
            'situation_matrimoniale': forms.Select(attrs={'class': 'form-select'}),
            'adresse':                forms.TextInput(attrs={'class': 'form-control'}),
            'lieu_residence':         forms.TextInput(attrs={'class': 'form-control'}),
            'profession':             forms.TextInput(attrs={'class': 'form-control'}),
            'ninea':                  forms.TextInput(attrs={'class': 'form-control'}),
        }


class ContratEnseignantForm(forms.ModelForm):
    """Champs propres au contrat (lieu et date de signature)."""
    class Meta:
        model = ContratEnseignant
        fields = ['lieu_signature', 'date_signature']
        widgets = {
            'lieu_signature': forms.TextInput(attrs={'class': 'form-control'}),
            'date_signature': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
        }
