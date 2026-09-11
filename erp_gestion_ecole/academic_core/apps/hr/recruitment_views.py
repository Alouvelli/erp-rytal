"""Recrutement — besoins de recrutement et suivi des candidats.

Workflow besoin      : SOUMISE -> VALIDEE -> EN_COURS -> POURVUE (ou REJETEE
                        depuis SOUMISE/VALIDEE).
Workflow candidat     : CANDIDATURE -> PRESELECTIONNE -> ENTRETIEN -> RETENU
                        (REJETE possible depuis les 3 premiers statuts).
« Embaucher » (candidat RETENU) crée un compte User + FichePersonnel et une
ligne de carrière (Assignment, type=RECRUTEMENT) — pas de modèle Employee
séparé, cf. décision d'architecture #1 du plan.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import RecruitmentRequest, Candidate, IllegalTransition, transition, log_hr_event, Assignment
from .views import _hr_required, _HR_MANAGERS, _generate_matricule
from academic_core.apps.accounts.models import User, Role
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification

REQUEST_TRANSITIONS = {
    ('SOUMISE', 'valider'):   'VALIDEE',
    ('VALIDEE', 'diffuser'):  'EN_COURS',
    ('EN_COURS', 'pourvoir'): 'POURVUE',
    ('SOUMISE', 'rejeter'):   'REJETEE',
    ('VALIDEE', 'rejeter'):   'REJETEE',
}
REQUEST_NEXT = {
    'SOUMISE':  ('valider', 'Valider'),
    'VALIDEE':  ('diffuser', 'Diffuser'),
    'EN_COURS': ('pourvoir', 'Marquer pourvue'),
}

CANDIDATE_TRANSITIONS = {
    ('CANDIDATURE', 'preselectionner'): 'PRESELECTIONNE',
    ('PRESELECTIONNE', 'entretien'):    'ENTRETIEN',
    ('ENTRETIEN', 'retenir'):           'RETENU',
    ('CANDIDATURE', 'rejeter'):         'REJETE',
    ('PRESELECTIONNE', 'rejeter'):      'REJETE',
    ('ENTRETIEN', 'rejeter'):           'REJETE',
}
CANDIDATE_NEXT = {
    'CANDIDATURE':    ('preselectionner', 'Présélectionner'),
    'PRESELECTIONNE': ('entretien', 'Passer en entretien'),
    'ENTRETIEN':      ('retenir', 'Retenir'),
}


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


@login_required
@_hr_required
def recruitment_list(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:dashboard')
    requests_qs = RecruitmentRequest.objects.select_related('demande_par', 'department').prefetch_related('candidats').order_by('-created_at')
    from academic_core.apps.academic_structure.models import Department
    departments = Department.objects.filter(is_active=True).order_by('name')
    # Rôles assignables à l'embauche : on exclut ADMIN/INST_ADMIN/SI_ADMIN, qui
    # suivent un circuit de création dédié (double écriture vers 'default').
    roles = Role.objects.exclude(name__in=['ADMIN', 'INST_ADMIN', 'SI_ADMIN']).order_by('name')
    return render(request, 'hr/recruitment_list.html', {
        'requests': requests_qs, 'departments': departments, 'roles': roles,
        'REQUEST_NEXT': REQUEST_NEXT, 'CANDIDATE_NEXT': CANDIDATE_NEXT,
    })


@login_required
@_hr_required
def recruitment_create(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:recruitment_list')
    if request.method == 'POST':
        from academic_core.apps.academic_structure.models import Department
        dept_id = request.POST.get('department') or None
        dept = Department.objects.filter(pk=dept_id).first() if dept_id else None
        req = RecruitmentRequest.objects.create(
            demande_par=request.user,
            titre=request.POST.get('titre', '').strip(),
            department=dept,
            poste=request.POST.get('poste', '').strip(),
            mode=request.POST.get('mode', RecruitmentRequest.MODE_EXTERNE),
            description=request.POST.get('description', '').strip(),
        )
        log_hr_event('recruitment_request', req.pk, request.user, 'creation', to_statut=req.statut)
        messages.success(request, f"Besoin de recrutement « {req.titre} » créé.")
    return redirect('hr:recruitment_list')


@login_required
@_hr_required
def recruitment_action(request, pk):
    req = get_object_or_404(RecruitmentRequest, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:recruitment_list')
    if request.method != 'POST':
        return redirect('hr:recruitment_list')
    action = request.POST.get('action', '')
    from_statut = req.statut
    try:
        new_statut = transition(REQUEST_TRANSITIONS, req.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:recruitment_list')
    req.statut = new_statut
    req.save()
    log_hr_event('recruitment_request', req.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)
    if req.demande_par:
        notify_users([req.demande_par], Notification.TYPE_HR_RECRUITMENT,
                     "Besoin de recrutement mis à jour",
                     f"« {req.titre} » est maintenant « {req.get_statut_display()} ».", link='/hr/recrutement/')
    messages.success(request, "Besoin de recrutement mis à jour.")
    return redirect('hr:recruitment_list')


@login_required
@_hr_required
def recruitment_delete(request, pk):
    req = get_object_or_404(RecruitmentRequest, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:recruitment_list')
    if request.method == 'POST':
        req.delete()
        messages.success(request, "Besoin de recrutement supprimé.")
    return redirect('hr:recruitment_list')


# ── Candidats ────────────────────────────────────────────────────────────────

@login_required
@_hr_required
def candidate_create(request, request_pk):
    req = get_object_or_404(RecruitmentRequest, pk=request_pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:recruitment_list')
    if request.method == 'POST':
        Candidate.objects.create(
            recruitment_request=req,
            prenom=request.POST.get('prenom', '').strip(),
            nom=request.POST.get('nom', '').strip(),
            email=request.POST.get('email', '').strip(),
            telephone=request.POST.get('telephone', '').strip(),
            source=request.POST.get('source', '').strip(),
        )
        messages.success(request, "Candidat ajouté.")
    return redirect('hr:recruitment_list')


@login_required
@_hr_required
def candidate_action(request, pk):
    candidate = get_object_or_404(Candidate.objects.select_related('recruitment_request'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:recruitment_list')
    if request.method != 'POST':
        return redirect('hr:recruitment_list')
    action = request.POST.get('action', '')
    from_statut = candidate.statut
    try:
        new_statut = transition(CANDIDATE_TRANSITIONS, candidate.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:recruitment_list')
    candidate.statut = new_statut
    if request.POST.get('score'):
        candidate.score = request.POST.get('score')
    candidate.save()
    log_hr_event('candidate', candidate.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)
    messages.success(request, "Candidat mis à jour.")
    return redirect('hr:recruitment_list')


@login_required
@_hr_required
def candidate_hire(request, pk):
    candidate = get_object_or_404(Candidate.objects.select_related('recruitment_request'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:recruitment_list')
    if candidate.statut != Candidate.STATUT_RETENU:
        messages.error(request, "Seul un candidat « Retenu » peut être embauché.")
        return redirect('hr:recruitment_list')
    if request.method != 'POST':
        return redirect('hr:recruitment_list')

    username = request.POST.get('username', '').strip()
    role_id = request.POST.get('role')
    if User.objects.filter(username=username).exists():
        messages.error(request, f"Le nom d'utilisateur « {username} » existe déjà.")
        return redirect('hr:recruitment_list')

    role = Role.objects.filter(pk=role_id).first()
    user = User.objects.create(
        username=username,
        first_name=candidate.prenom,
        last_name=candidate.nom,
        email=candidate.email,
        password=make_password(request.POST.get('password') or username),
        role=role,
        department=candidate.recruitment_request.department,
        must_change_password=True,
    )
    user.matricule_employe = _generate_matricule(user)
    user.save(update_fields=['matricule_employe'])

    from .models import FichePersonnel
    FichePersonnel.objects.get_or_create(
        user=user, defaults={'poste': candidate.recruitment_request.poste},
    )
    Assignment.objects.create(
        user=user, department=candidate.recruitment_request.department,
        poste=candidate.recruitment_request.poste,
        date_effet=timezone.now().date(),
        type_affectation=Assignment.TYPE_RECRUTEMENT,
        note=f"Recruté via le besoin « {candidate.recruitment_request.titre} » ({candidate.recruitment_request.get_mode_display()}).",
        created_by=request.user,
    )
    log_hr_event('candidate', candidate.pk, request.user, 'embauche', from_statut='RETENU', to_statut='RETENU')
    messages.success(request, f"{user.get_full_name()} a été embauché(e) — identifiant : {username}.")
    return redirect('hr:employe_fiche', pk=user.pk)
