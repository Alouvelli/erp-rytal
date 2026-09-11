"""Évaluations — campagnes d'évaluation annuelles du personnel.

Workflow évaluation : A_FAIRE -> AUTO_EVALUEE -> EVALUEE -> FINALISEE.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import EvaluationCampaign, Evaluation, EvaluationObjective, IllegalTransition, transition, log_hr_event
from .views import _hr_required, _staff_required, _HR_MANAGERS, _get_staff_queryset
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification

EVALUATION_TRANSITIONS = {
    ('A_FAIRE', 'auto_evaluer'):          'AUTO_EVALUEE',
    ('AUTO_EVALUEE', 'evaluer'):          'EVALUEE',
    ('EVALUEE', 'prendre_connaissance'):  'FINALISEE',
}


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


# ── Campagnes ────────────────────────────────────────────────────────────────

@login_required
@_hr_required
def evaluation_campaign_list(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:evaluation_list')
    campaigns = EvaluationCampaign.objects.all()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            EvaluationCampaign.objects.create(
                annee=request.POST.get('annee'),
                label=request.POST.get('label', '').strip(),
            )
            messages.success(request, "Campagne créée.")
        elif action == 'open':
            campaign = get_object_or_404(EvaluationCampaign, pk=request.POST.get('campaign_id'))
            campaign.statut = EvaluationCampaign.STATUT_OUVERTE
            campaign.save()
            staff = _get_staff_queryset(request)
            existing_ids = set(campaign.evaluations.values_list('user_id', flat=True))
            new_evals = [
                Evaluation(campaign=campaign, user=u)
                for u in staff if u.pk not in existing_ids
            ]
            Evaluation.objects.bulk_create(new_evals)
            notify_users(
                list(staff), Notification.TYPE_HR_EVALUATION,
                "Campagne d'évaluation ouverte",
                f"La campagne « {campaign.label} » est ouverte. Merci de compléter votre auto-évaluation.",
                link='/hr/evaluations/',
            )
            messages.success(request, f"Campagne ouverte — {len(new_evals)} évaluation(s) créée(s).")
        elif action == 'close':
            campaign = get_object_or_404(EvaluationCampaign, pk=request.POST.get('campaign_id'))
            campaign.statut = EvaluationCampaign.STATUT_CLOTUREE
            campaign.save()
            messages.success(request, "Campagne clôturée.")
        elif action == 'delete':
            campaign = get_object_or_404(EvaluationCampaign, pk=request.POST.get('campaign_id'))
            if campaign.evaluations.exists():
                messages.error(request, f"Impossible de supprimer : {campaign.evaluations.count()} évaluation(s) rattachée(s).")
            else:
                campaign.delete()
                messages.success(request, "Campagne supprimée.")
        return redirect('hr:evaluation_campaign_list')
    return render(request, 'hr/evaluation_campaign_list.html', {'campaigns': campaigns})


# ── Évaluations ──────────────────────────────────────────────────────────────

@login_required
@_staff_required
def evaluation_list(request):
    is_manager = _is_manager(request)
    if is_manager and request.GET.get('vue') == 'toutes':
        evaluations = Evaluation.objects.select_related('user', 'campaign').order_by('-campaign__annee', 'user__last_name')
    else:
        evaluations = Evaluation.objects.filter(user=request.user).select_related('campaign').order_by('-campaign__annee')
    return render(request, 'hr/evaluation_list.html', {
        'evaluations': evaluations, 'is_manager': is_manager,
        'vue': request.GET.get('vue', 'mine'),
    })


@login_required
@_staff_required
def evaluation_detail(request, pk):
    evaluation = get_object_or_404(Evaluation.objects.select_related('user', 'campaign'), pk=pk)
    is_manager = _is_manager(request)
    is_self = evaluation.user_id == request.user.pk
    if not (is_manager or is_self):
        messages.error(request, "Accès refusé.")
        return redirect('hr:evaluation_list')
    return render(request, 'hr/evaluation_detail.html', {
        'evaluation': evaluation, 'is_manager': is_manager, 'is_self': is_self,
        'objectifs': evaluation.objectifs.all(),
    })


@login_required
@_staff_required
def evaluation_action(request, pk):
    evaluation = get_object_or_404(Evaluation.objects.select_related('user'), pk=pk)
    is_manager = _is_manager(request)
    is_self = evaluation.user_id == request.user.pk
    if request.method != 'POST':
        return redirect('hr:evaluation_detail', pk=pk)

    action = request.POST.get('action', '')
    if action == 'auto_evaluer' and not is_self:
        messages.error(request, "Seul l'employé concerné peut s'auto-évaluer.")
        return redirect('hr:evaluation_detail', pk=pk)
    if action == 'evaluer' and not is_manager:
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:evaluation_detail', pk=pk)
    if action == 'prendre_connaissance' and not is_self:
        messages.error(request, "Seul l'employé concerné peut prendre connaissance de son évaluation.")
        return redirect('hr:evaluation_detail', pk=pk)

    from_statut = evaluation.statut
    try:
        new_statut = transition(EVALUATION_TRANSITIONS, evaluation.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:evaluation_detail', pk=pk)

    if action == 'auto_evaluer':
        evaluation.auto_evaluation = request.POST.get('auto_evaluation', '').strip()
        evaluation.souhait_carriere = request.POST.get('souhait_carriere', '').strip()
    elif action == 'evaluer':
        evaluation.evaluation_manager = request.POST.get('evaluation_manager', '').strip()
        note = request.POST.get('note_globale') or None
        evaluation.note_globale = note
        evaluation.evaluated_by = request.user
        evaluation.objectifs.all().delete()
        libelles = request.POST.getlist('objectif_libelle')
        poids_list = request.POST.getlist('objectif_poids')
        resultats = request.POST.getlist('objectif_resultat')
        for libelle, poids, resultat in zip(libelles, poids_list, resultats):
            if libelle.strip():
                EvaluationObjective.objects.create(
                    evaluation=evaluation, libelle=libelle.strip(),
                    poids=poids or 1, resultat=resultat.strip(),
                )

    evaluation.statut = new_statut
    evaluation.save()
    log_hr_event('evaluation', evaluation.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)

    if action == 'evaluer':
        notify_users(
            [evaluation.user], Notification.TYPE_HR_EVALUATION,
            "Votre évaluation est disponible",
            f"Votre responsable a complété votre évaluation ({evaluation.campaign.label}).",
            link='/hr/evaluations/',
        )

    messages.success(request, "Évaluation mise à jour.")
    return redirect('hr:evaluation_detail', pk=pk)
