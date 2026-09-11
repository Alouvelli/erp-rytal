"""
Message de bienvenue affiché à la toute première ouverture du chat par un
utilisateur. Généré de façon déterministe en Python (pas d'appel LLM) : pas
de coût, pas de latence, pas de risque d'hallucination sur le tout premier
message, et un texte garanti conforme au rôle.
"""
from academic_core.apps.accounts.models import Role

ROLE_WELCOME = {
    Role.ETUDIANT: (
        "Je peux te renseigner sur ton emploi du temps, tes notes, tes absences "
        "et ton bulletin."
    ),
    Role.ENSEIGNANT: (
        "Je peux t'aider avec ton emploi du temps, tes classes, ton cahier de "
        "texte et le suivi des présences de tes séances."
    ),
    Role.RESPONSABLE: (
        "Je peux t'aider à consulter l'emploi du temps, les notes et les "
        "présences de ton département."
    ),
    Role.ASSISTANTE: (
        "Je peux t'aider à consulter l'emploi du temps, les notes et les "
        "présences de ton département."
    ),
    Role.INST_ADMIN: (
        "Je peux t'aider à consulter l'emploi du temps, les notes, les présences, "
        "les annulations/reports, les utilisateurs et le résumé financier de "
        "ton institut."
    ),
    Role.ADMIN: (
        "Je peux t'aider à consulter la liste des instituts, leurs administrateurs "
        "et, une fois un institut sélectionné, son emploi du temps, ses notes, "
        "ses présences, ses annulations/reports, ses utilisateurs et son résumé "
        "financier."
    ),
    Role.ASSISTANTE_DG: (
        "Je peux t'aider à consulter l'emploi du temps, les notes, les présences, "
        "les annulations/reports, les utilisateurs et le résumé financier de "
        "l'institut."
    ),
}

GENERIC_WELCOME = (
    "Pour ton profil, je peux t'aider à naviguer dans l'application et répondre "
    "à des questions générales sur son fonctionnement ; des réponses "
    "personnalisées à tes propres données arriveront prochainement."
)


def build_welcome_message(user, request, institut_config):
    """Crée (si besoin) la conversation et insère le premier message, marqué is_welcome=True."""
    from . import db_utils
    from .models import ChatMessage

    sigle = institut_config.sigle if institut_config and institut_config.sigle else 'ISI'
    bot_name = f'RYTAL-{sigle}'
    first_name = user.first_name or user.get_username()
    body = ROLE_WELCOME.get(user.role_name, GENERIC_WELCOME)

    text = f"Bonjour {first_name}, je suis {bot_name}, ton assistant virtuel. {body}"

    conversation = db_utils.get_or_create_conversation(user)
    return db_utils.create_message(
        conversation, user, role=ChatMessage.ROLE_ASSISTANT,
        content=text, is_welcome=True,
    )
