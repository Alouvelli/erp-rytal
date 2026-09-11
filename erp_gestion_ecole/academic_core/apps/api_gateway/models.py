import hashlib
import secrets

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def generate_api_key():
    """Clé brute (jamais stockée telle quelle) — préfixée pour l'identifier
    visuellement comme une clé de cet ERP dans les journaux d'un consommateur."""
    return f"rytal_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key):
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


class APIResource(models.Model):
    """
    Catalogue des ressources d'API réellement exposées par l'ERP (ViewSets
    DRF déjà en place sous /api/v1/...), regroupées par fonctionnalité —
    c'est ce catalogue que l'onglet « API de Consommation » présente à
    l'administrateur d'institut, et dans lequel il choisit une ressource
    lorsqu'il accorde ou traite une demande d'accès (voir APIAccessGrant).
    """
    FONCT_ETUDIANTS     = 'ETUDIANTS'
    FONCT_EMARGEMENTS   = 'EMARGEMENTS'
    FONCT_NOTES         = 'NOTES'
    FONCT_ENSEIGNANTS   = 'ENSEIGNANTS'
    FONCT_PLANNING      = 'PLANNING'
    FONCT_STRUCTURE     = 'STRUCTURE'
    FONCT_ROOMS         = 'ROOMS'
    FONCT_SUBJECTS      = 'SUBJECTS'
    FONCT_CANCELLATIONS = 'CANCELLATIONS'
    FONCT_NOTIFICATIONS = 'NOTIFICATIONS'
    FONCT_ACCOUNTING    = 'ACCOUNTING'
    FONCT_HR            = 'HR'
    FONCT_COMMUNITY     = 'COMMUNITY'
    FONCT_STRATEGIC     = 'STRATEGIC'
    FONCT_INDICATORS    = 'INDICATORS'
    FONCT_PROCUREMENT   = 'PROCUREMENT'
    FONCT_QUALITY       = 'QUALITY'
    FONCT_RISKS         = 'RISKS'
    FONCT_COIP          = 'COIP'
    FONCT_ADMISSIONS    = 'ADMISSIONS'
    FONCT_AUTRE         = 'AUTRE'
    FONCTIONNALITE_CHOICES = [
        (FONCT_ETUDIANTS,     _('Étudiants')),
        (FONCT_EMARGEMENTS,   _('Émargements')),
        (FONCT_NOTES,         _('Notes & Évaluations')),
        (FONCT_ENSEIGNANTS,   _('Enseignants')),
        (FONCT_PLANNING,      _('Emploi du temps')),
        (FONCT_STRUCTURE,     _('Structure académique')),
        (FONCT_ROOMS,         _('Salles & Bâtiments')),
        (FONCT_SUBJECTS,      _('Matières')),
        (FONCT_CANCELLATIONS, _('Annulations de cours')),
        (FONCT_NOTIFICATIONS, _('Notifications')),
        (FONCT_ACCOUNTING,    _('Comptabilité')),
        (FONCT_HR,            _('Ressources Humaines')),
        (FONCT_COMMUNITY,     _('Service à la communauté')),
        (FONCT_STRATEGIC,     _('Plan stratégique')),
        (FONCT_INDICATORS,    _('Indicateurs')),
        (FONCT_PROCUREMENT,   _('Achats')),
        (FONCT_QUALITY,       _('Qualité')),
        (FONCT_RISKS,         _('Risques')),
        (FONCT_COIP,          _('COIP')),
        (FONCT_ADMISSIONS,    _('Admissions')),
        (FONCT_AUTRE,         _('Autre')),
    ]

    name = models.CharField(max_length=200, verbose_name=_('Nom de la ressource'))
    functionality = models.CharField(
        max_length=20, choices=FONCTIONNALITE_CHOICES, default=FONCT_AUTRE,
        verbose_name=_('Fonctionnalité'),
    )
    description = models.TextField(
        blank=True, verbose_name=_('Description'),
        help_text=_('Ce que renvoie cette ressource, et les filtres disponibles (paramètres de requête).'),
    )
    endpoint_path = models.CharField(
        max_length=300, verbose_name=_('Chemin de l\'API'),
        help_text=_("Ex. : /api/v1/students/ — une clé accordée sur cette ressource donne accès à ce chemin et ses sous-chemins."),
    )
    http_method = models.CharField(max_length=10, default='GET', verbose_name=_('Méthode HTTP'))
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_gateway_resources'
        verbose_name = _('Ressource API')
        verbose_name_plural = _('Ressources API')
        ordering = ['functionality', 'name']

    def __str__(self):
        return f"{self.name} ({self.endpoint_path})"


class APIAccessRequest(models.Model):
    """
    « Besoin » exprimé par un utilisateur : description libre de
    l'information dont il a besoin. L'administrateur d'institut l'examine et,
    s'il l'approuve, génère l'accès (APIAccessGrant) sur la ressource du
    catalogue correspondante — c'est ce traitement qui « génère l'API en
    fonction du besoin » : pas de nouveau code, mais une clé d'accès dédiée,
    scopée précisément à la ressource qui répond au besoin exprimé.
    """
    STATUS_PENDING  = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING,  _('En attente')),
        (STATUS_APPROVED, _('Approuvée')),
        (STATUS_REJECTED, _('Rejetée')),
    ]

    requested_by = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='api_access_requests',
        verbose_name=_('Demandeur'),
    )
    description = models.TextField(verbose_name=_('Besoin exprimé'))
    suggested_resource = models.ForeignKey(
        APIResource, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='suggested_for_requests', verbose_name=_('Ressource suggérée'),
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    admin_note = models.TextField(blank=True, verbose_name=_('Note de l\'administrateur'))
    processed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='api_access_requests_processed', verbose_name=_('Traitée par'),
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_gateway_access_requests'
        verbose_name = _('Demande d\'accès API')
        verbose_name_plural = _('Demandes d\'accès API')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requested_by} — {self.description[:50]}"


class APIAccessGrant(models.Model):
    """
    Accès effectif accordé à un utilisateur sur une ressource précise du
    catalogue — matérialisé par une clé (jamais stockée en clair : seul son
    empreinte SHA-256 est conservée). Le lien complet
    (chemin de la ressource + clé), affiché une seule fois à la création,
    est ce que l'administrateur peut « copier » et transmettre — voir
    api_gateway/views.py::grant_create / access_request_process.
    """
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='api_access_grants',
        verbose_name=_('Utilisateur autorisé'),
    )
    resource = models.ForeignKey(
        APIResource, on_delete=models.CASCADE, related_name='grants',
        verbose_name=_('Ressource'),
    )
    request = models.ForeignKey(
        APIAccessRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grants', verbose_name=_('Demande d\'origine'),
    )
    # Alias de la base tenant de cet institut au moment de la création — permet
    # à APIKeyAuthentication de router la requête vers la bonne base sans
    # dépendre du contexte de session (inexistant pour un appel API externe).
    db_alias = models.CharField(max_length=100, verbose_name=_('Base tenant'))
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    key_prefix = models.CharField(
        max_length=16, verbose_name=_('Préfixe (identification sans exposer la clé)'),
    )
    granted_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='api_access_grants_issued', verbose_name=_('Accordé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Expire le'))
    revoked = models.BooleanField(default=False, verbose_name=_('Révoquée'))
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='api_access_grants_revoked',
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'api_gateway_access_grants'
        verbose_name = _('Accès API accordé')
        verbose_name_plural = _('Accès API accordés')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} — {self.resource.name} ({self.key_prefix}…)"

    @property
    def is_valid(self):
        if self.revoked:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    @classmethod
    def issue(cls, *, user, resource, db_alias, granted_by, request=None, expires_at=None):
        """
        Crée un nouvel accès et retourne (grant, raw_key) — raw_key n'est
        JAMAIS accessible à nouveau après cet appel : à afficher/transmettre
        immédiatement, seul son empreinte est conservée en base.
        """
        raw_key = generate_api_key()
        grant = cls.objects.create(
            user=user, resource=resource, request=request, db_alias=db_alias,
            key_hash=hash_api_key(raw_key), key_prefix=raw_key[:14],
            granted_by=granted_by, expires_at=expires_at,
        )
        return grant, raw_key
