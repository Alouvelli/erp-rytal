from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from .models import User, Role, Direction


class LoginForm(AuthenticationForm):
    # Identification strictement par email (cf. MultiDBAuthBackend.authenticate,
    # qui ne recherche plus que sur le champ email) — le champ reste nommé
    # 'username' car requis tel quel par AuthenticationForm/ModelBackend, mais
    # sa valeur DOIT être une adresse email valide (voir clean_username).
    username = forms.CharField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': _('vous@exemple.com'),
            'autocomplete': 'email',
            'autofocus': True,
        }),
        label=_('Adresse email'),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': _('Mot de passe'),
        })
    )
    remember_me = forms.BooleanField(required=False, widget=forms.CheckboxInput(
        attrs={'class': 'form-check-input'}
    ))

    def clean_username(self):
        value = self.cleaned_data.get('username', '').strip()
        try:
            validate_email(value)
        except ValidationError:
            raise ValidationError(_("Veuillez saisir votre adresse email."))
        return value


def _department_widget():
    from academic_core.apps.academic_structure.models import Department
    return forms.Select(attrs={'class': 'form-select', 'id': 'id_department'})


def _setup_user_form_fields(form, requester=None):
    """Common field setup for UserCreateForm and UserUpdateForm."""
    from academic_core.apps.academic_structure.models import Department, InstitutConfig, Class
    is_super_admin = requester and getattr(requester, 'role_name', None) == 'ADMIN'
    _role_name = getattr(requester, 'role_name', None) if requester else None
    # Rôles rattachés à un seul institut (via user.institut_config) : doit être
    # tenu à jour avec User.is_inst_admin() (accounts/models.py) — cette liste
    # en était jusqu'ici une copie incomplète (SI_ADMIN manquant), ce qui
    # laissait un Administrateur du SI voir et choisir N'IMPORTE QUEL institut
    # à la création d'un utilisateur au lieu d'être verrouillé sur le sien.
    # CONTROLEUR fait exprès partie de is_inst_admin() mais est exclu ici : il
    # peut légitimement superviser PLUSIEURS instituts (cf. ControllerInstitut),
    # traité séparément juste en dessous.
    is_inst_admin  = _role_name in ('INST_ADMIN', 'SI_ADMIN', 'ASSISTANTE_DG')
    is_controleur  = _role_name == 'CONTROLEUR'

    inst_qs = InstitutConfig.objects.select_related('faculty').order_by('nom')

    def _resolve_requester_institut(req):
        """InstitutConfig de ce requester (hors Super Admin) — via
        institut_config pour les rôles INST_ADMIN/SI_ADMIN/ASSISTANTE_DG,
        sinon via department.faculty pour tous les autres rôles non-Super
        Admin (RESPONSABLE, ASSISTANTE, ADMIN_DIRECTION, ADMIN_DE, ...)."""
        cfg = getattr(req, 'institut_config', None)
        if cfg:
            return cfg
        dept = getattr(req, 'department', None)
        faculty = getattr(dept, 'faculty', None) if dept else None
        return InstitutConfig.objects.filter(faculty=faculty).first() if faculty else None

    # ── Champ Institut d'appartenance (target_institut) ────────────────────
    # Détermine dans quelle base de données l'utilisateur sera enregistré.
    # Verrouillé sur l'institut du requester pour TOUT rôle non-Super Admin
    # (hors Contrôleur Interne, qui supervise légitimement plusieurs instituts
    # — cf. ControllerInstitut) : la liste de rôles précédente ne couvrait que
    # INST_ADMIN/SI_ADMIN/ASSISTANTE_DG, laissant RESPONSABLE, ASSISTANTE,
    # ADMIN_DIRECTION, ADMIN_DE, ADMIN_DAF, ADMIN_COM, ADMIN_RH voir un
    # dropdown vide et non verrouillé.
    if 'target_institut' in form.fields:
        form.institut_locked = False
        if is_controleur:
            # Uniquement les instituts que ce Contrôleur Interne supervise
            # (voir ControllerInstitut / context_processors.controlled_instituts).
            form.fields['target_institut'].queryset = inst_qs.filter(
                controller_links__user=requester
            ).distinct()
        elif not is_super_admin:
            user_institut = _resolve_requester_institut(requester)
            if user_institut:
                form.fields['target_institut'].queryset = inst_qs.filter(pk=user_institut.pk)
                form.fields['target_institut'].initial  = user_institut.pk
                form.fields['target_institut'].empty_label = None
                form.institut_locked  = True
                form.institut_display = str(user_institut)
            else:
                form.fields['target_institut'].queryset = inst_qs.none()
        else:
            form.fields['target_institut'].queryset = inst_qs
        if not form.institut_locked:
            form.fields['target_institut'].empty_label = '— Choisir un institut —'
        form.fields['target_institut'].required   = True
        form.fields['target_institut'].label       = "Institut d'appartenance"
        form.fields['target_institut'].help_text   = (
            "L'utilisateur sera enregistré dans la base de données de cet institut."
        )
        if 'class' not in form.fields['target_institut'].widget.attrs.get('class', ''):
            form.fields['target_institut'].widget.attrs['class'] = 'form-select'

    # ── Département ────────────────────────────────────────────────────────
    dept_qs = Department.objects.filter(is_active=True).order_by('name')
    if is_inst_admin:
        cfg = getattr(requester, 'institut_config', None)
        faculty = cfg.faculty if cfg else None
        dept_qs = dept_qs.filter(faculty=faculty) if faculty else dept_qs.none()
    form.fields['department'].queryset    = dept_qs
    form.fields['department'].required    = False
    form.fields['department'].empty_label = '— Aucun département —'
    form.fields['department'].label       = 'Département assigné'

    # ── Classe assignée (rôle Responsable de classe) ───────────────────────
    class_qs = Class.objects.select_related('program__department').order_by('name')
    if is_inst_admin:
        cfg = getattr(requester, 'institut_config', None)
        faculty = cfg.faculty if cfg else None
        class_qs = class_qs.filter(program__department__faculty=faculty) if faculty else class_qs.none()
    form.fields['responsable_class'].queryset    = class_qs
    form.fields['responsable_class'].required    = False
    form.fields['responsable_class'].empty_label = '— Aucune classe —'
    form.fields['responsable_class'].label       = 'Classe assignée'
    form.fields['responsable_class'].widget.attrs['class'] = 'form-select'

    # ── Rôle ───────────────────────────────────────────────────────────────
    if is_super_admin:
        form.fields['role'].queryset = Role.objects.filter(name__in=[Role.INST_ADMIN, Role.ASSISTANTE_DG])
    else:
        form.fields['role'].queryset = Role.objects.exclude(name__in=['INST_ADMIN', 'ASSISTANTE_DG'])
    form.fields['role'].label = 'Rôle'

    form.fields['first_name'].label = 'Prénom'
    form.fields['last_name'].label  = 'Nom'
    form.fields['phone'].label      = 'Téléphone'
    form.fields['is_active'].label  = 'Compte actif'

    # ── Institut administré (pour INST_ADMIN/ASSISTANTE_DG) ────────────────
    if is_inst_admin:
        form.fields['institut_config'].widget   = forms.HiddenInput()
        form.fields['institut_config'].required = False
    else:
        form.fields['institut_config'].queryset    = inst_qs
        form.fields['institut_config'].required    = False
        form.fields['institut_config'].empty_label = '— Choisir un institut —'
        form.fields['institut_config'].label       = 'Institut administré (rôle INST_ADMIN uniquement)'
        form.fields['institut_config'].widget.attrs['class'] = 'form-select'


class UserCreateForm(UserCreationForm):
    # Champ dédié au routage DB — détermine dans quelle base l'utilisateur est créé
    target_institut = forms.ModelChoiceField(
        queryset=None,
        label="Institut d'appartenance",
        required=False,
        empty_label="— Choisir un institut —",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_target_institut'}),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'gender', 'role',
                  'department', 'responsable_class', 'institut_config', 'is_active']
        widgets = {
            'username':          forms.TextInput(attrs={'class': 'form-control'}),
            'first_name':        forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':         forms.TextInput(attrs={'class': 'form-control'}),
            'email':             forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':             forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+221 77 000 00 00'}),
            'gender':            forms.Select(attrs={'class': 'form-select'}),
            'role':              forms.Select(attrs={'class': 'form-select', 'id': 'id_role'}),
            'department':        forms.Select(attrs={'class': 'form-select', 'id': 'id_department'}),
            'responsable_class': forms.Select(attrs={'class': 'form-select', 'id': 'id_responsable_class'}),
            'institut_config':   forms.Select(attrs={'class': 'form-select', 'id': 'id_institut_config'}),
        }

    def __init__(self, *args, requester=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs['class'] = 'form-control'
        self.fields['password2'].widget.attrs['class'] = 'form-control'
        self.fields['username'].label  = 'Identifiant'
        self.fields['password1'].label = 'Mot de passe'
        self.fields['password2'].label = 'Confirmer le mot de passe'
        _setup_user_form_fields(self, requester)

    def clean_username(self):
        # Remplace la vérification par défaut de UserCreationForm (routée sur
        # get_current_db(), la base de l'institut actif) par une vérification
        # pinnée sur 'default' : tout compte créé avec succès y est dupliqué
        # (voir User.save()), donc c'est la seule base qui reflète TOUS les
        # instituts — sans ce pin, un identifiant déjà pris dans un autre
        # institut n'est pas détecté et un compte doublon peut être créé.
        username = self.cleaned_data.get('username', '').strip()
        qs = User.objects.using('default').filter(Q(username__iexact=username) | Q(email__iexact=username))
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Cet identifiant est déjà utilisé par un autre compte (dans cet institut ou un autre).")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            return email
        qs = User.objects.using('default').filter(Q(email__iexact=email) | Q(username__iexact=email))
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Cet email est déjà utilisé par un compte existant (dans cet institut ou un autre).")
        return email


class UserUpdateForm(forms.ModelForm):
    # Champ dédié au routage DB
    target_institut = forms.ModelChoiceField(
        queryset=None,
        label="Institut d'appartenance",
        required=False,
        empty_label="— Choisir un institut —",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_target_institut'}),
    )

    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Laisser vide pour ne pas changer', 'autocomplete': 'new-password'}),
    )
    new_password2 = forms.CharField(
        label="Confirmer le mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmer le nouveau mot de passe', 'autocomplete': 'new-password'}),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'gender', 'role',
                  'department', 'responsable_class', 'institut_config', 'avatar', 'is_active']
        widgets = {
            'first_name':        forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':         forms.TextInput(attrs={'class': 'form-control'}),
            'email':             forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':             forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+221 77 000 00 00'}),
            'gender':            forms.Select(attrs={'class': 'form-select'}),
            'role':              forms.Select(attrs={'class': 'form-select', 'id': 'id_role'}),
            'department':        forms.Select(attrs={'class': 'form-select', 'id': 'id_department'}),
            'responsable_class': forms.Select(attrs={'class': 'form-select', 'id': 'id_responsable_class'}),
            'institut_config':   forms.Select(attrs={'class': 'form-select', 'id': 'id_institut_config'}),
            'avatar':            forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, requester=None, **kwargs):
        super().__init__(*args, **kwargs)
        _setup_user_form_fields(self, requester)

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password1', '')
        p2 = cleaned.get('new_password2', '')
        if p1 or p2:
            if len(p1) < 6:
                self.add_error('new_password1', "Le mot de passe doit contenir au moins 6 caractères.")
            elif p1 != p2:
                self.add_error('new_password2', "Les deux mots de passe ne correspondent pas.")
        return cleaned


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'avatar']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control'}),
            'avatar':     forms.FileInput(attrs={'class': 'form-control'}),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'votre@email.com'})
    )


class InstAdminCreateForm(forms.ModelForm):
    """Formulaire de création d'un administrateur d'institut (super admin uniquement)."""
    from academic_core.apps.academic_structure.models import InstitutConfig as _IC

    password = forms.CharField(
        label="Mot de passe par défaut",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text="L'administrateur devra le changer à sa première connexion.",
    )
    password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    institut_config = forms.ModelChoiceField(
        queryset=None,
        label="Institut administré",
        required=True,
        empty_label="— Sélectionner un institut —",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    role = forms.ModelChoiceField(
        queryset=None,
        label="Rôle",
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'role', 'institut_config', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'prenom.nom@exemple.com'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+221 77 000 00 00'}),
            'is_active':  forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import InstitutConfig
        self.fields['institut_config'].queryset = InstitutConfig.objects.select_related('faculty').order_by('nom')
        self.fields['role'].queryset = Role.objects.filter(name=Role.INST_ADMIN)
        self.fields['first_name'].required = True
        self.fields['last_name'].required  = True
        self.fields['first_name'].label    = 'Prénom'
        self.fields['last_name'].label     = 'Nom'

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("L'email est obligatoire.")
        # Les comptes créés par ce formulaire (INST_ADMIN/SI_ADMIN) atterrissent
        # TOUJOURS dans 'default' en premier (voir User.save(), dual-write),
        # quelle que soit la base tenant actuellement active pour le Super
        # Admin (ex : un "Accéder" précédent laissé en session) — la vérification
        # d'unicité doit donc être pinnée sur 'default', pas sur le thread-local
        # get_current_db(), sans quoi un doublon existant y passe inaperçu et
        # provoque une IntegrityError sur users.username au save().
        qs = User.objects.using('default').filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        )
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Un compte avec cet email existe déjà.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password', '')
        p2 = cleaned.get('password_confirm', '')
        if p1 and len(p1) < 6:
            self.add_error('password', "Le mot de passe doit contenir au moins 6 caractères.")
        elif p1 and p1 != p2:
            self.add_error('password_confirm', "Les deux mots de passe ne correspondent pas.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        # L'email est directement le login (username)
        email = self.cleaned_data['email']
        user.username = email
        user.email = email
        user.set_password(self.cleaned_data['password'])
        user.must_change_password = True
        if commit:
            user.save()
        return user


class InstAdminEditForm(forms.ModelForm):
    """Formulaire de modification d'un administrateur d'institut."""
    new_password = forms.CharField(
        label="Nouveau mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Laisser vide pour ne pas changer', 'autocomplete': 'new-password'}),
    )
    new_password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    institut_config = forms.ModelChoiceField(
        queryset=None,
        label="Institut administré",
        required=False,
        empty_label="— Aucun —",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    role = forms.ModelChoiceField(
        queryset=None,
        label="Rôle",
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'role', 'institut_config', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control'}),
            'is_active':  forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import InstitutConfig
        self.fields['institut_config'].queryset = InstitutConfig.objects.select_related('faculty').order_by('nom')
        self.fields['role'].queryset = Role.objects.filter(name=Role.INST_ADMIN)
        self.fields['first_name'].required = True
        self.fields['last_name'].required  = True
        self.fields['first_name'].label    = 'Prénom'
        self.fields['last_name'].label     = 'Nom'

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("L'email est obligatoire.")
        # Voir InstAdminCreateForm.clean_email : ces comptes vivent dans
        # 'default' — pinner la vérification d'unicité là, en excluant le
        # compte en cours d'édition.
        qs = User.objects.using('default').filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        )
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Un compte avec cet email existe déjà.")
        return email

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


class ControleurCreateForm(forms.ModelForm):
    """
    Création d'un Contrôleur Interne (super admin uniquement), rattaché à un ou
    plusieurs instituts (voir accounts.models.ControllerInstitut). Sur le
    modèle de InstAdminCreateForm — mêmes conventions (email = login, mot de
    passe par défaut à changer à la première connexion).
    """
    password = forms.CharField(
        label="Mot de passe par défaut",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text="Le Contrôleur devra le changer à sa première connexion.",
    )
    password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    instituts = forms.ModelMultipleChoiceField(
        queryset=None,
        label="Instituts contrôlés",
        required=True,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Sélectionnez au moins un institut. Si deux ou plus sont "
                   "sélectionnés, le Contrôleur devra choisir son institut "
                   "d'accès à chaque connexion (et pourra en changer ensuite).",
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'prenom.nom@exemple.com'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+221 77 000 00 00'}),
            'is_active':  forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import InstitutConfig
        self.fields['instituts'].queryset = InstitutConfig.objects.exclude(
            db_alias=''
        ).select_related('faculty').order_by('nom')
        self.fields['first_name'].required = True
        self.fields['last_name'].required  = True
        self.fields['first_name'].label    = 'Prénom'
        self.fields['last_name'].label     = 'Nom'

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("L'email est obligatoire.")
        # Même raison que InstAdminCreateForm.clean_email : ce compte (Controleur)
        # atterrit toujours dans 'default' (écriture directe ou copie via
        # sync_user_to_default_db, voir User.save()) — vérifier l'unicité sur
        # 'default' explicitement plutôt que sur le thread-local get_current_db().
        qs = User.objects.using('default').filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        )
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Un compte avec cet email existe déjà.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password', '')
        p2 = cleaned.get('password_confirm', '')
        if p1 and p2 and p1 != p2:
            self.add_error('password_confirm', "Les deux mots de passe ne correspondent pas.")
        elif p1 and len(p1) < 6:
            self.add_error('password', "Le mot de passe doit contenir au moins 6 caractères.")
        return cleaned


class ControleurEditForm(forms.ModelForm):
    """Modification d'un Contrôleur Interne multi-instituts (super admin uniquement)."""
    new_password = forms.CharField(
        label="Nouveau mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Laisser vide pour ne pas changer', 'autocomplete': 'new-password'}),
    )
    new_password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    instituts = forms.ModelMultipleChoiceField(
        queryset=None,
        label="Instituts contrôlés",
        required=True,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control'}),
            'is_active':  forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.academic_structure.models import InstitutConfig
        self.fields['instituts'].queryset = InstitutConfig.objects.exclude(
            db_alias=''
        ).select_related('faculty').order_by('nom')
        if self.instance and self.instance.pk:
            self.fields['instituts'].initial = self.instance.controlled_institut_links.values_list(
                'institut_config_id', flat=True
            )
        self.fields['first_name'].required = True
        self.fields['last_name'].required  = True
        self.fields['first_name'].label    = 'Prénom'
        self.fields['last_name'].label     = 'Nom'

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("L'email est obligatoire.")
        # Voir InstAdminCreateForm.clean_email : ces comptes vivent dans
        # 'default' — pinner la vérification d'unicité là, en excluant le
        # compte en cours d'édition.
        qs = User.objects.using('default').filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        )
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Un compte avec cet email existe déjà.")
        return email

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
