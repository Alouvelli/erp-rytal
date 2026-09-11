from celery import shared_task
from django.utils import timezone


@shared_task
def cleanup_expired_tokens():
    """Supprime les tokens de réinitialisation expirés."""
    from .models import PasswordResetToken
    deleted, _ = PasswordResetToken.objects.filter(
        expires_at__lt=timezone.now()
    ).delete()
    return {'deleted_tokens': deleted}
