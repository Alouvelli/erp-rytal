"""Cellule d'Orientation et d'Insertion Professionnelle (COIP).

Regroupe, dans un seul fichier (comme community_service/models.py), les 10
sous-modules métier portés depuis l'application de référence GestionCOIP :
Alumni, Partenariats, Stages, Sorties pédagogiques, Activités COIP,
Recommandations, Orientation, Opportunités, Rapports, Archives.

Les entités déjà présentes dans erp_gestion_ecole (Student, User/Role,
Notification, audit trail) sont réutilisées par FK — aucune n'est redéfinie
ici (voir CLAUDE.md/plan pour les décisions d'architecture)."""
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# ═══════════════════════════════════════════════════════════════════════════
# 1. ALUMNI
# ═══════════════════════════════════════════════════════════════════════════

class Alumni(models.Model):
    SECTEUR_INFORMATIQUE = 'INFORMATIQUE'
    SECTEUR_FINANCE = 'FINANCE'
    SECTEUR_SANTE = 'SANTE'
    SECTEUR_EDUCATION = 'EDUCATION'
    SECTEUR_INDUSTRIE = 'INDUSTRIE'
    SECTEUR_COMMERCE = 'COMMERCE'
    SECTEUR_ADMIN_PUBLIQUE = 'ADMIN_PUBLIQUE'
    SECTEUR_BTP = 'BTP'
    SECTEUR_TELECOMS = 'TELECOMS'
    SECTEUR_ONG = 'ONG'
    SECTEUR_AUTRE = 'AUTRE'
    SECTEUR_CHOICES = [
        (SECTEUR_INFORMATIQUE, _('Informatique / Numérique')),
        (SECTEUR_FINANCE, _('Finance / Banque / Assurance')),
        (SECTEUR_SANTE, _('Santé')),
        (SECTEUR_EDUCATION, _('Éducation / Formation')),
        (SECTEUR_INDUSTRIE, _('Industrie')),
        (SECTEUR_COMMERCE, _('Commerce / Distribution')),
        (SECTEUR_ADMIN_PUBLIQUE, _('Administration publique')),
        (SECTEUR_BTP, _('BTP / Construction')),
        (SECTEUR_TELECOMS, _('Télécommunications')),
        (SECTEUR_ONG, _('ONG / Associatif')),
        (SECTEUR_AUTRE, _('Autre')),
    ]

    student = models.OneToOneField(
        'students.Student', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alumni_profile', verbose_name=_('Étudiant (dossier académique)'),
    )
    user = models.OneToOneField(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alumni_profile', verbose_name=_('Compte utilisateur'),
    )
    first_name = models.CharField(max_length=100, verbose_name=_('Prénom'))
    last_name = models.CharField(max_length=100, verbose_name=_('Nom'))
    email = models.EmailField(blank=True, verbose_name=_('Email'))
    phone = models.CharField(max_length=30, blank=True, verbose_name=_('Téléphone'))
    promotion = models.CharField(max_length=20, blank=True, verbose_name=_('Promotion'))
    diplome = models.CharField(max_length=150, blank=True, verbose_name=_('Diplôme obtenu'))
    filiere = models.ForeignKey(
        'academic_structure.Program', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alumni', verbose_name=_('Filière'),
    )
    annee_obtention = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Année d'obtention"))
    entreprise_actuelle = models.CharField(max_length=200, blank=True, verbose_name=_('Entreprise actuelle'))
    poste_occupe = models.CharField(max_length=200, blank=True, verbose_name=_('Poste occupé'))
    secteur_activite = models.CharField(
        max_length=20, choices=SECTEUR_CHOICES, blank=True, verbose_name=_("Secteur d'activité"),
    )
    is_employed = models.BooleanField(default=False, verbose_name=_('En activité'))
    pays = models.CharField(max_length=100, blank=True, verbose_name=_('Pays'))
    ville = models.CharField(max_length=100, blank=True, verbose_name=_('Ville'))
    linkedin = models.URLField(blank=True, verbose_name=_('Profil LinkedIn'))
    photo = models.ImageField(upload_to='coip/alumni/', null=True, blank=True, verbose_name=_('Photo'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alumni_crees', db_constraint=False, verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coip_alumni'
        verbose_name = _('Alumni')
        verbose_name_plural = _('Alumni')
        ordering = ['-annee_obtention', 'last_name']
        indexes = [
            models.Index(fields=['-annee_obtention']),
            models.Index(fields=['secteur_activite']),
            models.Index(fields=['is_employed']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.promotion or self.annee_obtention or '—'})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class AlumniCareerEvent(models.Model):
    alumni = models.ForeignKey(Alumni, on_delete=models.CASCADE, related_name='career_events')
    date = models.DateField(verbose_name=_('Date'))
    entreprise = models.CharField(max_length=200, verbose_name=_('Entreprise'))
    poste = models.CharField(max_length=200, verbose_name=_('Poste'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_alumni_career_event'
        verbose_name = _('Événement de carrière')
        verbose_name_plural = _('Événements de carrière')
        ordering = ['-date']

    def __str__(self):
        return f"{self.alumni} — {self.poste} @ {self.entreprise}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. PARTENARIATS
# ═══════════════════════════════════════════════════════════════════════════

class Partner(models.Model):
    TYPE_ENTREPRISE = 'ENTREPRISE'
    TYPE_INSTITUTION = 'INSTITUTION'
    TYPE_ONG = 'ONG'
    TYPE_ADMIN_PUBLIQUE = 'ADMIN_PUBLIQUE'
    TYPE_AUTRE = 'AUTRE'
    TYPE_CHOICES = [
        (TYPE_ENTREPRISE, _('Entreprise')),
        (TYPE_INSTITUTION, _("Institution d'enseignement")),
        (TYPE_ONG, _('ONG')),
        (TYPE_ADMIN_PUBLIQUE, _('Administration publique')),
        (TYPE_AUTRE, _('Autre')),
    ]

    raison_sociale = models.CharField(max_length=200, verbose_name=_('Raison sociale'))
    type_partenaire = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_ENTREPRISE, verbose_name=_('Type de partenaire'),
    )
    secteur = models.CharField(max_length=150, blank=True, verbose_name=_("Secteur d'activité"))
    adresse = models.CharField(max_length=255, blank=True, verbose_name=_('Adresse'))
    ville = models.CharField(max_length=100, blank=True, verbose_name=_('Ville'))
    pays = models.CharField(max_length=100, blank=True, default='Sénégal', verbose_name=_('Pays'))
    email = models.EmailField(blank=True, verbose_name=_('Email'))
    phone = models.CharField(max_length=30, blank=True, verbose_name=_('Téléphone'))
    site_web = models.URLField(blank=True, verbose_name=_('Site web'))
    logo = models.ImageField(upload_to='coip/partners/logos/', null=True, blank=True, verbose_name=_('Logo'))
    is_active = models.BooleanField(default=True, verbose_name=_('Actif'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='partenaires_crees', db_constraint=False, verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coip_partner'
        verbose_name = _('Partenaire')
        verbose_name_plural = _('Partenaires')
        ordering = ['raison_sociale']
        indexes = [
            models.Index(fields=['type_partenaire']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.raison_sociale


class PartnerContact(models.Model):
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='contacts')
    nom = models.CharField(max_length=150, verbose_name=_('Nom'))
    poste = models.CharField(max_length=150, blank=True, verbose_name=_('Poste'))
    email = models.EmailField(blank=True, verbose_name=_('Email'))
    phone = models.CharField(max_length=30, blank=True, verbose_name=_('Téléphone'))
    is_primary = models.BooleanField(default=False, verbose_name=_('Contact principal'))

    class Meta:
        db_table = 'coip_partner_contact'
        verbose_name = _('Contact partenaire')
        verbose_name_plural = _('Contacts partenaire')
        ordering = ['-is_primary', 'nom']

    def __str__(self):
        return f"{self.nom} ({self.partner.raison_sociale})"


class Partnership(models.Model):
    STATUT_EN_COURS = 'EN_COURS'
    STATUT_ACTIVE = 'ACTIVE'
    STATUT_EXPIREE = 'EXPIREE'
    STATUT_RESILIEE = 'RESILIEE'
    STATUT_CHOICES = [
        (STATUT_EN_COURS, _('En cours de négociation')),
        (STATUT_ACTIVE, _('Active')),
        (STATUT_EXPIREE, _('Expirée')),
        (STATUT_RESILIEE, _('Résiliée')),
    ]

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='partnerships')
    intitule = models.CharField(max_length=255, verbose_name=_('Intitulé de la convention'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    date_signature = models.DateField(verbose_name=_('Date de signature'))
    date_expiration = models.DateField(null=True, blank=True, verbose_name=_("Date d'expiration"))
    status = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_EN_COURS, verbose_name=_('Statut'))
    document = models.FileField(upload_to='coip/conventions/', null=True, blank=True, verbose_name=_('Document (convention)'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='partenariats_geres', verbose_name=_('Responsable COIP'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coip_partnership'
        verbose_name = _('Convention de partenariat')
        verbose_name_plural = _('Conventions de partenariat')
        ordering = ['-date_signature']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-date_signature']),
        ]

    def __str__(self):
        return f"{self.intitule} — {self.partner.raison_sociale}"

    @property
    def is_expired(self):
        return bool(self.date_expiration and self.date_expiration < timezone.localdate())

    @property
    def days_until_expiry(self):
        if not self.date_expiration:
            return None
        return (self.date_expiration - timezone.localdate()).days

    @property
    def statut_color(self):
        return {
            self.STATUT_EN_COURS: 'warning',
            self.STATUT_ACTIVE: 'success',
            self.STATUT_EXPIREE: 'secondary',
            self.STATUT_RESILIEE: 'danger',
        }.get(self.status, 'secondary')


class CollaborationHistory(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE, related_name='collaboration_history')
    date = models.DateField(verbose_name=_('Date'))
    type_collaboration = models.CharField(max_length=150, verbose_name=_('Type de collaboration'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        db_constraint=False, related_name='+', verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_collaboration_history'
        verbose_name = _('Historique de collaboration')
        verbose_name_plural = _('Historique de collaboration')
        ordering = ['-date']

    def __str__(self):
        return f"{self.partnership} — {self.date}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. STAGES
# ═══════════════════════════════════════════════════════════════════════════

class InternshipOffer(models.Model):
    TYPE_ACADEMIQUE = 'ACADEMIQUE'
    TYPE_PROFESSIONNEL = 'PROFESSIONNEL'
    TYPE_PFE = 'PFE'
    TYPE_CHOICES = [
        (TYPE_ACADEMIQUE, _('Stage académique')),
        (TYPE_PROFESSIONNEL, _('Stage professionnel')),
        (TYPE_PFE, _('Projet de fin d\'études')),
    ]

    STATUT_OUVERT = 'OUVERT'
    STATUT_FERME = 'FERME'
    STATUT_POURVU = 'POURVU'
    STATUT_CHOICES = [
        (STATUT_OUVERT, _('Ouvert')),
        (STATUT_FERME, _('Fermé')),
        (STATUT_POURVU, _('Pourvu')),
    ]

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='internship_offers')
    titre = models.CharField(max_length=200, verbose_name=_('Titre du poste'))
    description = models.TextField(blank=True, verbose_name=_('Description / missions'))
    type_stage = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_ACADEMIQUE, verbose_name=_('Type de stage'))
    filiere_cible = models.ForeignKey(
        'academic_structure.Program', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='internship_offers', verbose_name=_('Filière ciblée'),
    )
    duree = models.CharField(max_length=100, blank=True, verbose_name=_('Durée'))
    date_debut = models.DateField(null=True, blank=True, verbose_name=_('Date de début souhaitée'))
    date_fin = models.DateField(null=True, blank=True, verbose_name=_('Date de fin souhaitée'))
    status = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_OUVERT, verbose_name=_('Statut'))
    remunere = models.BooleanField(default=False, verbose_name=_('Rémunéré'))
    montant_remuneration = models.CharField(max_length=100, blank=True, verbose_name=_('Montant de la rémunération'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='offres_stage_creees', db_constraint=False, verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_internship_offer'
        verbose_name = _("Offre de stage")
        verbose_name_plural = _('Offres de stage')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['type_stage']),
        ]

    def __str__(self):
        return f"{self.titre} — {self.partner.raison_sociale}"

    @property
    def statut_color(self):
        return {
            self.STATUT_OUVERT: 'success',
            self.STATUT_FERME: 'secondary',
            self.STATUT_POURVU: 'info',
        }.get(self.status, 'secondary')


class Internship(models.Model):
    STATUT_EN_ATTENTE = 'EN_ATTENTE'
    STATUT_CONFIRME = 'CONFIRME'
    STATUT_EN_COURS = 'EN_COURS'
    STATUT_TERMINE = 'TERMINE'
    STATUT_ABANDONNE = 'ABANDONNE'
    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, _('En attente')),
        (STATUT_CONFIRME, _('Confirmé')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_TERMINE, _('Terminé')),
        (STATUT_ABANDONNE, _('Abandonné')),
    ]

    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='internships')
    offer = models.ForeignKey(
        InternshipOffer, on_delete=models.SET_NULL, null=True, blank=True, related_name='internships',
    )
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name='internships')
    titre = models.CharField(max_length=200, verbose_name=_('Intitulé du stage'))
    encadreur_entreprise = models.CharField(max_length=200, blank=True, verbose_name=_('Encadreur en entreprise'))
    encadreur_isi = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stages_encadres', verbose_name=_('Encadreur académique'),
    )
    date_debut = models.DateField(verbose_name=_('Date de début'))
    date_fin = models.DateField(null=True, blank=True, verbose_name=_('Date de fin'))
    status = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE, verbose_name=_('Statut'))
    rapport = models.FileField(upload_to='coip/internships/rapports/', null=True, blank=True, verbose_name=_('Rapport de stage'))
    note = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name=_('Note'))
    appreciation = models.TextField(blank=True, verbose_name=_('Appréciation'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coip_internship'
        verbose_name = _('Stage')
        verbose_name_plural = _('Stages')
        ordering = ['-date_debut']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-date_debut']),
        ]

    def __str__(self):
        return f"{self.titre} — {self.student}"

    @property
    def statut_color(self):
        return {
            self.STATUT_EN_ATTENTE: 'warning',
            self.STATUT_CONFIRME: 'info',
            self.STATUT_EN_COURS: 'primary',
            self.STATUT_TERMINE: 'success',
            self.STATUT_ABANDONNE: 'danger',
        }.get(self.status, 'secondary')


# ═══════════════════════════════════════════════════════════════════════════
# 4. SORTIES PÉDAGOGIQUES
# ═══════════════════════════════════════════════════════════════════════════

class EducationalVisit(models.Model):
    STATUT_PLANIFIE = 'PLANIFIE'
    STATUT_VALIDE = 'VALIDE'
    STATUT_EN_COURS = 'EN_COURS'
    STATUT_TERMINE = 'TERMINE'
    STATUT_ANNULE = 'ANNULE'
    STATUT_CHOICES = [
        (STATUT_PLANIFIE, _('Planifiée')),
        (STATUT_VALIDE, _('Validée')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_TERMINE, _('Terminée')),
        (STATUT_ANNULE, _('Annulée')),
    ]

    intitule = models.CharField(max_length=200, verbose_name=_('Intitulé'))
    lieu = models.CharField(max_length=200, verbose_name=_('Lieu'))
    date_depart = models.DateTimeField(verbose_name=_('Date/heure de départ'))
    date_retour = models.DateTimeField(null=True, blank=True, verbose_name=_('Date/heure de retour'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sorties_responsable', verbose_name=_('Responsable'),
    )
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Budget'))
    objectifs = models.TextField(blank=True, verbose_name=_('Objectifs pédagogiques'))
    transport = models.CharField(max_length=150, blank=True, verbose_name=_('Moyen de transport'))
    nombre_places = models.PositiveIntegerField(default=30, verbose_name=_('Nombre de places'))
    status = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_PLANIFIE, verbose_name=_('Statut'))
    rapport = models.TextField(blank=True, verbose_name=_('Rapport / compte-rendu'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sorties_creees', db_constraint=False, verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_educational_visit'
        verbose_name = _('Sortie pédagogique')
        verbose_name_plural = _('Sorties pédagogiques')
        ordering = ['-date_depart']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-date_depart']),
        ]

    def __str__(self):
        return f"{self.intitule} — {self.lieu}"

    @property
    def statut_color(self):
        return {
            self.STATUT_PLANIFIE: 'warning',
            self.STATUT_VALIDE: 'info',
            self.STATUT_EN_COURS: 'primary',
            self.STATUT_TERMINE: 'success',
            self.STATUT_ANNULE: 'danger',
        }.get(self.status, 'secondary')

    @property
    def places_restantes(self):
        return max(0, self.nombre_places - self.participants.count())


class VisitParticipant(models.Model):
    visit = models.ForeignKey(EducationalVisit, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='sorties_participations')
    autorisation = models.BooleanField(default=False, verbose_name=_('Autorisation parentale/administrative reçue'))
    present = models.BooleanField(default=False, verbose_name=_('Présent'))
    observations = models.TextField(blank=True, verbose_name=_('Observations'))
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_visit_participant'
        verbose_name = _('Participant à la sortie')
        verbose_name_plural = _('Participants aux sorties')
        unique_together = [('visit', 'user')]

    def __str__(self):
        return f"{self.user} — {self.visit}"


class VisitPhoto(models.Model):
    visit = models.ForeignKey(EducationalVisit, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='coip/visits/photos/')
    legende = models.CharField(max_length=200, blank=True, verbose_name=_('Légende'))
    uploaded_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name='+',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_visit_photo'
        verbose_name = _('Photo de sortie')
        verbose_name_plural = _('Photos de sortie')
        ordering = ['-uploaded_at']


# ═══════════════════════════════════════════════════════════════════════════
# 5. ACTIVITÉS COIP
# ═══════════════════════════════════════════════════════════════════════════

class Activity(models.Model):
    TYPE_CONFERENCE = 'CONFERENCE'
    TYPE_ATELIER = 'ATELIER'
    TYPE_SEMINAIRE = 'SEMINAIRE'
    TYPE_FORUM = 'FORUM'
    TYPE_JOURNEE_CARRIERE = 'JOURNEE_CARRIERE'
    TYPE_VISITE = 'VISITE'
    TYPE_AUTRE = 'AUTRE'
    TYPE_CHOICES = [
        (TYPE_CONFERENCE, _('Conférence')),
        (TYPE_ATELIER, _('Atelier')),
        (TYPE_SEMINAIRE, _('Séminaire')),
        (TYPE_FORUM, _('Forum')),
        (TYPE_JOURNEE_CARRIERE, _('Journée carrière')),
        (TYPE_VISITE, _('Visite')),
        (TYPE_AUTRE, _('Autre')),
    ]

    STATUT_PLANIFIE = 'PLANIFIE'
    STATUT_EN_COURS = 'EN_COURS'
    STATUT_TERMINE = 'TERMINE'
    STATUT_ANNULE = 'ANNULE'
    STATUT_CHOICES = [
        (STATUT_PLANIFIE, _('Planifiée')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_TERMINE, _('Terminée')),
        (STATUT_ANNULE, _('Annulée')),
    ]

    titre = models.CharField(max_length=200, verbose_name=_('Titre'))
    type_activite = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_AUTRE, verbose_name=_("Type d'activité"))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    objectifs = models.TextField(blank=True, verbose_name=_('Objectifs'))
    date_debut = models.DateTimeField(verbose_name=_('Date/heure de début'))
    date_fin = models.DateTimeField(null=True, blank=True, verbose_name=_('Date/heure de fin'))
    lieu = models.CharField(max_length=200, blank=True, verbose_name=_('Lieu'))
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Budget'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activites_coip_responsable', verbose_name=_('Responsable'),
    )
    partenaires = models.ManyToManyField(Partner, blank=True, related_name='activites_coip', verbose_name=_('Partenaires associés'))
    status = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_PLANIFIE, verbose_name=_('Statut'))
    programme = models.TextField(blank=True, verbose_name=_('Programme détaillé'))
    compte_rendu = models.TextField(blank=True, verbose_name=_('Compte-rendu'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activites_coip_creees', db_constraint=False, verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_activity'
        verbose_name = _('Activité COIP')
        verbose_name_plural = _('Activités COIP')
        ordering = ['-date_debut']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['type_activite']),
            models.Index(fields=['-date_debut']),
        ]

    def __str__(self):
        return self.titre

    @property
    def statut_color(self):
        return {
            self.STATUT_PLANIFIE: 'warning',
            self.STATUT_EN_COURS: 'primary',
            self.STATUT_TERMINE: 'success',
            self.STATUT_ANNULE: 'danger',
        }.get(self.status, 'secondary')


class ActivityParticipant(models.Model):
    ROLE_PARTICIPANT = 'PARTICIPANT'
    ROLE_INTERVENANT = 'INTERVENANT'
    ROLE_ORGANISATEUR = 'ORGANISATEUR'
    ROLE_CHOICES = [
        (ROLE_PARTICIPANT, _('Participant')),
        (ROLE_INTERVENANT, _('Intervenant')),
        (ROLE_ORGANISATEUR, _('Organisateur')),
    ]

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='activites_coip_participations')
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default=ROLE_PARTICIPANT, verbose_name=_('Rôle'))
    present = models.BooleanField(default=False, verbose_name=_('Présent'))
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_activity_participant'
        verbose_name = _("Participant à l'activité")
        verbose_name_plural = _('Participants aux activités')
        unique_together = [('activity', 'user')]

    def __str__(self):
        return f"{self.user} — {self.activity}"


class ActivityPhoto(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='coip/activities/photos/')
    legende = models.CharField(max_length=200, blank=True, verbose_name=_('Légende'))
    uploaded_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name='+',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_activity_photo'
        verbose_name = _("Photo d'activité")
        verbose_name_plural = _("Photos d'activité")
        ordering = ['-uploaded_at']


# ═══════════════════════════════════════════════════════════════════════════
# 6. RECOMMANDATIONS
# ═══════════════════════════════════════════════════════════════════════════

class RecommendationRequest(models.Model):
    STATUT_EN_ATTENTE = 'EN_ATTENTE'
    STATUT_VALIDEE = 'VALIDEE'
    STATUT_EN_REDACTION = 'EN_REDACTION'
    STATUT_SIGNEE = 'SIGNEE'
    STATUT_LIVREE = 'LIVREE'
    STATUT_REJETEE = 'REJETEE'
    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, _('En attente')),
        (STATUT_VALIDEE, _('Validée')),
        (STATUT_EN_REDACTION, _('En rédaction')),
        (STATUT_SIGNEE, _('Signée')),
        (STATUT_LIVREE, _('Livrée')),
        (STATUT_REJETEE, _('Rejetée')),
    ]

    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='recommendation_requests')
    motif = models.TextField(verbose_name=_('Motif de la demande'))
    destinataire = models.CharField(max_length=200, blank=True, verbose_name=_('Destinataire'))
    programme_concerne = models.CharField(max_length=200, blank=True, verbose_name=_('Programme / poste concerné'))
    observations_etudiant = models.TextField(blank=True, verbose_name=_("Observations de l'étudiant"))
    status = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE, verbose_name=_('Statut'))
    assigned_to = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recommandations_assignees', verbose_name=_('Assignée à'),
    )
    lettre_pdf = models.FileField(upload_to='coip/recommendations/', null=True, blank=True, verbose_name=_('Lettre (PDF)'))
    motif_rejet = models.TextField(blank=True, verbose_name=_('Motif de rejet'))
    date_demande = models.DateTimeField(auto_now_add=True)
    date_livraison = models.DateTimeField(null=True, blank=True, verbose_name=_('Date de livraison'))

    class Meta:
        db_table = 'coip_recommendation_request'
        verbose_name = _('Demande de recommandation')
        verbose_name_plural = _('Demandes de recommandation')
        ordering = ['-date_demande']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-date_demande']),
        ]

    def __str__(self):
        return f"Recommandation — {self.student} ({self.get_status_display()})"

    @property
    def statut_color(self):
        return {
            self.STATUT_EN_ATTENTE: 'warning',
            self.STATUT_VALIDEE: 'info',
            self.STATUT_EN_REDACTION: 'primary',
            self.STATUT_SIGNEE: 'primary',
            self.STATUT_LIVREE: 'success',
            self.STATUT_REJETEE: 'danger',
        }.get(self.status, 'secondary')


class RecommendationWorkflow(models.Model):
    recommendation = models.ForeignKey(RecommendationRequest, on_delete=models.CASCADE, related_name='workflow_history')
    status = models.CharField(max_length=15, choices=RecommendationRequest.STATUT_CHOICES, verbose_name=_('Statut'))
    comment = models.TextField(blank=True, verbose_name=_('Commentaire'))
    changed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name='+',
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_recommendation_workflow'
        verbose_name = _('Historique de workflow (recommandation)')
        verbose_name_plural = _('Historique de workflow (recommandations)')
        ordering = ['changed_at']

    def __str__(self):
        return f"{self.recommendation} — {self.get_status_display()} ({self.changed_at:%d/%m/%Y})"


# ═══════════════════════════════════════════════════════════════════════════
# 7. ORIENTATION
# ═══════════════════════════════════════════════════════════════════════════

class OrientationSession(models.Model):
    TYPE_ENTRETIEN = 'ENTRETIEN'
    TYPE_COACHING = 'COACHING'
    TYPE_ACCOMPAGNEMENT = 'ACCOMPAGNEMENT'
    TYPE_BILAN = 'BILAN'
    TYPE_CHOICES = [
        (TYPE_ENTRETIEN, _('Entretien individuel')),
        (TYPE_COACHING, _('Coaching')),
        (TYPE_ACCOMPAGNEMENT, _('Accompagnement de projet')),
        (TYPE_BILAN, _('Bilan de compétences')),
    ]

    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='orientation_sessions')
    conseiller = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='orientation_sessions_menees', verbose_name=_('Conseiller'),
    )
    type_session = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_ENTRETIEN, verbose_name=_('Type de séance'))
    date_session = models.DateTimeField(verbose_name=_('Date de la séance'))
    duree_minutes = models.PositiveIntegerField(default=60, verbose_name=_('Durée (minutes)'))
    observations = models.TextField(blank=True, verbose_name=_('Observations'))
    recommandations = models.TextField(blank=True, verbose_name=_('Recommandations'))
    objectifs_fixes = models.TextField(blank=True, verbose_name=_('Objectifs fixés'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_orientation_session'
        verbose_name = "Séance d'orientation"
        verbose_name_plural = "Séances d'orientation"
        ordering = ['-date_session']
        indexes = [
            models.Index(fields=['-date_session']),
            models.Index(fields=['type_session']),
        ]

    def __str__(self):
        return f"{self.get_type_session_display()} — {self.student} ({self.date_session:%d/%m/%Y})"


# ═══════════════════════════════════════════════════════════════════════════
# 8. OPPORTUNITÉS
# ═══════════════════════════════════════════════════════════════════════════

class Opportunity(models.Model):
    TYPE_EMPLOI = 'EMPLOI'
    TYPE_STAGE = 'STAGE'
    TYPE_BOURSE = 'BOURSE'
    TYPE_FORMATION = 'FORMATION'
    TYPE_CHOICES = [
        (TYPE_EMPLOI, _('Emploi')),
        (TYPE_STAGE, _('Stage')),
        (TYPE_BOURSE, _('Bourse')),
        (TYPE_FORMATION, _('Formation')),
    ]

    STATUT_PUBLIE = 'PUBLIE'
    STATUT_FERME = 'FERME'
    STATUT_EXPIRE = 'EXPIRE'
    STATUT_CHOICES = [
        (STATUT_PUBLIE, _('Publiée')),
        (STATUT_FERME, _('Fermée')),
        (STATUT_EXPIRE, _('Expirée')),
    ]

    titre = models.CharField(max_length=200, verbose_name=_('Titre'))
    type_opportunite = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_EMPLOI, verbose_name=_("Type d'opportunité"))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    partner = models.ForeignKey(
        Partner, on_delete=models.SET_NULL, null=True, blank=True, related_name='opportunities', verbose_name=_('Partenaire'),
    )
    lieu = models.CharField(max_length=200, blank=True, verbose_name=_('Lieu'))
    remuneration = models.CharField(max_length=150, blank=True, verbose_name=_('Rémunération'))
    date_limite = models.DateField(null=True, blank=True, verbose_name=_('Date limite de candidature'))
    filiere_cible = models.ForeignKey(
        'academic_structure.Program', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='opportunities', verbose_name=_('Filière ciblée'),
    )
    niveau_cible = models.ForeignKey(
        'academic_structure.Level', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='opportunities', verbose_name=_('Niveau ciblé'),
    )
    status = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_PUBLIE, verbose_name=_('Statut'))
    publie_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='opportunites_publiees', db_constraint=False, verbose_name=_('Publié par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_opportunity'
        verbose_name = _('Opportunité')
        verbose_name_plural = _('Opportunités')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['type_opportunite']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return self.titre

    @property
    def is_expired(self):
        return bool(self.date_limite and self.date_limite < timezone.localdate())

    @property
    def statut_color(self):
        return {
            self.STATUT_PUBLIE: 'success',
            self.STATUT_FERME: 'secondary',
            self.STATUT_EXPIRE: 'danger',
        }.get(self.status, 'secondary')


class JobApplication(models.Model):
    STATUT_SOUMIS = 'SOUMIS'
    STATUT_EN_EXAMEN = 'EN_EXAMEN'
    STATUT_RETENU = 'RETENU'
    STATUT_REJETE = 'REJETE'
    STATUT_EMBAUCHE = 'EMBAUCHE'
    STATUT_CHOICES = [
        (STATUT_SOUMIS, _('Soumise')),
        (STATUT_EN_EXAMEN, _('En examen')),
        (STATUT_RETENU, _('Candidature retenue')),
        (STATUT_REJETE, _('Rejetée')),
        (STATUT_EMBAUCHE, _('Embauché(e)')),
    ]

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='applications')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='job_applications')
    lettre_motivation = models.FileField(upload_to='coip/applications/lettres/', null=True, blank=True, verbose_name=_('Lettre de motivation'))
    cv = models.FileField(upload_to='coip/applications/cv/', null=True, blank=True, verbose_name=_('CV'))
    status = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_SOUMIS, verbose_name=_('Statut'))
    notes = models.TextField(blank=True, verbose_name=_('Notes internes'))
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coip_job_application'
        verbose_name = _('Candidature')
        verbose_name_plural = _('Candidatures')
        ordering = ['-submitted_at']
        unique_together = [('opportunity', 'student')]
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.student} → {self.opportunity}"

    @property
    def statut_color(self):
        return {
            self.STATUT_SOUMIS: 'secondary',
            self.STATUT_EN_EXAMEN: 'warning',
            self.STATUT_RETENU: 'info',
            self.STATUT_REJETE: 'danger',
            self.STATUT_EMBAUCHE: 'success',
        }.get(self.status, 'secondary')


# ═══════════════════════════════════════════════════════════════════════════
# 9. RAPPORTS
# ═══════════════════════════════════════════════════════════════════════════

class Report(models.Model):
    TYPE_MENSUEL = 'MENSUEL'
    TYPE_TRIMESTRIEL = 'TRIMESTRIEL'
    TYPE_ANNUEL = 'ANNUEL'
    TYPE_PERSONNALISE = 'PERSONNALISE'
    TYPE_CHOICES = [
        (TYPE_MENSUEL, _('Mensuel')),
        (TYPE_TRIMESTRIEL, _('Trimestriel')),
        (TYPE_ANNUEL, _('Annuel')),
        (TYPE_PERSONNALISE, _('Personnalisé')),
    ]

    FORMAT_PDF = 'PDF'
    FORMAT_EXCEL = 'EXCEL'
    FORMAT_CHOICES = [
        (FORMAT_PDF, 'PDF'),
        (FORMAT_EXCEL, 'Excel'),
    ]

    STATUT_EN_ATTENTE = 'EN_ATTENTE'
    STATUT_GENERE = 'GENERE'
    STATUT_ERREUR = 'ERREUR'
    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, _('En attente')),
        (STATUT_GENERE, _('Généré')),
        (STATUT_ERREUR, _('Erreur')),
    ]

    titre = models.CharField(max_length=200, verbose_name=_('Titre'))
    type_rapport = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_PERSONNALISE, verbose_name=_('Type de rapport'))
    format_fichier = models.CharField(max_length=10, choices=FORMAT_CHOICES, default=FORMAT_PDF, verbose_name=_('Format'))
    periode_debut = models.DateField(verbose_name=_('Début de période'))
    periode_fin = models.DateField(verbose_name=_('Fin de période'))
    status = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE, verbose_name=_('Statut'))
    fichier = models.FileField(upload_to='coip/reports/', null=True, blank=True, verbose_name=_('Fichier généré'))
    genere_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rapports_coip_generes', db_constraint=False, verbose_name=_('Généré par'),
    )
    generated_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Date de génération'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_report'
        verbose_name = _('Rapport COIP')
        verbose_name_plural = _('Rapports COIP')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.titre} ({self.get_format_fichier_display()})"

    @property
    def statut_color(self):
        return {
            self.STATUT_EN_ATTENTE: 'warning',
            self.STATUT_GENERE: 'success',
            self.STATUT_ERREUR: 'danger',
        }.get(self.status, 'secondary')


# ═══════════════════════════════════════════════════════════════════════════
# 10. ARCHIVES
# ═══════════════════════════════════════════════════════════════════════════

class Archive(models.Model):
    CAT_CONVENTION = 'CONVENTION'
    CAT_RAPPORT = 'RAPPORT'
    CAT_RECOMMANDATION = 'RECOMMANDATION'
    CAT_ACTIVITE = 'ACTIVITE'
    CAT_SORTIE = 'SORTIE'
    CAT_AUTRE = 'AUTRE'
    CATEGORIE_CHOICES = [
        (CAT_CONVENTION, _('Convention')),
        (CAT_RAPPORT, _('Rapport')),
        (CAT_RECOMMANDATION, _('Recommandation')),
        (CAT_ACTIVITE, _('Activité')),
        (CAT_SORTIE, _('Sortie pédagogique')),
        (CAT_AUTRE, _('Autre')),
    ]

    titre = models.CharField(max_length=200, verbose_name=_('Titre'))
    categorie = models.CharField(max_length=20, choices=CATEGORIE_CHOICES, default=CAT_AUTRE, verbose_name=_('Catégorie'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    fichier = models.FileField(upload_to='coip/archives/%Y/%m/', verbose_name=_('Fichier'))
    version = models.CharField(max_length=20, default='1.0', verbose_name=_('Version'))
    tags = models.CharField(max_length=255, blank=True, verbose_name=_('Tags (séparés par des virgules)'))
    depose_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='archives_deposees', db_constraint=False, verbose_name=_('Déposé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'coip_archive'
        verbose_name = 'Archive'
        verbose_name_plural = 'Archives'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['categorie']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.titre} (v{self.version})"

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]


class ArchiveVersion(models.Model):
    archive = models.ForeignKey(Archive, on_delete=models.CASCADE, related_name='versions')
    fichier = models.FileField(upload_to='coip/archives/%Y/%m/', verbose_name=_('Fichier'))
    version = models.CharField(max_length=20, verbose_name=_('Version'))
    commentaire = models.TextField(blank=True, verbose_name=_('Commentaire'))
    uploaded_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name='+',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coip_archive_version'
        verbose_name = "Version d'archive"
        verbose_name_plural = "Versions d'archive"
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.archive.titre} — v{self.version}"
