from django.conf import settings
from django.db import models


class ChatConversation(models.Model):
    """Conversation RYTAL unique et continue par utilisateur."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='chatbot_conversation',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_conversations'
        verbose_name = 'Conversation RYTAL'
        verbose_name_plural = 'Conversations RYTAL'

    def __str__(self):
        return f"Conversation RYTAL — {self.user}"


class ChatMessage(models.Model):
    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_CHOICES = [
        (ROLE_USER, 'Utilisateur'),
        (ROLE_ASSISTANT, 'RYTAL'),
    ]

    conversation = models.ForeignKey(
        ChatConversation, on_delete=models.CASCADE, related_name='messages',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    is_welcome = models.BooleanField(
        default=False,
        help_text="Message de bienvenue généré automatiquement, exclu du contexte envoyé au LLM.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chatbot_messages'
        verbose_name = 'Message RYTAL'
        verbose_name_plural = 'Messages RYTAL'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.role}] {self.content[:50]}"
