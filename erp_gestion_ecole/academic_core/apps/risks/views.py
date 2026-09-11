"""
Risques — Pilotage et Suivi Budgétaire. Même convention que
accounting/budget_views.py.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404


def _budget_required(user):
    role = user.role_name
    return role in ('CONTROLEUR', 'INST_ADMIN', 'SI_ADMIN', 'ADMIN_DAF', 'ADMIN')


def _denied(request):
    messages.error(request, "Accès réservé au Pilotage et Suivi Budgétaire.")
    return redirect('dashboard:index')


def _users_queryset():
    from academic_core.apps.accounts.models import User
    return User.objects.filter(is_active=True).order_by('first_name', 'last_name')


def _niveau_for_score(score):
    if score >= 16:
        return 'critique'
    if score >= 10:
        return 'eleve'
    if score >= 5:
        return 'modere'
    return 'faible'


@login_required
def matrice_risques(request):
    """Grille 5x5 gravité x probabilité, exclut les risques clos. HTML/CSS pur, pas de librairie JS."""
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Risque
    risques = Risque.objects.exclude(statut=Risque.STATUT_CLOS).select_related('responsable')

    grille = {}
    for g in range(5, 0, -1):
        for p in range(1, 6):
            grille[(g, p)] = []
    for r in risques:
        grille.setdefault((r.gravite, r.probabilite), []).append(r)

    lignes = [
        (g, [(p, _niveau_for_score(g * p), grille.get((g, p), [])) for p in range(1, 6)])
        for g in range(5, 0, -1)
    ]

    return render(request, 'risks/matrice.html', {
        'lignes': lignes,
        'nb_risques': risques.count(),
    })


@login_required
def risque_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Risque
    from academic_core.apps.strategic_plan.models import AxeStrategique, ObjectifStrategique, Programme, Projet
    from django.contrib.contenttypes.models import ContentType
    rattachements = [
        ('Axe stratégique', ContentType.objects.get_for_model(AxeStrategique), AxeStrategique.objects.all()),
        ('Objectif stratégique', ContentType.objects.get_for_model(ObjectifStrategique), ObjectifStrategique.objects.all()),
        ('Programme', ContentType.objects.get_for_model(Programme), Programme.objects.all()),
        ('Projet', ContentType.objects.get_for_model(Projet), Projet.objects.all()),
    ]
    return render(request, 'risks/risque_list.html', {
        'risques': Risque.objects.select_related('responsable'),
        'CATEGORIE_CHOICES': Risque.CATEGORIE_CHOICES,
        'STATUT_CHOICES': Risque.STATUT_CHOICES,
        'users': _users_queryset(),
        'rattachements': rattachements,
    })


@login_required
def risque_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('risks:risque_list')
    from django.contrib.contenttypes.models import ContentType
    from .models import Risque

    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    categorie = request.POST.get('categorie', '')
    date_identification = request.POST.get('date_identification') or None
    try:
        gravite = int(request.POST.get('gravite'))
        probabilite = int(request.POST.get('probabilite'))
        if not (1 <= gravite <= 5 and 1 <= probabilite <= 5):
            raise ValueError
    except (TypeError, ValueError):
        gravite = probabilite = None

    if not code or not libelle or categorie not in dict(Risque.CATEGORIE_CHOICES) or gravite is None or not date_identification:
        messages.error(request, "Code, libellé, catégorie, gravité/probabilité (1-5) et date d'identification sont obligatoires.")
        return redirect('risks:risque_list')
    if Risque.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('risks:risque_list')

    content_type = None
    object_id = None
    rattachement = request.POST.get('rattachement', '')
    if '|' in rattachement:
        ct_id, obj_id = rattachement.split('|', 1)
        if ct_id.isdigit() and obj_id.isdigit():
            content_type = ContentType.objects.filter(pk=int(ct_id)).first()
            object_id = int(obj_id)

    Risque.objects.create(
        code=code, libelle=libelle, description=request.POST.get('description', '').strip(),
        categorie=categorie, gravite=gravite, probabilite=probabilite,
        responsable_id=request.POST.get('responsable') or None,
        plan_mitigation=request.POST.get('plan_mitigation', '').strip(),
        date_identification=date_identification,
        content_type=content_type, object_id=object_id,
    )
    messages.success(request, f"Risque « {libelle} » créé.")
    return redirect('risks:risque_list')


@login_required
def risque_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Risque
    risque = get_object_or_404(Risque, pk=pk)
    if request.method != 'POST':
        return redirect('risks:risque_list')

    risque.libelle = request.POST.get('libelle', risque.libelle).strip()
    risque.description = request.POST.get('description', '').strip()
    categorie = request.POST.get('categorie', '')
    if categorie in dict(Risque.CATEGORIE_CHOICES):
        risque.categorie = categorie
    try:
        gravite = int(request.POST.get('gravite'))
        probabilite = int(request.POST.get('probabilite'))
        if 1 <= gravite <= 5:
            risque.gravite = gravite
        if 1 <= probabilite <= 5:
            risque.probabilite = probabilite
    except (TypeError, ValueError):
        pass
    risque.responsable_id = request.POST.get('responsable') or None
    risque.plan_mitigation = request.POST.get('plan_mitigation', '').strip()
    statut = request.POST.get('statut', '')
    if statut in dict(Risque.STATUT_CHOICES):
        risque.statut = statut
    risque.save()
    messages.success(request, "Risque modifié.")
    return redirect('risks:risque_list')


@login_required
def risque_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Risque
    risque = get_object_or_404(Risque, pk=pk)
    if request.method != 'POST':
        return redirect('risks:risque_list')
    risque.delete()
    messages.success(request, "Risque supprimé.")
    return redirect('risks:risque_list')


@login_required
def suivi_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('risks:risque_list')
    from .models import Risque, SuiviRisque
    risque = Risque.objects.filter(pk=request.POST.get('risque')).first()
    date_suivi = request.POST.get('date_suivi') or None
    if not risque or not date_suivi:
        messages.error(request, "Risque et date de suivi sont obligatoires.")
        return redirect('risks:risque_list')
    nouveau_statut = request.POST.get('nouveau_statut', '')
    SuiviRisque.objects.create(
        risque=risque, date_suivi=date_suivi,
        commentaire=request.POST.get('commentaire', '').strip(),
        nouveau_statut=nouveau_statut if nouveau_statut in dict(Risque.STATUT_CHOICES) else '',
        suivi_par=request.user,
    )
    if nouveau_statut in dict(Risque.STATUT_CHOICES):
        risque.statut = nouveau_statut
        risque.save(update_fields=['statut'])
    messages.success(request, "Suivi enregistré.")
    return redirect('risks:risque_list')
