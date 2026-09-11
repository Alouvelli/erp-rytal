"""
Résolution de la base SQLite sur laquelle vivent les données RYTAL
(ChatConversation / ChatMessage) pour un utilisateur donné.

Cas particulier : le Super Admin (ADMIN) n'existe QUE dans 'default' — il
n'est jamais synchronisé vers les bases institut, par design (voir
`_get_institute_db_for_user` dans accounts/backends.py : "Uniquement le Super
Admin (ADMIN) retourne None intentionnellement : sa base est 'default'").

Le routeur (`InstitutRouter`) place pourtant `chatbot` dans TENANT_ONLY_APP_LABELS
et route toute écriture vers `get_current_db()`. Dès que le Super Admin
sélectionne un institut à visiter, `current_db` devient la base tenant de cet
institut — où sa ligne User n'existe pas. La FK ChatConversation.user_id (ou
ChatMessage.conversation_id) échoue alors avec IntegrityError, et
`/chatbot/history/` renvoie 500 ("Impossible de charger la conversation").

On force donc explicitement 'default' pour ce rôle, quel que soit le contexte
institut actif — sa conversation RYTAL reste unique et continue, comme pour
n'importe quel autre utilisateur, mais vit toujours dans 'default'.
"""


def chat_db_alias(user):
    return 'default' if user.is_super_admin() else None


def get_or_create_conversation(user):
    from .models import ChatConversation
    alias = chat_db_alias(user)
    manager = ChatConversation.objects.using(alias) if alias else ChatConversation.objects
    conversation, _created = manager.get_or_create(user=user)
    return conversation


def get_messages(conversation, user):
    from .models import ChatMessage
    alias = chat_db_alias(user)
    manager = ChatMessage.objects.using(alias) if alias else ChatMessage.objects
    return manager.filter(conversation=conversation)


def create_message(conversation, user, **kwargs):
    from .models import ChatMessage
    alias = chat_db_alias(user)
    manager = ChatMessage.objects.using(alias) if alias else ChatMessage.objects
    return manager.create(conversation=conversation, **kwargs)


def delete_messages(conversation, user):
    get_messages(conversation, user).delete()
