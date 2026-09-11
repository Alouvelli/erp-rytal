from django.db import models
from django.utils.translation import gettext_lazy as _


class AcademicYear(models.Model):
    # db_constraint=False : AcademicYear est un modèle routé par tenant (une
    # ligne par base institut) alors que Faculty est un modèle maître (une
    # seule copie, toujours en base "default", voir db_router.py) — une vraie
    # contrainte SQL REFERENCES échouerait dès que la base tenant n'a pas
    # localement de ligne faculties avec le même id (cas normal, Faculty n'y
    # est jamais réellement peuplé).
    faculty = models.ForeignKey(
        'Faculty', on_delete=models.CASCADE, null=True, blank=True,
        related_name='academic_years', verbose_name=_('Institut'),
        db_constraint=False,
    )
    label = models.CharField(max_length=20, verbose_name=_('Libellé'))
    start_date = models.DateField(verbose_name=_('Date de début'))
    end_date = models.DateField(verbose_name=_('Date de fin'))
    is_current = models.BooleanField(default=False, verbose_name=_('Année en cours'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'academic_years'
        verbose_name = _('Année académique')
        verbose_name_plural = _('Années académiques')
        ordering = ['-start_date']
        unique_together = [('faculty', 'label')]

    @property
    def name(self):
        return self.label

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if self.is_current:
            # Unset is_current only for same faculty
            qs = AcademicYear.objects.exclude(pk=self.pk)
            if self.faculty_id:
                qs = qs.filter(faculty=self.faculty_id)
            qs.update(is_current=False)
        super().save(*args, **kwargs)


class Faculty(models.Model):
    code = models.CharField(max_length=20, unique=True, verbose_name=_('Code'))
    name = models.CharField(max_length=200, verbose_name=_('Nom'))
    dean = models.CharField(max_length=200, blank=True, verbose_name=_('Doyen'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'faculties'
        verbose_name = _('Institut')
        verbose_name_plural = _('Instituts')

    def __str__(self):
        return f"{self.code} - {self.name}"


class Department(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    # db_constraint=False : cf. AcademicYear.faculty ci-dessus — Department est
    # routé par tenant, Faculty est un modèle maître en base "default".
    faculty = models.ForeignKey(
        Faculty, on_delete=models.CASCADE, related_name='departments',
        db_constraint=False,
    )
    head = models.CharField(max_length=200, blank=True, verbose_name=_('Chef de département'))
    admin = models.OneToOneField(
        'accounts.User',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='administered_department', db_constraint=False,
        verbose_name=_('Administrateur de département')
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, verbose_name=_('Actif'))
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Portail public d'admission ──────────────────────────────────────────
    presentation_image = models.ImageField(
        upload_to='academic_structure/departments/presentation/%Y/%m/',
        blank=True, null=True, verbose_name=_('Image de présentation'),
    )
    presentation_video = models.FileField(
        upload_to='academic_structure/departments/presentation/%Y/%m/',
        blank=True, null=True, verbose_name=_('Vidéo de présentation'),
    )
    admissions_date_ouverture = models.DateField(
        null=True, blank=True, verbose_name=_("Date d'ouverture des inscriptions"),
        help_text=_('Non définie = pas de limite de ce côté (ouvert dès maintenant).'),
    )
    admissions_date_fermeture = models.DateField(
        null=True, blank=True, verbose_name=_('Date de fermeture des inscriptions'),
        help_text=_('Non définie = pas de limite de ce côté (jamais de fermeture automatique).'),
    )

    class Meta:
        db_table = 'departments'
        verbose_name = _('Département')
        verbose_name_plural = _('Départements')

    def __str__(self):
        return f"{self.code} - {self.name}"

    def admissions_ouvertes(self):
        """
        True si le portail public de candidature est ouvert pour ce
        département aujourd'hui, au regard de ses dates d'ouverture/fermeture
        des inscriptions — aucune date définie de part et d'autre = toujours
        ouvert (comportement historique, avant l'introduction de ces dates).
        """
        from django.utils import timezone
        today = timezone.now().date()
        if self.admissions_date_ouverture and today < self.admissions_date_ouverture:
            return False
        if self.admissions_date_fermeture and today > self.admissions_date_fermeture:
            return False
        return True


class Program(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200, verbose_name=_('Filière'))
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name='programs'
    )
    level = models.CharField(max_length=50, blank=True, default='', verbose_name=_('Niveau'))
    duration_years = models.PositiveSmallIntegerField(default=3, verbose_name=_('Durée (années)'))
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Portail public d'admission ──────────────────────────────────────────
    objectifs = models.TextField(blank=True, verbose_name=_('Objectifs de la formation'))
    competences = models.TextField(blank=True, verbose_name=_('Compétences visées'))
    debouches = models.TextField(blank=True, verbose_name=_('Débouchés'))
    modalites_admission = models.TextField(blank=True, verbose_name=_("Modalités d'admission"))
    places_disponibles = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_('Places disponibles'),
        help_text=_('Laisser vide pour un nombre de places illimité.'),
    )
    ouvert_admissions = models.BooleanField(
        default=True, verbose_name=_('Ouvert aux candidatures'),
        help_text=_('Décoché, la filière disparaît du portail public de candidature.'),
    )
    presentation_image = models.ImageField(
        upload_to='academic_structure/programs/presentation/%Y/%m/',
        blank=True, null=True, verbose_name=_('Image de présentation'),
    )
    presentation_video = models.FileField(
        upload_to='academic_structure/programs/presentation/%Y/%m/',
        blank=True, null=True, verbose_name=_('Vidéo de présentation'),
    )

    class Meta:
        db_table = 'programs'
        verbose_name = _('Filière')
        verbose_name_plural = _('Filières')

    def __str__(self):
        return f"{self.code} - {self.name}"

    def places_restantes(self, academic_year):
        """
        Places encore disponibles pour `academic_year` (illimité → None).
        Décompte les inscriptions déjà validées OU en attente de caisse (pas
        seulement VALIDATED) pour ne jamais sur-engager la filière pendant
        qu'un dossier est en cours de paiement.
        """
        if self.places_disponibles is None:
            return None
        from academic_core.apps.students.models import Enrollment
        occupees = Enrollment.objects.filter(
            class_group__program=self,
            academic_year=academic_year,
            status__in=[Enrollment.STATUS_VALIDATED, Enrollment.STATUS_PENDING_CAISSE],
        ).count()
        return max(self.places_disponibles - occupees, 0)


class Level(models.Model):
    name = models.CharField(max_length=50, verbose_name=_('Niveau'))
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = 'levels'
        verbose_name = _('Niveau')
        verbose_name_plural = _('Niveaux')
        ordering = ['order']

    def __str__(self):
        return self.name


class Semester(models.Model):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name='semesters'
    )
    # Niveau LMD concerné (Licence 1, Master 2...) — nécessaire pour qu'une
    # même année académique puisse porter à la fois le "Semestre 1" d'une
    # Licence 1 et le "Semestre 1" d'un Master 1 (numérotation LMD qui
    # redémarre par cycle), et pour que la liste des bulletins n'affiche que
    # les semestres pertinents pour le niveau de chaque classe.
    level = models.ForeignKey(
        'Level', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='semesters', verbose_name=_('Niveau'),
    )
    number = models.PositiveSmallIntegerField(verbose_name=_('Numéro du semestre'))
    label = models.CharField(max_length=50, verbose_name=_('Libellé'))
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    # ── Gestion des sessions (normale / rattrapage) ───────────────────────────
    session_normale_closed = models.BooleanField(
        default=False, verbose_name=_('Session normale clôturée')
    )
    session_normale_closed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_('Clôturée le')
    )
    session_normale_closed_by = models.ForeignKey(
        'accounts.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='semesters_closed',
        verbose_name=_('Clôturée par'), db_constraint=False,
    )
    session_rattrapage_active = models.BooleanField(
        default=False, verbose_name=_('Session rattrapage active')
    )

    # ── Verrouillage du semestre (Contrôleur interne) ─────────────────────────
    # Durant tout le semestre en question, seul le semestre ouvert (non verrouillé)
    # accepte des modifications (notes, cahier de texte, présences...).
    is_locked = models.BooleanField(
        default=False, verbose_name=_('Semestre verrouillé')
    )
    locked_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_('Verrouillé le')
    )
    locked_by = models.ForeignKey(
        'accounts.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='semesters_locked',
        verbose_name=_('Verrouillé par'), db_constraint=False,
    )

    class Meta:
        db_table = 'semesters'
        verbose_name = _('Semestre')
        verbose_name_plural = _('Semestres')
        unique_together = ('academic_year', 'number', 'level')
        ordering = ['academic_year', 'number']

    @property
    def name(self):
        return self.label if self.label else f"Semestre {self.number}"

    @property
    def lock_message(self):
        base = f"Le semestre « {self} » est verrouillé. Aucune modification n'est autorisée pour ce semestre."
        contact = getattr(self, 'locked_by', None)
        if contact:
            full_name = contact.get_full_name() or contact.username
            civility = getattr(contact, 'civility', '') or ''
            who = f"{civility} {full_name}".strip()
            return f"{base} Veuillez contacter le contrôleur interne, {who}, pour toute modification."
        return f"{base} Veuillez contacter le contrôleur interne pour toute modification."

    @property
    def session_label(self):
        if self.session_normale_closed and self.session_rattrapage_active:
            return 'rattrapage'
        return 'normale'

    def __str__(self):
        return f"{self.academic_year} - S{self.number}"


class Class(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name='classes'
    )
    level = models.ForeignKey(
        Level, on_delete=models.SET_NULL, null=True, related_name='classes'
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name='classes'
    )
    domaine = models.CharField(max_length=200, blank=True, default='', verbose_name=_('Domaine'))
    mention = models.CharField(max_length=200, blank=True, default='', verbose_name=_('Mention'))
    capacity = models.PositiveSmallIntegerField(default=40, verbose_name=_('Capacité'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'classes'
        verbose_name = _('Classe')
        verbose_name_plural = _('Classes')

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def student_count(self):
        return self.students.filter(status='VALIDATED', is_active=True).count()


class BulletinConfig(models.Model):
    """
    Configuration unique pour la génération des bulletins.
    Un seul enregistrement (singleton) — toujours lire via BulletinConfig.get().
    """
    director_title = models.CharField(
        max_length=200, default='Directrice des études',
        verbose_name=_('Titre du signataire'),
    )
    director_name = models.CharField(
        max_length=200, default='',
        verbose_name=_('Nom du signataire'),
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bulletin_config_updates', db_constraint=False,
    )

    class Meta:
        db_table = 'bulletin_config'
        verbose_name = _('Configuration bulletin')

    def __str__(self):
        return f"{self.director_title} — {self.director_name}"

    @classmethod
    def get(cls):
        """Retourne l'unique enregistrement, le crée si absent."""
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={'director_title': 'Directrice des études', 'director_name': ''},
        )
        return obj


class InstitutConfig(models.Model):
    """Configuration d'un établissement. Peut avoir plusieurs enregistrements (multi-institut)."""

    # ── Lien avec la structure ─────────────────────────────────────────────────
    faculty          = models.OneToOneField(
        'Faculty', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='institut_config', verbose_name=_('Faculté / Entité parente'),
    )
    # ── Statut ────────────────────────────────────────────────────────────────
    # Suspendu par défaut : un institut ne devient accessible que lorsque le
    # Super Admin le réactive explicitement en confirmant le code d'activation
    # de la plateforme (voir academic_structure/views.py::institut_list, action
    # 'toggle', et accounts.models.PlatformActivation).
    actif            = models.BooleanField(default=False, verbose_name=_('Institut actif'))
    date_suspension  = models.DateTimeField(null=True, blank=True, verbose_name=_('Date de suspension'))
    motif_suspension = models.TextField(blank=True, verbose_name=_('Motif de suspension'))
    # ── Identité ──────────────────────────────────────────────────────────────
    nom              = models.CharField(max_length=300, default='', verbose_name=_('Nom de l\'établissement'))
    sigle            = models.CharField(max_length=50,  blank=True,  verbose_name=_('Sigle / Acronyme'))
    slogan           = models.CharField(max_length=500, blank=True,  verbose_name=_('Devise / Slogan'))
    logo             = models.ImageField(
        upload_to='institut/logos/', null=True, blank=True,
        verbose_name=_('Logo principal'),
    )
    # ── Coordonnées ───────────────────────────────────────────────────────────
    pays             = models.CharField(max_length=100, default='Sénégal', verbose_name=_('Pays'))
    ville            = models.CharField(max_length=100, blank=True, verbose_name=_('Ville'))
    adresse          = models.TextField(blank=True, verbose_name=_('Adresse'))
    telephone        = models.CharField(max_length=50,  blank=True, verbose_name=_('Téléphone'))
    email            = models.EmailField(blank=True, verbose_name=_('Email institutionnel'))
    site_web         = models.URLField(blank=True, verbose_name=_('Site web'))
    # ── Informations légales ──────────────────────────────────────────────────
    annee_creation   = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Année de création'))
    numero_autorisation = models.CharField(max_length=200, blank=True, verbose_name=_('N° d\'autorisation'))
    statut_juridique = models.CharField(max_length=200, blank=True, verbose_name=_('Statut juridique'))
    # ── Matricule ─────────────────────────────────────────────────────────────
    matricule_prefix = models.CharField(
        max_length=20, blank=True, default='411',
        verbose_name=_('Préfixe matricule'),
        help_text=_('Préfixe fixe du matricule étudiant. Ex : 411 → 411-26-1234/ISI'),
    )
    # ── Signataires ───────────────────────────────────────────────────────────
    dg_titre         = models.CharField(max_length=200, blank=True, default='Directeur Général',  verbose_name=_('Titre DG'))
    dg_nom           = models.CharField(max_length=200, blank=True, verbose_name=_('Nom DG'))
    de_titre         = models.CharField(max_length=200, blank=True, default='Directeur des Études', verbose_name=_('Titre DE'))
    de_nom           = models.CharField(max_length=200, blank=True, verbose_name=_('Nom DE'))
    # ── Contrat de prestation de service (enseignants) ─────────────────────────
    # Texte modifiable selon les besoins de l'institut (voir aussi ContratArticle
    # pour les articles numérotés). Les valeurs par défaut reproduisent le texte
    # d'origine, afin de ne rien changer tant que l'institut ne les modifie pas.
    contrat_titre = models.CharField(
        max_length=200, blank=True, default='CONTRAT DE PRESTATION DE SERVICE',
        verbose_name=_('Titre du contrat'),
    )
    contrat_article1_texte = models.TextField(
        blank=True,
        default=(
            "le prestataire s'engage, dans le respect du manuel de procédures pédagogiques et du "
            "règlement intérieur de l'établissement, à dispenser des enseignements pour la période : "
            "{periode}. Les enseignements portent sur les modules suivants :"
        ),
        verbose_name=_("Article 1 — texte d'introduction"),
        help_text=_('Le repère {periode} est remplacé automatiquement par l’année académique du contrat.'),
    )
    contrat_cahier_charge_texte = models.TextField(
        blank=True,
        default=(
            "Les modalités d'exécution de la prestation et les objectifs fixés à atteindre sont "
            "définis dans un cahier de charge qui sera remis au prestataire. Ledit cahier de charge "
            "lie le prestataire."
        ),
        verbose_name=_('Paragraphe « cahier de charge »'),
    )
    # ── Apparence ─────────────────────────────────────────────────────────────
    couleur_primaire   = models.CharField(max_length=7, default='#00173B', verbose_name=_('Couleur principale'))
    couleur_secondaire = models.CharField(max_length=7, default='#D4AF37', verbose_name=_('Couleur secondaire'))
    # ── Portail public d'admission ──────────────────────────────────────────
    informations_paiement = models.TextField(
        blank=True, verbose_name=_('Informations de paiement'),
        help_text=_(
            "Coordonnées affichées au candidat pour régler ses frais d'inscription "
            "(numéros Wave/Orange Money, RIB pour virement, etc.)."
        ),
    )
    # ── Base de données dédiée ────────────────────────────────────────────────
    db_alias         = models.CharField(
        max_length=60, blank=True, default='',
        verbose_name=_('Alias base de données'),
        help_text=_('Ex: db_rytal_isi — généré automatiquement à la création'),
    )
    # ── Méta ──────────────────────────────────────────────────────────────────
    created_at       = models.DateTimeField(auto_now_add=True, null=True)
    updated_at       = models.DateTimeField(auto_now=True)
    updated_by       = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='institut_config_updates', db_constraint=False,
    )

    class Meta:
        db_table = 'institut_config'
        verbose_name = _('Configuration établissement')

    def __str__(self):
        return self.nom or 'Configuration établissement'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'nom': 'Institut Supérieur d\'Informatique'})
        return obj


class InstitutEmailConfig(models.Model):
    """
    Configuration SMTP propre à un institut, utilisée pour l'envoi des
    notifications qui le concernent (candidatures, inscriptions, paiements —
    voir academic_core/apps/notifications/utils.py::notify_users). Réglable
    par l'Administrateur d'institut (voir academic_structure/views.py::
    institut_email_config_view).

    Sans rapport avec le mécanisme d'activation de la plateforme (code
    d'activation, PLATFORM_RESET_EMAIL_1/2, EMAIL_* globaux du .env) — voir
    academic_core/apps/accounts/platform_activation.py, qui continue
    d'utiliser exclusivement la configuration email globale, inchangée.

    Modèle maître : vit exclusivement en base 'default' (voir
    MASTER_MODEL_NAMES dans db_router.py), comme InstitutConfig — un institut
    a une seule configuration email, indépendante de la base tenant active.
    """
    institut_config = models.OneToOneField(
        InstitutConfig, on_delete=models.CASCADE, related_name='email_config',
    )
    is_active = models.BooleanField(
        default=False, verbose_name=_('Utiliser cette configuration'),
        help_text=_(
            "Si activé, les notifications de cet institut sont envoyées via ces "
            "paramètres au lieu de la configuration email globale de la plateforme."
        ),
    )
    email_host = models.CharField(max_length=255, blank=True, verbose_name=_('Serveur SMTP'))
    email_port = models.PositiveIntegerField(default=587, verbose_name=_('Port SMTP'))
    email_use_tls = models.BooleanField(default=True, verbose_name=_('Utiliser TLS'))
    email_host_user = models.CharField(max_length=255, blank=True, verbose_name=_('Utilisateur SMTP'))
    email_host_password = models.CharField(max_length=255, blank=True, verbose_name=_('Mot de passe SMTP'))
    default_from_email = models.EmailField(blank=True, verbose_name=_('Adresse d\'expédition'))
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='institut_email_config_updates', db_constraint=False,
    )

    class Meta:
        db_table = 'institut_email_configs'
        verbose_name = _('Configuration email institut')
        verbose_name_plural = _('Configurations email instituts')

    def __str__(self):
        return f"Config email — {self.institut_config}"

    def is_usable(self) -> bool:
        return bool(self.is_active and self.email_host and self.email_host_user)


class InstitutPaymentConfig(models.Model):
    """
    Configuration de paiement en ligne propre à un institut, utilisée par le
    portail public de candidature pour le paiement des frais d'inscription
    (voir academic_core/apps/accounting/payment_gateway.py). Réglable par
    l'Administrateur d'institut (voir academic_structure/views.py::
    institut_payment_config_view).

    Trois moyens de paiement indépendamment activables, chacun avec sa
    propre configuration (remplace l'ancienne intégration par agrégateur
    unique PayDunya) :
      - Wave (API Checkout Sessions directe).
      - Orange Money (API Web Payment directe, OAuth2 client_credentials).
      - Virement bancaire (aucune API — coordonnées structurées affichées au
        candidat pour un virement manuel, toujours suivi d'un dépôt de
        preuve de paiement).

    ⚠️ Intégrations Wave/Orange Money construites selon la documentation
    publique de chaque API — non testées de bout en bout faute
    d'identifiants marchands réels au moment de l'écriture (voir
    accounting/payment_gateway.py). Tant qu'aucun moyen n'est activé et
    exploitable pour un institut, le portail continue de proposer
    uniquement le dépôt manuel de preuve de paiement (comportement inchangé).

    Sans rapport avec le mécanisme d'activation de la plateforme.

    Modèle maître : vit exclusivement en base 'default' (voir
    MASTER_MODEL_NAMES dans db_router.py), comme InstitutEmailConfig.
    """
    MODE_TEST = 'TEST'
    MODE_LIVE = 'LIVE'
    MODE_CHOICES = [
        (MODE_TEST, _('Test / Sandbox')),
        (MODE_LIVE, _('Production')),
    ]

    institut_config = models.OneToOneField(
        InstitutConfig, on_delete=models.CASCADE, related_name='payment_config',
    )

    # ── Wave ────────────────────────────────────────────────────────────────
    wave_active = models.BooleanField(default=False, verbose_name=_('Activer Wave'))
    wave_api_key = models.CharField(max_length=255, blank=True, verbose_name=_('Clé API Wave'))

    # ── Orange Money ────────────────────────────────────────────────────────
    om_active = models.BooleanField(default=False, verbose_name=_('Activer Orange Money'))
    om_client_id = models.CharField(max_length=255, blank=True, verbose_name=_('Client ID'))
    om_client_secret = models.CharField(max_length=255, blank=True, verbose_name=_('Client Secret'))
    om_merchant_key = models.CharField(
        max_length=255, blank=True, verbose_name=_('Merchant Key'),
        help_text=_("Clé marchand (Merchant Key) fournie par Orange Money."),
    )
    om_mode = models.CharField(
        max_length=10, choices=MODE_CHOICES, default=MODE_TEST,
        verbose_name=_('Mode Orange Money'),
    )
    om_region = models.CharField(
        max_length=5, default='sn', verbose_name=_('Code pays Orange Money'),
        help_text=_("Code pays utilisé dans l'URL de l'API Orange Money (ex. « sn » pour le Sénégal)."),
    )

    # ── Virement bancaire ───────────────────────────────────────────────────
    virement_active = models.BooleanField(default=False, verbose_name=_('Activer le virement bancaire'))
    banque_nom = models.CharField(max_length=150, blank=True, verbose_name=_('Nom de la banque'))
    banque_titulaire = models.CharField(max_length=150, blank=True, verbose_name=_('Titulaire du compte'))
    banque_iban = models.CharField(max_length=50, blank=True, verbose_name=_('IBAN'))
    banque_rib = models.CharField(max_length=50, blank=True, verbose_name=_('RIB'))
    banque_swift = models.CharField(max_length=20, blank=True, verbose_name=_('Code SWIFT/BIC'))
    virement_instructions = models.TextField(
        blank=True, verbose_name=_('Instructions complémentaires'),
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='institut_payment_config_updates', db_constraint=False,
    )

    class Meta:
        db_table = 'institut_payment_configs'
        verbose_name = _('Configuration paiement institut')
        verbose_name_plural = _('Configurations paiement instituts')

    def __str__(self):
        return f"Config paiement — {self.institut_config}"

    def wave_usable(self) -> bool:
        return bool(self.wave_active and self.wave_api_key)

    def orange_money_usable(self) -> bool:
        return bool(
            self.om_active and self.om_client_id
            and self.om_client_secret and self.om_merchant_key
        )

    def virement_usable(self) -> bool:
        return bool(self.virement_active and (self.banque_iban or self.banque_rib))

    def is_usable(self) -> bool:
        return self.wave_usable() or self.orange_money_usable() or self.virement_usable()


class ArchivedInstitutDatabase(models.Model):
    """
    Trace d'une base tenant archivée à la suppression d'un institut (voir
    academic_structure/utils.py::archive_institut_db et accounts/views.py::
    institut_delete). Le fichier lui-même est déplacé vers BASE_DIR/archives/
    — jamais supprimé à la suppression de l'institut — cette ligne permet de
    le retrouver, de le restaurer (recréer le même institut avec le même
    `code` régénère le même alias et réutilise le fichier existant plutôt
    que d'en cloner un vide — voir signals.py::auto_create_institute_db) ou
    de le supprimer définitivement une fois la donnée devenue inutile.

    Modèle maître : vit exclusivement en base 'default' (voir
    MASTER_MODEL_NAMES dans db_router.py), comme InstitutConfig.
    """
    nom   = models.CharField(max_length=200, verbose_name=_("Nom de l'institut"))
    sigle = models.CharField(max_length=30, blank=True)
    code  = models.CharField(
        max_length=30, blank=True,
        verbose_name=_('Code Faculty'),
        help_text=_("Recréer un institut avec ce même code régénère le même alias de base."),
    )
    alias = models.CharField(max_length=60, verbose_name=_('Alias base de données'))
    archived_path = models.CharField(max_length=255, verbose_name=_('Chemin du fichier archivé'))

    archived_at = models.DateTimeField(auto_now_add=True)
    archived_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', db_constraint=False,
    )

    restored_at = models.DateTimeField(null=True, blank=True)

    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Supprimée définitivement le'))
    deleted_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', db_constraint=False,
    )

    class Meta:
        db_table = 'archived_institut_databases'
        verbose_name = _("Base d'institut archivée")
        verbose_name_plural = _("Bases d'instituts archivées")
        ordering = ['-archived_at']

    def __str__(self):
        return f"{self.nom} ({self.alias})"


class InstitutDisabledTab(models.Model):
    """
    Onglet de la sidebar (voir academic_structure.feature_registry.TAB_LABELS)
    désactivé pour cet institut par le Super Admin. La présence d'une ligne vaut
    désactivation — activer un onglet supprime simplement sa ligne. Désactiver un
    onglet désactive automatiquement toutes ses fonctionnalités (voir
    feature_gate.is_feature_blocked et le filtrage de sidebar dans base.html).
    Modèle maître : vit exclusivement en base 'default', comme InstitutConfig
    (voir MASTER_MODEL_NAMES dans db_router.py).
    """
    institut_config = models.ForeignKey(
        InstitutConfig, on_delete=models.CASCADE, related_name='disabled_tabs',
    )
    tab_key = models.CharField(max_length=50, verbose_name=_('Onglet'))
    disabled_at = models.DateTimeField(auto_now_add=True)
    disabled_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        db_constraint=False,
    )

    class Meta:
        db_table = 'institut_disabled_tabs'
        unique_together = ('institut_config', 'tab_key')
        verbose_name = _('Onglet désactivé')
        verbose_name_plural = _('Onglets désactivés')

    def __str__(self):
        return f"{self.institut_config} — {self.tab_key} (désactivé)"


class InstitutDisabledFeature(models.Model):
    """
    Fonctionnalité précise (un lien de sidebar, identifié par son nom d'URL
    Django `app_label:url_name`) désactivée pour cet institut, indépendamment du
    reste de son onglet. `tab_key` est dénormalisé uniquement pour regrouper
    l'affichage de la page de gestion — la désactivation elle-même s'applique
    partout où ce nom d'URL apparaît dans la sidebar (voir feature_registry.py).
    Modèle maître : vit exclusivement en base 'default'.
    """
    institut_config = models.ForeignKey(
        InstitutConfig, on_delete=models.CASCADE, related_name='disabled_features',
    )
    tab_key = models.CharField(max_length=50, verbose_name=_('Onglet parent'))
    feature_key = models.CharField(max_length=100, verbose_name=_('Fonctionnalité'))
    disabled_at = models.DateTimeField(auto_now_add=True)
    disabled_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        db_constraint=False,
    )

    class Meta:
        db_table = 'institut_disabled_features'
        unique_together = ('institut_config', 'feature_key')
        verbose_name = _('Fonctionnalité désactivée')
        verbose_name_plural = _('Fonctionnalités désactivées')

    def __str__(self):
        return f"{self.institut_config} — {self.feature_key} (désactivée)"


class InstitutFiliation(models.Model):
    """Filiation / tutelle / partenaire affiché dans les documents et l'interface."""

    TYPE_TUTELLE      = 'TUTELLE'
    TYPE_PARTENAIRE   = 'PARTENAIRE'
    TYPE_ACCREDITATION = 'ACCREDITATION'
    TYPE_RESEAU       = 'RESEAU'
    TYPE_CHOICES = [
        (TYPE_TUTELLE,       _('Tutelle / Ministère')),
        (TYPE_PARTENAIRE,    _('Partenaire')),
        (TYPE_ACCREDITATION, _('Accréditation')),
        (TYPE_RESEAU,        _('Réseau / Association')),
    ]

    config      = models.ForeignKey(
        InstitutConfig, on_delete=models.CASCADE,
        related_name='filiations', verbose_name=_('Configuration'),
    )
    nom         = models.CharField(max_length=300, verbose_name=_('Nom'))
    type_filiation = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_TUTELLE, verbose_name=_('Type'))
    logo        = models.ImageField(
        upload_to='institut/filiations/', null=True, blank=True,
        verbose_name=_('Logo'),
    )
    site_web    = models.URLField(blank=True, verbose_name=_('Site web'))
    ordre       = models.PositiveSmallIntegerField(default=0, verbose_name=_('Ordre d\'affichage'))
    actif       = models.BooleanField(default=True, verbose_name=_('Affiché'))

    class Meta:
        db_table = 'institut_filiations'
        verbose_name = _('Filiation')
        verbose_name_plural = _('Filiations')
        ordering = ['ordre', 'nom']

    def __str__(self):
        return f"{self.get_type_filiation_display()} — {self.nom}"


# ── Texte par défaut des articles 2 à 23 du contrat de prestation de service ──
# Reproduit le modèle d'origine de l'institut. Sert à préremplir ContratArticle
# pour tout nouvel institut (voir seed_default_contrat_articles ci-dessous) — un
# institut peut ensuite librement modifier, désactiver ou ajouter des articles.
DEFAULT_CONTRAT_ARTICLES = [
    (2, "le prestataire doit fournir obligatoirement, un Numéro d'Identification National "
        "des Entreprises et Associations (NINEA)."),
    (3, "le prestataire assurera les enseignements conformément au programme proposé par "
        "l'établissement."),
    (4, "le prestataire doit remettre le support de cours et les plans de séance du module, "
        "avant le début des enseignements."),
    (5, "Pour chaque module, l'établissement devra remettre au prestataire un syllabus qui "
        "décrit le contenu du cours, les méthodes utilisées ainsi que les modes d'évaluation."),
    (6, "Le prestataire s'engage à exécuter le syllabus dans sa totalité et ce dans le délai "
        "fixé par la direction pédagogique. Il remettra un support de cours aux étudiants et "
        "à l'administration en début de semestre."),
    (7, "A la fin de chaque séance, le prestataire remplit le cahier de texte afin de "
        "permettre à la direction de faire le suivi pédagogique."),
    (8, "Le prestataire devra effectuer le contrôle des connaissances, en respect du manuel "
        "de procédure. Il devra faire au minimum un devoir et un examen par Elément "
        "Constitutif (EC). Il devra prévoir un sujet pour chaque (EC) pour la session de "
        "rattrapage."),
    (9, "Le prestataire doit participer aux conseils de classes, organisés par la direction "
        "des études, pour faire la délibération des résultats des examens, après chaque "
        "session."),
    (10, "Le prestataire s'engage à respecter les horaires d'enseignement établis de commun "
         "accord entre lui et la direction des études."),
    (11, "Le prestataire s'engage à déposer auprès de la direction pédagogique, les sujets "
         "pour les examens et devoirs au moins une semaine à l'avance pour permettre au "
         "service étude (bureau des examens) de faire la reprographie."),
    (12, "Le prestataire s'engage à corriger les épreuves et déposer les notes au plus tard "
         "une semaine après chaque évaluation (devoirs, examens)."),
    (13, "le prestataire n'a pas le droit de vendre aux étudiants des ouvrages et du matériel "
         "sans l'autorisation de l'administration."),
    (14, "Les exposés faits par les étudiants, ainsi que les polycopies distribuées, ne "
         "peuvent en aucun cas remplacer les cours."),
    (15, "Une évaluation de la prestation sera effectuée par les étudiants avant la période "
         "des examens de chaque semestre."),
    (16, "Les prestataires sont tenus pour chacune de leurs classes, de participer à "
         "l'encadrement des étudiants pour leur mémoire de fin de cycle."),
    (17, "Les indemnités d'encadrement pour chaque étudiant s'élèvent à 30 000 pour la "
         "licence et 50 000 pour le master. Les frais de soutenance pour chaque étudiant "
         "s'élèvent à 8000 f CFA pour les licences et 10 000 F CFA pour les masters. Les "
         "frais de pré soutenance s'élèvent à 8000 f CFA pour les masters."),
    (18, "le prestataire doit déposer une facture, à la fin de chaque mois."),
    (19, "l'établissement s'engage à payer, après traitement de la facture, les prestations "
         "du prestataire selon les taux horaires ci-dessous :<br/>"
         "— 7 000 F CFA pour la Licence 1 et 2 ;<br/>"
         "— 9 000 F CFA pour la Licence 3 et DITI 3 ;<br/>"
         "— 10 000 F CFA pour le Master, DITI 4 et DITI5."),
    (20, "Une retenue de 5% est opérée sur tout paiement si le montant est supérieur ou égal "
         "à 25 000 f cfa, conformément au code des impôts."),
    (21, "le prestataire est tenu de respecter le règlement intérieur de l'établissement, "
         "ainsi que toute autre disposition régissant le bon fonctionnement de l'institut."),
    (22, "Compte tenu de l'activité de l'établissement, du marché fortement concurrentiel "
         "sur lequel il évolue, le prestataire s'engage formellement à ne divulguer à qui "
         "que ce soit et sous quelque forme que ce soit aucun des projets, études, "
         "conceptions, etc. intéressant l'établissement ainsi que tous autres "
         "renseignements confidentiels dont le prestataire pourrait avoir connaissance."),
    (23, "toutes contestations, tous litiges relatifs à l'interprétation ou à l'exécution du "
         "présent contrat de prestation, doivent faire l'objet d'un règlement à l'amiable. "
         "Au cas où tel règlement ne peut être obtenu à propos du différend, compétence est "
         "donnée aux juridictions."),
]


def seed_default_contrat_articles(config):
    """Préremplit les articles 2-23 par défaut pour un InstitutConfig qui n'en a aucun."""
    if config.contrat_articles.exists():
        return
    ContratArticle.objects.bulk_create([
        ContratArticle(config=config, numero=numero, texte=texte)
        for numero, texte in DEFAULT_CONTRAT_ARTICLES
    ])


class ContratArticle(models.Model):
    """
    Article numéroté du contrat de prestation de service (enseignants) — voir
    teachers.pdf_contrat.generate_contrat_pdf(). Modifiable par institut afin de
    l'adapter à ses propres règles (tarifs, procédures, etc.), sans toucher au
    code. Les articles inactifs sont conservés mais exclus du PDF généré.
    """
    config  = models.ForeignKey(
        InstitutConfig, on_delete=models.CASCADE,
        related_name='contrat_articles', verbose_name=_('Configuration'),
    )
    numero  = models.PositiveSmallIntegerField(verbose_name=_('Numéro'))
    texte   = models.TextField(verbose_name=_('Texte'))
    actif   = models.BooleanField(default=True, verbose_name=_('Inclus dans le contrat'))

    class Meta:
        db_table = 'contrat_articles'
        verbose_name = _('Article de contrat')
        verbose_name_plural = _('Articles de contrat')
        ordering = ['numero']

    def __str__(self):
        return f"Article {self.numero}"


class AbonnementInstitut(models.Model):
    """Abonnement annuel d'un institut. Conditionne l'acces a la plateforme."""

    STATUT_ACTIF       = 'ACTIF'
    STATUT_EXPIRE      = 'EXPIRE'
    STATUT_SUSPENDU    = 'SUSPENDU'
    STATUT_EN_ATTENTE  = 'EN_ATTENTE'
    STATUT_CHOICES = [
        (STATUT_ACTIF,      _('Actif')),
        (STATUT_EXPIRE,     _('Expire')),
        (STATUT_SUSPENDU,   _('Suspendu')),
        (STATUT_EN_ATTENTE, _("En attente de paiement")),
    ]

    config           = models.ForeignKey(
        InstitutConfig, on_delete=models.CASCADE,
        related_name='abonnements', verbose_name=_("Etablissement"),
    )
    date_debut       = models.DateField(verbose_name=_("Date de debut"))
    duree_annees     = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("Duree (annees)"),
        help_text=_("Nombre d annees de l abonnement (1, 2, 3...)"),
    )
    date_fin         = models.DateField(verbose_name=_("Date d expiration"), editable=False)
    montant          = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name=_("Montant (FCFA)"),
    )
    reference_paiement = models.CharField(
        max_length=100, blank=True, verbose_name=_("Reference de paiement"),
    )
    statut           = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE,
        verbose_name=_("Statut"),
    )
    notes            = models.TextField(blank=True, verbose_name=_("Notes"))
    # Seuils (jours) pour lesquels un rappel a déjà été envoyé — ex: [60, 30]
    rappels_envoyes  = models.JSONField(default=list, blank=True, verbose_name=_("Rappels envoyés"))
    created_by       = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="abonnements_crees", db_constraint=False,
        verbose_name=_("Cree par"),
    )
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "abonnements_instituts"
        verbose_name = _("Abonnement institut")
        verbose_name_plural = _("Abonnements instituts")
        ordering = ["-date_debut"]

    def save(self, *args, **kwargs):
        self.date_fin = self._calc_date_fin()
        super().save(*args, **kwargs)

    def _calc_date_fin(self):
        from datetime import date
        d = self.date_debut
        y = d.year + self.duree_annees
        try:
            return d.replace(year=y)
        except ValueError:
            return d.replace(year=y, day=28)

    def __str__(self):
        return f"{self.config.nom or self.config.sigle} | {self.date_debut} -> {self.date_fin} | {self.get_statut_display()}"

    @property
    def is_valid(self):
        from datetime import date
        return self.statut == self.STATUT_ACTIF and self.date_fin >= date.today()

    @property
    def jours_restants(self):
        from datetime import date
        if not self.date_fin:
            return 0
        return (self.date_fin - date.today()).days

    @property
    def alerte(self):
        """Niveau d alerte : ok / warning / critical / expired."""
        j = self.jours_restants
        if self.statut != self.STATUT_ACTIF:
            return "expired"
        if j < 0:
            return "expired"
        if j <= 30:
            return "critical"
        if j <= 90:
            return "warning"
        return "ok"


class DiplomaSupplementConfig(models.Model):
    """
    Contenu descriptif du « Supplément au diplôme » d'une filière (Program),
    saisi une seule fois par la Direction des Études puis réutilisé pour
    générer le document de chaque étudiant éligible de cette filière (voir
    accounting/views.py::diploma_supplement_pdf). Les champs reprennent tels
    quels les rubriques du modèle Word fourni comme référence pour ce
    document ; seules les données propres à l'étudiant (identité, relevé des
    modules réellement suivis) sont calculées automatiquement.
    """
    program = models.OneToOneField(
        Program, on_delete=models.CASCADE, related_name='diploma_supplement_config',
        verbose_name=_('Filière'),
    )
    domaine = models.CharField(
        max_length=200, blank=True, verbose_name=_('Domaine'),
        help_text=_('Ex. : Sciences et technologies. Si vide, repris du champ « Domaine » de la classe la plus récente de la filière.')
    )
    langue_etudes = models.CharField(
        max_length=100, blank=True, default='Le français', verbose_name=_("Langue d'études")
    )
    definition_qualification = models.TextField(
        blank=True, verbose_name=_('Définition de la qualification'),
        help_text=_('Ce que le diplômé est capable de faire — compétences et champ professionnel visés.')
    )
    duree_texte = models.CharField(
        max_length=300, blank=True, verbose_name=_('Durée'),
        help_text=_("Ex. : « 2 années universitaires après l'obtention de la licence ».")
    )
    conditions_admission = models.TextField(
        blank=True, verbose_name=_("Conditions d'admission"),
        help_text=_('Une condition par ligne — chaque ligne devient une puce du document.')
    )
    poursuite_etudes = models.TextField(
        blank=True, verbose_name=_("Poursuite d'études"),
    )
    statut_professionnel = models.CharField(
        max_length=300, blank=True, verbose_name=_("Statut professionnel conféré"),
    )
    forme_etudes = models.CharField(
        max_length=100, blank=True, default='En présentiel', verbose_name=_('Forme des études'),
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='diploma_supplement_config_updates', db_constraint=False,
    )

    class Meta:
        db_table = 'diploma_supplement_configs'
        verbose_name = _('Configuration supplément de diplôme')
        verbose_name_plural = _('Configurations supplément de diplôme')

    def __str__(self):
        return f"Supplément de diplôme — {self.program.name}"

    @property
    def conditions_admission_list(self):
        return [line.strip() for line in (self.conditions_admission or '').splitlines() if line.strip()]
