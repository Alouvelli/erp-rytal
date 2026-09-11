"""Stages — gestion des stagiaires externes.

Workflow : DEMANDE -> ENTRETIEN -> ACCEPTE -> EN_COURS -> TERMINE
(DEMANDE/ENTRETIEN -> REJETE). L'attestation de stage n'est disponible
qu'une fois le stage TERMINE.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import Internship, IllegalTransition, transition, log_hr_event
from .views import _hr_required, _HR_MANAGERS, _get_staff_queryset
from .pdf_hr_docs import generate_stage_attestation_pdf
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification

INTERNSHIP_TRANSITIONS = {
    ('DEMANDE', 'entretien'):   'ENTRETIEN',
    ('ENTRETIEN', 'accepter'):  'ACCEPTE',
    ('ACCEPTE', 'demarrer'):    'EN_COURS',
    ('EN_COURS', 'terminer'):   'TERMINE',
    ('DEMANDE', 'rejeter'):     'REJETE',
    ('ENTRETIEN', 'rejeter'):   'REJETE',
}

NEXT_ACTION = {
    'DEMANDE':   ('entretien', 'Passer en entretien'),
    'ENTRETIEN': ('accepter', 'Accepter le stage'),
    'ACCEPTE':   ('demarrer', 'Démarrer le stage'),
    'EN_COURS':  ('terminer', 'Terminer le stage'),
}


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


@login_required
@_hr_required
def internship_list(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:dashboard')
    internships = Internship.objects.select_related('tuteur').order_by('-date_debut')
    return render(request, 'hr/internship_list.html', {
        'internships': internships,
        'staff': _get_staff_queryset(request),
        'NEXT_ACTION': NEXT_ACTION,
    })


@login_required
@_hr_required
def internship_create(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:internship_list')
    if request.method == 'POST':
        tuteur_pk = request.POST.get('tuteur') or None
        tuteur = _get_staff_queryset(request).filter(pk=tuteur_pk).first() if tuteur_pk else None
        internship = Internship.objects.create(
            prenom=request.POST.get('prenom', '').strip(),
            nom=request.POST.get('nom', '').strip(),
            ecole=request.POST.get('ecole', '').strip(),
            sujet=request.POST.get('sujet', '').strip(),
            tuteur=tuteur,
            date_debut=request.POST.get('date_debut') or None,
            date_fin=request.POST.get('date_fin') or None,
            created_by=request.user,
        )
        log_hr_event('internship', internship.pk, request.user, 'creation', to_statut=internship.statut)
        messages.success(request, f"Demande de stage enregistrée pour {internship.prenom} {internship.nom}.")
    return redirect('hr:internship_list')


@login_required
@_hr_required
def internship_action(request, pk):
    internship = get_object_or_404(Internship.objects.select_related('tuteur'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:internship_list')
    if request.method != 'POST':
        return redirect('hr:internship_list')

    action = request.POST.get('action', '')
    from_statut = internship.statut
    try:
        new_statut = transition(INTERNSHIP_TRANSITIONS, internship.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:internship_list')

    internship.statut = new_statut
    internship.save()
    log_hr_event('internship', internship.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)

    if action == 'accepter' and internship.tuteur:
        notify_users(
            [internship.tuteur], Notification.TYPE_HR_INTERNSHIP, "Nouveau stagiaire à encadrer",
            f"Le stage de {internship.prenom} {internship.nom} a été accepté — vous êtes désigné(e) tuteur.",
            link='/hr/stages/',
        )

    messages.success(request, "Stage mis à jour.")
    return redirect('hr:internship_list')


@login_required
@_hr_required
def internship_delete(request, pk):
    internship = get_object_or_404(Internship, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:internship_list')
    if request.method == 'POST':
        internship.delete()
        messages.success(request, "Stage supprimé.")
    return redirect('hr:internship_list')


@login_required
@_hr_required
def internship_attestation_pdf(request, pk):
    internship = get_object_or_404(Internship.objects.select_related('tuteur'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:internship_list')
    if internship.statut != Internship.STATUT_TERMINE:
        messages.error(request, "L'attestation n'est disponible qu'une fois le stage terminé.")
        return redirect('hr:internship_list')
    return generate_stage_attestation_pdf(request, internship)
