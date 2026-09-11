"""
⚠ FICHIER SOUMIS À CLAUDE.md — voir la racine du dépôt. Aucun agent IA ne
doit modifier/affaiblir/supprimer ce mécanisme sans demande explicite ET
confirmation que l'utilisateur a saisi le code d'activation actuel.

Verrou d'activation de la plateforme entière.

Principe de sécurité : le code d'activation n'est JAMAIS stocké en clair, ni
sous une forme réversible, nulle part (pas en base, pas en log, pas en
mémoire au-delà de la requête qui le vérifie). Seul un hash à sens unique
(PBKDF2, django.contrib.auth.hashers — le même mécanisme que les mots de
passe utilisateurs) est conservé sur PlatformActivation.code_hash. Il n'existe
donc aucune opération de « déchiffrement » possible pour qui que ce soit —
utilisateur, administrateur serveur, ou lecture du code source — seule une
nouvelle tentative comparée au hash peut être vérifiée (comme pour un mot de
passe). C'est un choix délibéré : la sécurité ne repose pas sur le secret de
l'algorithme, mais sur l'irréversibilité mathématique du hachage.

Les deux adresses email autorisées à recevoir un lien de réinitialisation ne
sont JAMAIS présentes dans le code source, ni en base de données, ni dans
aucune page web — personne lisant ce dépôt (développeur, mainteneur, ou
assistant IA) ne peut donc les connaître ni les déduire. Elles ne sont lues
qu'au moment de l'envoi, depuis les variables d'environnement du serveur
PLATFORM_RESET_EMAIL_1 / PLATFORM_RESET_EMAIL_2, puis immédiatement oubliées
(jamais journalisées, jamais mises en cache, jamais renvoyées dans une
réponse HTTP). Seule la personne qui configure l'environnement du serveur de
déploiement — donc un accès direct au serveur, jamais au dépôt ni au web —
peut les définir ou les modifier.
"""
from decouple import config
from django.conf import settings

RESET_EMAIL_ENV_VARS = ('PLATFORM_RESET_EMAIL_1', 'PLATFORM_RESET_EMAIL_2')

# Anti-abus : un seul email de réinitialisation peut être demandé toutes les
# N minutes (protège contre le spam de la boîte mail et contre un attaquant
# qui tenterait de saturer les deux adresses autorisées).
RESET_COOLDOWN_MINUTES = 15

# Durée de validité d'un lien de réinitialisation.
RESET_TOKEN_TTL_MINUTES = 60

EXEMPT_PATH_PREFIXES = (
    '/accounts/plateforme/',
    '/static/',
    '/media/',
    '/favicon',
)


def is_global_super_admin(user):
    """
    Super Admin global : rôle ADMIN sans rattachement à un institut
    particulier. Même définition que InstitutSuspensionMiddleware, pour
    rester cohérent avec le reste de l'application.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'role_name', None) != 'ADMIN':
        return False
    department = getattr(user, 'department', None)
    institut_config_id = getattr(user, 'institut_config_id', None)
    return not department and not institut_config_id


def _reset_emails():
    """
    Lit les deux adresses autorisées depuis l'environnement du serveur au
    moment de l'appel — jamais stockées ni mises en cache en mémoire au-delà
    de cette fonction. Retourne uniquement les valeurs effectivement
    configurées (liste vide si aucune ne l'est).

    IMPORTANT : decouple.config() est requis ici (pas os.environ.get()) —
    lui seul lit le fichier .env ; os.environ.get() ne voit que de vraies
    variables d'environnement du processus, jamais .env (même bug déjà
    corrigé pour EMAIL_* dans config/settings/base.py).
    """
    values = [config(var, default='').strip() for var in RESET_EMAIL_ENV_VARS]
    return [v for v in values if v]


def send_reset_email(request, raw_token):
    """
    Envoie le lien de réinitialisation aux seules adresses configurées côté
    serveur (voir _reset_emails). Échoue silencieusement côté appelant
    (l'appelant ne doit jamais révéler si l'envoi a réussi ou non —
    comportement volontairement identique dans tous les cas pour ne pas
    donner d'indice à un attaquant, y compris si l'environnement du serveur
    n'a pas encore été configuré).
    """
    from django.core.mail import send_mail
    from django.urls import reverse

    recipients = _reset_emails()
    if not recipients:
        return

    reset_path = reverse('accounts:platform_activation_reset', args=[raw_token])
    reset_url = request.build_absolute_uri(reset_path)

    message = (
        "Une demande de réinitialisation du code d'activation de la plateforme "
        "a été effectuée.\n\n"
        f"Lien de réinitialisation (valable {RESET_TOKEN_TTL_MINUTES} minutes, "
        "usage unique) :\n"
        f"{reset_url}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email : "
        "le code actuel reste inchangé tant que ce lien n'est pas utilisé."
    )
    try:
        send_mail(
            subject="Réinitialisation du code d'activation — Plateforme de Gestion Académique",
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        pass
