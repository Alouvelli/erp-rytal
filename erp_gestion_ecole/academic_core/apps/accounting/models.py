import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ComptabiliteConfig(models.Model):
    """Configuration comptable globale (singleton, conservé pour compatibilité)."""
    frais_generaux = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name=_('Frais généraux (FCFA)'),
    )
    # Seuils d'alerte du KPI de Pilotage et Suivi Budgétaire (LigneBudgetaire.statut_kpi) :
    # taux d'exécution (montant_execute / montant_revise) >= seuil_rouge -> rouge,
    # >= seuil_orange -> orange, sinon vert.
    budget_seuil_orange = models.DecimalField(
        max_digits=4, decimal_places=2, default=0.80,
        verbose_name=_("Seuil d'alerte orange (taux d'exécution budgétaire)"),
    )
    budget_seuil_rouge = models.DecimalField(
        max_digits=4, decimal_places=2, default=1.00,
        verbose_name=_("Seuil d'alerte rouge (taux d'exécution budgétaire)"),
    )
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='comptabilite_configs', db_constraint=False,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'comptabilite_config'
        verbose_name = _('Configuration comptable')

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Config comptable — Frais généraux : {self.frais_generaux} FCFA"


class PartenaireBourse(models.Model):
    """Partenaire de bourse (organisme finançant des bourses d'étudiants)."""
    code            = models.CharField(max_length=30, unique=True, verbose_name=_('Code'))
    intitule        = models.CharField(max_length=200, verbose_name=_('Intitulé'))
    is_active       = models.BooleanField(default=True, verbose_name=_('Actif'))
    created_by      = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='partenaires_bourse_crees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'partenaires_bourse'
        verbose_name = _('Partenaire de bourse')
        verbose_name_plural = _('Partenaires de bourse')
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.intitule}"


class FraisGenerauxNiveau(models.Model):
    """Frais généraux configurés par niveau. Gérés par le Comptable/Admin."""
    level = models.OneToOneField(
        'academic_structure.Level',
        on_delete=models.CASCADE,
        related_name='frais_generaux_config',
        verbose_name=_('Niveau'),
    )
    frais_totaux = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais totaux d\'inscription (FCFA)'),
        help_text=_('Montant total des frais d\'inscription pour ce niveau'),
    )
    frais_generaux = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name=_('Frais généraux (FCFA)'),
        help_text=_('Montant soustrait automatiquement des frais totaux pour ce niveau'),
    )
    frais_mensuel = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Mensualité scolarité (FCFA)'),
        help_text=_('Montant mensuel de scolarité à payer pour ce niveau'),
    )
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='frais_generaux_updates', db_constraint=False,
        verbose_name=_('Mis à jour par'),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'frais_generaux_niveau'
        verbose_name = _('Frais généraux par niveau')
        verbose_name_plural = _('Frais généraux par niveau')
        ordering = ['level__name']

    def __str__(self):
        return f"{self.level} — {self.frais_generaux} FCFA"

    @classmethod
    def get_for_level(cls, level):
        """Retourne l'objet config pour un niveau, None si non défini."""
        if level is None:
            return None
        try:
            return cls.objects.get(level=level)
        except cls.DoesNotExist:
            return None


class FraisMensuelClasse(models.Model):
    """
    Frais de scolarité configurés par classe (prioritaires sur FraisGenerauxNiveau) :
    montant global de la formation, mensualité, et frais annexes (tenue, assurance,
    Amicale, bibliothèque). Définis directement à la création/modification de la classe.
    """
    class_group = models.OneToOneField(
        'academic_structure.Class',
        on_delete=models.CASCADE,
        related_name='frais_mensuel_config',
        verbose_name=_('Classe'),
    )
    montant_global = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Montant global de la formation (FCFA)'),
        help_text=_("Coût total de la formation pour cette classe"),
    )
    frais_mensuel = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Mensualité scolarité (FCFA)'),
        help_text=_('Montant mensuel dû pour cette classe'),
    )
    frais_inscription = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_("Frais d'inscription (FCFA)"),
        help_text=_("Utilisé pour calculer le droit d'inscription lors de la validation d'inscription"),
    )
    frais_tenue = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais de tenue (FCFA)'),
    )
    frais_assurance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais d\'assurance (FCFA)'),
    )
    frais_amea = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais Amicale (FCFA)'),
    )
    frais_bibliotheque = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais Bibliothèque (FCFA)'),
    )
    frais_soutenance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais de soutenance normal (FCFA)'),
        help_text=_(
            "Applicable en Licence 3 et Master 2. Pré-rempli automatiquement "
            "(60 000 FCFA en L3, 100 000 FCFA en M2), modifiable."
        ),
    )
    frais_soutenance_speciale = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Frais de soutenance spéciale (FCFA)'),
        help_text=_(
            "Applicable en Licence 3 et Master 2. Pré-rempli automatiquement "
            "(180 000 FCFA en L3, 200 000 FCFA en M2), modifiable."
        ),
    )
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='frais_mensuel_classe_updates', db_constraint=False,
        verbose_name=_('Mis à jour par'),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'frais_mensuel_classe'
        verbose_name = _('Frais par classe')
        verbose_name_plural = _('Frais par classe')
        ordering = ['class_group__level__name', 'class_group__name']

    def __str__(self):
        return f"{self.class_group} — {self.frais_mensuel} FCFA/mois"


class HourlyRate(models.Model):
    """Taux horaire défini par l'admin du département, par niveau et année académique.
    La durée d'une séance est déduite de l'emploi du temps (end_time - start_time)."""

    department = models.ForeignKey(
        'academic_structure.Department',
        on_delete=models.CASCADE,
        related_name='hourly_rates',
        verbose_name=_('Département'),
    )
    level = models.ForeignKey(
        'academic_structure.Level',
        on_delete=models.CASCADE,
        related_name='hourly_rates',
        verbose_name=_('Niveau'),
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear',
        on_delete=models.CASCADE,
        related_name='hourly_rates',
        verbose_name=_('Année académique'),
    )
    rate_per_hour = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name=_('Taux horaire (FCFA/heure)'),
    )
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_hourly_rates', db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hourly_rates'
        verbose_name = _('Taux horaire')
        verbose_name_plural = _('Taux horaires')
        unique_together = ('department', 'level', 'academic_year')
        ordering = ['department', 'level']

    def __str__(self):
        return f"{self.department.code} | {self.level} | {self.rate_per_hour} FCFA/h"

    def amount_for_session(self, duration_hours):
        """Montant pour une séance de durée donnée (en heures)."""
        from decimal import Decimal
        return self.rate_per_hour * Decimal(str(duration_hours))


class TeacherHonoraire(models.Model):
    """Honoraire enregistré automatiquement à la validation d'une fiche d'émargement."""

    attendance_sheet = models.OneToOneField(
        'attendance.AttendanceSheet',
        on_delete=models.CASCADE,
        related_name='honoraire',
        verbose_name=_('Feuille d\'émargement'),
    )
    teacher = models.ForeignKey(
        'teachers.Teacher',
        on_delete=models.CASCADE,
        related_name='honoraires',
        verbose_name=_('Enseignant'),
    )
    department = models.ForeignKey(
        'academic_structure.Department',
        on_delete=models.CASCADE,
        related_name='honoraires',
        verbose_name=_('Département'),
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear',
        on_delete=models.CASCADE,
        related_name='honoraires',
        verbose_name=_('Année académique'),
    )
    session_date = models.DateField(verbose_name=_('Date de la séance'))
    duration_hours = models.DecimalField(
        max_digits=5, decimal_places=2,
        verbose_name=_('Durée (heures)'),
    )
    rate_per_hour = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name=_('Taux horaire (FCFA/h)'),
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name=_('Montant (FCFA)'),
    )
    validated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validated_honoraires', db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'teacher_honoraires'
        verbose_name = _('Honoraire enseignant')
        verbose_name_plural = _('Honoraires enseignants')
        ordering = ['-session_date']

    @property
    def impots(self):
        from decimal import Decimal, ROUND_HALF_UP
        return (self.amount * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)

    @property
    def net_a_payer(self):
        return self.amount - self.impots

    def __str__(self):
        return f"{self.teacher} | {self.session_date} | {self.amount} FCFA"


class AcademicYearDistribution(models.Model):
    """Répartition de l'année académique en mois pour une classe donnée."""

    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear',
        on_delete=models.CASCADE,
        related_name='distributions',
        verbose_name=_('Année académique'),
    )
    class_group = models.ForeignKey(
        'academic_structure.Class',
        on_delete=models.CASCADE,
        related_name='year_distribution',
        verbose_name=_('Classe'),
    )
    MONTHS = [
        (1, _('Janvier')), (2, _('Février')), (3, _('Mars')), (4, _('Avril')),
        (5, _('Mai')), (6, _('Juin')), (7, _('Juillet')), (8, _('Août')),
        (9, _('Septembre')), (10, _('Octobre')), (11, _('Novembre')), (12, _('Décembre')),
    ]
    start_month = models.PositiveSmallIntegerField(
        choices=MONTHS,
        default=9,
        verbose_name=_('Mois de début'),
        help_text=_("Premier mois de l'année académique pour cette classe"),
    )
    nb_months = models.PositiveSmallIntegerField(
        verbose_name=_('Nombre de mois'),
        help_text=_("Nombre de mois de l'année académique attribués à cette classe"),
    )
    notes = models.TextField(blank=True, verbose_name=_('Observations'))
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_distributions', db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'academic_year_distributions'
        verbose_name = _("Répartition année académique")
        verbose_name_plural = _("Répartitions années académiques")
        unique_together = ('academic_year', 'class_group')
        ordering = ['academic_year', 'class_group__name']

    @property
    def end_month(self):
        """Mois de fin = mois de début + nb_months - 1 (cyclique sur 12)."""
        return ((self.start_month - 1 + self.nb_months - 1) % 12) + 1

    @property
    def end_month_display(self):
        return dict(self.MONTHS).get(self.end_month, '')

    @property
    def start_month_display(self):
        return dict(self.MONTHS).get(self.start_month, '')

    def __str__(self):
        return f"{self.class_group} — {self.academic_year} : {self.start_month_display} → {self.end_month_display} ({self.nb_months} mois)"


class HonoraireBudgetLine(models.Model):
    """Ligne de budget prévisionnel des honoraires pour une classe, sur une
    année académique — saisie par le chef de département (« Budget honoraires
    mensuels »). Le taux horaire n'est pas dupliqué ici : il est lu depuis
    HourlyRate (département + niveau de la classe + année) au moment du calcul,
    pour rester la seule source de vérité."""

    department = models.ForeignKey(
        'academic_structure.Department',
        on_delete=models.CASCADE,
        related_name='honoraire_budget_lines',
        verbose_name=_('Département'),
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear',
        on_delete=models.CASCADE,
        related_name='honoraire_budget_lines',
        verbose_name=_('Année académique'),
    )
    class_group = models.ForeignKey(
        'academic_structure.Class',
        on_delete=models.CASCADE,
        related_name='honoraire_budget_lines',
        verbose_name=_('Classe'),
    )
    vha = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        verbose_name=_('Volume horaire annuel budgété'),
    )
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_honoraire_budget_lines', db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'honoraire_budget_lines'
        verbose_name = _('Ligne de budget honoraires')
        verbose_name_plural = _('Lignes de budget honoraires')
        unique_together = ('department', 'academic_year', 'class_group')
        ordering = ['class_group__level__order', 'class_group__name']

    def __str__(self):
        return f"{self.class_group} — {self.academic_year} (budget honoraires)"

    def hourly_rate(self):
        """Taux horaire courant pour cette ligne, lu depuis HourlyRate
        (département + niveau de la classe + année) — None si non défini."""
        return HourlyRate.objects.filter(
            department=self.department,
            level=self.class_group.level,
            academic_year=self.academic_year,
        ).first()


class HonoraireBudgetMonth(models.Model):
    """Volume horaire budgété pour un mois donné d'une HonoraireBudgetLine.
    Les honoraires du mois (H_month) ne sont pas stockés — calculés à la
    volée : volume_heures × HonoraireBudgetLine.hourly_rate().rate_per_hour."""

    line = models.ForeignKey(
        HonoraireBudgetLine,
        on_delete=models.CASCADE,
        related_name='months',
        verbose_name=_('Ligne de budget'),
    )
    year = models.PositiveSmallIntegerField(verbose_name=_('Année civile du mois'))
    month = models.PositiveSmallIntegerField(
        choices=AcademicYearDistribution.MONTHS,
        verbose_name=_('Mois'),
    )
    volume_heures = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
        verbose_name=_('Volume horaire budgété'),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'honoraire_budget_months'
        verbose_name = _('Mois de budget honoraires')
        verbose_name_plural = _('Mois de budget honoraires')
        unique_together = ('line', 'year', 'month')
        ordering = ['year', 'month']

    def __str__(self):
        return f"{self.line} — {self.month}/{self.year} : {self.volume_heures}h"

    def honoraires(self):
        rate = self.line.hourly_rate()
        if not rate:
            return None
        return self.volume_heures * rate.rate_per_hour


class AccountingClosure(models.Model):
    """Clôture journalière de la comptabilité."""
    closure_date        = models.DateField(unique=True, verbose_name=_('Date de clôture'))
    academic_year       = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='closures', verbose_name=_('Année académique'),
    )
    nb_validated        = models.PositiveIntegerField(default=0, verbose_name=_('Inscriptions validées'))
    nb_pending          = models.PositiveIntegerField(default=0, verbose_name=_('En attente'))
    nb_rejected         = models.PositiveIntegerField(default=0, verbose_name=_('Rejetées'))
    nb_suspended        = models.PositiveIntegerField(default=0, verbose_name=_('Comptes suspendus'))
    total_collected     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Total encaissé (FCFA)'))
    total_installments  = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Mensualités encaissées (FCFA)'))
    total_remaining     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Total restant dû (FCFA)'))
    total_entrees       = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Total entrées de caisse (FCFA)'))
    total_sorties       = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Total sorties de caisse (FCFA)'))
    notes               = models.TextField(blank=True, verbose_name=_('Observations'))
    closed_by           = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='closures', db_constraint=False, verbose_name=_('Clôturé par'),
    )
    closed_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounting_closures'
        verbose_name = _('Clôture comptable')
        verbose_name_plural = _('Clôtures comptables')
        ordering = ['-closure_date']

    def __str__(self):
        return f"Clôture du {self.closure_date.strftime('%d/%m/%Y')} — {self.total_collected} FCFA"


class ClosureEmailConfig(models.Model):
    """Adresses e-mail destinataires du rapport de clôture journalière (singleton)."""
    recipients = models.TextField(
        verbose_name=_('Adresses e-mail (une par ligne)'),
        blank=True,
        help_text=_('Chaque ligne = une adresse e-mail qui recevra le rapport de clôture.'),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'accounting_closure_email_config'
        verbose_name = _('Config e-mail clôture')

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def get_recipients_list(self):
        return [e.strip() for e in self.recipients.splitlines() if e.strip()]

    def __str__(self):
        return "Config e-mail clôture"


class CaissePayment(models.Model):
    """Paiement enregistré à la caisse (inscription, scolarité, soutenance)."""

    TYPE_INSCRIPTION = 'INSCRIPTION'
    TYPE_SCOLARITE   = 'SCOLARITE'
    TYPE_SOUTENANCE  = 'SOUTENANCE'
    TYPE_CHOICES = [
        (TYPE_INSCRIPTION, _("Frais d'inscription")),
        (TYPE_SCOLARITE,   _('Frais de scolarité')),
        (TYPE_SOUTENANCE,  _('Frais de soutenance')),
    ]

    SOUTENANCE_NORMALE  = 'NORMALE'
    SOUTENANCE_SPECIALE = 'SPECIALE'
    SOUTENANCE_TYPE_CHOICES = [
        (SOUTENANCE_NORMALE,  _('Normale')),
        (SOUTENANCE_SPECIALE, _('Spéciale')),
    ]

    reference    = models.CharField(
        max_length=30, unique=True, editable=False,
        verbose_name=_('Référence reçu'),
    )
    student      = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE,
        related_name='caisse_payments', verbose_name=_('Étudiant'),
    )
    payment_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES,
        verbose_name=_('Type de frais'),
    )
    amount       = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name=_('Montant (FCFA)'),
    )
    payment_date  = models.DateField(verbose_name=_('Date de paiement'))
    payment_month = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name=_('Mois concerné'),
        help_text=_('Numéro du mois (1-12), uniquement pour les frais de scolarité'),
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='caisse_payments',
        verbose_name=_('Année académique'),
    )
    enrollment   = models.ForeignKey(
        'students.Enrollment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='caisse_payments',
        verbose_name=_('Inscription liée'),
    )
    payment_months = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name=_('Mois payés'),
        help_text=_('Liste de numéros de mois séparés par virgule, ex: 10,11,12,6'),
    )
    soutenance_type = models.CharField(
        max_length=10, choices=SOUTENANCE_TYPE_CHOICES, blank=True,
        verbose_name=_('Type de soutenance'),
        help_text=_("Uniquement pour les frais de soutenance : normale ou spéciale."),
    )
    notes        = models.TextField(blank=True, verbose_name=_('Observations'))
    created_by   = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caisse_payments_created', db_constraint=False,
        verbose_name=_('Enregistré par'),
    )
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'caisse_payments'
        verbose_name = _('Paiement caisse')
        verbose_name_plural = _('Paiements caisse')
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"{self.reference} — {self.student} — {self.amount} FCFA"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        """
        Génère une référence unique REC-{année}-{compteur}. Part de
        count()+1 (compact, sans trou dans le cas normal) mais vérifie
        l'existence et incrémente jusqu'à trouver un numéro libre — un simple
        count()+1 peut entrer en collision avec une référence déjà existante
        dès que la séquence a un trou (suppression, données reprises d'une
        autre base lors d'une migration, etc.), provoquant un IntegrityError
        sur la contrainte unique au moment du save().
        """
        from datetime import date
        year = date.today().year
        count = CaissePayment.objects.filter(created_at__year=year).count() + 1
        for _ in range(1000):
            ref = f"REC-{year}-{count:05d}"
            if not CaissePayment.objects.filter(reference=ref).exists():
                return ref
            count += 1
        # Filet de sécurité improbable : suffixe aléatoire pour garantir l'unicité
        import random
        return f"REC-{year}-{count:05d}-{random.randint(1000, 9999)}"

    MOIS_FR = ['', 'Janvier','Février','Mars','Avril','Mai','Juin',
               'Juillet','Août','Septembre','Octobre','Novembre','Décembre']

    def get_type_label(self):
        return dict(self.TYPE_CHOICES).get(self.payment_type, self.payment_type)

    def get_soutenance_type_label(self):
        return dict(self.SOUTENANCE_TYPE_CHOICES).get(self.soutenance_type, '')

    def get_month_label(self):
        if self.payment_month and 1 <= self.payment_month <= 12:
            return self.MOIS_FR[self.payment_month]
        return ''

    def get_months_labels(self):
        """Retourne la liste des noms de mois pour un paiement multi-mois."""
        labels = []
        for m in (self.payment_months or '').split(','):
            m = m.strip()
            if m.isdigit() and 1 <= int(m) <= 12:
                labels.append(self.MOIS_FR[int(m)])
        return labels


class PaymentProof(models.Model):
    """
    Preuve de paiement déposée par un candidat depuis le portail public
    d'admission (voir academic_core/apps/admissions) — le paiement lui-même se
    fait hors plateforme (Wave/Orange Money/carte/virement) ; le Caissier
    valide ce justificatif, ce qui déclenche la création du CaissePayment
    correspondant (voir accounting/services.py::finalize_enrollment_payment).
    """
    WAVE            = 'WAVE'
    ORANGE_MONEY    = 'ORANGE_MONEY'
    VISA            = 'VISA'
    VIREMENT        = 'VIREMENT'
    MOYEN_CHOICES = [
        (WAVE,         'Wave'),
        (ORANGE_MONEY, 'Orange Money'),
        (VISA,         'Carte bancaire (VISA)'),
        (VIREMENT,     'Virement bancaire'),
    ]

    STATUS_PENDING   = 'PENDING'
    STATUS_VALIDATED = 'VALIDATED'
    STATUS_REJECTED  = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING,   _('En attente')),
        (STATUS_VALIDATED, _('Validé')),
        (STATUS_REJECTED,  _('Rejeté')),
    ]

    enrollment = models.ForeignKey(
        'students.Enrollment', on_delete=models.CASCADE,
        related_name='payment_proofs', verbose_name=_('Inscription'),
    )
    moyen_paiement = models.CharField(
        max_length=15, choices=MOYEN_CHOICES, verbose_name=_('Moyen de paiement'),
    )
    montant_declare = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name=_('Montant déclaré (FCFA)'),
    )
    reference_paiement = models.CharField(
        max_length=100, blank=True, verbose_name=_('Référence de paiement'),
    )
    piece_justificative = models.FileField(
        upload_to='admissions/justificatifs/%Y/%m/',
        verbose_name=_('Reçu / capture d\'écran'),
    )
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Déposé le'))
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING,
        verbose_name=_('Statut'),
    )
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_proofs_reviewed', db_constraint=False,
        verbose_name=_('Traité par'),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Traité le'))
    motif_rejet = models.TextField(blank=True, verbose_name=_('Motif de rejet'))

    class Meta:
        db_table = 'payment_proofs'
        verbose_name = _('Preuve de paiement')
        verbose_name_plural = _('Preuves de paiement')
        ordering = ['-submitted_at']

    def __str__(self):
        return f"Justificatif {self.get_moyen_paiement_display()} — {self.enrollment.student} ({self.get_status_display()})"


class OnlinePaymentTransaction(models.Model):
    """
    Transaction de paiement en ligne initiée par un candidat depuis le
    portail public d'admission via Wave ou Orange Money (voir
    academic_structure.InstitutPaymentConfig et
    academic_core/apps/accounting/payment_gateway.py). Contrairement à
    PaymentProof (justificatif déposé manuellement, validé par le Caissier),
    une transaction en ligne est confirmée automatiquement par le webhook du
    fournisseur (voir admissions/views.py::wave_webhook_view /
    orange_money_webhook_view), qui appelle ensuite services.py::
    finalize_enrollment_payment — même logique de finalisation que la
    validation manuelle d'une preuve de paiement.

    Tenant-only (comme PaymentProof/CaissePayment) : vit dans la base de
    l'institut concerné, jamais dans 'default'.
    """
    PROVIDER_WAVE = 'WAVE'
    PROVIDER_ORANGE_MONEY = 'ORANGE_MONEY'
    PROVIDER_CHOICES = [
        (PROVIDER_WAVE, 'Wave'),
        (PROVIDER_ORANGE_MONEY, 'Orange Money'),
    ]

    STATUS_PENDING   = 'PENDING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED    = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_PENDING,   _('En attente')),
        (STATUS_COMPLETED, _('Confirmé')),
        (STATUS_FAILED,    _('Échoué / annulé')),
    ]

    enrollment = models.ForeignKey(
        'students.Enrollment', on_delete=models.CASCADE,
        related_name='online_payment_transactions', verbose_name=_('Inscription'),
    )
    provider = models.CharField(
        max_length=20, choices=PROVIDER_CHOICES, verbose_name=_('Fournisseur'),
    )
    invoice_token = models.CharField(
        max_length=100, unique=True, verbose_name=_('Jeton de la transaction'),
        help_text=_("Identifiant de session Wave (checkout session id) ou pay_token Orange Money."),
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_('Montant (FCFA)'))
    payment_method = models.CharField(
        max_length=30, blank=True, verbose_name=_('Moyen utilisé'),
        help_text=_("Détail renseigné par le fournisseur à la confirmation (ex. numéro de mobile money)."),
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    raw_response = models.TextField(
        blank=True, verbose_name=_('Réponse brute de l\'agrégateur'),
        help_text=_('Conservée à des fins de diagnostic/audit.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'online_payment_transactions'
        verbose_name = _('Transaction de paiement en ligne')
        verbose_name_plural = _('Transactions de paiement en ligne')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_provider_display()} {self.invoice_token} — {self.get_status_display()}"


class CaisseMovement(models.Model):
    """
    Entrée ou sortie de caisse (hors paiements étudiants, déjà couverts par
    CaissePayment) — alimente le Brouillard / État journalier et la clôture.

    Seul le Trésorier Général (ou un rôle de supervision globale : Admin,
    Administrateur d'institut, Contrôleur Interne) peut saisir un mouvement.
    Une SORTIE créée par le Trésorier Général vaut autorisation de décaisser :
    elle reste « en attente » (is_executed=False) tant que le Caissier (ou le
    Trésorier Général lui-même) n'a pas cliqué sur « Décaisser ». Une ENTRÉE
    est enregistrée directement (is_executed=True dès la création).
    """
    TYPE_ENTREE = 'ENTREE'
    TYPE_SORTIE = 'SORTIE'
    TYPE_CHOICES = [
        (TYPE_ENTREE, _('Entrée')),
        (TYPE_SORTIE, _('Sortie')),
    ]

    CAT_FOURNITURES_BUREAU   = 'FOURNITURES_BUREAU'
    CAT_CARBURANT            = 'CARBURANT'
    CAT_EAU                  = 'EAU'
    CAT_ELECTRICITE          = 'ELECTRICITE'
    CAT_TELEPHONE            = 'TELEPHONE'
    CAT_INTERNET             = 'INTERNET'
    CAT_LOYER                = 'LOYER'
    CAT_ENTRETIEN            = 'ENTRETIEN'
    CAT_ASSURANCE            = 'ASSURANCE'
    CAT_HONORAIRES           = 'HONORAIRES'
    CAT_PUBLICITE_COMM       = 'PUBLICITE_COMM'
    CAT_DEPLACEMENTS         = 'DEPLACEMENTS'
    CAT_HEBERGEMENT          = 'HEBERGEMENT'
    CAT_FRAIS_POSTAUX        = 'FRAIS_POSTAUX'
    CAT_GARDIENNAGE_SECURITE = 'GARDIENNAGE_SECURITE'
    CAT_RECEPTIONS           = 'RECEPTIONS'
    CAT_FRAIS_BANCAIRES      = 'FRAIS_BANCAIRES'
    CAT_SALAIRES             = 'SALAIRES'
    CAT_CHARGES_SOCIALES     = 'CHARGES_SOCIALES'
    CAT_FORMATION_PERSONNEL  = 'FORMATION_PERSONNEL'
    CAT_IMPOTS_TAXES         = 'IMPOTS_TAXES'
    CAT_INTERETS_BANCAIRES   = 'INTERETS_BANCAIRES'
    CAT_AUTRE                = 'AUTRE'
    CATEGORIE_CHOICES = [
        (CAT_FOURNITURES_BUREAU,   _('Fournitures de bureau')),
        (CAT_CARBURANT,            _('Carburant')),
        (CAT_EAU,                  _('Eau')),
        (CAT_ELECTRICITE,          _('Électricité')),
        (CAT_TELEPHONE,            _('Téléphone')),
        (CAT_INTERNET,             _('Internet')),
        (CAT_LOYER,                _('Loyer')),
        (CAT_ENTRETIEN,            _('Entretien et maintenance')),
        (CAT_ASSURANCE,            _('Assurance')),
        (CAT_HONORAIRES,           _('Honoraires')),
        (CAT_PUBLICITE_COMM,       _('Publicité et communication')),
        (CAT_DEPLACEMENTS,         _('Déplacements et missions')),
        (CAT_HEBERGEMENT,          _('Hébergement')),
        (CAT_FRAIS_POSTAUX,        _('Frais postaux')),
        (CAT_GARDIENNAGE_SECURITE, _('Gardiennage et sécurité')),
        (CAT_RECEPTIONS,           _('Réceptions')),
        (CAT_FRAIS_BANCAIRES,      _('Frais bancaires')),
        (CAT_SALAIRES,             _('Salaires')),
        (CAT_CHARGES_SOCIALES,     _('Charges sociales')),
        (CAT_FORMATION_PERSONNEL,  _('Formation du personnel')),
        (CAT_IMPOTS_TAXES,         _('Impôts et taxes')),
        (CAT_INTERETS_BANCAIRES,   _('Intérêts bancaires')),
        (CAT_AUTRE,                _('Autre')),
    ]

    # Compte SYSCOHADA associé (par matricule) suggéré automatiquement pour
    # chaque catégorie de dépense — plusieurs catégories peuvent partager le
    # même compte (ex : Fournitures/Carburant/Eau → 604).
    CATEGORIE_COMPTE_MATRICULE = {
        CAT_FOURNITURES_BUREAU:   '60410000',
        CAT_CARBURANT:            '60410000',
        CAT_EAU:                  '60410000',
        CAT_ELECTRICITE:          '62810000',
        CAT_TELEPHONE:            '62810000',
        CAT_INTERNET:             '62810000',
        CAT_LOYER:                '62200000',
        CAT_ENTRETIEN:            '62410000',
        CAT_ASSURANCE:            '62500000',
        CAT_HONORAIRES:           '63200000',
        CAT_PUBLICITE_COMM:       '62700000',
        CAT_DEPLACEMENTS:         '63300000',
        CAT_HEBERGEMENT:          '63300000',
        CAT_FRAIS_POSTAUX:        '63400000',
        CAT_GARDIENNAGE_SECURITE: '63500000',
        CAT_RECEPTIONS:           '63600000',
        CAT_FRAIS_BANCAIRES:      '63100000',
        CAT_SALAIRES:             '66100000',
        CAT_CHARGES_SOCIALES:     '66400000',
        CAT_FORMATION_PERSONNEL:  '66600000',
        CAT_IMPOTS_TAXES:         '64000000',
        CAT_INTERETS_BANCAIRES:   '67000000',
        CAT_AUTRE:                '65800000',
    }

    movement_type = models.CharField(max_length=10, choices=TYPE_CHOICES, verbose_name=_('Type'))
    amount        = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_('Montant (FCFA)'))
    movement_date = models.DateField(verbose_name=_('Date'))
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='caisse_movements',
        verbose_name=_('Année académique'),
    )
    motif         = models.CharField(max_length=255, verbose_name=_('Motif'))
    beneficiaire  = models.CharField(max_length=200, blank=True, verbose_name=_('Bénéficiaire / Fournisseur'))
    # Direction (centre de coût — voir accounts.Direction, déjà la dimension
    # obligatoire de LigneBudgetaire) à laquelle ce mouvement est imputé : le
    # bénéficiaire d'une sortie de caisse relève toujours d'une direction, et
    # donc du budget de cette direction — voir accounting/budget_views.py::
    # suivi_budget_directions_view pour le rapprochement quotidien budget/caisse
    # par direction. Optionnel (SET_NULL) pour ne pas casser les mouvements déjà
    # saisis avant l'introduction de ce champ.
    direction     = models.ForeignKey(
        'accounts.Direction', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caisse_movements', db_constraint=False,
        verbose_name=_('Direction (centre de coût)'),
    )
    categorie     = models.CharField(max_length=20, choices=CATEGORIE_CHOICES, blank=True, verbose_name=_('Catégorie de dépense'))
    piece_justificative = models.CharField(max_length=100, blank=True, verbose_name=_('Pièce justificative (référence)'))
    notes         = models.TextField(blank=True, verbose_name=_('Observations'))

    # Compte de caisse/banque sur lequel l'opération est imputée (« N° compte »
    # / « Nom compte » du modèle de référence) — un compte de nature TRESORERIE.
    compte_caisse   = models.ForeignKey(
        'CompteComptable', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mouvements_caisse', db_constraint=False,
        verbose_name=_('N° compte (caisse / banque)'),
    )
    # Compte associé (contrepartie SYSCOHADA) — obligatoire à la saisie ; son
    # choix dépend de la nature de l'opération (Entrée → compte de tiers/produit,
    # Sortie → compte de charge selon la catégorie de dépense).
    compte_associe  = models.ForeignKey(
        'CompteComptable', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mouvements_associes', db_constraint=False,
        verbose_name=_('Compte associé'),
    )
    justificatif    = models.FileField(
        upload_to='caisse_justificatifs/%Y/%m/', null=True, blank=True,
        verbose_name=_('Justificatif (pièce scannée)'),
    )

    created_by    = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caisse_movements_crees', db_constraint=False,
        verbose_name=_('Saisi par (Trésorier Général)'),
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    # Décaissement effectif (pertinent uniquement pour une SORTIE — une ENTRÉE
    # est exécutée directement à la création).
    is_executed   = models.BooleanField(default=False, verbose_name=_('Exécuté (décaissé)'))
    executed_by   = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caisse_movements_executes', db_constraint=False,
        verbose_name=_('Décaissé par (Caissier)'),
    )
    executed_at   = models.DateTimeField(null=True, blank=True, verbose_name=_('Décaissé le'))

    class Meta:
        db_table = 'caisse_movements'
        verbose_name = _('Mouvement de caisse')
        verbose_name_plural = _('Mouvements de caisse')
        ordering = ['-movement_date', '-created_at']

    def __str__(self):
        return f"{self.get_movement_type_display()} — {self.amount} FCFA — {self.motif}"


class CompteComptable(models.Model):
    """
    Compte comptable (plan comptable SYSCOHADA révisé) — ex. « 57110000 —
    CAISSE PRINCIPALE ISI », « 60410000 — Achats de fournitures ». Défini
    exclusivement par le Trésorier Général ; sert de compte de caisse/banque
    (nature TRESORERIE) ou de compte associé/contrepartie (TIERS, PRODUIT,
    CHARGE) sur les mouvements de caisse (Entrée & Sortie Caisse).
    """
    CLASSE_1 = '1'
    CLASSE_2 = '2'
    CLASSE_3 = '3'
    CLASSE_4 = '4'
    CLASSE_5 = '5'
    CLASSE_6 = '6'
    CLASSE_7 = '7'
    CLASSE_8 = '8'
    CLASSE_CHOICES = [
        (CLASSE_1, _('Classe 1 — Comptes de ressources durables')),
        (CLASSE_2, _('Classe 2 — Comptes d’actif immobilisé')),
        (CLASSE_3, _('Classe 3 — Comptes de stocks')),
        (CLASSE_4, _('Classe 4 — Comptes de tiers')),
        (CLASSE_5, _('Classe 5 — Comptes de trésorerie')),
        (CLASSE_6, _('Classe 6 — Comptes de charges')),
        (CLASSE_7, _('Classe 7 — Comptes de produits')),
        (CLASSE_8, _('Classe 8 — Autres charges / produits (HAO)')),
    ]

    NATURE_TRESORERIE = 'TRESORERIE'
    NATURE_TIERS       = 'TIERS'
    NATURE_PRODUIT     = 'PRODUIT'
    NATURE_CHARGE      = 'CHARGE'
    NATURE_CHOICES = [
        (NATURE_TRESORERIE, _('Trésorerie (caisse / banque)')),
        (NATURE_TIERS,       _('Tiers (clients, fournisseurs…)')),
        (NATURE_PRODUIT,     _('Produit (recette)')),
        (NATURE_CHARGE,      _('Charge (dépense)')),
    ]

    SENS_ENTREE = 'ENTREE'
    SENS_SORTIE = 'SORTIE'
    SENS_MIXTE  = 'MIXTE'
    SENS_CHOICES = [
        (SENS_ENTREE, _('Entrée uniquement')),
        (SENS_SORTIE, _('Sortie uniquement')),
        (SENS_MIXTE,  _('Entrée et Sortie')),
    ]

    matricule  = models.CharField(max_length=30, unique=True, verbose_name=_('Matricule'))
    libelle    = models.CharField(max_length=200, verbose_name=_('Libellé'))
    classe     = models.CharField(max_length=1, choices=CLASSE_CHOICES, default=CLASSE_5, verbose_name=_('Classe SYSCOHADA'))
    nature     = models.CharField(max_length=12, choices=NATURE_CHOICES, default=NATURE_TRESORERIE, verbose_name=_('Nature du compte'))
    sens       = models.CharField(max_length=6, choices=SENS_CHOICES, default=SENS_MIXTE, verbose_name=_('Sens (nature de l’opération)'))
    categorie  = models.CharField(
        max_length=20, choices=CaisseMovement.CATEGORIE_CHOICES, blank=True,
        verbose_name=_('Catégorie de dépense associée'),
        help_text=_('Suggestion automatique de ce compte lorsque cette catégorie de dépense est choisie sur une Sortie.'),
    )
    is_active  = models.BooleanField(default=True, verbose_name=_('Actif'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='comptes_comptables_crees', db_constraint=False,
        verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'comptes_comptables'
        verbose_name = _('Compte comptable')
        verbose_name_plural = _('Comptes comptables')
        ordering = ['matricule']

    def __str__(self):
        return f"{self.matricule} — {self.libelle}"


# ─────────────────────────────────────────────────────────────────────────────
# Pilotage et Suivi Budgétaire — Contrôleur Interne / Administrateur d'institut /
# Directeur Administratif et Financier (ADMIN_DAF).
#
# L'exercice budgétaire réutilise AcademicYear (déjà scopé par institut) plutôt
# qu'un nouveau calendrier fiscal séparé ; le centre de coût réutilise
# accounts.Direction (déjà utilisé par DemandeDepense) plutôt qu'une entité
# générique dédiée. Le suivi de l'exécuté se branche sur DemandeDepense (voir
# son champ ligne_budgetaire ci-dessous et le signal dans signals.py) : aucune
# duplication du mouvement de caisse existant.
# ─────────────────────────────────────────────────────────────────────────────

class SourceFinancement(models.Model):
    """Origine des fonds d'une ligne budgétaire (frais de scolarité, subvention…)."""
    TYPE_ETAT            = 'ETAT'
    TYPE_FRAIS_SCOLARITE = 'FRAIS_SCOLARITE'
    TYPE_SUBVENTION      = 'SUBVENTION'
    TYPE_PARTENARIAT     = 'PARTENARIAT'
    TYPE_DON             = 'DON'
    TYPE_AUTRE           = 'AUTRE'
    TYPE_CHOICES = [
        (TYPE_ETAT,            _('État')),
        (TYPE_FRAIS_SCOLARITE, _('Frais de scolarité')),
        (TYPE_SUBVENTION,      _('Subvention')),
        (TYPE_PARTENARIAT,     _('Partenariat')),
        (TYPE_DON,             _('Don')),
        (TYPE_AUTRE,           _('Autre')),
    ]

    code        = models.SlugField(max_length=30, unique=True, verbose_name=_('Code'))
    libelle     = models.CharField(max_length=200, verbose_name=_('Libellé'))
    type_source = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name=_('Type de source'))
    is_active   = models.BooleanField(default=True, verbose_name=_('Active'))
    created_by  = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sources_financement_creees', db_constraint=False,
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'budget_sources_financement'
        verbose_name = _('Source de financement')
        verbose_name_plural = _('Sources de financement')
        ordering = ['libelle']

    def __str__(self):
        return self.libelle


class LigneBudgetaire(models.Model):
    """
    Enveloppe budgétaire pour un (exercice, Direction, compte comptable, source
    de financement) donné. montant_engage/montant_execute ne sont jamais
    modifiés directement (editable=False) — ils sont maintenus respectivement
    par budget_services.EngagementService (réservation/libération à la
    validation/annulation d'un engagement) et par le signal de décaissement de
    DemandeDepense (voir signals.py).
    """
    NATURE_FONCTIONNEMENT = 'FONCTIONNEMENT'
    NATURE_INVESTISSEMENT = 'INVESTISSEMENT'
    NATURE_CHOICES = [
        (NATURE_FONCTIONNEMENT, _('Fonctionnement')),
        (NATURE_INVESTISSEMENT, _('Investissement')),
    ]

    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.PROTECT,
        related_name='lignes_budgetaires', db_constraint=False, verbose_name=_('Exercice (année académique)'),
    )
    direction = models.ForeignKey(
        'accounts.Direction', on_delete=models.PROTECT,
        related_name='lignes_budgetaires', db_constraint=False, verbose_name=_('Direction (centre de coût)'),
    )
    compte_comptable = models.ForeignKey(
        CompteComptable, on_delete=models.PROTECT,
        related_name='lignes_budgetaires', verbose_name=_('Compte comptable'),
    )
    source_financement = models.ForeignKey(
        SourceFinancement, on_delete=models.PROTECT,
        related_name='lignes_budgetaires', verbose_name=_('Source de financement'),
    )
    nature = models.CharField(max_length=20, choices=NATURE_CHOICES, default=NATURE_FONCTIONNEMENT, verbose_name=_('Nature'))

    # Dimensions de tag optionnelles vers le Plan Stratégique de Développement
    # (n'affectent aucun calcul de montant — purement déclaratif, comme dans
    # le projet de référence appSuiviBudgetaire).
    axe_strategique = models.ForeignKey(
        'strategic_plan.AxeStrategique', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lignes_budgetaires', verbose_name=_('Axe stratégique'),
    )
    projet = models.ForeignKey(
        'strategic_plan.Projet', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lignes_budgetaires', verbose_name=_('Projet'),
    )

    montant_initial = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Montant initial (FCFA)'))
    montant_revise   = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name=_('Montant révisé (FCFA)'))
    montant_engage   = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False, verbose_name=_('Montant engagé (FCFA)'))
    montant_execute  = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False, verbose_name=_('Montant exécuté (FCFA)'))

    notes = models.TextField(blank=True, verbose_name=_('Notes'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lignes_budgetaires_creees', db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'budget_lignes'
        verbose_name = _('Ligne budgétaire')
        verbose_name_plural = _('Lignes budgétaires')
        ordering = ['-academic_year__start_date', 'direction']
        unique_together = ('academic_year', 'direction', 'compte_comptable', 'source_financement')

    def save(self, *args, **kwargs):
        # Le montant révisé démarre égal au montant initial ; il n'est ensuite
        # modifié que par un BudgetRectificatif validé.
        if not self.montant_revise and self.montant_initial:
            self.montant_revise = self.montant_initial
        super().save(*args, **kwargs)

    @property
    def montant_disponible(self):
        """Ce qu'il reste à engager sur cette ligne."""
        return self.montant_revise - self.montant_engage

    @property
    def taux_execution(self):
        if not self.montant_revise:
            return Decimal('0')
        return self.montant_execute / self.montant_revise

    @property
    def statut_kpi(self):
        """'vert' / 'orange' / 'rouge' selon les seuils de ComptabiliteConfig."""
        cfg = ComptabiliteConfig.get()
        taux = self.taux_execution
        if taux >= cfg.budget_seuil_rouge:
            return 'rouge'
        if taux >= cfg.budget_seuil_orange:
            return 'orange'
        return 'vert'

    def __str__(self):
        return f"{self.direction} — {self.compte_comptable} ({self.academic_year})"


class BudgetRectificatif(models.Model):
    """Demande d'ajustement (positif ou négatif) du montant révisé d'une ligne budgétaire."""
    STATUT_DEMANDE = 'DEMANDE'
    STATUT_VALIDE  = 'VALIDE'
    STATUT_REJETE  = 'REJETE'
    STATUT_CHOICES = [
        (STATUT_DEMANDE, _('Demandé')),
        (STATUT_VALIDE,  _('Validé')),
        (STATUT_REJETE,  _('Rejeté')),
    ]

    ligne_budgetaire = models.ForeignKey(
        LigneBudgetaire, on_delete=models.CASCADE, related_name='rectificatifs',
        verbose_name=_('Ligne budgétaire'),
    )
    montant_ajustement = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name=_("Montant d'ajustement (FCFA)"),
        help_text=_('Positif pour augmenter le budget, négatif pour le réduire.'),
    )
    motif = models.TextField(verbose_name=_('Motif'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_DEMANDE, verbose_name=_('Statut'))

    demande_par = models.ForeignKey(
        'accounts.User', on_delete=models.PROTECT, related_name='rectificatifs_demandes',
        db_constraint=False, verbose_name=_('Demandé par'),
    )
    demande_at = models.DateTimeField(auto_now_add=True)

    valide_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rectificatifs_valides', db_constraint=False, verbose_name=_('Validé par'),
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, verbose_name=_('Motif du rejet'))

    class Meta:
        db_table = 'budget_rectificatifs'
        verbose_name = _('Budget rectificatif')
        verbose_name_plural = _('Budgets rectificatifs')
        ordering = ['-demande_at']

    def __str__(self):
        return f"Rectificatif {self.ligne_budgetaire} ({self.montant_ajustement:+})"


class EngagementBudgetaire(models.Model):
    """
    Réservation d'une partie du budget disponible d'une ligne, avant dépense
    effective. Machine à états gérée par budget_services.EngagementService :
    BROUILLON -> SOUMIS -> VALIDE (réserve montant_engage) ou REJETE ;
    VALIDE -> ANNULE (libère montant_engage).
    """
    STATUT_BROUILLON = 'BROUILLON'
    STATUT_SOUMIS    = 'SOUMIS'
    STATUT_VALIDE    = 'VALIDE'
    STATUT_REJETE    = 'REJETE'
    STATUT_ANNULE    = 'ANNULE'
    STATUT_CHOICES = [
        (STATUT_BROUILLON, _('Brouillon')),
        (STATUT_SOUMIS,    _('Soumis')),
        (STATUT_VALIDE,    _('Validé')),
        (STATUT_REJETE,    _('Rejeté')),
        (STATUT_ANNULE,    _('Annulé')),
    ]

    ligne_budgetaire = models.ForeignKey(
        LigneBudgetaire, on_delete=models.PROTECT, related_name='engagements',
        verbose_name=_('Ligne budgétaire'),
    )
    reference = models.CharField(max_length=50, unique=True, blank=True, verbose_name=_('Référence'))
    objet = models.CharField(max_length=255, verbose_name=_('Objet'))
    montant = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_('Montant (FCFA)'))
    date_engagement = models.DateField(default=timezone.now, verbose_name=_("Date d'engagement"))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_BROUILLON, verbose_name=_('Statut'))

    demandeur = models.ForeignKey(
        'accounts.User', on_delete=models.PROTECT, related_name='engagements_budgetaires_demandes',
        db_constraint=False, verbose_name=_('Demandeur'),
    )
    piece_justificative = models.FileField(
        upload_to='budget/engagements/%Y/%m/', null=True, blank=True, verbose_name=_('Pièce justificative'),
    )

    valide_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='engagements_budgetaires_valides', db_constraint=False, verbose_name=_('Validé par'),
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, verbose_name=_('Motif du rejet'))

    class Meta:
        db_table = 'budget_engagements'
        verbose_name = _('Engagement budgétaire')
        verbose_name_plural = _('Engagements budgétaires')
        ordering = ['-date_engagement']

    def __str__(self):
        return f"{self.reference} ({self.montant})"

    def save(self, *args, **kwargs):
        # Même schéma que DemandeDepense.reference : insérer d'abord pour
        # obtenir un pk, puis générer la référence lisible (ENG-{année}-{pk}).
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.reference:
            annee = self.date_engagement.year if self.date_engagement else timezone.now().year
            self.reference = f"ENG-{annee}-{str(self.pk).zfill(5)}"
            super().save(update_fields=['reference'])


class DemandeDepense(models.Model):
    """
    Demande de dépense formulée par une Direction. Workflow :
    Direction (soumission) → Trésorier Général (validation ou rejet) →
    Caissier (décaissement) → génère automatiquement le mouvement de
    caisse correspondant (Sortie) dans Entrée & Sortie Caisse.
    """
    STATUT_EN_ATTENTE = 'EN_ATTENTE'
    STATUT_VALIDEE    = 'VALIDEE'
    STATUT_REJETEE    = 'REJETEE'
    STATUT_DECAISSEE  = 'DECAISSEE'
    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, _('En attente de validation')),
        (STATUT_VALIDEE,    _('Validée — en attente de décaissement')),
        (STATUT_REJETEE,    _('Rejetée')),
        (STATUT_DECAISSEE,  _('Décaissée')),
    ]

    reference = models.CharField(max_length=10, unique=True, blank=True, verbose_name=_('N° de référence'))
    direction = models.ForeignKey(
        'accounts.Direction', on_delete=models.PROTECT, related_name='demandes_depense',
        db_constraint=False, verbose_name=_('Direction'),
    )

    objet     = models.CharField(max_length=255, verbose_name=_('Objet de la demande'))
    categorie = models.CharField(max_length=20, choices=CaisseMovement.CATEGORIE_CHOICES, blank=True, verbose_name=_('Catégorie de dépense'))
    motif     = models.TextField(verbose_name=_('Motif / Description de la dépense'))
    montant   = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_('Montant (FCFA)'))

    ordonnateur  = models.CharField(max_length=150, blank=True, verbose_name=_('Ordonnateur'))
    fournisseur  = models.CharField(max_length=200, blank=True, verbose_name=_('Fournisseur'))
    beneficiaire = models.CharField(max_length=200, blank=True, verbose_name=_('Bénéficiaire'))

    piece_justificative = models.CharField(max_length=100, blank=True, verbose_name=_('Pièce justificative (référence)'))
    justificatif = models.FileField(upload_to='demandes_depense/%Y/%m/', null=True, blank=True, verbose_name=_('Justificatif'))

    statut = models.CharField(max_length=12, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE, verbose_name=_('Statut'))

    requested_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_depense_soumises', db_constraint=False,
        verbose_name=_('Soumise par'),
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    validated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_depense_validees', db_constraint=False,
        verbose_name=_('Validée par (Trésorier Général)'),
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, verbose_name=_('Motif du rejet'))

    decaisse_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_depense_decaissees', db_constraint=False,
        verbose_name=_('Décaissée par (Caissier)'),
    )
    decaisse_at = models.DateTimeField(null=True, blank=True)

    caisse_movement = models.OneToOneField(
        CaisseMovement, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demande_depense', db_constraint=False,
        verbose_name=_('Mouvement de caisse généré'),
    )

    # Rattachement optionnel à une ligne budgétaire (Pilotage et Suivi
    # Budgétaire) : quand la demande passe à DECAISSEE, un signal (voir
    # signals.py) recalcule ligne_budgetaire.montant_execute automatiquement.
    ligne_budgetaire = models.ForeignKey(
        'LigneBudgetaire', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_depense', verbose_name=_('Ligne budgétaire'),
    )

    class Meta:
        db_table = 'demandes_depense'
        verbose_name = _('Demande de dépense')
        verbose_name_plural = _('Demandes de dépense')
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.reference} — {self.objet}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.reference:
            self.reference = str(self.pk).zfill(10)
            super().save(update_fields=['reference'])
