from django.db import models
from django.utils.translation import gettext_lazy as _
from academic_core.apps.accounts.models import User
from academic_core.apps.academic_structure.models import Class, AcademicYear
from .countries import COUNTRY_NATIONALITY, COUNTRY_CHOICES, AUTRE as COUNTRY_AUTRE


class Student(models.Model):
    GENDER_M = 'M'
    GENDER_F = 'F'
    GENDER_CHOICES = [(GENDER_M, _('Masculin')), (GENDER_F, _('Féminin'))]

    CLASS_REP_NONE         = ''
    CLASS_REP_RESPONSABLE  = 'RESPONSABLE'
    CLASS_REP_ADJOINT      = 'ADJOINT'
    CLASS_REP_CHOICES = [
        (CLASS_REP_NONE,        _('Aucun')),
        (CLASS_REP_RESPONSABLE, _('Responsable de classe')),
        (CLASS_REP_ADJOINT,     _('Adjoint du responsable de classe')),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='student_profile'
    )
    matricule        = models.CharField(max_length=30, unique=True, verbose_name=_('Matricule'))
    date_of_birth    = models.DateField(null=True, blank=True, verbose_name=_('Date de naissance'))
    place_of_birth   = models.CharField(max_length=200, blank=True, verbose_name=_('Lieu de naissance'))
    country_of_birth = models.CharField(
        max_length=100, choices=COUNTRY_CHOICES, blank=True, verbose_name=_('Pays de naissance'),
    )
    nationality      = models.CharField(
        max_length=100, blank=True, verbose_name=_('Nationalité'),
        help_text=_("Déduite automatiquement du pays de naissance (modifiable si « Autre pays »)."),
    )
    gender           = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, verbose_name=_('Genre'))
    phone            = models.CharField(max_length=20, blank=True, verbose_name=_('Téléphone'))
    address          = models.TextField(blank=True, verbose_name=_('Adresse'))
    current_class    = models.ForeignKey(
        Class, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='class_students', verbose_name=_('Classe')
    )
    class_rep_role   = models.CharField(
        max_length=15, choices=CLASS_REP_CHOICES, blank=True, default=CLASS_REP_NONE,
        verbose_name=_('Rôle de représentation de classe'),
        help_text=_("Un étudiant nommé responsable ou adjoint de sa classe peut consulter et valider le cahier de texte de cette classe, en plus de ses droits d'étudiant."),
    )
    class_rep_since  = models.DateTimeField(null=True, blank=True, verbose_name=_('Nommé le'))
    class_rep_by     = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='class_reps_appointed', db_constraint=False,
        verbose_name=_('Nommé par'),
    )
    # Tuteur / personne à contacter
    guardian_first_name = models.CharField(max_length=100, blank=True, verbose_name=_('Prénom tuteur'))
    guardian_last_name  = models.CharField(max_length=100, blank=True, verbose_name=_('Nom tuteur'))
    guardian_phone      = models.CharField(max_length=20, blank=True, verbose_name=_('Téléphone tuteur'))
    guardian_address    = models.TextField(blank=True, verbose_name=_('Adresse tuteur'))
    guardian_email      = models.EmailField(blank=True, verbose_name=_('Email tuteur'))
    # Compatibilité ascendante
    guardian_name       = models.CharField(max_length=200, blank=True, verbose_name=_('Tuteur (ancien)'))
    photo               = models.ImageField(
        upload_to='students/photos/', null=True, blank=True,
        verbose_name=_('Photo')
    )
    payment_suspended   = models.BooleanField(default=False, verbose_name=_('Suspendu pour impayé'))
    suspension_date     = models.DateField(null=True, blank=True, verbose_name=_('Date de suspension'))
    # Bourse
    is_boursier         = models.BooleanField(default=False, verbose_name=_('Étudiant boursier'))
    partenaire_bourse   = models.ForeignKey(
        'accounting.PartenaireBourse', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='etudiants_boursiers', verbose_name=_('Partenaire de bourse'),
        db_constraint=False,
    )
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'students'
        verbose_name = _('Étudiant')
        verbose_name_plural = _('Étudiants')

    def save(self, *args, **kwargs):
        # Nationalité dérivée automatiquement du pays de naissance — sauf
        # « Autre pays », où elle reste une saisie manuelle (aucun gentilé
        # à déduire pour un pays hors liste).
        if self.country_of_birth and self.country_of_birth != COUNTRY_AUTRE:
            self.nationality = COUNTRY_NATIONALITY.get(self.country_of_birth, self.nationality)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.matricule} - {self.user.get_full_name()}"

    @property
    def full_name(self):
        return self.user.get_full_name()

    @property
    def email(self):
        return self.user.email

    def current_enrollment(self):
        return self.enrollments.filter(
            academic_year__is_current=True
        ).select_related('class_group', 'academic_year').first()

    def enrollment_for_year(self, academic_year):
        """Inscription validée de cet étudiant pour une année académique
        donnée (courante ou passée) — support du sélecteur d'année étudiant."""
        if academic_year is None:
            return None
        return self.enrollments.filter(
            academic_year=academic_year, status=Enrollment.STATUS_VALIDATED
        ).select_related('class_group__program', 'academic_year').first()


class Enrollment(models.Model):
    STATUS_PENDING        = 'PENDING'
    STATUS_PENDING_CAISSE = 'PENDING_CAISSE'
    STATUS_VALIDATED      = 'VALIDATED'
    STATUS_REJECTED       = 'REJECTED'
    STATUS_ABANDONED      = 'ABANDONED'
    STATUS_SUSPENDED      = 'SUSPENDED'
    STATUS_CHOICES        = [
        (STATUS_PENDING,        _('En attente')),
        (STATUS_PENDING_CAISSE, _('En attente caisse')),
        (STATUS_VALIDATED,      _('Validée')),
        (STATUS_REJECTED,       _('Rejetée')),
        (STATUS_ABANDONED,      _('Abandon')),
        (STATUS_SUSPENDED,      _("Suspension d'inscription")),
    ]
    TYPE_NEW             = 'NEW'
    TYPE_REINSCRIPTION   = 'REINSCRIPTION'
    TYPE_CHANGE_FILIERE  = 'CHANGE_FILIERE'
    TYPE_CHOICES        = [
        (TYPE_NEW,           _('Nouvelle inscription')),
        (TYPE_REINSCRIPTION, _('Réinscription')),
        (TYPE_CHANGE_FILIERE, _('Changement de filière')),
    ]

    student       = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='enrollments')
    class_group   = models.ForeignKey(
        Class, on_delete=models.CASCADE, related_name='students',
        verbose_name=_('Classe'),
    )
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='enrollments')
    enrollment_date = models.DateField(auto_now_add=True)
    is_active     = models.BooleanField(default=True)

    # Validation & paiement
    status            = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name=_('Statut'))
    enrollment_type   = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_NEW, verbose_name=_("Type d'inscription"))
    previous_class    = models.ForeignKey(
        Class, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='past_students', verbose_name=_('Classe précédente'),
    )
    total_fees          = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais totaux (FCFA)'))
    frais_generaux      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais généraux (FCFA)'))
    payment_amount      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Montant versé (FCFA)'))
    payment_date        = models.DateField(null=True, blank=True, verbose_name=_('Date de paiement'))
    payment_reference   = models.CharField(max_length=100, blank=True, verbose_name=_('Référence paiement'))
    monthly_installment = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_('Versement mensuel (FCFA)'),
        help_text=_('Montant fixe à verser chaque mois pour solder le restant dû'),
    )
    # Frais annexes (pré-remplis depuis FraisMensuelClasse à la création de la
    # classe, modifiables par inscription) — informatifs, non sommés dans le
    # montant à payer à l'inscription.
    frais_tenue               = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais de tenue (FCFA)'))
    frais_assurance           = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_("Frais d'assurance (FCFA)"))
    frais_amea                = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais Amicale (FCFA)'))
    frais_bibliotheque        = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais Bibliothèque (FCFA)'))
    frais_soutenance          = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais de soutenance normal (FCFA)'))
    frais_soutenance_speciale = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Frais de soutenance spéciale (FCFA)'))
    # Bourse : pourcentage du montant global que l'étudiant boursier doit payer
    bourse_pourcentage        = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name=_('Pourcentage à payer (boursier)'))
    # Bourse : suivi de la régularisation du solde (part du partenaire) par le
    # Trésorier Général — échéance fixée au cas par cas pour chaque étudiant.
    bourse_deadline             = models.DateField(null=True, blank=True, verbose_name=_('Échéance de régularisation (partenaire)'))
    bourse_regularized          = models.BooleanField(default=False, verbose_name=_('Régularisé'))
    bourse_regularized_date     = models.DateField(null=True, blank=True, verbose_name=_('Date de régularisation'))
    bourse_regularized_amount   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Montant régularisé (FCFA)'))
    bourse_regularized_by       = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bourse_regularisations', db_constraint=False,
        verbose_name=_('Régularisé par'),
    )
    bourse_regularisation_notes = models.TextField(blank=True, verbose_name=_('Observations (régularisation)'))
    # Mois payés en avance : CSV de tokens "mois" ou "mois:montant" (ex: "9,10:75000,11")
    advance_months    = models.CharField(max_length=300, blank=True, default='',
                                         verbose_name=_('Mois payés en avance'))
    validated_by      = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validated_enrollments', db_constraint=False,
        verbose_name=_('Validé par'),
    )
    validated_at      = models.DateTimeField(null=True, blank=True, verbose_name=_('Date de validation'))
    notes             = models.TextField(blank=True, verbose_name=_('Observations'))

    # Abandon / Suspension d'inscription
    status_changed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date d'abandon/suspension"))
    status_changed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='status_changed_enrollments', db_constraint=False,
        verbose_name=_('Enregistré par'),
    )
    status_reason     = models.TextField(blank=True, verbose_name=_("Motif d'abandon/suspension"))
    # Crédit reporté (frais + mensualités déjà payés) d'une inscription suspendue,
    # automatiquement pris en compte lors d'une réinscription ultérieure.
    credit_report     = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name=_('Crédit reporté (FCFA)'),
        help_text=_("Montant déjà payé lors d'une inscription suspendue, reporté sur cette réinscription."),
    )

    class Meta:
        db_table = 'enrollments'
        verbose_name = _('Inscription')
        verbose_name_plural = _('Inscriptions')
        ordering = ['-enrollment_date']

    def __str__(self):
        return f"{self.student} → {self.class_group} ({self.academic_year}) [{self.get_status_display()}]"

    @property
    def net_fees(self):
        """Net à payer — égal aux frais totaux (les frais généraux ne sont plus déduits)."""
        return self.total_fees

    @property
    def remaining_amount(self):
        """Restant dû = frais nets - montant versé."""
        if self.net_fees is None:
            return None
        return max(self.net_fees - (self.payment_amount or 0), 0)

    @property
    def bourse_montant_etudiant(self):
        """
        Boursier uniquement : montant total à payer par l'étudiant (Montant
        global × pourcentage de bourse), tel que défini lors de la validation
        d'inscription — référence fixe, indépendante de ce qui a déjà été
        effectivement encaissé (payment_amount).
        """
        from decimal import Decimal
        if not (self.student_id and self.student.is_boursier):
            return None
        if self.total_fees is None or self.bourse_pourcentage is None:
            return None
        return self.total_fees * self.bourse_pourcentage / Decimal('100')

    @property
    def bourse_montant_a_recouvrer(self):
        """
        Boursier uniquement : part du montant global restant à recouvrer
        auprès du partenaire = Montant global − Montant à payer par
        l'étudiant (bourse_montant_etudiant).
        """
        from decimal import Decimal
        montant_etudiant = self.bourse_montant_etudiant
        if montant_etudiant is None or self.total_fees is None:
            return None
        return max(self.total_fees - montant_etudiant, Decimal('0'))

    @property
    def bourse_remaining_amount(self):
        """
        Boursier uniquement : solde restant dû par l'étudiant = montant à sa
        charge (bourse_montant_etudiant) − montant déjà versé (payment_amount).
        À utiliser à la place de `remaining_amount` (basé sur le montant
        global) pour tout ce qui concerne le reste à payer par un boursier.
        """
        from decimal import Decimal
        montant = self.bourse_montant_etudiant
        if montant is None:
            return None
        return max(montant - (self.payment_amount or Decimal('0')), Decimal('0'))

    @property
    def is_l3_m2(self):
        """Licence 3 / Master 2 uniquement : seuls niveaux concernés par les
        frais de soutenance (cf. FraisMensuelClasse.frais_soutenance*)."""
        level = getattr(self.class_group, 'level', None)
        return bool(level and level.name in ('Licence 3', 'Master 2'))

    def get_frais_soutenance(self, speciale=False):
        """Montant effectif des frais de soutenance (normal ou spéciale) :
        valeur propre à cette inscription si renseignée, sinon repli sur la
        configuration de la classe (FraisMensuelClasse)."""
        field = 'frais_soutenance_speciale' if speciale else 'frais_soutenance'
        val = getattr(self, field, None)
        if val is not None:
            return val
        try:
            return getattr(self.class_group.frais_mensuel_config, field)
        except Exception:
            return None

    @property
    def soutenance_payment(self):
        """Paiement de frais de soutenance déjà enregistré pour cette
        inscription, s'il existe (un seul paiement de ce type attendu)."""
        from academic_core.apps.accounting.models import CaissePayment
        return self.caisse_payments.filter(
            payment_type=CaissePayment.TYPE_SOUTENANCE
        ).order_by('-created_at').first()

    @property
    def is_validated(self):
        return self.status == self.STATUS_VALIDATED

    @property
    def is_reinscription(self):
        return self.enrollment_type == self.TYPE_REINSCRIPTION

    @property
    def is_change_filiere(self):
        return self.enrollment_type == self.TYPE_CHANGE_FILIERE

    def advance_months_list(self):
        """
        Parse `advance_months` en liste de (mois, montant).

        Format stocké : CSV de tokens "mois" ou "mois:montant" (ex: "10,11:75000,12").
        Un token sans montant explicite retombe sur `monthly_installment`.
        """
        from decimal import Decimal, InvalidOperation
        result = []
        for token in (self.advance_months or '').split(','):
            token = token.strip()
            if not token:
                continue
            if ':' in token:
                m_str, amt_str = token.split(':', 1)
            else:
                m_str, amt_str = token, ''
            if not m_str.isdigit():
                continue
            amount = None
            if amt_str.strip():
                try:
                    amount = Decimal(amt_str)
                except InvalidOperation:
                    amount = None
            if amount is None:
                amount = self.monthly_installment
            result.append((int(m_str), amount))
        return result

    @property
    def total_paid_amount(self):
        """Montant total déjà réglé (paiement d'inscription + mensualités payées)."""
        from decimal import Decimal
        total = self.payment_amount or Decimal('0')
        installments_paid = self.installments.filter(is_paid=True).aggregate(
            s=models.Sum('amount_paid')
        )['s'] or Decimal('0')
        return total + installments_paid

    @staticmethod
    def generate_payment_reference():
        """Génère une référence unique : INS-{AAAA}-{NNNNN}"""
        import random, string
        from django.utils import timezone
        year = timezone.now().year
        for _ in range(20):
            rand5 = ''.join(random.choices(string.digits, k=5))
            ref = f'INS-{year}-{rand5}'
            if not Enrollment.objects.filter(payment_reference=ref).exists():
                return ref
        return f'INS-{year}-{"".join(random.choices(string.digits, k=8))}'


class PaymentInstallment(models.Model):
    """Échéancier mensuel pour le solde restant dû sur une inscription."""
    enrollment         = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name='installments',
        verbose_name=_('Inscription'),
    )
    installment_number = models.PositiveSmallIntegerField(verbose_name=_('N° échéance'))
    due_date           = models.DateField(verbose_name=_("Date d'échéance"))
    amount_expected    = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_('Montant dû (FCFA)'))
    amount_paid        = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name=_('Montant reçu (FCFA)'))
    paid_date          = models.DateField(null=True, blank=True, verbose_name=_('Date de paiement'))
    is_paid            = models.BooleanField(default=False, verbose_name=_('Réglée'))
    notes              = models.TextField(blank=True, verbose_name=_('Observations'))

    # Étudiants boursiers : l'échéance doit être préparée (montant/infos
    # définis) par le Trésorier Général avant que le Caissier ne puisse
    # simplement valider l'encaissement et imprimer le reçu, sans rien
    # pouvoir modifier lui-même.
    prepared_by        = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='prepared_installments', db_constraint=False,
        verbose_name=_('Préparée par (Trésorier Général)'),
    )
    prepared_at         = models.DateTimeField(null=True, blank=True, verbose_name=_('Préparée le'))

    class Meta:
        db_table = 'payment_installments'
        verbose_name = _('Échéance de paiement')
        verbose_name_plural = _('Échéances de paiement')
        unique_together = ('enrollment', 'installment_number')
        ordering = ['due_date']

    def __str__(self):
        return f"Échéance {self.installment_number} — {self.due_date} — {self.amount_expected} FCFA"
