"""
Qualité — Pilotage et Suivi Budgétaire. Même convention que
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


@login_required
def quality_dashboard(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CritereQualite

    referentiels = []
    for code, label in CritereQualite.REFERENTIEL_CHOICES:
        criteres = CritereQualite.objects.filter(referentiel=code).prefetch_related('auto_evaluations')
        evaluations = []
        for c in criteres:
            derniere = c.auto_evaluations.order_by('-campagne').first()
            evaluations.append({'critere': c, 'derniere': derniere})
        taux_moyen = 0
        avec_note = [e['derniere'].taux_reussite for e in evaluations if e['derniere']]
        if avec_note:
            taux_moyen = round(sum(avec_note) / len(avec_note) * 100)
        referentiels.append({'code': code, 'label': label, 'evaluations': evaluations, 'taux_moyen': taux_moyen})

    return render(request, 'quality/dashboard.html', {'referentiels': referentiels})


@login_required
def critere_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CritereQualite
    return render(request, 'quality/critere_list.html', {
        'criteres': CritereQualite.objects.all(),
        'REFERENTIEL_CHOICES': CritereQualite.REFERENTIEL_CHOICES,
    })


@login_required
def critere_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('quality:critere_list')
    from .models import CritereQualite
    referentiel = request.POST.get('referentiel', '')
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    if referentiel not in dict(CritereQualite.REFERENTIEL_CHOICES) or not code or not libelle:
        messages.error(request, "Référentiel, code et libellé sont obligatoires.")
        return redirect('quality:critere_list')
    if CritereQualite.objects.filter(referentiel=referentiel, code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » existe déjà pour ce référentiel.")
        return redirect('quality:critere_list')
    try:
        ponderation = max(1, int(request.POST.get('ponderation', 1)))
    except (TypeError, ValueError):
        ponderation = 1
    CritereQualite.objects.create(
        referentiel=referentiel, code=code, libelle=libelle,
        categorie=request.POST.get('categorie', '').strip(),
        description=request.POST.get('description', '').strip(),
        ponderation=ponderation,
    )
    messages.success(request, f"Critère « {code} » créé.")
    return redirect('quality:critere_list')


@login_required
def critere_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CritereQualite
    critere = get_object_or_404(CritereQualite, pk=pk)
    if request.method != 'POST':
        return redirect('quality:critere_list')
    critere.libelle = request.POST.get('libelle', critere.libelle).strip()
    critere.categorie = request.POST.get('categorie', '').strip()
    critere.description = request.POST.get('description', '').strip()
    try:
        critere.ponderation = max(1, int(request.POST.get('ponderation', critere.ponderation)))
    except (TypeError, ValueError):
        pass
    critere.save()
    messages.success(request, "Critère modifié.")
    return redirect('quality:critere_list')


@login_required
def critere_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CritereQualite
    critere = get_object_or_404(CritereQualite, pk=pk)
    if request.method != 'POST':
        return redirect('quality:critere_list')
    critere.delete()
    messages.success(request, "Critère supprimé.")
    return redirect('quality:critere_list')


@login_required
def evaluation_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('quality:critere_list')
    from decimal import Decimal, InvalidOperation
    from .models import CritereQualite, AutoEvaluation
    critere = CritereQualite.objects.filter(pk=request.POST.get('critere')).first()
    campagne = request.POST.get('campagne', '').strip()
    try:
        note = Decimal(request.POST.get('note', '').replace(',', '.'))
        note_max = Decimal(request.POST.get('note_max', '4').replace(',', '.') or '4')
    except (InvalidOperation, ValueError):
        note = None
        note_max = Decimal('4')
    if not critere or not campagne or note is None:
        messages.error(request, "Critère, campagne et note sont obligatoires.")
        return redirect('quality:critere_list')
    if AutoEvaluation.objects.filter(critere=critere, campagne=campagne).exists():
        messages.error(request, "Une évaluation existe déjà pour ce critère et cette campagne.")
        return redirect('quality:critere_list')
    AutoEvaluation.objects.create(
        critere=critere, campagne=campagne, note=note, note_max=note_max,
        commentaire=request.POST.get('commentaire', '').strip(), evalue_par=request.user,
    )
    messages.success(request, "Auto-évaluation enregistrée.")
    return redirect('quality:critere_list')


@login_required
def plan_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import PlanAmelioration, CritereQualite
    return render(request, 'quality/plan_list.html', {
        'plans': PlanAmelioration.objects.select_related('critere', 'responsable'),
        'criteres': CritereQualite.objects.all(),
        'users': _users_queryset(),
        'STATUT_CHOICES': PlanAmelioration.STATUT_CHOICES,
    })


@login_required
def plan_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('quality:plan_list')
    from .models import PlanAmelioration, CritereQualite
    critere = CritereQualite.objects.filter(pk=request.POST.get('critere')).first()
    action = request.POST.get('action', '').strip()
    if not critere or not action:
        messages.error(request, "Critère et action sont obligatoires.")
        return redirect('quality:plan_list')
    PlanAmelioration.objects.create(
        critere=critere, action=action,
        description=request.POST.get('description', '').strip(),
        responsable_id=request.POST.get('responsable') or None,
        date_echeance=request.POST.get('date_echeance') or None,
    )
    messages.success(request, f"Plan d'amélioration « {action} » créé.")
    return redirect('quality:plan_list')


@login_required
def plan_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import PlanAmelioration
    plan = get_object_or_404(PlanAmelioration, pk=pk)
    if request.method != 'POST':
        return redirect('quality:plan_list')
    plan.action = request.POST.get('action', plan.action).strip()
    plan.description = request.POST.get('description', '').strip()
    plan.responsable_id = request.POST.get('responsable') or None
    plan.date_echeance = request.POST.get('date_echeance') or None
    statut = request.POST.get('statut', '')
    if statut in dict(PlanAmelioration.STATUT_CHOICES):
        plan.statut = statut
    try:
        plan.taux_avancement = max(0, min(100, int(request.POST.get('taux_avancement', plan.taux_avancement))))
    except (TypeError, ValueError):
        pass
    plan.save()
    messages.success(request, "Plan d'amélioration modifié.")
    return redirect('quality:plan_list')


@login_required
def plan_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import PlanAmelioration
    plan = get_object_or_404(PlanAmelioration, pk=pk)
    if request.method != 'POST':
        return redirect('quality:plan_list')
    plan.delete()
    messages.success(request, "Plan d'amélioration supprimé.")
    return redirect('quality:plan_list')
