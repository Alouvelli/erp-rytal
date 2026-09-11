from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class StaffPresence(models.Model):
    """Pointage journalier d'un membre du personnel."""

    STATUT_PRESENT      = 'PRESENT'
    STATUT_ABSENT       = 'ABSENT'
    STATUT_RETARD       = 'RETARD'
    STATUT_CONGE        = 'CONGE'
    STATUT_DEMI_JOURNEE = 'DEMI_JOURNEE'
    STATUT_TELETRAVAIL  = 'TELETRAVAIL'
    STATUT_FERIE        = 'FERIE'

    STATUT_CHOICES = [
        (STATUT_PRESENT,      _('Présent')),
        (STATUT_ABSENT,       _('Absent')),
        (STATUT_RETARD,       _('Retard')),
        (STATUT_CONGE,        _('En congé')),
        (STATUT_DEMI_JOURNEE, _('Demi-journée')),
        (STATUT_TELETRAVAIL,  _('Télétravail')),
        (STATUT_FERIE,        _('Jour férié')),
    ]

    STATUT_COLORS = {
        STATUT_PRESENT:      'success',
        STATUT_ABSENT:       'danger',
        STATUT_RETARD:       'warning',
        STATUT_CONGE:        'info',
        STATUT_DEMI_JOURNEE: 'secondary',
        STATUT_TELETRAVAIL:  'primary',
        STATUT_FERIE:        'dark',
    }

    user            = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='staff_presences', verbose_name=_('Employé'),
    )
    date            = models.DateField(verbose_name=_('Date'))
    statut          = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default=STATUT_PRESENT,
        verbose_name=_('Statut'),
    )
    heure_arrivee   = models.TimeField(null=True, blank=True, verbose_name=_("Heure d'arrivée"))
    heure_depart    = models.TimeField(null=True, blank=True, verbose_name=_('Heure de départ'))
    justification   = models.TextField(blank=True, verbose_name=_('Justification / Observations'))
    document        = models.FileField(
        upload_to='hr/justifications/', null=True, blank=True,
        verbose_name=_('Document justificatif'),
    )
    enregistre_par  = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='presences_enregistrees', verbose_name=_('Enregistré par'),
        db_constraint=False,
    )
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'staff_presences'
        verbose_name        = _('Présence personnel')
        verbose_name_plural = _('Présences personnel')
        unique_together     = ('user', 'date')
        ordering            = ['-date', 'user__last_name']
        indexes             = [
            models.Index(fields=['date']),
            models.Index(fields=['user', 'date']),
            models.Index(fields=['statut']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.date} — {self.get_statut_display()}"

    @property
    def statut_color(self):
        return self.STATUT_COLORS.get(self.statut, 'secondary')

    @property
    def duree_minutes(self):
        """Durée de présence en minutes si arrivée et départ renseignés."""
        if self.heure_arrivee and self.heure_depart:
            from datetime import datetime, date
            d = date.today()
            debut = datetime.combine(d, self.heure_arrivee)
            fin   = datetime.combine(d, self.heure_depart)
            delta = fin - debut
            return max(delta.seconds // 60, 0)
        return None

    @property
    def duree_label(self):
        m = self.duree_minutes
        if m is None:
            return '—'
        h, mn = divmod(m, 60)
        return f"{h}h{mn:02d}"


class DemandeConge(models.Model):
    """Demande de congé ou d'absence d'un membre du personnel."""

    TYPE_ANNUEL      = 'ANNUEL'
    TYPE_MALADIE     = 'MALADIE'
    TYPE_EXCEPTIONNEL = 'EXCEPTIONNEL'
    TYPE_MATERNITE   = 'MATERNITE'
    TYPE_SANS_SOLDE  = 'SANS_SOLDE'
    TYPE_MISSION     = 'MISSION'

    TYPE_CHOICES = [
        (TYPE_ANNUEL,       _('Congé annuel')),
        (TYPE_MALADIE,      _('Congé maladie')),
        (TYPE_EXCEPTIONNEL, _('Congé exceptionnel')),
        (TYPE_MATERNITE,    _('Congé maternité/paternité')),
        (TYPE_SANS_SOLDE,   _('Congé sans solde')),
        (TYPE_MISSION,      _('Mission / Déplacement')),
    ]

    STATUT_EN_ATTENTE = 'EN_ATTENTE'
    STATUT_APPROUVE   = 'APPROUVE'
    STATUT_REJETE     = 'REJETE'

    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, _('En attente')),
        (STATUT_APPROUVE,   _('Approuvée')),
        (STATUT_REJETE,     _('Rejetée')),
    ]

    user            = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='demandes_conge', verbose_name=_('Employé'),
    )
    type_conge      = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_ANNUEL,
        verbose_name=_('Type de congé'),
    )
    date_debut      = models.DateField(verbose_name=_('Date de début'))
    date_fin        = models.DateField(verbose_name=_('Date de fin'))
    motif           = models.TextField(verbose_name=_('Motif'))
    statut          = models.CharField(
        max_length=15, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE,
        verbose_name=_('Statut'),
    )
    valide_par      = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conges_valides', verbose_name=_('Validé par'),
        db_constraint=False,
    )
    valide_le       = models.DateTimeField(null=True, blank=True, verbose_name=_('Validé le'))
    commentaire_rh  = models.TextField(blank=True, verbose_name=_('Commentaire RH'))
    document        = models.FileField(
        upload_to='hr/conges/', null=True, blank=True,
        verbose_name=_('Document justificatif'),
    )
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'demandes_conge'
        verbose_name        = _('Demande de congé')
        verbose_name_plural = _('Demandes de congé')
        ordering            = ['-created_at']
        indexes             = [
            models.Index(fields=['user', 'statut']),
            models.Index(fields=['date_debut', 'date_fin']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.get_type_conge_display()} — {self.date_debut} → {self.date_fin}"

    @property
    def nombre_jours(self):
        if self.date_debut and self.date_fin:
            return (self.date_fin - self.date_debut).days + 1
        return 0

    @property
    def statut_color(self):
        return {'EN_ATTENTE': 'warning', 'APPROUVE': 'success', 'REJETE': 'danger'}.get(self.statut, 'secondary')


class FichePersonnel(models.Model):
    """Fiche employé détaillée (informations contractuelles), en complément du compte User."""

    CONTRAT_CDI          = 'CDI'
    CONTRAT_CDD          = 'CDD'
    CONTRAT_STAGE        = 'STAGE'
    CONTRAT_PRESTATAIRE  = 'PRESTATAIRE'
    CONTRAT_VACATION     = 'VACATION'

    CONTRAT_CHOICES = [
        (CONTRAT_CDI,         _('CDI')),
        (CONTRAT_CDD,         _('CDD')),
        (CONTRAT_STAGE,       _('Stage')),
        (CONTRAT_PRESTATAIRE, _('Prestataire')),
        (CONTRAT_VACATION,    _('Vacation')),
    ]

    user                       = models.OneToOneField(
        'accounts.User', on_delete=models.CASCADE,
        related_name='fiche_personnel', verbose_name=_('Employé'),
    )
    poste                      = models.CharField(max_length=150, blank=True, verbose_name=_('Poste / Fonction'))
    type_contrat               = models.CharField(
        max_length=15, choices=CONTRAT_CHOICES, default=CONTRAT_CDI,
        verbose_name=_('Type de contrat'),
    )
    date_embauche              = models.DateField(null=True, blank=True, verbose_name=_("Date d'embauche"))
    date_fin_contrat           = models.DateField(null=True, blank=True, verbose_name=_('Date de fin de contrat'))
    numero_cnss                = models.CharField(max_length=30, blank=True, verbose_name=_('N° CNSS'))
    numero_ipres               = models.CharField(max_length=30, blank=True, verbose_name=_('N° IPRES'))
    adresse                    = models.TextField(blank=True, verbose_name=_('Adresse'))
    contact_urgence_nom        = models.CharField(max_length=150, blank=True, verbose_name=_("Contact d'urgence — Nom"))
    contact_urgence_telephone  = models.CharField(max_length=20, blank=True, verbose_name=_("Contact d'urgence — Téléphone"))
    notes                      = models.TextField(blank=True, verbose_name=_('Notes RH'))
    created_at                 = models.DateTimeField(auto_now_add=True)
    updated_at                 = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_fiche_personnel'
        verbose_name        = _('Fiche personnel')
        verbose_name_plural = _('Fiches personnel')

    def __str__(self):
        return f"Fiche — {self.user.get_full_name()}"

    def anciennete(self, reference_date=None):
        """
        Ancienneté formatée ('X ans Y mois') entre date_embauche et reference_date
        (aujourd'hui par défaut, ou la fin du mois d'un bulletin de salaire pour
        refléter l'ancienneté telle qu'elle était à cette période de paie).
        """
        if not self.date_embauche:
            return None
        ref = reference_date or timezone.localdate()
        if ref < self.date_embauche:
            return None
        years = ref.year - self.date_embauche.year
        months = ref.month - self.date_embauche.month
        if ref.day < self.date_embauche.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        parts = []
        if years:
            parts.append(f"{years} an{'s' if years > 1 else ''}")
        if months or not years:
            parts.append(f"{months} mois")
        return ' '.join(parts)


class SalaireConfig(models.Model):
    """Structure salariale mensuelle récurrente d'un employé (base pour la génération des bulletins)."""

    user          = models.OneToOneField(
        'accounts.User', on_delete=models.CASCADE,
        related_name='salaire_config', verbose_name=_('Employé'),
    )
    salaire_base  = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Salaire de base (FCFA)'))
    primes        = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Primes / Indemnités (FCFA)'))
    retenues      = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Retenues / Cotisations (FCFA)'))
    notes         = models.TextField(blank=True, verbose_name=_('Détail des primes et retenues'))
    is_active     = models.BooleanField(default=True, verbose_name=_('Actif'))
    updated_by    = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='salaire_configs_modifies', verbose_name=_('Modifié par'),
        db_constraint=False,
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_salaire_config'
        verbose_name        = _('Configuration salariale')
        verbose_name_plural = _('Configurations salariales')

    def __str__(self):
        return f"Salaire — {self.user.get_full_name()} — {self.salaire_net} FCFA"

    @property
    def salaire_net(self):
        return (self.salaire_base or 0) + (self.primes or 0) - (self.retenues or 0)


class BulletinSalaire(models.Model):
    """Bulletin de salaire mensuel d'un employé (snapshot généré à partir de SalaireConfig)."""

    STATUT_BROUILLON = 'BROUILLON'
    STATUT_VALIDE    = 'VALIDE'
    STATUT_PAYE      = 'PAYE'

    STATUT_CHOICES = [
        (STATUT_BROUILLON, _('Brouillon')),
        (STATUT_VALIDE,    _('Validé')),
        (STATUT_PAYE,      _('Payé')),
    ]

    user            = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='bulletins_salaire', verbose_name=_('Employé'),
    )
    annee           = models.PositiveSmallIntegerField(verbose_name=_('Année'))
    mois            = models.PositiveSmallIntegerField(verbose_name=_('Mois'))
    salaire_base    = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Salaire de base (FCFA)'))
    primes          = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Primes / Indemnités (FCFA)'))
    retenues        = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Retenues / Cotisations (FCFA)'))
    salaire_net     = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_('Net à payer (FCFA)'))
    statut          = models.CharField(
        max_length=10, choices=STATUT_CHOICES, default=STATUT_BROUILLON,
        verbose_name=_('Statut'),
    )
    date_paiement   = models.DateField(null=True, blank=True, verbose_name=_('Date de paiement'))
    notes           = models.TextField(blank=True, verbose_name=_('Notes'))
    generated_by    = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bulletins_salaire_generes', verbose_name=_('Généré par'),
        db_constraint=False,
    )
    validated_by    = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bulletins_salaire_valides', verbose_name=_('Validé par'),
        db_constraint=False,
    )
    validated_at    = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_bulletin_salaire'
        verbose_name        = _('Bulletin de salaire')
        verbose_name_plural = _('Bulletins de salaire')
        unique_together     = ('user', 'annee', 'mois')
        ordering            = ['-annee', '-mois', 'user__last_name']
        indexes = [
            models.Index(fields=['annee', 'mois']),
            models.Index(fields=['user', 'annee', 'mois']),
        ]

    def __str__(self):
        return f"Bulletin — {self.user.get_full_name()} — {self.mois:02d}/{self.annee}"

    def save(self, *args, **kwargs):
        self.salaire_net = (self.salaire_base or 0) + (self.primes or 0) - (self.retenues or 0)
        super().save(*args, **kwargs)

    @property
    def statut_color(self):
        return {'BROUILLON': 'secondary', 'VALIDE': 'success', 'PAYE': 'primary'}.get(self.statut, 'secondary')


# ═════════════════════════════════════════════════════════════════════════
# Infrastructure partagée des workflows RH
# ═════════════════════════════════════════════════════════════════════════

class IllegalTransition(Exception):
    """Levée quand une transition de statut demandée n'est pas autorisée."""
    pass


def transition(allowed, current, action):
    """Résout (statut_courant, action) -> nouveau statut via le dict `allowed`
    ({(from_statut, action): to_statut}). Lève IllegalTransition sinon."""
    key = (current, action)
    if key not in allowed:
        raise IllegalTransition(f"Transition « {action} » impossible depuis « {current} »")
    return allowed[key]


class HRWorkflowEvent(models.Model):
    """Trace d'audit générique pour toute transition de statut d'un workflow RH
    (Discipline, Évaluations, Missions, Recrutement, Documents…) — une seule
    table réutilisée par tous les modules plutôt qu'une table d'événements
    dupliquée par module."""

    module      = models.CharField(max_length=30, verbose_name=_('Module'))
    object_id   = models.PositiveIntegerField(verbose_name=_('Identifiant objet'))
    actor       = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hr_workflow_events', verbose_name=_('Acteur'),
        db_constraint=False,
    )
    action      = models.CharField(max_length=50, verbose_name=_('Action'))
    from_statut = models.CharField(max_length=30, blank=True, verbose_name=_('Statut initial'))
    to_statut   = models.CharField(max_length=30, blank=True, verbose_name=_('Statut final'))
    commentaire = models.TextField(blank=True, verbose_name=_('Commentaire'))
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_workflow_event'
        verbose_name        = _('Événement de workflow RH')
        verbose_name_plural = _('Événements de workflow RH')
        ordering            = ['-created_at']
        indexes             = [models.Index(fields=['module', 'object_id'])]

    def __str__(self):
        return f"{self.module} #{self.object_id} — {self.action}"


def log_hr_event(module, object_id, actor, action, from_statut='', to_statut='', commentaire=''):
    """Raccourci pour journaliser un événement de workflow RH."""
    return HRWorkflowEvent.objects.create(
        module=module, object_id=object_id, actor=actor, action=action,
        from_statut=from_statut, to_statut=to_statut, commentaire=commentaire,
    )


class AccueilScanEvent(models.Model):
    """Dernier résultat d'un pointage self-service (étudiant ou personnel) au
    Contrôle Accueil — le QR affiché à l'accueil (students/views.py::
    controle_scan) est scanné avec le téléphone DE LA PERSONNE, sur sa propre
    session ; l'écran d'accueil n'a donc aucun moyen de savoir qu'un scan a eu
    lieu autrement qu'en interrogeant le serveur. Cette table stocke le
    dernier résultat (photo, statut de paiement, etc.) pour que l'écran
    d'accueil puisse l'afficher à côté du QR via un polling court (voir
    students/views.py::controle_scan_poll). Purement d'affichage, sans valeur
    d'audit durable — les lignes anciennes sont purgées à chaque écriture."""

    TYPE_STUDENT = 'student'
    TYPE_STAFF   = 'staff'
    TYPE_CHOICES = [
        (TYPE_STUDENT, _('Étudiant')),
        (TYPE_STAFF,   _('Personnel')),
    ]

    scan_type  = models.CharField(max_length=10, choices=TYPE_CHOICES, verbose_name=_('Type'))
    payload    = models.JSONField(verbose_name=_('Résultat du scan'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Horodatage'))

    class Meta:
        db_table            = 'hr_accueil_scan_event'
        verbose_name        = _('Évènement de scan accueil')
        verbose_name_plural  = _('Évènements de scan accueil')
        ordering             = ['-created_at']
        indexes              = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return f"{self.get_scan_type_display()} — {self.created_at:%d/%m/%Y %H:%M:%S}"


# ═════════════════════════════════════════════════════════════════════════
# Carrière & Contrats
# ═════════════════════════════════════════════════════════════════════════

class Contract(models.Model):
    """Contrat de travail d'un employé — historique (un employé peut avoir
    plusieurs contrats successifs)."""

    TYPE_CDI        = 'CDI'
    TYPE_CDD        = 'CDD'
    TYPE_STAGE      = 'STAGE'
    TYPE_INTERIM    = 'INTERIM'
    TYPE_PRESTATION = 'PRESTATION'

    TYPE_CHOICES = [
        (TYPE_CDI,        _('CDI')),
        (TYPE_CDD,        _('CDD')),
        (TYPE_STAGE,      _('Stage')),
        (TYPE_INTERIM,    _('Intérim')),
        (TYPE_PRESTATION, _('Prestation')),
    ]

    STATUT_ACTIF    = 'ACTIF'
    STATUT_SUSPENDU = 'SUSPENDU'
    STATUT_TERMINE  = 'TERMINE'

    STATUT_CHOICES = [
        (STATUT_ACTIF,    _('Actif')),
        (STATUT_SUSPENDU, _('Suspendu')),
        (STATUT_TERMINE,  _('Terminé')),
    ]

    user         = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='contrats', verbose_name=_('Employé'),
    )
    type_contrat = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_CDI, verbose_name=_('Type de contrat'))
    date_debut   = models.DateField(verbose_name=_('Date de début'))
    date_fin     = models.DateField(null=True, blank=True, verbose_name=_('Date de fin'))
    salaire_brut = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name=_('Salaire brut (FCFA)'))
    statut       = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_ACTIF, verbose_name=_('Statut'))
    signe_le     = models.DateField(null=True, blank=True, verbose_name=_('Signé le'))
    created_by   = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contrats_crees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_contract'
        verbose_name        = _('Contrat')
        verbose_name_plural = _('Contrats')
        ordering            = ['-date_debut']

    def __str__(self):
        return f"{self.get_type_contrat_display()} — {self.user.get_full_name()} ({self.date_debut})"

    @property
    def statut_color(self):
        return {'ACTIF': 'success', 'SUSPENDU': 'warning', 'TERMINE': 'secondary'}.get(self.statut, 'secondary')


class ContractAmendment(models.Model):
    """Avenant à un contrat (changement de salaire, de poste, etc.)."""

    contract   = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='avenants', verbose_name=_('Contrat'))
    date_effet = models.DateField(verbose_name=_("Date d'effet"))
    objet      = models.CharField(max_length=200, verbose_name=_('Objet'))
    details    = models.TextField(blank=True, verbose_name=_('Détails'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='avenants_crees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_contract_amendment'
        verbose_name        = _('Avenant')
        verbose_name_plural = _('Avenants')
        ordering            = ['-date_effet']

    def __str__(self):
        return f"Avenant — {self.objet} ({self.date_effet})"


class Assignment(models.Model):
    """Historique de carrière : chaque changement de poste/département d'un
    employé ajoute une ligne — journal append-only, jamais modifié en place."""

    TYPE_RECRUTEMENT = 'RECRUTEMENT'
    TYPE_PROMOTION   = 'PROMOTION'
    TYPE_MOBILITE    = 'MOBILITE'

    TYPE_CHOICES = [
        (TYPE_RECRUTEMENT, _('Recrutement')),
        (TYPE_PROMOTION,   _('Promotion')),
        (TYPE_MOBILITE,    _('Mobilité interne')),
    ]

    user              = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='affectations', verbose_name=_('Employé'),
    )
    department        = models.ForeignKey(
        'academic_structure.Department', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name=_('Département'),
    )
    poste             = models.CharField(max_length=150, blank=True, verbose_name=_('Poste'))
    date_effet        = models.DateField(verbose_name=_("Date d'effet"))
    type_affectation  = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_MOBILITE, verbose_name=_('Type'))
    note              = models.TextField(blank=True, verbose_name=_('Note'))
    created_by        = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='affectations_creees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_assignment'
        verbose_name        = _('Affectation')
        verbose_name_plural = _('Affectations (carrière)')
        ordering            = ['-date_effet']

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.get_type_affectation_display()} ({self.date_effet})"


# ═════════════════════════════════════════════════════════════════════════
# Discipline
# ═════════════════════════════════════════════════════════════════════════

class DisciplinaryCase(models.Model):
    """Dossier disciplinaire d'un employé."""

    STATUT_DEMANDE_EXPLICATION = 'DEMANDE_EXPLICATION'
    STATUT_REPONSE_RECUE       = 'REPONSE_RECUE'
    STATUT_CONSEIL             = 'CONSEIL'
    STATUT_SANCTION            = 'SANCTION'
    STATUT_CLASSE              = 'CLASSE'

    STATUT_CHOICES = [
        (STATUT_DEMANDE_EXPLICATION, _("Demande d'explication")),
        (STATUT_REPONSE_RECUE,       _('Réponse reçue')),
        (STATUT_CONSEIL,             _('Conseil de discipline')),
        (STATUT_SANCTION,            _('Sanction prononcée')),
        (STATUT_CLASSE,              _('Classé sans suite')),
    ]

    SANCTION_AVERTISSEMENT = 'AVERTISSEMENT'
    SANCTION_BLAME         = 'BLAME'
    SANCTION_MISE_A_PIED   = 'MISE_A_PIED'
    SANCTION_LICENCIEMENT  = 'LICENCIEMENT'

    SANCTION_CHOICES = [
        (SANCTION_AVERTISSEMENT, _('Avertissement')),
        (SANCTION_BLAME,         _('Blâme')),
        (SANCTION_MISE_A_PIED,   _('Mise à pied')),
        (SANCTION_LICENCIEMENT,  _('Licenciement')),
    ]

    user          = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='dossiers_disciplinaires', verbose_name=_('Employé'),
    )
    motif         = models.TextField(verbose_name=_('Motif'))
    explication   = models.TextField(blank=True, verbose_name=_("Explication de l'employé"))
    sanction_type = models.CharField(max_length=15, choices=SANCTION_CHOICES, blank=True, verbose_name=_('Type de sanction'))
    decision      = models.TextField(blank=True, verbose_name=_('Décision'))
    statut        = models.CharField(max_length=25, choices=STATUT_CHOICES, default=STATUT_DEMANDE_EXPLICATION, verbose_name=_('Statut'))
    initiated_by  = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dossiers_disciplinaires_inities', verbose_name=_('Initié par'),
        db_constraint=False,
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_disciplinary_case'
        verbose_name        = _('Dossier disciplinaire')
        verbose_name_plural = _('Dossiers disciplinaires')
        ordering            = ['-created_at']

    def __str__(self):
        return f"Dossier — {self.user.get_full_name()} ({self.get_statut_display()})"

    @property
    def statut_color(self):
        return {
            'DEMANDE_EXPLICATION': 'warning', 'REPONSE_RECUE': 'info',
            'CONSEIL': 'primary', 'SANCTION': 'danger', 'CLASSE': 'secondary',
        }.get(self.statut, 'secondary')


# ═════════════════════════════════════════════════════════════════════════
# Évaluations
# ═════════════════════════════════════════════════════════════════════════

class EvaluationCampaign(models.Model):
    STATUT_BROUILLON = 'BROUILLON'
    STATUT_OUVERTE   = 'OUVERTE'
    STATUT_CLOTUREE  = 'CLOTUREE'

    STATUT_CHOICES = [
        (STATUT_BROUILLON, _('Brouillon')),
        (STATUT_OUVERTE,   _('Ouverte')),
        (STATUT_CLOTUREE,  _('Clôturée')),
    ]

    annee      = models.PositiveSmallIntegerField(verbose_name=_('Année'))
    label      = models.CharField(max_length=150, verbose_name=_('Libellé'))
    statut     = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_BROUILLON, verbose_name=_('Statut'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_evaluation_campaign'
        verbose_name        = _("Campagne d'évaluation")
        verbose_name_plural = _("Campagnes d'évaluation")
        ordering            = ['-annee']

    def __str__(self):
        return f"{self.label} ({self.annee})"


class Evaluation(models.Model):
    STATUT_A_FAIRE      = 'A_FAIRE'
    STATUT_AUTO_EVALUEE = 'AUTO_EVALUEE'
    STATUT_EVALUEE      = 'EVALUEE'
    STATUT_FINALISEE    = 'FINALISEE'

    STATUT_CHOICES = [
        (STATUT_A_FAIRE,      _('À faire')),
        (STATUT_AUTO_EVALUEE, _('Auto-évaluée')),
        (STATUT_EVALUEE,      _('Évaluée')),
        (STATUT_FINALISEE,    _('Finalisée')),
    ]

    campaign            = models.ForeignKey(EvaluationCampaign, on_delete=models.CASCADE, related_name='evaluations', verbose_name=_('Campagne'))
    user                = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='evaluations', verbose_name=_('Employé'),
    )
    statut              = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_A_FAIRE, verbose_name=_('Statut'))
    auto_evaluation      = models.TextField(blank=True, verbose_name=_('Auto-évaluation'))
    souhait_carriere     = models.TextField(blank=True, verbose_name=_('Souhaits de carrière'))
    evaluation_manager   = models.TextField(blank=True, verbose_name=_("Évaluation du responsable"))
    note_globale         = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Note globale (1 à 5)'))
    evaluated_by         = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='evaluations_realisees', verbose_name=_('Évalué par'),
        db_constraint=False,
    )
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_evaluation'
        verbose_name        = _('Évaluation')
        verbose_name_plural  = _('Évaluations')
        unique_together      = ('campaign', 'user')
        ordering             = ['-campaign__annee', 'user__last_name']

    def __str__(self):
        return f"Évaluation — {self.user.get_full_name()} ({self.campaign.label})"

    @property
    def statut_color(self):
        return {
            'A_FAIRE': 'secondary', 'AUTO_EVALUEE': 'info',
            'EVALUEE': 'primary', 'FINALISEE': 'success',
        }.get(self.statut, 'secondary')


class EvaluationObjective(models.Model):
    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='objectifs', verbose_name=_('Évaluation'))
    libelle    = models.CharField(max_length=200, verbose_name=_('Libellé'))
    poids      = models.PositiveSmallIntegerField(default=1, verbose_name=_('Poids'))
    resultat   = models.TextField(blank=True, verbose_name=_('Résultat'))

    class Meta:
        db_table            = 'hr_evaluation_objective'
        verbose_name        = _("Objectif d'évaluation")
        verbose_name_plural = _("Objectifs d'évaluation")

    def __str__(self):
        return self.libelle


# ═════════════════════════════════════════════════════════════════════════
# Missions
# ═════════════════════════════════════════════════════════════════════════

class Mission(models.Model):
    STATUT_SOUMISE       = 'SOUMISE'
    STATUT_VALIDEE       = 'VALIDEE'
    STATUT_EFFECTUEE     = 'EFFECTUEE'
    STATUT_RAPPORT_REMIS = 'RAPPORT_REMIS'
    STATUT_REJETEE       = 'REJETEE'

    STATUT_CHOICES = [
        (STATUT_SOUMISE,       _('Soumise')),
        (STATUT_VALIDEE,       _('Validée')),
        (STATUT_EFFECTUEE,     _('Effectuée')),
        (STATUT_RAPPORT_REMIS, _('Rapport remis')),
        (STATUT_REJETEE,       _('Rejetée')),
    ]

    user         = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='missions', verbose_name=_('Employé'),
    )
    objet        = models.CharField(max_length=255, verbose_name=_('Objet'))
    destination  = models.CharField(max_length=120, verbose_name=_('Destination'))
    date_debut   = models.DateField(verbose_name=_('Date de début'))
    date_fin     = models.DateField(verbose_name=_('Date de fin'))
    rapport      = models.TextField(blank=True, verbose_name=_('Rapport de mission'))
    statut       = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_SOUMISE, verbose_name=_('Statut'))
    validated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='missions_validees', verbose_name=_('Validé par'),
        db_constraint=False,
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_mission'
        verbose_name        = _('Mission')
        verbose_name_plural = _('Missions')
        ordering            = ['-date_debut']

    def __str__(self):
        return f"{self.objet} — {self.user.get_full_name()} ({self.destination})"

    @property
    def statut_color(self):
        return {
            'SOUMISE': 'warning', 'VALIDEE': 'info', 'EFFECTUEE': 'primary',
            'RAPPORT_REMIS': 'success', 'REJETEE': 'danger',
        }.get(self.statut, 'secondary')


# ═════════════════════════════════════════════════════════════════════════
# Intérims & Passations de service
# ═════════════════════════════════════════════════════════════════════════

class Interim(models.Model):
    MOTIF_CONGE   = 'CONGE'
    MOTIF_ABSENCE = 'ABSENCE'
    MOTIF_MISSION = 'MISSION'
    MOTIF_AUTRE   = 'AUTRE'

    MOTIF_CHOICES = [
        (MOTIF_CONGE,   _('Congé')),
        (MOTIF_ABSENCE, _('Absence')),
        (MOTIF_MISSION, _('Mission')),
        (MOTIF_AUTRE,   _('Autre')),
    ]

    STATUT_ACTIVE   = 'ACTIVE'
    STATUT_CLOTUREE = 'CLOTUREE'

    STATUT_CHOICES = [
        (STATUT_ACTIVE,   _('Active')),
        (STATUT_CLOTUREE, _('Clôturée')),
    ]

    titulaire   = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='interims_titulaire', verbose_name=_('Titulaire'),
    )
    interimaire = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='interims_remplacant', verbose_name=_('Intérimaire'),
        db_constraint=False,
    )
    motif       = models.CharField(max_length=10, choices=MOTIF_CHOICES, default=MOTIF_AUTRE, verbose_name=_('Motif'))
    date_debut  = models.DateField(verbose_name=_('Date de début'))
    date_fin    = models.DateField(verbose_name=_('Date de fin'))
    statut      = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_ACTIVE, verbose_name=_('Statut'))
    note        = models.TextField(blank=True, verbose_name=_('Note'))
    created_by  = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='interims_crees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_interim'
        verbose_name        = _('Intérim')
        verbose_name_plural = _('Intérims')
        ordering            = ['-date_debut']

    def __str__(self):
        interimaire = self.interimaire.get_full_name() if self.interimaire else '—'
        return f"Intérim — {interimaire} remplace {self.titulaire.get_full_name()}"

    @property
    def statut_color(self):
        return {'ACTIVE': 'success', 'CLOTUREE': 'secondary'}.get(self.statut, 'secondary')


class Handover(models.Model):
    """Passation de service entre un agent sortant et un agent entrant."""

    STATUT_SOUMISE = 'SOUMISE'
    STATUT_VALIDEE = 'VALIDEE'

    STATUT_CHOICES = [
        (STATUT_SOUMISE, _('Soumise')),
        (STATUT_VALIDEE, _('Validée')),
    ]

    sortant              = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='passations_sortant', verbose_name=_('Agent sortant'),
    )
    entrant              = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='passations_entrant', verbose_name=_('Agent entrant'),
        db_constraint=False,
    )
    poste                = models.CharField(max_length=255, verbose_name=_('Poste concerné'))
    date_passation       = models.DateField(verbose_name=_('Date de passation'))
    elements_transferes  = models.TextField(blank=True, verbose_name=_('Éléments transférés'))
    statut               = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_SOUMISE, verbose_name=_('Statut'))
    created_by           = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='passations_creees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_handover'
        verbose_name        = _('Passation de service')
        verbose_name_plural = _('Passations de service')
        ordering            = ['-date_passation']

    def __str__(self):
        entrant = self.entrant.get_full_name() if self.entrant else '—'
        return f"Passation — {self.poste} ({self.sortant.get_full_name()} → {entrant})"

    @property
    def statut_color(self):
        return {'SOUMISE': 'warning', 'VALIDEE': 'success'}.get(self.statut, 'secondary')


# ═════════════════════════════════════════════════════════════════════════
# Stages
# ═════════════════════════════════════════════════════════════════════════

class Internship(models.Model):
    STATUT_DEMANDE   = 'DEMANDE'
    STATUT_ENTRETIEN = 'ENTRETIEN'
    STATUT_ACCEPTE   = 'ACCEPTE'
    STATUT_EN_COURS  = 'EN_COURS'
    STATUT_TERMINE   = 'TERMINE'
    STATUT_REJETE    = 'REJETE'

    STATUT_CHOICES = [
        (STATUT_DEMANDE,   _('Demande')),
        (STATUT_ENTRETIEN, _('Entretien')),
        (STATUT_ACCEPTE,   _('Accepté')),
        (STATUT_EN_COURS,  _('En cours')),
        (STATUT_TERMINE,   _('Terminé')),
        (STATUT_REJETE,    _('Rejeté')),
    ]

    prenom     = models.CharField(max_length=100, verbose_name=_('Prénom'))
    nom        = models.CharField(max_length=100, verbose_name=_('Nom'))
    ecole      = models.CharField(max_length=200, blank=True, verbose_name=_('École / Établissement'))
    sujet      = models.CharField(max_length=255, blank=True, verbose_name=_('Sujet de stage'))
    tuteur     = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stagiaires_encadres', verbose_name=_('Tuteur'),
        db_constraint=False,
    )
    date_debut = models.DateField(verbose_name=_('Date de début'))
    date_fin   = models.DateField(verbose_name=_('Date de fin'))
    statut     = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_DEMANDE, verbose_name=_('Statut'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stages_crees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_internship'
        verbose_name        = _('Stage')
        verbose_name_plural = _('Stages')
        ordering            = ['-date_debut']

    def __str__(self):
        return f"Stage — {self.prenom} {self.nom} ({self.get_statut_display()})"

    @property
    def statut_color(self):
        return {
            'DEMANDE': 'secondary', 'ENTRETIEN': 'info', 'ACCEPTE': 'primary',
            'EN_COURS': 'warning', 'TERMINE': 'success', 'REJETE': 'danger',
        }.get(self.statut, 'secondary')


# ═════════════════════════════════════════════════════════════════════════
# Intégration (Onboarding)
# ═════════════════════════════════════════════════════════════════════════

class Onboarding(models.Model):
    STATUT_EN_COURS = 'EN_COURS'
    STATUT_TERMINE  = 'TERMINE'

    STATUT_CHOICES = [
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_TERMINE,  _('Terminé')),
    ]

    DEFAULT_TASKS = [
        "Remise du kit d'accueil",
        "Signature du livret d'accueil",
        "Présentation à l'équipe",
        "Mise en place des accès informatiques",
        "Planning d'intégration communiqué",
        "Point de mi-période d'essai",
    ]

    user       = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='onboardings', verbose_name=_('Employé'),
    )
    date_debut = models.DateField(verbose_name=_('Date de début'))
    statut     = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_EN_COURS, verbose_name=_('Statut'))
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='onboardings_crees', verbose_name=_('Créé par'),
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_onboarding'
        verbose_name        = _('Intégration')
        verbose_name_plural = _('Intégrations')
        ordering            = ['-date_debut']

    def __str__(self):
        return f"Intégration — {self.user.get_full_name()}"

    @property
    def statut_color(self):
        return {'EN_COURS': 'warning', 'TERMINE': 'success'}.get(self.statut, 'secondary')

    @property
    def progress_pct(self):
        total = self.taches.count()
        if not total:
            return 0
        done = self.taches.filter(fait=True).count()
        return round(done * 100 / total)


class OnboardingTask(models.Model):
    onboarding  = models.ForeignKey(Onboarding, on_delete=models.CASCADE, related_name='taches', verbose_name=_('Intégration'))
    libelle     = models.CharField(max_length=200, verbose_name=_('Tâche'))
    responsable = models.CharField(max_length=50, default='RH', verbose_name=_('Responsable'))
    fait        = models.BooleanField(default=False, verbose_name=_('Fait'))
    ordre       = models.PositiveSmallIntegerField(default=0, verbose_name=_('Ordre'))

    class Meta:
        db_table            = 'hr_onboarding_task'
        verbose_name        = _("Tâche d'intégration")
        verbose_name_plural = _("Tâches d'intégration")
        ordering            = ['ordre', 'id']

    def __str__(self):
        return self.libelle


# ═════════════════════════════════════════════════════════════════════════
# Recrutement
# ═════════════════════════════════════════════════════════════════════════

class RecruitmentRequest(models.Model):
    MODE_INTERNE = 'INTERNE'
    MODE_EXTERNE = 'EXTERNE'

    MODE_CHOICES = [
        (MODE_INTERNE, _('Recrutement interne')),
        (MODE_EXTERNE, _('Appel externe')),
    ]

    STATUT_SOUMISE  = 'SOUMISE'
    STATUT_VALIDEE  = 'VALIDEE'
    STATUT_EN_COURS = 'EN_COURS'
    STATUT_POURVUE  = 'POURVUE'
    STATUT_REJETEE  = 'REJETEE'

    STATUT_CHOICES = [
        (STATUT_SOUMISE,  _('Soumise')),
        (STATUT_VALIDEE,  _('Validée')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_POURVUE,  _('Pourvue')),
        (STATUT_REJETEE,  _('Rejetée')),
    ]

    demande_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='besoins_recrutement', verbose_name=_('Demandé par'),
        db_constraint=False,
    )
    titre       = models.CharField(max_length=200, verbose_name=_('Titre du poste'))
    department  = models.ForeignKey(
        'academic_structure.Department', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name=_('Département'),
    )
    poste       = models.CharField(max_length=150, blank=True, verbose_name=_('Poste'))
    mode        = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_EXTERNE, verbose_name=_('Mode'))
    description = models.TextField(blank=True, verbose_name=_('Description du besoin'))
    statut      = models.CharField(max_length=10, choices=STATUT_CHOICES, default=STATUT_SOUMISE, verbose_name=_('Statut'))
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_recruitment_request'
        verbose_name        = _('Besoin de recrutement')
        verbose_name_plural = _('Besoins de recrutement')
        ordering            = ['-created_at']

    def __str__(self):
        return f"{self.titre} ({self.get_statut_display()})"

    @property
    def statut_color(self):
        return {
            'SOUMISE': 'warning', 'VALIDEE': 'info', 'EN_COURS': 'primary',
            'POURVUE': 'success', 'REJETEE': 'danger',
        }.get(self.statut, 'secondary')


class Candidate(models.Model):
    STATUT_CANDIDATURE    = 'CANDIDATURE'
    STATUT_PRESELECTIONNE = 'PRESELECTIONNE'
    STATUT_ENTRETIEN      = 'ENTRETIEN'
    STATUT_RETENU         = 'RETENU'
    STATUT_REJETE         = 'REJETE'

    STATUT_CHOICES = [
        (STATUT_CANDIDATURE,    _('Candidature reçue')),
        (STATUT_PRESELECTIONNE, _('Présélectionné')),
        (STATUT_ENTRETIEN,      _('Entretien')),
        (STATUT_RETENU,         _('Retenu')),
        (STATUT_REJETE,         _('Rejeté')),
    ]

    recruitment_request = models.ForeignKey(
        RecruitmentRequest, on_delete=models.CASCADE,
        related_name='candidats', verbose_name=_('Besoin de recrutement'),
    )
    prenom     = models.CharField(max_length=100, verbose_name=_('Prénom'))
    nom        = models.CharField(max_length=100, verbose_name=_('Nom'))
    email      = models.EmailField(blank=True, verbose_name=_('Email'))
    telephone  = models.CharField(max_length=20, blank=True, verbose_name=_('Téléphone'))
    source     = models.CharField(max_length=100, blank=True, verbose_name=_('Source'))
    statut     = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_CANDIDATURE, verbose_name=_('Statut'))
    score      = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Score'))
    notes      = models.TextField(blank=True, verbose_name=_('Notes'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_candidate'
        verbose_name        = _('Candidat')
        verbose_name_plural = _('Candidats')
        ordering            = ['-created_at']

    def __str__(self):
        return f"{self.prenom} {self.nom} — {self.get_statut_display()}"

    @property
    def statut_color(self):
        return {
            'CANDIDATURE': 'secondary', 'PRESELECTIONNE': 'info', 'ENTRETIEN': 'warning',
            'RETENU': 'success', 'REJETE': 'danger',
        }.get(self.statut, 'secondary')


# ═════════════════════════════════════════════════════════════════════════
# Documents & Attestations
# ═════════════════════════════════════════════════════════════════════════

class Document(models.Model):
    """Document RH générique (GED simple, sans chiffrement — même convention
    que les justificatifs de congé/présence déjà stockés en FileField brut)."""

    user        = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, null=True, blank=True,
        related_name='documents_rh', verbose_name=_('Employé'),
    )
    categorie   = models.CharField(max_length=60, verbose_name=_('Catégorie'))
    fichier     = models.FileField(upload_to='hr/documents/', verbose_name=_('Fichier'))
    uploaded_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='documents_rh_uploades', verbose_name=_('Déposé par'),
        db_constraint=False,
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table            = 'hr_document'
        verbose_name        = _('Document')
        verbose_name_plural = _('Documents')
        ordering            = ['-created_at']

    def __str__(self):
        return f"{self.categorie} — {self.user.get_full_name() if self.user else '—'}"


class DocumentRequest(models.Model):
    TYPE_ATTESTATION_TRAVAIL = 'ATTESTATION_TRAVAIL'
    TYPE_ATTESTATION_SALAIRE = 'ATTESTATION_SALAIRE'
    TYPE_CERTIFICAT_TRAVAIL  = 'CERTIFICAT_TRAVAIL'

    TYPE_CHOICES = [
        (TYPE_ATTESTATION_TRAVAIL, _('Attestation de travail')),
        (TYPE_ATTESTATION_SALAIRE, _('Attestation de salaire')),
        (TYPE_CERTIFICAT_TRAVAIL,  _('Certificat de travail')),
    ]

    STATUT_SOUMISE       = 'SOUMISE'
    STATUT_EN_TRAITEMENT = 'EN_TRAITEMENT'
    STATUT_SIGNEE        = 'SIGNEE'
    STATUT_DISPONIBLE    = 'DISPONIBLE'
    STATUT_REJETEE       = 'REJETEE'

    STATUT_CHOICES = [
        (STATUT_SOUMISE,       _('Soumise')),
        (STATUT_EN_TRAITEMENT, _('En traitement')),
        (STATUT_SIGNEE,        _('Signée')),
        (STATUT_DISPONIBLE,    _('Disponible')),
        (STATUT_REJETEE,       _('Rejetée')),
    ]

    user          = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE,
        related_name='demandes_documents', verbose_name=_('Employé'),
    )
    type_document = models.CharField(max_length=25, choices=TYPE_CHOICES, verbose_name=_('Type de document'))
    statut        = models.CharField(max_length=15, choices=STATUT_CHOICES, default=STATUT_SOUMISE, verbose_name=_('Statut'))
    document      = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes', verbose_name=_('Document généré'),
    )
    assigned_to   = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_documents_traitees', verbose_name=_('Traité par'),
        db_constraint=False,
    )
    commentaire   = models.TextField(blank=True, verbose_name=_('Commentaire'))
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'hr_document_request'
        verbose_name        = _('Demande de document')
        verbose_name_plural = _('Demandes de documents')
        ordering            = ['-created_at']

    def __str__(self):
        return f"{self.get_type_document_display()} — {self.user.get_full_name()}"

    @property
    def statut_color(self):
        return {
            'SOUMISE': 'warning', 'EN_TRAITEMENT': 'info', 'SIGNEE': 'primary',
            'DISPONIBLE': 'success', 'REJETEE': 'danger',
        }.get(self.statut, 'secondary')
