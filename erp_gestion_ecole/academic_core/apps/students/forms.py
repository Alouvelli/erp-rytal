from django import forms
from .models import Student
from .countries import COUNTRY_CHOICES


class StudentUserForm(forms.Form):
    """Formulaire combiné : création compte utilisateur + profil étudiant."""

    # ── Institut d'appartenance ───────────────────────────────────────────
    target_institut = forms.ModelChoiceField(
        queryset=None,
        label="Institut d'appartenance",
        empty_label="— Choisir un institut —",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_target_institut',
        }),
        help_text="Les données de l'étudiant seront enregistrées dans la base de cet institut.",
    )

    # Inscription
    class_group = forms.ChoiceField(
        label="Classe",
        choices=[('', '— Sélectionner une classe —')],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_class_group'}),
    )
    academic_year = forms.ChoiceField(
        label="Année académique",
        choices=[('', '— Sélectionner une année —')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    # Compte utilisateur
    first_name = forms.CharField(max_length=100, label="Prénom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, label="Nom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control'}))
    username = forms.CharField(
        max_length=150, label="Identifiant de connexion",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'ex : ETU2024001',
            'autocomplete': 'off',
        }),
        help_text="L'identifiant que l'étudiant utilisera pour se connecter."
    )
    password = forms.CharField(
        label="Mot de passe temporaire",
        initial='Passer123',
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Mot de passe provisoire',
            'autocomplete': 'off',
        }),
        help_text="L'étudiant devra le changer à sa première connexion."
    )

    # Profil étudiant
    matricule = forms.CharField(max_length=30, label="Matricule",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    date_of_birth = forms.DateField(label="Date de naissance",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'))
    place_of_birth = forms.CharField(max_length=200, label="Lieu de naissance",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    country_of_birth = forms.ChoiceField(choices=COUNTRY_CHOICES, label="Pays de naissance",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_country_of_birth'}))
    nationality = forms.CharField(max_length=100, label="Nationalité", required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_nationality', 'readonly': 'readonly'}),
        help_text="Renseignée automatiquement selon le pays de naissance — modifiable uniquement si « Autre pays ».")
    gender = forms.ChoiceField(choices=[('', '— Sélectionner —'), ('M', 'Masculin'), ('F', 'Féminin')],
        label="Genre",
        widget=forms.Select(attrs={'class': 'form-select'}))
    phone = forms.CharField(max_length=20, label="Téléphone",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    address = forms.CharField(label="Adresse",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))

    # Photo
    photo = forms.ImageField(
        label="Photo de l'étudiant",
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'id': 'id_photo'}),
        help_text="Importez une photo ou utilisez la webcam."
    )
    photo_webcam = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_photo_webcam'}),
        help_text="Données base64 de la photo prise par la webcam."
    )

    # Tuteur
    guardian_first_name = forms.CharField(max_length=100, label="Prénom tuteur",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    guardian_last_name = forms.CharField(max_length=100, label="Nom tuteur",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    guardian_phone = forms.CharField(max_length=20, label="Téléphone tuteur",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    guardian_address = forms.CharField(label="Adresse tuteur",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    guardian_email = forms.EmailField(label="Email tuteur",
        widget=forms.EmailInput(attrs={'class': 'form-control'}))

    # Bourse
    is_boursier = forms.BooleanField(
        label="Étudiant boursier", required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_boursier'}),
    )
    partenaire_bourse = forms.ModelChoiceField(
        queryset=None, label="Partenaire de bourse", required=False,
        empty_label="— Sélectionner un partenaire —",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_partenaire_bourse'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounting.models import PartenaireBourse
        self.fields['partenaire_bourse'].queryset = PartenaireBourse.objects.filter(is_active=True).order_by('code')

    def clean_gender(self):
        gender = self.cleaned_data.get('gender')
        if not gender:
            raise forms.ValidationError("Ce champ est obligatoire.")
        return gender

    def clean_email(self):
        from django.db.models import Q
        from academic_core.apps.accounts.models import User
        email = self.cleaned_data['email']
        # Vérification pinnée sur 'default' (base maître) et non sur get_current_db()
        # (base de l'institut actuellement actif) : tout compte créé avec succès y est
        # dupliqué (voir User.save()), donc c'est la seule base qui reflète TOUS les
        # instituts. Sans ce pin, un email déjà utilisé dans un autre institut n'est
        # pas détecté ici et un compte étudiant doublon peut être créé pour une
        # identité qui appartient en réalité à un autre institut.
        qs = User.objects.using('default').filter(Q(email__iexact=email) | Q(username__iexact=email))
        if self.initial.get('user_pk'):
            qs = qs.exclude(pk=self.initial['user_pk'])
        if qs.exists():
            raise forms.ValidationError("Cet email est déjà utilisé par un compte existant (dans cet institut ou un autre).")
        return email

    def clean_username(self):
        from django.db.models import Q
        from academic_core.apps.accounts.models import User
        username = self.cleaned_data['username'].strip()
        qs = User.objects.using('default').filter(Q(username__iexact=username) | Q(email__iexact=username))
        if self.initial.get('user_pk'):
            qs = qs.exclude(pk=self.initial['user_pk'])
        if qs.exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé par un autre compte (dans cet institut ou un autre).")
        return username

    def clean_matricule(self):
        matricule = self.cleaned_data['matricule']
        qs = Student.objects.filter(matricule=matricule)
        if self.initial.get('student_pk'):
            qs = qs.exclude(pk=self.initial['student_pk'])
        if qs.exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé.")
        return matricule


class StudentForm(forms.ModelForm):
    """Formulaire mise à jour du profil étudiant (+ champs utilisateur)."""

    # Photo (gérée manuellement dans la vue — non liée à Meta.fields)
    photo = forms.ImageField(required=False, label="Photo",
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}))
    # Champ caché requis pour que le bouton "Utiliser la webcam" (JS partagé
    # avec le formulaire de création) trouve #id_photo_webcam dans le DOM —
    # sans ce champ déclaré, {{ form.photo_webcam }} ne rend rien en édition
    # et la capture webcam échoue silencieusement.
    photo_webcam = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_photo_webcam'}),
    )

    # Champs User (hors modèle Student)
    first_name = forms.CharField(max_length=100, label="Prénom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, label="Nom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control'}))
    username = forms.CharField(max_length=150, label="Identifiant interne (matricule)",
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

    class Meta:
        model = Student
        # 'photo' est géré manuellement dans la vue pour éviter toute suppression accidentelle
        fields = ['matricule', 'date_of_birth', 'place_of_birth', 'country_of_birth', 'nationality',
                  'gender', 'phone',
                  'address',
                  'guardian_first_name', 'guardian_last_name',
                  'guardian_phone', 'guardian_address', 'guardian_email',
                  'is_boursier', 'partenaire_bourse']
        widgets = {
            'matricule':          forms.TextInput(attrs={'class': 'form-control'}),
            'date_of_birth':      forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'place_of_birth':     forms.TextInput(attrs={'class': 'form-control'}),
            'country_of_birth':   forms.Select(attrs={'class': 'form-select', 'id': 'id_country_of_birth'}),
            'nationality':        forms.TextInput(attrs={'class': 'form-control', 'id': 'id_nationality', 'readonly': 'readonly'}),
            'gender':             forms.Select(attrs={'class': 'form-select'}),
            'phone':              forms.TextInput(attrs={'class': 'form-control'}),
            'address':            forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'guardian_first_name':forms.TextInput(attrs={'class': 'form-control'}),
            'guardian_last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'guardian_phone':     forms.TextInput(attrs={'class': 'form-control'}),
            'guardian_address':   forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'guardian_email':     forms.EmailInput(attrs={'class': 'form-control'}),
            'is_boursier':        forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_boursier'}),
            'partenaire_bourse':  forms.Select(attrs={'class': 'form-select', 'id': 'id_partenaire_bourse'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounting.models import PartenaireBourse
        self.fields['partenaire_bourse'].queryset = PartenaireBourse.objects.filter(is_active=True).order_by('code')
        self.fields['partenaire_bourse'].empty_label = "— Sélectionner un partenaire —"
        self.fields['partenaire_bourse'].required = False

    def clean_email(self):
        from academic_core.apps.accounts.models import User
        email = self.cleaned_data['email']
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk and hasattr(self.instance, 'user_id'):
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email

    def clean_username(self):
        from academic_core.apps.accounts.models import User
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


class StudentImportForm(forms.Form):
    csv_file = forms.FileField(label="Fichier CSV",
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv'}))
