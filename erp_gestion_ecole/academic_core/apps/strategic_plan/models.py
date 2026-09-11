"""
Plan Stratégique de Développement (PSD) — Pilotage et Suivi Budgétaire.

Hiérarchie : CadrageStrategique (PSD) -> AxeStrategique -> ObjectifStrategique
-> Programme -> Projet -> Activite -> SousActivite, avec Jalon/Livrable/
MembreEquipeProjet rattachés à Projet.

Miroir de apps/strategic_plan/models.py du projet de référence
appSuiviBudgetaire, adapté aux conventions de ce projet (accounts.User,
db_constraint=False sur les FK cross-app, verbose_name en français).
"""
from django.db import models
from django.utils.translation import gettext_lazy as _


class CadrageStrategique(models.Model):
    """Vision / mission / valeurs d'un Plan Stratégique de Développement."""
    libelle = models.CharField(max_length=200, verbose_name=_('Libellé'))
    annee_debut = models.PositiveIntegerField(verbose_name=_('Année de début'))
    annee_fin = models.PositiveIntegerField(verbose_name=_('Année de fin'))
    vision = models.TextField(verbose_name=_('Vision'))
    mission = models.TextField(verbose_name=_('Mission'))
    valeurs = models.TextField(blank=True, verbose_name=_('Valeurs'), help_text=_('Une valeur par ligne.'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_cadrages'
        verbose_name = _('Cadrage stratégique')
        verbose_name_plural = _('Cadrages stratégiques')
        ordering = ['-annee_debut']

    def __str__(self):
        return f"{self.libelle} ({self.annee_debut}-{self.annee_fin})"

    @property
    def liste_valeurs(self):
        return [v.strip() for v in self.valeurs.splitlines() if v.strip()]


class AxeStrategique(models.Model):
    """Axe stratégique d'un cadrage — sert aussi de dimension de tag pour LigneBudgetaire."""
    cadrage = models.ForeignKey(
        CadrageStrategique, on_delete=models.PROTECT, null=True, blank=True,
        related_name='axes', verbose_name=_('Cadrage stratégique'),
    )
    code = models.SlugField(max_length=20, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    annee_debut = models.PositiveIntegerField(null=True, blank=True, verbose_name=_('Année de début'))
    annee_fin = models.PositiveIntegerField(null=True, blank=True, verbose_name=_('Année de fin'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_axes'
        verbose_name = _('Axe stratégique')
        verbose_name_plural = _('Axes stratégiques')
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class ObjectifStrategique(models.Model):
    PERSPECTIVE_FINANCIERE = 'financiere'
    PERSPECTIVE_CLIENTS_ETUDIANTS = 'clients_etudiants'
    PERSPECTIVE_PROCESSUS_INTERNES = 'processus_internes'
    PERSPECTIVE_APPRENTISSAGE_INNOVATION = 'apprentissage_innovation'
    PERSPECTIVE_CHOICES = [
        (PERSPECTIVE_FINANCIERE, _('Financière')),
        (PERSPECTIVE_CLIENTS_ETUDIANTS, _('Clients / Étudiants')),
        (PERSPECTIVE_PROCESSUS_INTERNES, _('Processus internes')),
        (PERSPECTIVE_APPRENTISSAGE_INNOVATION, _('Apprentissage & Innovation')),
    ]

    axe = models.ForeignKey(
        AxeStrategique, on_delete=models.PROTECT, related_name='objectifs', verbose_name=_('Axe stratégique'),
    )
    code = models.SlugField(max_length=20, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='objectifs_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    description = models.TextField(blank=True, verbose_name=_('Description'))
    perspective_bsc = models.CharField(
        max_length=30, choices=PERSPECTIVE_CHOICES, blank=True, verbose_name=_('Perspective BSC'),
        help_text=_('Renseigner pour faire apparaître cet objectif dans le Balanced Scorecard.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_objectifs'
        verbose_name = _('Objectif stratégique')
        verbose_name_plural = _('Objectifs stratégiques')
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class Programme(models.Model):
    objectif = models.ForeignKey(
        ObjectifStrategique, on_delete=models.PROTECT, related_name='programmes', verbose_name=_('Objectif stratégique'),
    )
    code = models.SlugField(max_length=20, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='programmes_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_programmes'
        verbose_name = _('Programme')
        verbose_name_plural = _('Programmes')
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class Projet(models.Model):
    STATUT_PLANIFIE = 'planifie'
    STATUT_EN_COURS = 'en_cours'
    STATUT_SUSPENDU = 'suspendu'
    STATUT_TERMINE = 'termine'
    STATUT_ANNULE = 'annule'
    STATUT_CHOICES = [
        (STATUT_PLANIFIE, _('Planifié')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_SUSPENDU, _('Suspendu')),
        (STATUT_TERMINE, _('Terminé')),
        (STATUT_ANNULE, _('Annulé')),
    ]

    programme = models.ForeignKey(
        Programme, on_delete=models.PROTECT, related_name='projets', verbose_name=_('Programme'),
    )
    code = models.SlugField(max_length=20, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='projets_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    budget_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name=_('Budget total prévisionnel (FCFA)'),
        help_text=_('Champ déclaratif — indépendant du suivi réel via les lignes budgétaires.'),
    )
    date_debut = models.DateField(null=True, blank=True, verbose_name=_('Date de début'))
    date_fin = models.DateField(null=True, blank=True, verbose_name=_('Date de fin'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_PLANIFIE, verbose_name=_('Statut'))
    taux_avancement = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Taux d'avancement (%)"),
        help_text=_('Recalculé automatiquement à partir des activités.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_projets'
        verbose_name = _('Projet')
        verbose_name_plural = _('Projets')
        ordering = ['-date_debut', 'code']

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class Activite(models.Model):
    STATUT_PLANIFIEE = 'planifiee'
    STATUT_EN_COURS = 'en_cours'
    STATUT_TERMINEE = 'terminee'
    STATUT_RETARDEE = 'retardee'
    STATUT_ANNULEE = 'annulee'
    STATUT_CHOICES = [
        (STATUT_PLANIFIEE, _('Planifiée')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_TERMINEE, _('Terminée')),
        (STATUT_RETARDEE, _('Retardée')),
        (STATUT_ANNULEE, _('Annulée')),
    ]

    projet = models.ForeignKey(
        Projet, on_delete=models.CASCADE, related_name='activites', verbose_name=_('Projet'),
    )
    code = models.SlugField(max_length=30, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activites_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    budget = models.DecimalField(max_digits=16, decimal_places=2, default=0, verbose_name=_('Budget (FCFA)'))
    date_debut = models.DateField(null=True, blank=True, verbose_name=_('Date de début'))
    date_fin = models.DateField(null=True, blank=True, verbose_name=_('Date de fin'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_PLANIFIEE, verbose_name=_('Statut'))
    taux_avancement = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Taux d'avancement (%)"),
        help_text=_('Recalculé automatiquement à partir des sous-activités.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_activites'
        verbose_name = _('Activité')
        verbose_name_plural = _('Activités')
        ordering = ['date_debut', 'code']

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class SousActivite(models.Model):
    activite = models.ForeignKey(
        Activite, on_delete=models.CASCADE, related_name='sous_activites', verbose_name=_('Activité'),
    )
    code = models.SlugField(max_length=30, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sous_activites_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    date_debut = models.DateField(null=True, blank=True, verbose_name=_('Date de début'))
    date_fin = models.DateField(null=True, blank=True, verbose_name=_('Date de fin'))
    statut = models.CharField(max_length=20, choices=Activite.STATUT_CHOICES, default=Activite.STATUT_PLANIFIEE, verbose_name=_('Statut'))
    taux_avancement = models.PositiveSmallIntegerField(default=0, verbose_name=_("Taux d'avancement (%)"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_sous_activites'
        verbose_name = _('Sous-activité')
        verbose_name_plural = _('Sous-activités')
        ordering = ['date_debut', 'code']

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class Jalon(models.Model):
    """Milestone d'un projet."""
    STATUT_A_VENIR = 'a_venir'
    STATUT_ATTEINT = 'atteint'
    STATUT_MANQUE = 'manque'
    STATUT_CHOICES = [
        (STATUT_A_VENIR, _('À venir')),
        (STATUT_ATTEINT, _('Atteint')),
        (STATUT_MANQUE, _('Manqué')),
    ]

    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name='jalons', verbose_name=_('Projet'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    date_prevue = models.DateField(verbose_name=_('Date prévue'))
    date_reelle = models.DateField(null=True, blank=True, verbose_name=_('Date réelle'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='jalons_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_A_VENIR, verbose_name=_('Statut'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_jalons'
        verbose_name = _('Jalon')
        verbose_name_plural = _('Jalons')
        ordering = ['date_prevue']

    def __str__(self):
        return f"{self.libelle} ({self.projet.code})"


class Livrable(models.Model):
    """Deliverable d'un projet."""
    STATUT_EN_PREPARATION = 'en_preparation'
    STATUT_LIVRE = 'livre'
    STATUT_VALIDE = 'valide'
    STATUT_REJETE = 'rejete'
    STATUT_CHOICES = [
        (STATUT_EN_PREPARATION, _('En préparation')),
        (STATUT_LIVRE, _('Livré')),
        (STATUT_VALIDE, _('Validé')),
        (STATUT_REJETE, _('Rejeté')),
    ]

    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name='livrables', verbose_name=_('Projet'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    date_prevue = models.DateField(null=True, blank=True, verbose_name=_('Date prévue'))
    date_livraison = models.DateField(null=True, blank=True, verbose_name=_('Date de livraison'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='livrables_strategiques', db_constraint=False, verbose_name=_('Responsable'),
    )
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_EN_PREPARATION, verbose_name=_('Statut'))
    fichier = models.FileField(upload_to='psd/livrables/%Y/%m/', null=True, blank=True, verbose_name=_('Fichier'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_livrables'
        verbose_name = _('Livrable')
        verbose_name_plural = _('Livrables')
        ordering = ['date_prevue']

    def __str__(self):
        return f"{self.libelle} ({self.projet.code})"


class MembreEquipeProjet(models.Model):
    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name='membres_equipe', verbose_name=_('Projet'))
    utilisateur = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='equipes_projets_strategiques',
        db_constraint=False, verbose_name=_('Utilisateur'),
    )
    role_dans_projet = models.CharField(max_length=100, verbose_name=_('Rôle dans le projet'))
    date_affectation = models.DateField(auto_now_add=True, verbose_name=_("Date d'affectation"))

    class Meta:
        db_table = 'psd_membres_equipe'
        verbose_name = _("Membre d'équipe projet")
        verbose_name_plural = _("Membres d'équipe projet")
        unique_together = ('projet', 'utilisateur')

    def __str__(self):
        return f"{self.utilisateur} — {self.projet.code} ({self.role_dans_projet})"


class PlanTravailAnnuel(models.Model):
    """
    Plan de Travail Annuel (PTA) d'un titulaire (Administrateur de direction,
    Administrateur d'institut, Contrôleur Interne, Chef de département, CIAQ,
    COIP, Directeur des études, DAF, Administrateur Direction COM, DRH,
    Administrateur du SI — voir accounts.User.can_manage_pta) pour une année
    académique donnée — reprend la structure du modèle « MAQUETTE DE PLAN DE
    TRAVAIL ANNUEL » fourni par l'institut (un PTA par titulaire et par
    exercice, ses lignes rattachées à un Objectif stratégique — et donc, via
    Objectif.axe, à un Axe stratégique).
    """
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.PROTECT,
        related_name='plans_travail_annuels', db_constraint=False, verbose_name=_('Année académique'),
    )
    titulaire = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='plans_travail_annuels',
        db_constraint=False, verbose_name=_('Titulaire'),
    )
    direction = models.ForeignKey(
        'accounts.Direction', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='plans_travail_annuels', db_constraint=False, verbose_name=_('Direction'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psd_pta'
        verbose_name = _('Plan de Travail Annuel')
        verbose_name_plural = _('Plans de Travail Annuels')
        unique_together = ('academic_year', 'titulaire')
        ordering = ['-academic_year__start_date', 'titulaire__last_name']

    def __str__(self):
        return f"PTA {self.titulaire.get_full_name()} — {self.academic_year}"


class PlanTravailAnnuelLigne(models.Model):
    """Une ligne du PTA : rattachée à un Objectif stratégique (et donc à son
    Axe, via objectif_strategique.axe — l'Axe n'est choisi côté formulaire que
    pour filtrer la liste des objectifs, pas stocké séparément), avec ses
    activités, dates, indicateur de performance et élément de preuve — mêmes
    colonnes que la maquette Excel."""
    REALISATION_CHOICES = [(v, f'{v}%') for v in range(0, 101, 10)]

    plan = models.ForeignKey(
        PlanTravailAnnuel, on_delete=models.CASCADE, related_name='lignes', verbose_name=_('PTA'),
    )
    objectif_strategique = models.ForeignKey(
        ObjectifStrategique, on_delete=models.PROTECT, related_name='lignes_pta',
        verbose_name=_('Objectifs stratégiques'),
    )
    activites = models.TextField(blank=True, verbose_name=_('Activités'))
    date_debut_activite = models.DateField(null=True, blank=True, verbose_name=_("Date de début d'activité"))
    date_fin_activite = models.DateField(null=True, blank=True, verbose_name=_("Date de fin d'activité"))
    indicateur_performance = models.TextField(blank=True, verbose_name=_('Indicateur de performance'))
    element_preuve = models.TextField(blank=True, verbose_name=_('Élément de preuve'))
    realisations = models.PositiveSmallIntegerField(
        choices=REALISATION_CHOICES, default=0, verbose_name=_('Réalisations (%)'),
        help_text=_("Niveau de réalisation de l'activité, par palier de 10%."),
    )
    ordre = models.PositiveSmallIntegerField(default=0, verbose_name=_('Ordre'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psd_pta_lignes'
        verbose_name = _('Ligne de PTA')
        verbose_name_plural = _('Lignes de PTA')
        ordering = ['objectif_strategique__axe__code', 'objectif_strategique__code', 'ordre', 'pk']

    def __str__(self):
        return f"{self.objectif_strategique.code} — {self.activites[:50]}"
