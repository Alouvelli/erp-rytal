"""Intérims & Passations de service — couverture temporaire de poste.

Interim  : ACTIVE -> CLOTUREE (pas de réouverture).
Handover : SOUMISE -> VALIDEE (pas de rejet).
Création réservée aux gestionnaires RH dans les deux cas ; consultation
« mine » ouverte aux personnes concernées (titulaire/intérimaire, sortant/entrant).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.dateparse import parse_date

from .models import Interim, Handover, log_hr_event
from .views import _hr_required, _staff_required, _HR_MANAGERS, _get_staff_queryset
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


# ── Intérims ─────────────────────────────────────────────────────────────────

@login_required
@_staff_required
def interim_list(request):
    is_manager = _is_manager(request)
    if is_manager and request.GET.get('vue') == 'toutes':
        interims = Interim.objects.select_related('titulaire', 'interimaire').order_by('-date_debut')
    else:
        interims = Interim.objects.filter(
            Q(titulaire=request.user) | Q(interimaire=request.user)
        ).select_related('titulaire', 'interimaire').order_by('-date_debut')
    return render(request, 'hr/interim_list.html', {
        'interims': interims, 'is_manager': is_manager, 'vue': request.GET.get('vue', 'mine'),
        'staff': _get_staff_queryset(request) if is_manager else None,
    })


@login_required
@_hr_required
def interim_create(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:interim_list')
    if request.method == 'POST':
        staff = _get_staff_queryset(request)
        titulaire = get_object_or_404(staff, pk=request.POST.get('titulaire'))
        interimaire = get_object_or_404(staff, pk=request.POST.get('interimaire'))
        date_debut = parse_date(request.POST.get('date_debut', ''))
        date_fin = parse_date(request.POST.get('date_fin', ''))
        interim = Interim.objects.create(
            titulaire=titulaire, interimaire=interimaire,
            motif=request.POST.get('motif', Interim.MOTIF_AUTRE),
            date_debut=date_debut, date_fin=date_fin,
            note=request.POST.get('note', '').strip(),
            created_by=request.user,
        )
        log_hr_event('interim', interim.pk, request.user, 'creation', to_statut=interim.statut)
        notify_users(
            [titulaire, interimaire], Notification.TYPE_HR_INTERIM, "Intérim mis en place",
            f"Un intérim a été enregistré du {date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}.",
            link='/hr/interims/',
        )
        messages.success(request, "Intérim enregistré.")
    return redirect('hr:interim_list')


@login_required
@_hr_required
def interim_close(request, pk):
    interim = get_object_or_404(Interim, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:interim_list')
    if request.method == 'POST':
        interim.statut = Interim.STATUT_CLOTUREE
        interim.save()
        log_hr_event('interim', interim.pk, request.user, 'cloture', to_statut=interim.statut)
        messages.success(request, "Intérim clôturé.")
    return redirect('hr:interim_list')


@login_required
@_hr_required
def interim_delete(request, pk):
    interim = get_object_or_404(Interim, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:interim_list')
    if request.method == 'POST':
        interim.delete()
        messages.success(request, "Intérim supprimé.")
    return redirect('hr:interim_list')


# ── Passations de service ─────────────────────────────────────────────────────

@login_required
@_staff_required
def handover_list(request):
    is_manager = _is_manager(request)
    if is_manager and request.GET.get('vue') == 'toutes':
        handovers = Handover.objects.select_related('sortant', 'entrant').order_by('-date_passation')
    else:
        handovers = Handover.objects.filter(
            Q(sortant=request.user) | Q(entrant=request.user)
        ).select_related('sortant', 'entrant').order_by('-date_passation')
    return render(request, 'hr/passation_list.html', {
        'handovers': handovers, 'is_manager': is_manager, 'vue': request.GET.get('vue', 'mine'),
        'staff': _get_staff_queryset(request) if is_manager else None,
    })


@login_required
@_hr_required
def handover_create(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:handover_list')
    if request.method == 'POST':
        staff = _get_staff_queryset(request)
        sortant = get_object_or_404(staff, pk=request.POST.get('sortant'))
        entrant = get_object_or_404(staff, pk=request.POST.get('entrant'))
        handover = Handover.objects.create(
            sortant=sortant, entrant=entrant,
            poste=request.POST.get('poste', '').strip(),
            date_passation=request.POST.get('date_passation') or None,
            elements_transferes=request.POST.get('elements_transferes', '').strip(),
            created_by=request.user,
        )
        log_hr_event('handover', handover.pk, request.user, 'creation', to_statut=handover.statut)
        notify_users(
            [sortant, entrant], Notification.TYPE_HR_HANDOVER, "Passation de service",
            f"Une passation de service pour le poste « {handover.poste} » a été enregistrée.",
            link='/hr/passations/',
        )
        messages.success(request, "Passation de service enregistrée.")
    return redirect('hr:handover_list')


@login_required
@_hr_required
def handover_validate(request, pk):
    handover = get_object_or_404(Handover, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:handover_list')
    if request.method == 'POST':
        handover.statut = Handover.STATUT_VALIDEE
        handover.save()
        log_hr_event('handover', handover.pk, request.user, 'validation', to_statut=handover.statut)
        messages.success(request, "Passation validée.")
    return redirect('hr:handover_list')


@login_required
@_hr_required
def handover_delete(request, pk):
    handover = get_object_or_404(Handover, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:handover_list')
    if request.method == 'POST':
        handover.delete()
        messages.success(request, "Passation supprimée.")
    return redirect('hr:handover_list')
