"""
Achats (Procurement) — Pilotage et Suivi Budgétaire.

Pipeline complet : DemandeAchat -> AppelOffres -> OffreFournisseur ->
CommandeAchat -> ReceptionAchat -> FactureAchat -> PaiementAchat, rattaché
aux lignes budgétaires existantes (accounting.LigneBudgetaire).

Adapté du projet de référence appSuiviBudgetaire (apps/procurement) :
- pas d'équivalent `finance.Tiers` dans ce projet -> nouveau modèle simple
  `Fournisseur`.
- `PaiementAchat` ne crée pas un modèle `finance.Depense` séparé (qui
  n'existe pas ici) : il génère directement une `accounting.DemandeDepense`
  déjà DECAISSEE, liée à la même ligne budgétaire, ce qui réutilise
  automatiquement le signal existant `recompute_montant_execute` de la V1
  budget (voir procurement/services.py) au lieu de dupliquer cette logique.
"""
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Fournisseur(models.Model):
    nom = models.CharField(max_length=200, verbose_name=_('Nom'))
    contact_nom = models.CharField(max_length=150, blank=True, verbose_name=_('Nom du contact'))
    telephone = models.CharField(max_length=30, blank=True, verbose_name=_('Téléphone'))
    email = models.EmailField(blank=True, verbose_name=_('Email'))
    adresse = models.CharField(max_length=255, blank=True, verbose_name=_('Adresse'))
    is_active = models.BooleanField(default=True, verbose_name=_('Actif'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'achats_fournisseurs'
        verbose_name = _('Fournisseur')
        verbose_name_plural = _('Fournisseurs')
        ordering = ['nom']

    def __str__(self):
        return self.nom


class DemandeAchat(models.Model):
    STATUT_BROUILLON = 'brouillon'
    STATUT_SOUMISE = 'soumise'
    STATUT_VALIDEE = 'validee'
    STATUT_REJETEE = 'rejetee'
    STATUT_ANNULEE = 'annulee'
    STATUT_CHOICES = [
        (STATUT_BROUILLON, _('Brouillon')),
        (STATUT_SOUMISE, _('Soumise')),
        (STATUT_VALIDEE, _('Validée')),
        (STATUT_REJETEE, _('Rejetée')),
        (STATUT_ANNULEE, _('Annulée')),
    ]
    TYPE_FOURNITURES = 'fournitures'
    TYPE_SERVICES = 'services'
    TYPE_EQUIPEMENT = 'equipement'
    TYPE_TRAVAUX = 'travaux'
    TYPE_AUTRE = 'autre'
    TYPE_CHOICES = [
        (TYPE_FOURNITURES, _('Fournitures')),
        (TYPE_SERVICES, _('Services')),
        (TYPE_EQUIPEMENT, _('Équipement')),
        (TYPE_TRAVAUX, _('Travaux')),
        (TYPE_AUTRE, _('Autre')),
    ]

    reference = models.CharField(max_length=50, unique=True, blank=True, verbose_name=_('Référence'))
    objet = models.CharField(max_length=255, verbose_name=_('Objet'))
    centre_cout = models.ForeignKey(
        'accounts.Direction', on_delete=models.PROTECT, related_name='demandes_achat',
        db_constraint=False, verbose_name=_('Centre de coût (Direction)'),
    )
    ligne_budgetaire = models.ForeignKey(
        'accounting.LigneBudgetaire', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_achat', verbose_name=_('Ligne budgétaire'),
    )
    type_depense = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_FOURNITURES, verbose_name=_('Type de dépense'))
    demandeur = models.ForeignKey(
        'accounts.User', on_delete=models.PROTECT, related_name='demandes_achat',
        db_constraint=False, verbose_name=_('Demandeur'),
    )
    date_demande = models.DateField(default=timezone.now, verbose_name=_('Date de demande'))
    montant_estime = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_('Montant estimé (FCFA)'))
    justification = models.TextField(blank=True, verbose_name=_('Justification'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_BROUILLON, verbose_name=_('Statut'))
    rejection_reason = models.TextField(blank=True, verbose_name=_('Motif du rejet'))
    valide_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_achat_validees', db_constraint=False, verbose_name=_('Validée par'),
    )
    date_validation = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'achats_demandes'
        verbose_name = _("Demande d'achat")
        verbose_name_plural = _("Demandes d'achat")
        ordering = ['-date_demande']

    def __str__(self):
        return f"{self.reference} — {self.objet}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.reference:
            self.reference = f"DA-{self.date_demande.year}-{str(self.pk).zfill(5)}"
            super().save(update_fields=['reference'])


class AppelOffres(models.Model):
    STATUT_OUVERT = 'ouvert'
    STATUT_CLOTURE = 'cloture'
    STATUT_ATTRIBUE = 'attribue'
    STATUT_ANNULE = 'annule'
    STATUT_CHOICES = [
        (STATUT_OUVERT, _('Ouvert')),
        (STATUT_CLOTURE, _('Clôturé')),
        (STATUT_ATTRIBUE, _('Attribué')),
        (STATUT_ANNULE, _('Annulé')),
    ]

    demande_achat = models.OneToOneField(DemandeAchat, on_delete=models.CASCADE, related_name='appel_offres', verbose_name=_("Demande d'achat"))
    reference = models.CharField(max_length=50, unique=True, blank=True, verbose_name=_('Référence'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    date_lancement = models.DateField(default=timezone.now, verbose_name=_('Date de lancement'))
    date_limite = models.DateField(null=True, blank=True, verbose_name=_('Date limite de dépôt'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_OUVERT, verbose_name=_('Statut'))

    class Meta:
        db_table = 'achats_appels_offres'
        verbose_name = _("Appel d'offres")
        verbose_name_plural = _("Appels d'offres")
        ordering = ['-date_lancement']

    def __str__(self):
        return self.reference or f"AO — {self.demande_achat.objet}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.reference:
            self.reference = f"AO-{self.date_lancement.year}-{str(self.pk).zfill(5)}"
            super().save(update_fields=['reference'])


class OffreFournisseur(models.Model):
    STATUT_RECUE = 'recue'
    STATUT_RETENUE = 'retenue'
    STATUT_REJETEE = 'rejetee'
    STATUT_CHOICES = [
        (STATUT_RECUE, _('Reçue')),
        (STATUT_RETENUE, _('Retenue')),
        (STATUT_REJETEE, _('Rejetée')),
    ]

    appel_offres = models.ForeignKey(AppelOffres, on_delete=models.CASCADE, related_name='offres', verbose_name=_("Appel d'offres"))
    fournisseur = models.ForeignKey(Fournisseur, on_delete=models.PROTECT, related_name='offres', verbose_name=_('Fournisseur'))
    montant_propose = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_('Montant proposé (FCFA)'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_RECUE, verbose_name=_('Statut'))
    document = models.FileField(upload_to='achats/offres/%Y/%m/', null=True, blank=True, verbose_name=_('Document'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'achats_offres_fournisseurs'
        verbose_name = _('Offre fournisseur')
        verbose_name_plural = _('Offres fournisseurs')
        ordering = ['montant_propose']

    def __str__(self):
        return f"{self.fournisseur} — {self.montant_propose}"


class CommandeAchat(models.Model):
    STATUT_EN_COURS = 'en_cours'
    STATUT_LIVREE = 'livree'
    STATUT_ANNULEE = 'annulee'
    STATUT_CHOICES = [
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_LIVREE, _('Livrée')),
        (STATUT_ANNULEE, _('Annulée')),
    ]

    demande_achat = models.ForeignKey(DemandeAchat, on_delete=models.PROTECT, related_name='commandes', verbose_name=_("Demande d'achat"))
    fournisseur = models.ForeignKey(Fournisseur, on_delete=models.PROTECT, related_name='commandes', verbose_name=_('Fournisseur'))
    reference = models.CharField(max_length=50, unique=True, blank=True, verbose_name=_('Référence'))
    montant = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_('Montant (FCFA)'))
    date_commande = models.DateField(default=timezone.now, verbose_name=_('Date de commande'))
    date_livraison_prevue = models.DateField(null=True, blank=True, verbose_name=_('Date de livraison prévue'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_EN_COURS, verbose_name=_('Statut'))

    class Meta:
        db_table = 'achats_commandes'
        verbose_name = _('Commande')
        verbose_name_plural = _('Commandes')
        ordering = ['-date_commande']

    def __str__(self):
        return self.reference or f"CMD — {self.fournisseur}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.reference:
            self.reference = f"CMD-{self.date_commande.year}-{str(self.pk).zfill(5)}"
            super().save(update_fields=['reference'])


class ReceptionAchat(models.Model):
    commande = models.ForeignKey(CommandeAchat, on_delete=models.CASCADE, related_name='receptions', verbose_name=_('Commande'))
    date_reception = models.DateField(default=timezone.now, verbose_name=_('Date de réception'))
    conforme = models.BooleanField(default=True, verbose_name=_('Conforme'))
    commentaire = models.TextField(blank=True, verbose_name=_('Commentaire'))
    recu_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='receptions_achat', db_constraint=False, verbose_name=_('Reçu par'),
    )

    class Meta:
        db_table = 'achats_receptions'
        verbose_name = _('Réception')
        verbose_name_plural = _('Réceptions')
        ordering = ['-date_reception']

    def __str__(self):
        return f"Réception {self.commande.reference} ({self.date_reception})"


class FactureAchat(models.Model):
    STATUT_EN_ATTENTE = 'en_attente'
    STATUT_VALIDEE = 'validee'
    STATUT_PAYEE = 'payee'
    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, _('En attente')),
        (STATUT_VALIDEE, _('Validée')),
        (STATUT_PAYEE, _('Payée')),
    ]

    commande = models.ForeignKey(CommandeAchat, on_delete=models.PROTECT, related_name='factures', verbose_name=_('Commande'))
    numero_facture = models.CharField(max_length=50, verbose_name=_('Numéro de facture'))
    montant = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_('Montant (FCFA)'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_EN_ATTENTE, verbose_name=_('Statut'))
    piece_jointe = models.FileField(upload_to='achats/factures/%Y/%m/', null=True, blank=True, verbose_name=_('Pièce jointe'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'achats_factures'
        verbose_name = _('Facture')
        verbose_name_plural = _('Factures')
        ordering = ['-created_at']
        unique_together = ('commande', 'numero_facture')

    def __str__(self):
        return f"{self.numero_facture} ({self.commande.reference})"


class PaiementAchat(models.Model):
    STATUT_PLANIFIE = 'planifie'
    STATUT_EFFECTUE = 'effectue'
    STATUT_ANNULE = 'annule'
    STATUT_CHOICES = [
        (STATUT_PLANIFIE, _('Planifié')),
        (STATUT_EFFECTUE, _('Effectué')),
        (STATUT_ANNULE, _('Annulé')),
    ]
    MODE_VIREMENT = 'virement'
    MODE_CHEQUE = 'cheque'
    MODE_ESPECES = 'especes'
    MODE_CHOICES = [
        (MODE_VIREMENT, _('Virement')),
        (MODE_CHEQUE, _('Chèque')),
        (MODE_ESPECES, _('Espèces')),
    ]

    facture = models.ForeignKey(FactureAchat, on_delete=models.PROTECT, related_name='paiements', verbose_name=_('Facture'))
    montant = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_('Montant (FCFA)'))
    date_paiement = models.DateField(default=timezone.now, verbose_name=_('Date de paiement'))
    mode_paiement = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_VIREMENT, verbose_name=_('Mode de paiement'))
    reference_paiement = models.CharField(max_length=100, blank=True, verbose_name=_('Référence de paiement'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_PLANIFIE, verbose_name=_('Statut'))

    # Adapté de la référence (`depense_generee` -> `finance.Depense`) : ici on
    # génère une accounting.DemandeDepense déjà DECAISSEE, ce qui réutilise le
    # calcul existant de LigneBudgetaire.montant_execute (voir services.py).
    demande_depense_generee = models.ForeignKey(
        'accounting.DemandeDepense', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='paiement_achat_origine', verbose_name=_('Demande de dépense générée'),
    )

    class Meta:
        db_table = 'achats_paiements'
        verbose_name = _('Paiement')
        verbose_name_plural = _('Paiements')
        ordering = ['-date_paiement']

    def __str__(self):
        return f"Paiement {self.montant} — {self.facture.numero_facture}"
