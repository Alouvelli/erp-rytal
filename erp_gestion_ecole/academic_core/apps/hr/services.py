"""
Résolution + pointage du personnel — logique partagée entre :
  - hr.checkin_views.pointage_self_checkin / accueil_self_checkin (scan de sa
    propre carte, ou du QR fixe affiché à l'accueil)
  - hr.checkin_views.accueil_staff_lookup (AJAX Contrôle Accueil, hr app)
  - students.views.controle_scan_lookup (AJAX Contrôle Accueil, students app)

Centralisée ici pour que les 3 points d'entrée appliquent exactement la même
règle horaire et le même toggle arrivée → départ.
"""
import re
from datetime import time as dtime

from django.db.models import Q
from django.utils import timezone

from .models import StaffPresence

HEURE_LIMITE_PRESENT = dtime(8, 15)
HEURE_LIMITE_RETARD  = dtime(11, 30)

# URL du QR au verso de la carte personnel : /hr/pointer/<token>/
TOKEN_URL_RE = re.compile(r'/hr/pointer/([^/?#]+)/')


def compute_statut(now_time):
    if now_time < HEURE_LIMITE_PRESENT:
        return StaffPresence.STATUT_PRESENT
    if now_time < HEURE_LIMITE_RETARD:
        return StaffPresence.STATUT_RETARD
    return StaffPresence.STATUT_ABSENT


def find_staff_by_token(token):
    """
    Cherche l'employé par jeton QR dans toutes les bases tenant connues.
    Pointe le thread-local vers la bonne base si trouvé hors de la base courante.
    """
    from django.conf import settings
    from academic_core.apps.accounts.models import User
    from academic_core.db_router import set_current_db, get_current_db

    try:
        return User.objects.get(staff_qr_token=token, is_active=True)
    except User.DoesNotExist:
        pass

    current = get_current_db()
    for alias in settings.DATABASES:
        if alias == current:
            continue
        try:
            emp = User.objects.using(alias).get(staff_qr_token=token, is_active=True)
            set_current_db(alias)
            return emp
        except User.DoesNotExist:
            continue
    return None


def resolve_staff_from_text(raw_text):
    """
    Résout un membre du personnel à partir d'un texte scanné/saisi :
    URL /hr/pointer/<token>/ (QR carte), matricule, email ou nom.
    Retourne (staff_user, error_message) — error_message est None si trouvé,
    ou déjà renseigné pour le cas "jeton invalide" (distinct du cas
    "non trouvé du tout", que l'appelant peut vouloir traiter différemment).
    """
    from academic_core.apps.accounts.models import User
    from academic_core.apps.teachers.models import Teacher

    raw = (raw_text or '').strip()
    if not raw:
        return None, None

    m = TOKEN_URL_RE.search(raw)
    if m:
        staff_user = find_staff_by_token(m.group(1))
        if staff_user is None:
            return None, 'Carte invalide ou jeton expiré.'
        return staff_user, None

    vacataire_ids = Teacher.objects.filter(
        statut=Teacher.STATUT_VACATAIRE
    ).values_list('user_id', flat=True)
    base_qs = User.objects.select_related('role').filter(
        is_active=True
    ).exclude(role__name='ETUDIANT').exclude(pk__in=vacataire_ids)

    staff_user = base_qs.filter(matricule_employe__iexact=raw).first()
    if not staff_user:
        staff_user = base_qs.filter(
            Q(email__iexact=raw) |
            Q(first_name__icontains=raw) |
            Q(last_name__icontains=raw)
        ).first()
    return staff_user, None


def checkin_staff(staff_user, actor=None):
    """
    Enregistre le pointage du jour pour cet employé : arrivée au 1er scan,
    départ au 2e, 'déjà complet' au-delà. Retourne (presence, action, created).
    """
    today     = timezone.localdate()
    now_local = timezone.localtime(timezone.now())
    now_time  = now_local.time().replace(second=0, microsecond=0)

    presence = StaffPresence.objects.filter(user=staff_user, date=today).first()
    created = False
    if presence is None:
        presence = StaffPresence.objects.create(
            user=staff_user, date=today, statut=compute_statut(now_time),
            heure_arrivee=now_time, enregistre_par=actor,
        )
        created = True
        action = 'arrivee'
    elif not presence.heure_depart:
        presence.heure_depart = now_time
        presence.save(update_fields=['heure_depart', 'updated_at'])
        action = 'depart'
    else:
        action = 'deja_complet'

    return presence, action, created


def resolve_and_checkin_staff(raw_text, actor=None):
    """
    Résout un employé depuis un texte scanné/saisi et enregistre son pointage
    du jour. Retourne :
      {'found': False, 'message': ...}
      {'found': True, 'staff_user':..., 'presence':..., 'action': 'arrivee'|'depart'|'deja_complet', 'created': bool}
    """
    staff_user, error = resolve_staff_from_text(raw_text)
    if error:
        return {'found': False, 'message': error}
    if staff_user is None:
        return {'found': False, 'message': 'Aucun employé trouvé pour cette référence.'}

    presence, action, created = checkin_staff(staff_user, actor=actor)
    return {
        'found': True,
        'staff_user': staff_user,
        'presence': presence,
        'action': action,
        'created': created,
    }
