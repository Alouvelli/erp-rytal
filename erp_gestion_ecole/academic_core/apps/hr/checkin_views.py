"""
Pointage du personnel via QR code de la carte.

Règles horaires :
  - Avant 08h15               -> Présent
  - Entre 08h15 et 11h30       -> Retard
  - 11h30 et au-delà          -> Absent (fenêtre de pointage matinal dépassée)
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .services import (
    find_staff_by_token as _find_staff_by_token,
    checkin_staff,
    resolve_and_checkin_staff,
)


def pointage_self_checkin(request, token):
    """
    Scanné depuis la carte du personnel : enregistre l'arrivée (1er scan du jour)
    ou le départ (2e scan du jour), sans authentification.
    """
    employe = _find_staff_by_token(token)
    if employe is None:
        raise Http404("Carte invalide ou jeton expiré.")

    presence, action, _created = checkin_staff(employe)

    return render(request, 'hr/pointage_confirmation.html', {
        'employe':  employe,
        'presence': presence,
        'action':   action,
        'now':      timezone.localtime(timezone.now()),
    })


# ─────────────────────────────────────────────────────────────────────────────
# CONTRÔLE ACCUEIL — scan AJAX depuis l'interface web
# ─────────────────────────────────────────────────────────────────────────────

_ACCUEIL_ROLES = ('CONTROLE_ACCUEIL', 'ADMIN', 'INST_ADMIN', 'ADMIN_DIRECTION',
                  'ADMIN_DE', 'ADMIN_DAF', 'ADMIN_COM', 'ADMIN_RH', 'ASSISTANTE_DE')


@login_required
@require_http_methods(["POST"])
def accueil_staff_lookup(request):
    """
    AJAX endpoint — Contrôle Accueil.
    Body JSON: {"qr_data": "<url ou matricule>"} | {"matricule": "..."}
    Détecte les URLs /hr/pointer/{token}/ (QR de la carte personnel) ou
    cherche par matricule/nom pour la saisie manuelle.
    Enregistre automatiquement le pointage (arrivée au 1er scan du jour,
    départ au 2e).
    """
    role_name = request.user.role.name if request.user.role else ''
    if role_name not in _ACCUEIL_ROLES:
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Corps JSON invalide'}, status=400)

    raw = body.get('qr_data', '').strip() or body.get('matricule', '').strip()
    result = resolve_and_checkin_staff(raw, actor=request.user)

    if not result['found']:
        return JsonResponse({'found': False, 'message': result['message']})

    staff_user = result['staff_user']
    presence   = result['presence']

    avatar_url = None
    if staff_user.avatar:
        try:
            avatar_url = staff_user.avatar.url
        except Exception:
            pass

    return JsonResponse({
        'found':  True,
        'type':   'staff',
        'staff':  {
            'nom':    staff_user.get_full_name(),
            'role':   staff_user.role.get_name_display() if staff_user.role else '—',
            'email':  staff_user.email,
            'matricule': staff_user.matricule_employe or '—',
            'avatar': avatar_url,
        },
        'presence': {
            'action':        result['action'],
            'nouvelle':      result['created'],
            'statut':        presence.statut,
            'statut_label':  presence.get_statut_display(),
            'statut_color':  presence.statut_color,
            'heure_arrivee': presence.heure_arrivee.strftime('%H:%M') if presence.heure_arrivee else None,
            'heure_depart':  presence.heure_depart.strftime('%H:%M') if presence.heure_depart else None,
            'date':          presence.date.strftime('%d/%m/%Y'),
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# QR "Contrôle Accueil" — le personnel scanne, depuis sa propre caméra, le QR
# affiché à l'accueil (inverse de pointage_self_checkin : ici c'est le QR qui
# est fixe/partagé pour la journée, et l'identité vient de la session).
# ─────────────────────────────────────────────────────────────────────────────

def daily_accueil_token(for_date=None):
    """
    Jeton du jour dérivé de SECRET_KEY + base tenant courante + date — aucun
    stockage en base : se régénère automatiquement chaque jour et diffère par
    institut (get_current_db), sans modèle ni migration supplémentaire.
    """
    import hashlib
    from django.conf import settings
    from academic_core.db_router import get_current_db

    for_date = for_date or timezone.localdate()
    alias = get_current_db() or 'default'
    raw = f"{settings.SECRET_KEY}:accueil-checkin:{alias}:{for_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


@login_required
@require_http_methods(["POST"])
def accueil_self_checkin(request, token):
    """
    Scanné depuis 'Ma carte de pointage' / 'Pointage à l'accueil' : identité
    déduite de la session (le jeton identifie seulement le point de contrôle
    accueil pour la journée, pas la personne). Branche selon le rôle :
      - Étudiant  -> statut de paiement affiché en carte (voir
        students.services.build_student_card_status), aucun StaffPresence.
      - Personnel -> arrivée (1er scan du jour) / départ (2e scan), inchangé.
    """
    if token != daily_accueil_token():
        return JsonResponse({
            'ok': False,
            'error': "QR Code invalide ou expiré — redemandez l'affichage à l'accueil.",
        }, status=404)

    if request.user.is_etudiant():
        student = getattr(request.user, 'student_profile', None)
        if not student:
            return JsonResponse({
                'ok': False,
                'error': "Profil étudiant introuvable.",
            }, status=404)
        from academic_core.apps.students.services import build_student_card_status
        card = build_student_card_status(student)
        response_data = {'ok': True, 'type': 'student', **card}
        _record_accueil_scan_event('student', response_data)
        return JsonResponse(response_data)

    if request.user.is_super_admin():
        return JsonResponse({
            'ok': False,
            'error': "Cette fonctionnalité n'est pas disponible pour le Super Administrateur.",
        }, status=403)

    # Filet de sécurité : voir le commentaire équivalent dans
    # hr.views.ma_carte_personnel — StaffPresence a une FK vers User dans
    # cette même base tenant ; si la copie locale de l'utilisateur manque
    # (synchronisation initiale échouée silencieusement), la réparer avant
    # l'insertion plutôt que de planter sur une IntegrityError FK.
    from django.conf import settings
    from academic_core.db_router import get_current_db
    from academic_core.apps.accounts.models import User as _User
    current_alias = get_current_db()
    if current_alias and current_alias != 'default' and current_alias in settings.DATABASES \
            and not _User.objects.filter(pk=request.user.pk).exists():
        from academic_core.apps.accounts.db_utils import sync_user_to_institute_db
        sync_user_to_institute_db(request.user, current_alias)

    presence, action, _created = checkin_staff(request.user)

    avatar_url = None
    if request.user.avatar:
        try:
            avatar_url = request.user.avatar.url
        except Exception:
            pass

    response_data = {
        'ok':           True,
        'type':         'staff',
        'action':       action,
        'statut':       presence.statut,
        'statut_label': presence.get_statut_display(),
        'statut_color': presence.statut_color,
        'heure':        timezone.localtime(timezone.now()).strftime('%H:%M'),
        'nom':          request.user.get_full_name(),
        'role':         request.user.role.get_name_display() if request.user.role else '—',
        'avatar':       avatar_url,
    }
    _record_accueil_scan_event('staff', response_data)
    return JsonResponse(response_data)


def _record_accueil_scan_event(scan_type, payload):
    """Persiste le dernier résultat de pointage self-service pour que l'écran
    d'accueil (students/views.py::controle_scan) puisse l'afficher à côté du
    QR via polling — voir hr/models.py::AccueilScanEvent. Purge les lignes de
    plus d'une heure à chaque écriture (pur affichage temps réel, aucune
    valeur d'archive à conserver)."""
    from datetime import timedelta
    from .models import AccueilScanEvent
    AccueilScanEvent.objects.create(scan_type=scan_type, payload=payload)
    AccueilScanEvent.objects.filter(created_at__lt=timezone.now() - timedelta(hours=1)).delete()
