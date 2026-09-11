import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from . import llm, rule_engine, welcome
from . import db_utils


def _get_institut_config(request):
    from academic_core.apps.academic_structure.models import InstitutConfig
    faculty = getattr(request, 'active_faculty', None)
    if not faculty:
        return None
    try:
        return InstitutConfig.objects.using('default').get(faculty=faculty)
    except InstitutConfig.DoesNotExist:
        return None


def _serialize(message):
    return {
        'role': message.role,
        'content': message.content,
        'created_at': message.created_at.isoformat(),
    }


@login_required
@require_http_methods(['GET'])
def chat_history(request):
    conversation = db_utils.get_or_create_conversation(request.user)
    if not db_utils.get_messages(conversation, request.user).exists():
        welcome.build_welcome_message(request.user, request, _get_institut_config(request))

    messages = db_utils.get_messages(conversation, request.user).order_by('created_at')
    return JsonResponse({'messages': [_serialize(m) for m in messages]})


@login_required
@ratelimit(key='user', rate='20/m', method='POST', block=False)
@require_http_methods(['POST'])
def chat_send(request):
    if getattr(request, 'limited', False):
        return JsonResponse(
            {'error': "Trop de messages envoyés d'un coup, merci de patienter un instant."},
            status=429,
        )

    try:
        payload = json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Requête invalide.'}, status=400)

    text = (payload.get('message') or '').strip()
    if not text:
        return JsonResponse({'error': 'Message vide.'}, status=400)
    if len(text) > settings.CHATBOT_MAX_MESSAGE_LENGTH:
        return JsonResponse({'error': 'Message trop long.'}, status=400)

    conversation = db_utils.get_or_create_conversation(request.user)
    if not db_utils.get_messages(conversation, request.user).exists():
        welcome.build_welcome_message(request.user, request, _get_institut_config(request))

    user_message = db_utils.create_message(conversation, request.user, role='user', content=text)

    institut_config = _get_institut_config(request)
    if settings.CHATBOT_USE_LLM:
        reply_text = llm.run_chat_turn(request, conversation, text, institut_config)
    else:
        reply_text = rule_engine.respond(request, conversation, text, institut_config)
    assistant_message = db_utils.create_message(conversation, request.user, role='assistant', content=reply_text)

    return JsonResponse({
        'user_message': _serialize(user_message),
        'reply': _serialize(assistant_message),
    })


@login_required
@require_http_methods(['POST'])
def chat_reset(request):
    conversation = db_utils.get_or_create_conversation(request.user)
    db_utils.delete_messages(conversation, request.user)
    welcome.build_welcome_message(request.user, request, _get_institut_config(request))
    return JsonResponse({'status': 'ok'})
