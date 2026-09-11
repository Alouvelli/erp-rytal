import bleach
from django import forms
from django.db.models import Q

RICH_TEXT_ALLOWED_TAGS = ['p', 'br', 'ul', 'ol', 'li', 'b', 'strong', 'i', 'em', 'u']


def sanitize_rich_text(html):
    """
    Nettoie le HTML produit par l'éditeur à puces (voir filiere_content_edit.html
    — contenteditable + document.execCommand, sans dépendance externe) avant
    stockage : liste blanche stricte de balises, aucun attribut autorisé (pas
    de style/onXXX/href...). Toujours appelé à l'écriture, jamais fait
    confiance au HTML brut soumis par le formulaire.
    """
    if not html:
        return ''
    cleaned = bleach.clean(html, tags=RICH_TEXT_ALLOWED_TAGS, attributes={}, strip=True)
    return cleaned.strip()


def plaintext_to_rich_html(text):
    """
    Convertit un contenu texte brut hérité (une idée par ligne, saisi avant
    l'introduction de l'éditeur à puces) en HTML affichable dans l'éditeur —
    chaque ligne devient un élément de liste. Si le contenu contient déjà des
    balises HTML (déjà migré via l'éditeur), il est renvoyé tel quel.
    """
    if not text:
        return ''
    if '<' in text:
        return text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    items = ''.join(f'<li>{bleach.clean(line, tags=[], strip=True)}</li>' for line in lines)
    return f'<ul>{items}</ul>'


def account_has_completed_payment(user):
    """
    True si ce compte a déjà finalisé le paiement de son inscription (rôle
    passé à Role.ETUDIANT, ou une Enrollment déjà VALIDATED) — seul ce cas
    réserve définitivement son email. Avant ce stade, une nouvelle tentative
    d'inscription avec le même email remplace silencieusement l'ancienne
    (voir signup_view/_purge_candidat_account dans admissions/views.py) ;
    le chef de département retrouve la candidature courante dans « Comptes
    candidats » dès qu'elle est soumise, rien n'est masqué.
    """
    from academic_core.apps.accounts.models import Role
    if user.role_id and user.role.name == Role.ETUDIANT:
        return True
    student = getattr(user, 'student_profile', None)
    if not student:
        return False
    from academic_core.apps.students.models import Enrollment
    return student.enrollments.filter(status=Enrollment.STATUS_VALIDATED).exists()


class ProgramContentForm(forms.Form):
    """
    Édition du contenu portail d'une filière — réservée au chef du
    département auquel elle appartient (voir admissions/views.py::
    filiere_content_edit_view).
    """
    level = forms.CharField(
        label="Niveau", required=False, max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex : Licence 1, Master 2…'}),
        help_text="Utilisé pour regrouper les filières par niveau sur le portail public.",
    )
    objectifs = forms.CharField(
        label="Objectifs de la formation", required=False,
        widget=forms.Textarea(attrs={'class': 'form-control rich-text-source', 'style': 'display:none;'}),
    )
    competences = forms.CharField(
        label="Compétences visées", required=False,
        widget=forms.Textarea(attrs={'class': 'form-control rich-text-source', 'style': 'display:none;'}),
    )
    debouches = forms.CharField(
        label="Débouchés", required=False,
        widget=forms.Textarea(attrs={'class': 'form-control rich-text-source', 'style': 'display:none;'}),
    )
    modalites_admission = forms.CharField(
        label="Modalités d'admission", required=False,
        widget=forms.Textarea(attrs={'class': 'form-control rich-text-source', 'style': 'display:none;'}),
    )

    def clean_objectifs(self):
        return sanitize_rich_text(self.cleaned_data.get('objectifs', ''))

    def clean_competences(self):
        return sanitize_rich_text(self.cleaned_data.get('competences', ''))

    def clean_debouches(self):
        return sanitize_rich_text(self.cleaned_data.get('debouches', ''))

    def clean_modalites_admission(self):
        return sanitize_rich_text(self.cleaned_data.get('modalites_admission', ''))
    places_disponibles = forms.IntegerField(
        label="Places disponibles", required=False, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Laisser vide pour un nombre de places illimité.",
    )
    ouvert_admissions = forms.BooleanField(
        label="Ouvert aux candidatures sur le portail public", required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    presentation_image = forms.ImageField(
        label="Image de présentation", required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text="Affichée sur le portail public. JPG/PNG, 5 Mo max.",
    )
    presentation_video = forms.FileField(
        label="Vidéo de présentation", required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text="Affichée sur le portail public. MP4/WebM, 25 Mo max.",
    )

    def clean_presentation_image(self):
        return _validate_image_file(self.cleaned_data.get('presentation_image'))

    def clean_presentation_video(self):
        return _validate_video_file(self.cleaned_data.get('presentation_video'))


class CandidateSignupForm(forms.Form):
    """Création de compte candidat depuis le portail public d'admission."""
    first_name = forms.CharField(max_length=100, label="Prénom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, label="Nom",
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, label="Téléphone", required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}))
    password = forms.CharField(
        label="Mot de passe", min_length=6,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    password_confirm = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    def clean_email(self):
        from academic_core.apps.accounts.models import User
        email = self.cleaned_data['email'].strip().lower()
        existing = User.objects.using('default').filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        ).first()
        if existing and account_has_completed_payment(existing):
            raise forms.ValidationError(
                "Un compte avec une inscription déjà finalisée existe pour cet email."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password'), cleaned.get('password_confirm')
        if p1 and p2 and p1 != p2:
            self.add_error('password_confirm', "Les deux mots de passe ne correspondent pas.")
        return cleaned


class CandidatureForm(forms.Form):
    """Soumission de candidature — choix de la filière + motivation."""
    program = forms.ModelChoiceField(
        queryset=None, label="Filière souhaitée",
        empty_label="— Sélectionner une filière —",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    motivation = forms.CharField(
        label="Lettre de motivation", required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
    )

    def __init__(self, *args, programs_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['program'].queryset = programs_queryset

    def clean_program(self):
        from academic_core.apps.academic_structure.models import AcademicYear
        program = self.cleaned_data['program']
        current_year = AcademicYear.objects.filter(is_current=True).first()
        if current_year:
            restantes = program.places_restantes(current_year)
            if restantes is not None and restantes <= 0:
                raise forms.ValidationError(
                    "Cette filière n'a plus de places disponibles pour l'année en cours."
                )
        return program


class PaymentProofForm(forms.Form):
    """Dépôt de preuve de paiement des frais d'inscription."""
    moyen_paiement = forms.ChoiceField(
        label="Moyen de paiement",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    montant_declare = forms.DecimalField(
        label="Montant versé (FCFA)", min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    reference_paiement = forms.CharField(
        max_length=100, label="Référence de la transaction", required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    piece_justificative = forms.FileField(
        label="Reçu / capture d'écran",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academic_core.apps.accounting.models import PaymentProof
        self.fields['moyen_paiement'].choices = PaymentProof.MOYEN_CHOICES

    def clean_piece_justificative(self):
        f = self.cleaned_data['piece_justificative']
        max_size = 5 * 1024 * 1024  # 5 Mo
        if f.size > max_size:
            raise forms.ValidationError("Le fichier ne doit pas dépasser 5 Mo.")
        allowed_ext = ('.pdf', '.jpg', '.jpeg', '.png')
        if not f.name.lower().endswith(allowed_ext):
            raise forms.ValidationError("Formats acceptés : PDF, JPG, PNG.")
        return f


def _validate_document_file(f):
    if not f:
        return f
    max_size = 5 * 1024 * 1024  # 5 Mo
    if f.size > max_size:
        raise forms.ValidationError("Le fichier ne doit pas dépasser 5 Mo.")
    allowed_ext = ('.pdf', '.jpg', '.jpeg', '.png')
    if not f.name.lower().endswith(allowed_ext):
        raise forms.ValidationError("Formats acceptés : PDF, JPG, PNG.")
    return f


def _validate_image_file(f):
    if not f:
        return f
    max_size = 5 * 1024 * 1024  # 5 Mo
    if f.size > max_size:
        raise forms.ValidationError("L'image ne doit pas dépasser 5 Mo.")
    allowed_ext = ('.jpg', '.jpeg', '.png', '.webp')
    if not f.name.lower().endswith(allowed_ext):
        raise forms.ValidationError("Formats acceptés : JPG, PNG, WEBP.")
    return f


def _validate_video_file(f):
    if not f:
        return f
    max_size = 25 * 1024 * 1024  # 25 Mo
    if f.size > max_size:
        raise forms.ValidationError("La vidéo ne doit pas dépasser 25 Mo.")
    allowed_ext = ('.mp4', '.webm', '.mov')
    if not f.name.lower().endswith(allowed_ext):
        raise forms.ValidationError("Formats acceptés : MP4, WEBM, MOV.")
    return f


class DepartmentPresentationForm(forms.Form):
    """
    Image/vidéo de présentation du département affichée sur le portail
    public — réservée au chef du département (voir admissions/views.py::
    department_presentation_edit_view).
    """
    presentation_image = forms.ImageField(
        label="Image de présentation", required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text="Affichée sur le portail public. JPG/PNG/WEBP, 5 Mo max.",
    )
    presentation_video = forms.FileField(
        label="Vidéo de présentation", required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text="Affichée sur le portail public. MP4/WEBM/MOV, 25 Mo max.",
    )
    description = forms.CharField(
        label="Description du département", required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        help_text="Affichée à côté de la vidéo/image de présentation sur le portail public.",
    )

    def clean_presentation_image(self):
        return _validate_image_file(self.cleaned_data.get('presentation_image'))

    def clean_presentation_video(self):
        return _validate_video_file(self.cleaned_data.get('presentation_video'))


class DepartmentAdmissionsDatesForm(forms.Form):
    """
    Fenêtre d'ouverture/fermeture des inscriptions d'un département — pilote
    l'affichage de son bandeau sur le portail public (voir
    Department.admissions_ouvertes et admissions\views.py::
    department_admissions_dates_edit_view). Accessible au chef du département
    concerné et à la Direction Communication.
    """
    # format='%Y-%m-%d' explicite : <input type="date"> exige strictement le
    # format ISO pour afficher la valeur pré-remplie — le format localisé
    # (ex. 23/04/2026) que Django utiliserait par défaut n'est pas reconnu
    # par le widget natif du navigateur, qui affiche alors le champ vide.
    admissions_date_ouverture = forms.DateField(
        label="Date d'ouverture des inscriptions", required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
        help_text="Laisser vide : pas de limite, ouvert dès maintenant.",
    )
    admissions_date_fermeture = forms.DateField(
        label="Date de fermeture des inscriptions", required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
        help_text="Laisser vide : jamais de fermeture automatique.",
    )

    def clean(self):
        cd = super().clean()
        ouverture, fermeture = cd.get('admissions_date_ouverture'), cd.get('admissions_date_fermeture')
        if ouverture and fermeture and fermeture < ouverture:
            raise forms.ValidationError(
                "La date de fermeture doit être postérieure ou égale à la date d'ouverture."
            )
        return cd


class CandidatureDocumentsForm(forms.Form):
    """
    Dépôt des pièces justificatives de validation de la candidature. CNI et
    diplôme du BAC sont exigés pour tous les candidats ; relevé du BAC +
    deux photos d'identité pour les candidats de 1ère année ; au moins un
    bulletin de semestre antérieur pour les candidats de 2ième à 5ième année
    (voir clean() ci-dessous et Candidature.required_document_types). Les
    bulletins eux-mêmes, en nombre variable, sont gérés hors de ce Form via
    un champ multi-fichiers natif traité directement par la vue.
    """
    niveau_entree = forms.ChoiceField(
        label="Année d'entrée",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    cni_passeport = forms.FileField(
        label="Carte Nationale d'Identité (CNI) ou Passeport",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
    )
    diplome_bac = forms.FileField(
        label="Diplôme / Attestation du BAC",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
    )
    releve_bac = forms.FileField(
        label="Relevé du BAC", required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Obligatoire pour un candidat de 1ère année.",
    )
    photo_identite_1 = forms.FileField(
        label="Photo d'identité (1)", required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Obligatoire pour un candidat de 1ère année.",
    )
    photo_identite_2 = forms.FileField(
        label="Photo d'identité (2)", required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Obligatoire pour un candidat de 1ère année.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Candidature
        self.fields['niveau_entree'].choices = list(Candidature.NIVEAU_CHOICES)

    def clean_cni_passeport(self):
        return _validate_document_file(self.cleaned_data.get('cni_passeport'))

    def clean_diplome_bac(self):
        return _validate_document_file(self.cleaned_data.get('diplome_bac'))

    def clean_releve_bac(self):
        return _validate_document_file(self.cleaned_data.get('releve_bac'))

    def clean_photo_identite_1(self):
        return _validate_document_file(self.cleaned_data.get('photo_identite_1'))

    def clean_photo_identite_2(self):
        return _validate_document_file(self.cleaned_data.get('photo_identite_2'))

    def clean(self):
        cleaned = super().clean()
        from .models import Candidature
        if cleaned.get('niveau_entree') == Candidature.NIVEAU_L1:
            for field in ('releve_bac', 'photo_identite_1', 'photo_identite_2'):
                if not cleaned.get(field):
                    self.add_error(field, "Obligatoire pour un candidat de 1ère année.")
        return cleaned
