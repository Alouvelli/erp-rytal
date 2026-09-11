"""Intégration (onboarding) — parcours d'accueil d'un nouvel employé.

À la création, une checklist par défaut (Onboarding.DEFAULT_TASKS) est
insérée automatiquement. Les tâches peuvent être cochées/décochées et
complétées librement ; la clôture de l'intégration est une action manuelle.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import Onboarding, OnboardingTask, log_hr_event
from .views import _hr_required, _staff_required, _HR_MANAGERS, _get_staff_queryset
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


@login_required
@_staff_required
def onboarding_list(request):
    is_manager = _is_manager(request)
    if is_manager:
        onboardings = Onboarding.objects.select_related('user').prefetch_related('taches').order_by('-date_debut')
    else:
        onboardings = Onboarding.objects.filter(user=request.user).prefetch_related('taches').order_by('-date_debut')
    return render(request, 'hr/onboarding_list.html', {
        'onboardings': onboardings, 'is_manager': is_manager,
        'staff': _get_staff_queryset(request) if is_manager else None,
    })


@login_required
@_hr_required
def onboarding_create(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:onboarding_list')
    if request.method == 'POST':
        employe = get_object_or_404(_get_staff_queryset(request), pk=request.POST.get('user'))
        onboarding = Onboarding.objects.create(
            user=employe,
            date_debut=request.POST.get('date_debut') or None,
            created_by=request.user,
        )
        OnboardingTask.objects.bulk_create([
            OnboardingTask(onboarding=onboarding, libelle=libelle, ordre=i)
            for i, libelle in enumerate(Onboarding.DEFAULT_TASKS)
        ])
        log_hr_event('onboarding', onboarding.pk, request.user, 'creation', to_statut=onboarding.statut)
        notify_users(
            [employe], Notification.TYPE_HR_ONBOARDING, "Bienvenue !",
            "Votre parcours d'intégration a démarré.", link='/hr/onboarding/',
        )
        messages.success(request, f"Intégration démarrée pour {employe.get_full_name()}.")
    return redirect('hr:onboarding_list')


@login_required
@_staff_required
def onboarding_detail(request, pk):
    onboarding = get_object_or_404(Onboarding.objects.select_related('user'), pk=pk)
    is_manager = _is_manager(request)
    if not is_manager and onboarding.user_id != request.user.pk:
        messages.error(request, "Accès refusé.")
        return redirect('hr:onboarding_list')
    return render(request, 'hr/onboarding_detail.html', {
        'onboarding': onboarding, 'is_manager': is_manager,
        'taches': onboarding.taches.all(),
    })


@login_required
@_hr_required
def onboarding_task_toggle(request, pk):
    task = get_object_or_404(OnboardingTask, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:onboarding_detail', pk=task.onboarding_id)
    if request.method == 'POST':
        task.fait = not task.fait
        task.save()
    return redirect('hr:onboarding_detail', pk=task.onboarding_id)


@login_required
@_hr_required
def onboarding_task_create(request, pk):
    onboarding = get_object_or_404(Onboarding, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:onboarding_detail', pk=pk)
    if request.method == 'POST':
        max_ordre = onboarding.taches.count()
        OnboardingTask.objects.create(
            onboarding=onboarding,
            libelle=request.POST.get('libelle', '').strip(),
            responsable=request.POST.get('responsable', 'RH'),
            ordre=max_ordre,
        )
        messages.success(request, "Tâche ajoutée.")
    return redirect('hr:onboarding_detail', pk=pk)


@login_required
@_hr_required
def onboarding_complete(request, pk):
    onboarding = get_object_or_404(Onboarding.objects.select_related('user'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:onboarding_detail', pk=pk)
    if request.method == 'POST':
        onboarding.statut = Onboarding.STATUT_TERMINE
        onboarding.save()
        log_hr_event('onboarding', onboarding.pk, request.user, 'cloture', to_statut=onboarding.statut)
        messages.success(request, "Intégration clôturée.")
    return redirect('hr:onboarding_detail', pk=pk)
