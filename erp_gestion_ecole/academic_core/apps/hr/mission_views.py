"""Missions — ordres de mission et suivi des déplacements professionnels.

Workflow : SOUMISE -> VALIDEE -> EFFECTUEE -> RAPPORT_REMIS (ou REJETEE
depuis SOUMISE). Auto-service : chaque agent crée ses propres missions ;
la validation est réservée aux gestionnaires RH.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import Mission, IllegalTransition, transition, log_hr_event
from .views import _staff_required, _HR_MANAGERS
from .pdf_hr_docs import generate_ordre_mission_pdf
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification

MISSION_TRANSITIONS = {
    ('SOUMISE', 'valider'):           'VALIDEE',
    ('SOUMISE', 'rejeter'):           'REJETEE',
    ('VALIDEE', 'effectuer'):         'EFFECTUEE',
    ('EFFECTUEE', 'remettre_rapport'): 'RAPPORT_REMIS',
}


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


@login_required
@_staff_required
def mission_list(request):
    is_manager = _is_manager(request)
    if is_manager and request.GET.get('vue') == 'toutes':
        missions = Mission.objects.select_related('user').order_by('-date_debut')
    else:
        missions = Mission.objects.filter(user=request.user).order_by('-date_debut')
    return render(request, 'hr/mission_list.html', {
        'missions': missions, 'is_manager': is_manager, 'vue': request.GET.get('vue', 'mine'),
    })


@login_required
@_staff_required
def mission_create(request):
    if request.method == 'POST':
        mission = Mission.objects.create(
            user=request.user,
            objet=request.POST.get('objet', '').strip(),
            destination=request.POST.get('destination', '').strip(),
            date_debut=request.POST.get('date_debut') or None,
            date_fin=request.POST.get('date_fin') or None,
        )
        log_hr_event('mission', mission.pk, request.user, 'soumission', to_statut=mission.statut)
        messages.success(request, "Mission soumise.")
    return redirect('hr:mission_list')


@login_required
@_staff_required
def mission_action(request, pk):
    mission = get_object_or_404(Mission.objects.select_related('user'), pk=pk)
    is_manager = _is_manager(request)
    is_self = mission.user_id == request.user.pk
    if request.method != 'POST':
        return redirect('hr:mission_list')

    action = request.POST.get('action', '')
    if action in ('valider', 'rejeter') and not is_manager:
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:mission_list')
    if action in ('effectuer', 'remettre_rapport') and not (is_self or is_manager):
        messages.error(request, "Accès refusé.")
        return redirect('hr:mission_list')

    from_statut = mission.statut
    try:
        new_statut = transition(MISSION_TRANSITIONS, mission.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:mission_list')

    if action == 'remettre_rapport':
        mission.rapport = request.POST.get('rapport', '').strip()
    if action == 'valider':
        mission.validated_by = request.user

    mission.statut = new_statut
    mission.save()
    log_hr_event('mission', mission.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)

    if action == 'valider':
        notify_users([mission.user], Notification.TYPE_HR_MISSION, "Mission validée",
                      f"Votre mission « {mission.objet} » a été validée.", link='/hr/missions/')
    elif action == 'rejeter':
        notify_users([mission.user], Notification.TYPE_HR_MISSION, "Mission rejetée",
                      f"Votre mission « {mission.objet} » a été rejetée.", priority='HIGH', link='/hr/missions/')

    messages.success(request, "Mission mise à jour.")
    return redirect('hr:mission_list')


@login_required
@_staff_required
def mission_delete(request, pk):
    mission = get_object_or_404(Mission, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:mission_list')
    if request.method == 'POST':
        mission.delete()
        messages.success(request, "Mission supprimée.")
    return redirect('hr:mission_list')


@login_required
@_staff_required
def mission_order_pdf(request, pk):
    mission = get_object_or_404(Mission.objects.select_related('user'), pk=pk)
    is_manager = _is_manager(request)
    if not (is_manager or mission.user_id == request.user.pk):
        messages.error(request, "Accès refusé.")
        return redirect('hr:mission_list')
    if mission.statut in (Mission.STATUT_SOUMISE, Mission.STATUT_REJETEE):
        messages.error(request, "L'ordre de mission n'est disponible qu'après validation.")
        return redirect('hr:mission_list')
    return generate_ordre_mission_pdf(request, mission)
