from django.db import models
from django.utils.translation import gettext_lazy as _


class Candidature(models.Model):
    """
    Candidature déposée par un utilisateur (Role.CANDIDAT) sur le portail
    public d'admission, avant de pouvoir remplir le formulaire d'inscription
    complet (voir students.Enrollment, créé une fois cette candidature
    validée par le chef du département concerné).

    Modèle tenant-only ('admissions' est dans TENANT_ONLY_APP_LABELS,
    academic_core/db_router.py) : vit dans la base de l'institut où le
    candidat s'est inscrit, comme Enrollment/CaissePayment.
    """
    STATUS_PENDING   = 'PENDING'
    STATUS_VALIDATED = 'VALIDATED'
    STATUS_REJECTED  = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING,   _('En attente')),
        (STATUS_VALIDATED, _('Validée')),
        (STATUS_REJECTED,  _('Rejetée')),
    ]

    NIVEAU_L1 = 'L1'
    NIVEAU_L2 = 'L2'
    NIVEAU_L3 = 'L3'
    NIVEAU_L4 = 'L4'
    NIVEAU_L5 = 'L5'
    NIVEAU_CHOICES = [
        (NIVEAU_L1, '1ère année'),
        (NIVEAU_L2, '2ième année'),
        (NIVEAU_L3, '3ième année'),
        (NIVEAU_L4, '4ième année'),
        (NIVEAU_L5, '5ième année'),
    ]

    user = models.OneToOneField(
        'accounts.User', on_delete=models.CASCADE,
        related_name='candidature', db_constraint=False,
        verbose_name=_('Candidat'),
    )
    program = models.ForeignKey(
        'academic_structure.Program', on_delete=models.CASCADE,
        related_name='candidatures', verbose_name=_('Filière souhaitée'),
    )
    niveau_entree = models.CharField(
        max_length=2, choices=NIVEAU_CHOICES, blank=True,
        verbose_name=_("Année d'entrée"),
        help_text=_(
            "Déclarée par le candidat — détermine les pièces justificatives "
            "demandées (voir required_document_types)."
        ),
    )
    motivation = models.TextField(blank=True, verbose_name=_('Lettre de motivation'))
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Déposée le'))
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING,
        verbose_name=_('Statut'),
    )
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='candidatures_reviewed', db_constraint=False,
        verbose_name=_('Traitée par'),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Traitée le'))
    motif_rejet = models.TextField(blank=True, verbose_name=_('Motif de rejet'))

    class Meta:
        db_table = 'candidatures'
        verbose_name = _('Candidature')
        verbose_name_plural = _('Candidatures')
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.user.get_full_name()} → {self.program} ({self.get_status_display()})"

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    @property
    def is_validated(self):
        return self.status == self.STATUS_VALIDATED

    def required_document_types(self):
        """Types de pièces requises selon l'année d'entrée déclarée (vide
        tant que le candidat ne l'a pas encore renseignée)."""
        if not self.niveau_entree:
            return []
        base = [CandidatureDocument.TYPE_CNI_PASSEPORT, CandidatureDocument.TYPE_DIPLOME_BAC]
        if self.niveau_entree == self.NIVEAU_L1:
            return base + [CandidatureDocument.TYPE_RELEVE_BAC, CandidatureDocument.TYPE_PHOTO_IDENTITE]
        return base + [CandidatureDocument.TYPE_BULLETIN]

    def documents_completes(self):
        """
        True si toutes les pièces requises pour l'année déclarée ont été
        déposées — 2 photos distinctes exigées pour la 1ère année, au moins
        un bulletin pour les années 2 à 5.
        """
        if not self.niveau_entree:
            return False
        required = set(self.required_document_types())
        uploaded_types = set(self.documents.values_list('document_type', flat=True))

        if CandidatureDocument.TYPE_PHOTO_IDENTITE in required:
            if self.documents.filter(document_type=CandidatureDocument.TYPE_PHOTO_IDENTITE).count() < 2:
                return False
            required.discard(CandidatureDocument.TYPE_PHOTO_IDENTITE)

        if CandidatureDocument.TYPE_BULLETIN in required:
            if not self.documents.filter(document_type=CandidatureDocument.TYPE_BULLETIN).exists():
                return False
            required.discard(CandidatureDocument.TYPE_BULLETIN)

        return required.issubset(uploaded_types)


class CandidatureDocument(models.Model):
    """
    Pièce justificative déposée par le candidat pour la validation de sa
    candidature — CNI/Passeport et diplôme du BAC pour tous, + relevé du BAC
    et deux photos d'identité pour les candidats de 1ère année, + les
    bulletins des semestres antérieurs pour les candidats de 2ième à 5ième
    année (voir Candidature.required_document_types/documents_completes).
    """
    TYPE_CNI_PASSEPORT   = 'CNI_PASSEPORT'
    TYPE_DIPLOME_BAC     = 'DIPLOME_BAC'
    TYPE_RELEVE_BAC      = 'RELEVE_BAC'
    TYPE_PHOTO_IDENTITE  = 'PHOTO_IDENTITE'
    TYPE_BULLETIN        = 'BULLETIN'
    TYPE_CHOICES = [
        (TYPE_CNI_PASSEPORT,  "Carte Nationale d'Identité ou Passeport"),
        (TYPE_DIPLOME_BAC,    'Diplôme / Attestation du BAC'),
        (TYPE_RELEVE_BAC,     'Relevé du BAC'),
        (TYPE_PHOTO_IDENTITE, "Photo d'identité"),
        (TYPE_BULLETIN,       'Bulletin de semestre antérieur'),
    ]

    candidature = models.ForeignKey(
        Candidature, on_delete=models.CASCADE, related_name='documents',
        verbose_name=_('Candidature'),
    )
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name=_('Type de pièce'))
    libelle = models.CharField(
        max_length=100, blank=True, verbose_name=_('Libellé'),
        help_text=_("Ex : « Bulletin semestre 1 » — pour les pièces répétables."),
    )
    fichier = models.FileField(
        upload_to='admissions/documents_candidature/%Y/%m/', verbose_name=_('Fichier'),
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'candidature_documents'
        verbose_name = _('Pièce justificative de candidature')
        verbose_name_plural = _('Pièces justificatives de candidature')
        ordering = ['document_type', 'uploaded_at']

    def __str__(self):
        return f"{self.get_document_type_display()} — {self.candidature.user.get_full_name()}"
