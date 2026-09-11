"""Discipline — dossiers disciplinaires du personnel.

Workflow : DEMANDE_EXPLICATION -> REPONSE_RECUE -> CONSEIL -> SANCTION|CLASSE
(CLASSE accessible aussi directement depuis DEMANDE_EXPLICATION/REPONSE_RECUE).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import DisciplinaryCase, IllegalTransition, transition, log_hr_event
from .views import _hr_required, _staff_required, _HR_MANAGERS, _get_staff_queryset
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification

DISCIPLINE_TRANSITIONS = {
    ('DEMANDE_EXPLICATION', 'repondre'):          'REPONSE_RECUE',
    ('REPONSE_RECUE', 'convoquer_conseil'):        'CONSEIL',
    ('CONSEIL', 'sanctionner'):                    'SANCTION',
    ('CONSEIL', 'classer'):                        'CLASSE',
    ('DEMANDE_EXPLICATION', 'classer'):            'CLASSE',
    ('REPONSE_RECUE', 'classer'):                  'CLASSE',
}

NEXT_ACTION = {
    'DEMANDE_EXPLICATION': ('repondre', 'Enregistrer la réponse'),
    'REPONSE_RECUE':       ('convoquer_conseil', 'Convoquer le conseil'),
    'CONSEIL':             ('sanctionner', 'Prononcer une sanction'),
}


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


@login_required
@_staff_required
def discipline_list(request):
    is_manager = _is_manager(request)
    if is_manager:
        cases = DisciplinaryCase.objects.select_related('user', 'initiated_by').order_by('-created_at')
    else:
        cases = DisciplinaryCase.objects.filter(user=request.user).select_related('user').order_by('-created_at')
    return render(request, 'hr/discipline_list.html', {
        'cases':      cases,
        'is_manager': is_manager,
        'staff':      _get_staff_queryset(request) if is_manager else None,
    })


@login_required
@_hr_required
def discipline_create(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:discipline_list')
    if request.method == 'POST':
        user_pk = request.POST.get('user')
        employe = get_object_or_404(_get_staff_queryset(request), pk=user_pk)
        case = DisciplinaryCase.objects.create(
            user=employe,
            motif=request.POST.get('motif', '').strip(),
            initiated_by=request.user,
        )
        log_hr_event('discipline', case.pk, request.user, 'ouverture', to_statut=case.statut)
        notify_users(
            [employe], Notification.TYPE_HR_DISCIPLINE,
            "Demande d'explication",
            f"Un dossier disciplinaire a été ouvert vous concernant : {case.motif[:120]}",
            priority='HIGH', link='/hr/discipline/',
        )
        messages.success(request, f"Dossier disciplinaire ouvert pour {employe.get_full_name()}.")
        return redirect('hr:discipline_detail', pk=case.pk)
    return redirect('hr:discipline_list')


@login_required
@_staff_required
def discipline_detail(request, pk):
    case = get_object_or_404(DisciplinaryCase.objects.select_related('user', 'initiated_by'), pk=pk)
    is_manager = _is_manager(request)
    if not is_manager and case.user_id != request.user.pk:
        messages.error(request, "Accès refusé.")
        return redirect('hr:discipline_list')
    next_action = NEXT_ACTION.get(case.statut)
    return render(request, 'hr/discipline_detail.html', {
        'case': case, 'is_manager': is_manager, 'next_action': next_action,
    })


@login_required
@_hr_required
def discipline_action(request, pk):
    case = get_object_or_404(DisciplinaryCase.objects.select_related('user'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:discipline_detail', pk=pk)
    if request.method != 'POST':
        return redirect('hr:discipline_detail', pk=pk)

    action = request.POST.get('action', '')
    from_statut = case.statut
    try:
        new_statut = transition(DISCIPLINE_TRANSITIONS, case.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:discipline_detail', pk=pk)

    if action == 'repondre':
        case.explication = request.POST.get('explication', '').strip()
    elif action == 'sanctionner':
        case.sanction_type = request.POST.get('sanction_type', '')
        case.decision = request.POST.get('decision', '').strip()
    elif action == 'classer':
        case.decision = request.POST.get('decision', '').strip() or case.decision

    case.statut = new_statut
    case.save()
    log_hr_event('discipline', case.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)

    if new_statut == DisciplinaryCase.STATUT_SANCTION:
        notify_users(
            [case.user], Notification.TYPE_HR_DISCIPLINE,
            "Décision disciplinaire",
            f"Une sanction a été prononcée : {case.get_sanction_type_display()}.",
            priority='HIGH', link='/hr/discipline/',
        )
    elif new_statut == DisciplinaryCase.STATUT_CLASSE:
        notify_users(
            [case.user], Notification.TYPE_HR_DISCIPLINE,
            "Dossier disciplinaire classé",
            "Votre dossier disciplinaire a été classé sans suite.",
            link='/hr/discipline/',
        )

    messages.success(request, "Dossier mis à jour.")
    return redirect('hr:discipline_detail', pk=pk)


@login_required
@_hr_required
def discipline_delete(request, pk):
    case = get_object_or_404(DisciplinaryCase, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:discipline_list')
    if request.method == 'POST':
        case.delete()
        messages.success(request, "Dossier disciplinaire supprimé.")
    return redirect('hr:discipline_list')
