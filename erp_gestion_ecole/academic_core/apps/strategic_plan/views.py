"""
Plan Stratégique de Développement — Pilotage et Suivi Budgétaire.

Même convention que accounting/budget_views.py : vues function-based, gardes
_budget_required(user), formulaires HTML bruts postés directement, imports de
modèles locaux à chaque vue.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse


def _budget_required(user):
    role = user.role_name
    return role in ('CONTROLEUR', 'INST_ADMIN', 'SI_ADMIN', 'ADMIN_DAF', 'ADMIN')


def _denied(request):
    messages.error(request, "Accès réservé au Pilotage et Suivi Budgétaire.")
    return redirect('dashboard:index')


def _users_queryset():
    from academic_core.apps.accounts.models import User
    return User.objects.filter(is_active=True).order_by('first_name', 'last_name')


# ─────────────────────────────────────────────────────────────────────────────
# Cadrages stratégiques
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def cadrage_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CadrageStrategique
    return render(request, 'strategic_plan/cadrage_list.html', {
        'cadrages': CadrageStrategique.objects.all(),
    })


@login_required
def cadrage_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('strategic_plan:cadrage_list')
    from .models import CadrageStrategique
    libelle = request.POST.get('libelle', '').strip()
    try:
        annee_debut = int(request.POST.get('annee_debut'))
        annee_fin = int(request.POST.get('annee_fin'))
    except (TypeError, ValueError):
        messages.error(request, "Années de début/fin invalides.")
        return redirect('strategic_plan:cadrage_list')
    if not libelle:
        messages.error(request, "Le libellé est obligatoire.")
        return redirect('strategic_plan:cadrage_list')
    CadrageStrategique.objects.create(
        libelle=libelle, annee_debut=annee_debut, annee_fin=annee_fin,
        vision=request.POST.get('vision', '').strip(),
        mission=request.POST.get('mission', '').strip(),
        valeurs=request.POST.get('valeurs', '').strip(),
    )
    messages.success(request, f"Cadrage stratégique « {libelle} » créé.")
    return redirect('strategic_plan:cadrage_list')


@login_required
def cadrage_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CadrageStrategique
    cadrage = get_object_or_404(CadrageStrategique, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:cadrage_list')
    cadrage.libelle = request.POST.get('libelle', cadrage.libelle).strip()
    try:
        cadrage.annee_debut = int(request.POST.get('annee_debut'))
        cadrage.annee_fin = int(request.POST.get('annee_fin'))
    except (TypeError, ValueError):
        pass
    cadrage.vision = request.POST.get('vision', '').strip()
    cadrage.mission = request.POST.get('mission', '').strip()
    cadrage.valeurs = request.POST.get('valeurs', '').strip()
    cadrage.save()
    messages.success(request, "Cadrage stratégique modifié.")
    return redirect('strategic_plan:cadrage_list')


@login_required
def cadrage_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CadrageStrategique
    cadrage = get_object_or_404(CadrageStrategique, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:cadrage_list')
    if cadrage.axes.exists():
        messages.error(request, "Impossible de supprimer : des axes stratégiques y sont rattachés.")
        return redirect('strategic_plan:cadrage_list')
    cadrage.delete()
    messages.success(request, "Cadrage stratégique supprimé.")
    return redirect('strategic_plan:cadrage_list')


# ─────────────────────────────────────────────────────────────────────────────
# Axes stratégiques
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def axe_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import AxeStrategique, CadrageStrategique
    return render(request, 'strategic_plan/axe_list.html', {
        'axes': AxeStrategique.objects.select_related('cadrage').prefetch_related('objectifs'),
        'cadrages': CadrageStrategique.objects.all(),
    })


@login_required
def axe_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('strategic_plan:axe_list')
    from .models import AxeStrategique, CadrageStrategique
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    if not code or not libelle:
        messages.error(request, "Code et libellé sont obligatoires.")
        return redirect('strategic_plan:axe_list')
    if AxeStrategique.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('strategic_plan:axe_list')
    cadrage = CadrageStrategique.objects.filter(pk=request.POST.get('cadrage')).first()
    AxeStrategique.objects.create(
        cadrage=cadrage, code=code, libelle=libelle,
        description=request.POST.get('description', '').strip(),
        annee_debut=request.POST.get('annee_debut') or None,
        annee_fin=request.POST.get('annee_fin') or None,
    )
    messages.success(request, f"Axe stratégique « {libelle} » créé.")
    return redirect('strategic_plan:axe_list')


@login_required
def axe_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import AxeStrategique, CadrageStrategique
    axe = get_object_or_404(AxeStrategique, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:axe_list')
    axe.libelle = request.POST.get('libelle', axe.libelle).strip()
    axe.description = request.POST.get('description', '').strip()
    axe.cadrage = CadrageStrategique.objects.filter(pk=request.POST.get('cadrage')).first()
    axe.annee_debut = request.POST.get('annee_debut') or None
    axe.annee_fin = request.POST.get('annee_fin') or None
    axe.save()
    messages.success(request, "Axe stratégique modifié.")
    return redirect('strategic_plan:axe_list')


@login_required
def axe_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import AxeStrategique
    axe = get_object_or_404(AxeStrategique, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:axe_list')
    if axe.objectifs.exists():
        messages.error(request, "Impossible de supprimer : des objectifs y sont rattachés.")
        return redirect('strategic_plan:axe_list')
    axe.delete()
    messages.success(request, "Axe stratégique supprimé.")
    return redirect('strategic_plan:axe_list')


# ─────────────────────────────────────────────────────────────────────────────
# Objectifs stratégiques
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def objectif_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import ObjectifStrategique, AxeStrategique
    return render(request, 'strategic_plan/objectif_list.html', {
        'objectifs': ObjectifStrategique.objects.select_related('axe', 'responsable').prefetch_related('programmes'),
        'axes': AxeStrategique.objects.all(),
        'PERSPECTIVE_CHOICES': ObjectifStrategique.PERSPECTIVE_CHOICES,
        'users': _users_queryset(),
    })


@login_required
def objectif_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('strategic_plan:objectif_list')
    from .models import ObjectifStrategique, AxeStrategique
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    axe = AxeStrategique.objects.filter(pk=request.POST.get('axe')).first()
    if not code or not libelle or not axe:
        messages.error(request, "Axe, code et libellé sont obligatoires.")
        return redirect('strategic_plan:objectif_list')
    if ObjectifStrategique.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('strategic_plan:objectif_list')
    perspective = request.POST.get('perspective_bsc', '')
    if perspective not in dict(ObjectifStrategique.PERSPECTIVE_CHOICES):
        perspective = ''
    ObjectifStrategique.objects.create(
        axe=axe, code=code, libelle=libelle,
        responsable_id=request.POST.get('responsable') or None,
        description=request.POST.get('description', '').strip(),
        perspective_bsc=perspective,
    )
    messages.success(request, f"Objectif stratégique « {libelle} » créé.")
    return redirect('strategic_plan:objectif_list')


@login_required
def objectif_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import ObjectifStrategique, AxeStrategique
    objectif = get_object_or_404(ObjectifStrategique, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:objectif_list')
    objectif.libelle = request.POST.get('libelle', objectif.libelle).strip()
    axe = AxeStrategique.objects.filter(pk=request.POST.get('axe')).first()
    if axe:
        objectif.axe = axe
    objectif.responsable_id = request.POST.get('responsable') or None
    objectif.description = request.POST.get('description', '').strip()
    perspective = request.POST.get('perspective_bsc', '')
    if perspective in dict(ObjectifStrategique.PERSPECTIVE_CHOICES) or perspective == '':
        objectif.perspective_bsc = perspective
    objectif.save()
    messages.success(request, "Objectif stratégique modifié.")
    return redirect('strategic_plan:objectif_list')


@login_required
def objectif_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import ObjectifStrategique
    objectif = get_object_or_404(ObjectifStrategique, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:objectif_list')
    if objectif.programmes.exists():
        messages.error(request, "Impossible de supprimer : des programmes y sont rattachés.")
        return redirect('strategic_plan:objectif_list')
    objectif.delete()
    messages.success(request, "Objectif stratégique supprimé.")
    return redirect('strategic_plan:objectif_list')


# ─────────────────────────────────────────────────────────────────────────────
# Programmes
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def programme_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Programme, ObjectifStrategique
    return render(request, 'strategic_plan/programme_list.html', {
        'programmes': Programme.objects.select_related('objectif', 'responsable').prefetch_related('projets'),
        'objectifs': ObjectifStrategique.objects.all(),
        'users': _users_queryset(),
    })


@login_required
def programme_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('strategic_plan:programme_list')
    from .models import Programme, ObjectifStrategique
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    objectif = ObjectifStrategique.objects.filter(pk=request.POST.get('objectif')).first()
    if not code or not libelle or not objectif:
        messages.error(request, "Objectif, code et libellé sont obligatoires.")
        return redirect('strategic_plan:programme_list')
    if Programme.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('strategic_plan:programme_list')
    Programme.objects.create(
        objectif=objectif, code=code, libelle=libelle,
        responsable_id=request.POST.get('responsable') or None,
    )
    messages.success(request, f"Programme « {libelle} » créé.")
    return redirect('strategic_plan:programme_list')


@login_required
def programme_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Programme, ObjectifStrategique
    programme = get_object_or_404(Programme, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:programme_list')
    programme.libelle = request.POST.get('libelle', programme.libelle).strip()
    objectif = ObjectifStrategique.objects.filter(pk=request.POST.get('objectif')).first()
    if objectif:
        programme.objectif = objectif
    programme.responsable_id = request.POST.get('responsable') or None
    programme.save()
    messages.success(request, "Programme modifié.")
    return redirect('strategic_plan:programme_list')


@login_required
def programme_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Programme
    programme = get_object_or_404(Programme, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:programme_list')
    if programme.projets.exists():
        messages.error(request, "Impossible de supprimer : des projets y sont rattachés.")
        return redirect('strategic_plan:programme_list')
    programme.delete()
    messages.success(request, "Programme supprimé.")
    return redirect('strategic_plan:programme_list')


# ─────────────────────────────────────────────────────────────────────────────
# Projets
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def projet_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Projet, Programme
    qs = Projet.objects.select_related('programme', 'responsable')
    programme_filt = request.GET.get('programme', '').strip()
    if programme_filt.isdigit():
        qs = qs.filter(programme_id=int(programme_filt))
    return render(request, 'strategic_plan/projet_list.html', {
        'projets': qs,
        'programmes': Programme.objects.all(),
        'users': _users_queryset(),
        'STATUT_CHOICES': Projet.STATUT_CHOICES,
        'programme_filter': programme_filt,
    })


@login_required
def projet_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_list')
    from decimal import Decimal, InvalidOperation
    from .models import Projet, Programme
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    programme = Programme.objects.filter(pk=request.POST.get('programme')).first()
    if not code or not libelle or not programme:
        messages.error(request, "Programme, code et libellé sont obligatoires.")
        return redirect('strategic_plan:projet_list')
    if Projet.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('strategic_plan:projet_list')
    try:
        budget_total = Decimal(request.POST.get('budget_total', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        budget_total = Decimal('0')
    Projet.objects.create(
        programme=programme, code=code, libelle=libelle,
        responsable_id=request.POST.get('responsable') or None,
        budget_total=budget_total,
        date_debut=request.POST.get('date_debut') or None,
        date_fin=request.POST.get('date_fin') or None,
    )
    messages.success(request, f"Projet « {libelle} » créé.")
    return redirect('strategic_plan:projet_list')


@login_required
def projet_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from decimal import Decimal, InvalidOperation
    from .models import Projet, Programme
    projet = get_object_or_404(Projet, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=pk)
    projet.libelle = request.POST.get('libelle', projet.libelle).strip()
    programme = Programme.objects.filter(pk=request.POST.get('programme')).first()
    if programme:
        projet.programme = programme
    projet.responsable_id = request.POST.get('responsable') or None
    try:
        projet.budget_total = Decimal(request.POST.get('budget_total', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        pass
    projet.date_debut = request.POST.get('date_debut') or None
    projet.date_fin = request.POST.get('date_fin') or None
    statut = request.POST.get('statut', '')
    if statut in dict(Projet.STATUT_CHOICES):
        projet.statut = statut
    projet.save()
    messages.success(request, "Projet modifié.")
    return redirect('strategic_plan:projet_detail', pk=pk)


@login_required
def projet_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Projet
    projet = get_object_or_404(Projet, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_list')
    if projet.activites.exists():
        messages.error(request, "Impossible de supprimer : des activités y sont rattachées.")
        return redirect('strategic_plan:projet_list')
    projet.delete()
    messages.success(request, "Projet supprimé.")
    return redirect('strategic_plan:projet_list')


@login_required
def projet_detail(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Projet, Programme, Jalon, Livrable
    projet = get_object_or_404(Projet.objects.select_related('programme', 'responsable'), pk=pk)
    return render(request, 'strategic_plan/projet_detail.html', {
        'projet': projet,
        'activites': projet.activites.select_related('responsable').prefetch_related('sous_activites'),
        'jalons': projet.jalons.select_related('responsable').order_by('date_prevue'),
        'livrables': projet.livrables.select_related('responsable').order_by('date_prevue'),
        'membres': projet.membres_equipe.select_related('utilisateur'),
        'programmes': Programme.objects.all(),
        'users': _users_queryset(),
        'STATUT_CHOICES': Projet.STATUT_CHOICES,
        'JALON_STATUT_CHOICES': Jalon.STATUT_CHOICES,
        'LIVRABLE_STATUT_CHOICES': Livrable.STATUT_CHOICES,
    })


@login_required
def projet_gantt(request, pk):
    """Barres horizontales flottantes Chart.js (type:'bar', indexAxis:'y'), données via json.dumps."""
    if not _budget_required(request.user):
        return _denied(request)
    import json
    from datetime import date
    from .models import Projet

    projet = get_object_or_404(Projet, pk=pk)
    activites = list(projet.activites.filter(date_debut__isnull=False, date_fin__isnull=False).order_by('date_debut'))

    if not activites:
        return render(request, 'strategic_plan/projet_gantt.html', {'projet': projet, 'has_data': False})

    origine = min(a.date_debut for a in activites)
    rows = []
    for a in activites:
        rows.append({
            'label': a.libelle,
            'start': (a.date_debut - origine).days,
            'end': (a.date_fin - origine).days if a.date_fin else (a.date_debut - origine).days,
            'progress': a.taux_avancement,
            'start_date': a.date_debut.isoformat(),
            'end_date': a.date_fin.isoformat() if a.date_fin else '',
        })
        for s in a.sous_activites.filter(date_debut__isnull=False, date_fin__isnull=False).order_by('date_debut'):
            rows.append({
                'label': f"↳ {s.libelle}",
                'start': (s.date_debut - origine).days,
                'end': (s.date_fin - origine).days if s.date_fin else (s.date_debut - origine).days,
                'progress': s.taux_avancement,
                'start_date': s.date_debut.isoformat(),
                'end_date': s.date_fin.isoformat() if s.date_fin else '',
            })

    return render(request, 'strategic_plan/projet_gantt.html', {
        'projet': projet,
        'has_data': True,
        'gantt_row_count': len(rows),
        'gantt_labels_json': json.dumps([r['label'] for r in rows]),
        'gantt_start_json': json.dumps([r['start'] for r in rows]),
        'gantt_duration_json': json.dumps([max(r['end'] - r['start'], 0) for r in rows]),
        'gantt_progress_json': json.dumps([r['progress'] for r in rows]),
        'gantt_start_date_json': json.dumps([r['start_date'] for r in rows]),
        'gantt_end_date_json': json.dumps([r['end_date'] for r in rows]),
    })


@login_required
def projet_kanban(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Projet, Activite
    projet = get_object_or_404(Projet, pk=pk)
    activites = projet.activites.select_related('responsable').prefetch_related('sous_activites')
    colonnes = [
        (code, label, [a for a in activites if a.statut == code])
        for code, label in Activite.STATUT_CHOICES
    ]
    return render(request, 'strategic_plan/projet_kanban.html', {
        'projet': projet,
        'colonnes': colonnes,
        'STATUT_CHOICES': Activite.STATUT_CHOICES,
    })


@login_required
def activite_changer_statut(request, pk):
    """Endpoint léger appelé en fetch() depuis le Kanban — retourne la carte re-rendue."""
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Activite
    activite = get_object_or_404(Activite, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_kanban', pk=activite.projet_id)
    statut = request.POST.get('statut', '')
    if statut in dict(Activite.STATUT_CHOICES):
        activite.statut = statut
        activite.save(update_fields=['statut'])
        messages.success(request, f"Statut de « {activite.libelle} » mis à jour.")
    return redirect('strategic_plan:projet_kanban', pk=activite.projet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Activités
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def activite_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('dashboard:index')
    from decimal import Decimal, InvalidOperation
    from .models import Activite, Projet
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    projet = Projet.objects.filter(pk=request.POST.get('projet')).first()
    if not code or not libelle or not projet:
        messages.error(request, "Projet, code et libellé sont obligatoires.")
        return redirect('strategic_plan:projet_detail', pk=projet.pk) if projet else redirect('strategic_plan:projet_list')
    if Activite.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('strategic_plan:projet_detail', pk=projet.pk)
    try:
        budget = Decimal(request.POST.get('budget', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        budget = Decimal('0')
    Activite.objects.create(
        projet=projet, code=code, libelle=libelle,
        responsable_id=request.POST.get('responsable') or None,
        budget=budget,
        date_debut=request.POST.get('date_debut') or None,
        date_fin=request.POST.get('date_fin') or None,
    )
    messages.success(request, f"Activité « {libelle} » créée.")
    return redirect('strategic_plan:projet_detail', pk=projet.pk)


@login_required
def activite_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from decimal import Decimal, InvalidOperation
    from .models import Activite
    activite = get_object_or_404(Activite, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=activite.projet_id)
    activite.libelle = request.POST.get('libelle', activite.libelle).strip()
    activite.responsable_id = request.POST.get('responsable') or None
    try:
        activite.budget = Decimal(request.POST.get('budget', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        pass
    activite.date_debut = request.POST.get('date_debut') or None
    activite.date_fin = request.POST.get('date_fin') or None
    statut = request.POST.get('statut', '')
    if statut in dict(Activite.STATUT_CHOICES):
        activite.statut = statut
    activite.save()
    messages.success(request, "Activité modifiée.")
    return redirect('strategic_plan:projet_detail', pk=activite.projet_id)


@login_required
def activite_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Activite
    activite = get_object_or_404(Activite, pk=pk)
    projet_id = activite.projet_id
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=projet_id)
    if activite.sous_activites.exists():
        messages.error(request, "Impossible de supprimer : des sous-activités y sont rattachées.")
        return redirect('strategic_plan:projet_detail', pk=projet_id)
    activite.delete()
    messages.success(request, "Activité supprimée.")
    return redirect('strategic_plan:projet_detail', pk=projet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Sous-activités
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def sous_activite_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('dashboard:index')
    from .models import SousActivite, Activite
    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    activite = Activite.objects.filter(pk=request.POST.get('activite')).first()
    if not code or not libelle or not activite:
        messages.error(request, "Activité, code et libellé sont obligatoires.")
        return redirect('strategic_plan:projet_detail', pk=activite.projet_id) if activite else redirect('strategic_plan:projet_list')
    if SousActivite.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('strategic_plan:projet_detail', pk=activite.projet_id)
    try:
        taux = max(0, min(100, int(request.POST.get('taux_avancement', 0))))
    except (TypeError, ValueError):
        taux = 0
    SousActivite.objects.create(
        activite=activite, code=code, libelle=libelle,
        responsable_id=request.POST.get('responsable') or None,
        date_debut=request.POST.get('date_debut') or None,
        date_fin=request.POST.get('date_fin') or None,
        taux_avancement=taux,
    )
    messages.success(request, f"Sous-activité « {libelle} » créée.")
    return redirect('strategic_plan:projet_detail', pk=activite.projet_id)


@login_required
def sous_activite_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import SousActivite, Activite
    sous_activite = get_object_or_404(SousActivite, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=sous_activite.activite.projet_id)
    sous_activite.libelle = request.POST.get('libelle', sous_activite.libelle).strip()
    sous_activite.responsable_id = request.POST.get('responsable') or None
    sous_activite.date_debut = request.POST.get('date_debut') or None
    sous_activite.date_fin = request.POST.get('date_fin') or None
    statut = request.POST.get('statut', '')
    if statut in dict(Activite.STATUT_CHOICES):
        sous_activite.statut = statut
    try:
        sous_activite.taux_avancement = max(0, min(100, int(request.POST.get('taux_avancement', sous_activite.taux_avancement))))
    except (TypeError, ValueError):
        pass
    sous_activite.save()
    messages.success(request, "Sous-activité modifiée.")
    return redirect('strategic_plan:projet_detail', pk=sous_activite.activite.projet_id)


@login_required
def sous_activite_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import SousActivite
    sous_activite = get_object_or_404(SousActivite, pk=pk)
    projet_id = sous_activite.activite.projet_id
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=projet_id)
    sous_activite.delete()
    messages.success(request, "Sous-activité supprimée.")
    return redirect('strategic_plan:projet_detail', pk=projet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Jalons
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def jalon_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('dashboard:index')
    from .models import Jalon, Projet
    projet = Projet.objects.filter(pk=request.POST.get('projet')).first()
    libelle = request.POST.get('libelle', '').strip()
    date_prevue = request.POST.get('date_prevue') or None
    if not projet or not libelle or not date_prevue:
        messages.error(request, "Projet, libellé et date prévue sont obligatoires.")
        return redirect('strategic_plan:projet_detail', pk=projet.pk) if projet else redirect('strategic_plan:projet_list')
    Jalon.objects.create(
        projet=projet, libelle=libelle, date_prevue=date_prevue,
        responsable_id=request.POST.get('responsable') or None,
    )
    messages.success(request, f"Jalon « {libelle} » créé.")
    return redirect('strategic_plan:projet_detail', pk=projet.pk)


@login_required
def jalon_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Jalon
    jalon = get_object_or_404(Jalon, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=jalon.projet_id)
    jalon.libelle = request.POST.get('libelle', jalon.libelle).strip()
    jalon.date_prevue = request.POST.get('date_prevue') or jalon.date_prevue
    jalon.date_reelle = request.POST.get('date_reelle') or None
    jalon.responsable_id = request.POST.get('responsable') or None
    statut = request.POST.get('statut', '')
    if statut in dict(Jalon.STATUT_CHOICES):
        jalon.statut = statut
    jalon.save()
    messages.success(request, "Jalon modifié.")
    return redirect('strategic_plan:projet_detail', pk=jalon.projet_id)


@login_required
def jalon_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Jalon
    jalon = get_object_or_404(Jalon, pk=pk)
    projet_id = jalon.projet_id
    if request.method == 'POST':
        jalon.delete()
        messages.success(request, "Jalon supprimé.")
    return redirect('strategic_plan:projet_detail', pk=projet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Livrables
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def livrable_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('dashboard:index')
    from .models import Livrable, Projet
    projet = Projet.objects.filter(pk=request.POST.get('projet')).first()
    libelle = request.POST.get('libelle', '').strip()
    if not projet or not libelle:
        messages.error(request, "Projet et libellé sont obligatoires.")
        return redirect('strategic_plan:projet_detail', pk=projet.pk) if projet else redirect('strategic_plan:projet_list')
    Livrable.objects.create(
        projet=projet, libelle=libelle,
        description=request.POST.get('description', '').strip(),
        date_prevue=request.POST.get('date_prevue') or None,
        responsable_id=request.POST.get('responsable') or None,
        fichier=request.FILES.get('fichier'),
    )
    messages.success(request, f"Livrable « {libelle} » créé.")
    return redirect('strategic_plan:projet_detail', pk=projet.pk)


@login_required
def livrable_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Livrable
    livrable = get_object_or_404(Livrable, pk=pk)
    if request.method != 'POST':
        return redirect('strategic_plan:projet_detail', pk=livrable.projet_id)
    livrable.libelle = request.POST.get('libelle', livrable.libelle).strip()
    livrable.description = request.POST.get('description', '').strip()
    livrable.date_prevue = request.POST.get('date_prevue') or None
    livrable.date_livraison = request.POST.get('date_livraison') or None
    livrable.responsable_id = request.POST.get('responsable') or None
    statut = request.POST.get('statut', '')
    if statut in dict(Livrable.STATUT_CHOICES):
        livrable.statut = statut
    if request.FILES.get('fichier'):
        livrable.fichier = request.FILES.get('fichier')
    livrable.save()
    messages.success(request, "Livrable modifié.")
    return redirect('strategic_plan:projet_detail', pk=livrable.projet_id)


@login_required
def livrable_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Livrable
    livrable = get_object_or_404(Livrable, pk=pk)
    projet_id = livrable.projet_id
    if request.method == 'POST':
        livrable.delete()
        messages.success(request, "Livrable supprimé.")
    return redirect('strategic_plan:projet_detail', pk=projet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Équipe projet
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def membre_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('dashboard:index')
    from .models import MembreEquipeProjet, Projet
    projet = Projet.objects.filter(pk=request.POST.get('projet')).first()
    utilisateur_id = request.POST.get('utilisateur')
    role = request.POST.get('role_dans_projet', '').strip()
    if not projet or not utilisateur_id or not role:
        messages.error(request, "Projet, utilisateur et rôle sont obligatoires.")
        return redirect('strategic_plan:projet_detail', pk=projet.pk) if projet else redirect('strategic_plan:projet_list')
    if MembreEquipeProjet.objects.filter(projet=projet, utilisateur_id=utilisateur_id).exists():
        messages.error(request, "Cet utilisateur est déjà membre de l'équipe.")
        return redirect('strategic_plan:projet_detail', pk=projet.pk)
    MembreEquipeProjet.objects.create(projet=projet, utilisateur_id=utilisateur_id, role_dans_projet=role)
    messages.success(request, "Membre ajouté à l'équipe.")
    return redirect('strategic_plan:projet_detail', pk=projet.pk)


@login_required
def membre_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import MembreEquipeProjet
    membre = get_object_or_404(MembreEquipeProjet, pk=pk)
    projet_id = membre.projet_id
    if request.method == 'POST':
        membre.delete()
        messages.success(request, "Membre retiré de l'équipe.")
    return redirect('strategic_plan:projet_detail', pk=projet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Import Excel + export PDF — un couple de vues par entité, même convention :
# GET (?download=1) télécharge le modèle, GET sans paramètre affiche le
# formulaire d'import, POST traite le fichier .xlsx uploadé ligne par ligne
# (voir academic_core/excel_utils.py). Chaque erreur de ligne est reportée
# sans bloquer l'import des autres lignes valides.
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_user_by_email(email):
    if not email:
        return None
    from academic_core.apps.accounts.models import User
    return User.objects.filter(email__iexact=str(email).strip()).first()


def _import_summary(request, redirect_name, created, skipped, errors):
    if created:
        messages.success(request, f"{created} élément(s) importé(s).")
    if skipped:
        messages.warning(request, f"{skipped} ligne(s) ignorée(s).")
    for err in errors[:8]:
        messages.error(request, err)
    if len(errors) > 8:
        messages.error(request, f"... et {len(errors) - 8} autre(s) erreur(s).")
    return redirect(redirect_name)


@login_required
def cadrage_import(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from .models import CadrageStrategique

    headers = ['Libellé', 'Année début', 'Année fin', 'Vision', 'Mission', 'Valeurs (une par ligne)']
    if request.method == 'GET' and request.GET.get('download'):
        return build_xlsx_template(
            filename='modele_import_cadrages.xlsx', sheet_title='Cadrages',
            headers=headers,
            example_row=[
                'Plan stratégique 2024-2028', 2024, 2028,
                "Devenir un institut de référence en Afrique de l'Ouest",
                'Former des professionnels compétents et responsables',
                'Excellence\nIntégrité\nInnovation',
            ],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Cadrages stratégiques',
            'back_url': reverse('strategic_plan:cadrage_list'),
            'columns_help': [
                ('Libellé', True, ''),
                ('Année début', True, 'Nombre entier, ex. 2024'),
                ('Année fin', True, 'Nombre entier, ex. 2028'),
                ('Vision', False, ''),
                ('Mission', False, ''),
                ('Valeurs (une par ligne)', False, "Plusieurs valeurs séparées par des retours à la ligne dans la cellule"),
            ],
        })

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('strategic_plan:cadrage_import')

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        libelle, annee_debut, annee_fin, vision, mission, valeurs = row
        libelle = (libelle or '').strip() if isinstance(libelle, str) else (libelle or '')
        try:
            annee_debut = int(annee_debut)
            annee_fin = int(annee_fin)
        except (TypeError, ValueError):
            skipped += 1
            errors.append(f"Ligne {line_num} : années de début/fin invalides.")
            continue
        if not libelle:
            skipped += 1
            errors.append(f"Ligne {line_num} : libellé manquant.")
            continue
        CadrageStrategique.objects.create(
            libelle=str(libelle).strip(), annee_debut=annee_debut, annee_fin=annee_fin,
            vision=str(vision or '').strip(), mission=str(mission or '').strip(),
            valeurs=str(valeurs or '').strip(),
        )
        created += 1

    return _import_summary(request, 'strategic_plan:cadrage_list', created, skipped, errors)


@login_required
def cadrage_pdf(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.pdf_utils import simple_list_pdf
    from .models import CadrageStrategique

    rows = [
        [c.libelle, f"{c.annee_debut}-{c.annee_fin}", c.vision[:120], c.mission[:120]]
        for c in CadrageStrategique.objects.all()
    ]
    return simple_list_pdf(
        request, title='Cadrages stratégiques',
        headers=['Libellé', 'Période', 'Vision', 'Mission'],
        rows=rows, filename='cadrages_strategiques.pdf',
        col_widths=[5 * 28.35, 3 * 28.35, 9 * 28.35, 9 * 28.35],
    )


@login_required
def axe_import(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from .models import AxeStrategique, CadrageStrategique

    headers = ['Code', 'Libellé', 'Cadrage (libellé exact)', 'Description', 'Année début', 'Année fin']
    if request.method == 'GET' and request.GET.get('download'):
        return build_xlsx_template(
            filename='modele_import_axes.xlsx', sheet_title='Axes',
            headers=headers,
            example_row=['AXE1', 'Gouvernance et pilotage', '', 'Renforcer la gouvernance institutionnelle', 2024, 2028],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Axes stratégiques',
            'back_url': reverse('strategic_plan:axe_list'),
            'columns_help': [
                ('Code', True, 'Doit être unique'),
                ('Libellé', True, ''),
                ('Cadrage (libellé exact)', False, 'Doit correspondre exactement au libellé d\'un cadrage existant, sinon laissé vide'),
                ('Description', False, ''),
                ('Année début', False, ''),
                ('Année fin', False, ''),
            ],
        })

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('strategic_plan:axe_import')

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        code, libelle, cadrage_libelle, description, annee_debut, annee_fin = row
        code = str(code or '').strip()
        libelle = str(libelle or '').strip()
        if not code or not libelle:
            skipped += 1
            errors.append(f"Ligne {line_num} : code et libellé sont obligatoires.")
            continue
        if AxeStrategique.objects.filter(code__iexact=code).exists():
            skipped += 1
            errors.append(f"Ligne {line_num} : le code « {code} » est déjà utilisé.")
            continue
        cadrage = None
        if cadrage_libelle:
            cadrage = CadrageStrategique.objects.filter(libelle__iexact=str(cadrage_libelle).strip()).first()
        AxeStrategique.objects.create(
            cadrage=cadrage, code=code, libelle=libelle,
            description=str(description or '').strip(),
            annee_debut=int(annee_debut) if str(annee_debut or '').strip().isdigit() else None,
            annee_fin=int(annee_fin) if str(annee_fin or '').strip().isdigit() else None,
        )
        created += 1

    return _import_summary(request, 'strategic_plan:axe_list', created, skipped, errors)


@login_required
def axe_pdf(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.pdf_utils import simple_list_pdf
    from .models import AxeStrategique

    axes = AxeStrategique.objects.select_related('cadrage')
    rows = [
        [a.code, a.libelle, a.cadrage.libelle if a.cadrage else '—', a.objectifs.count()]
        for a in axes
    ]
    return simple_list_pdf(
        request, title='Axes stratégiques',
        headers=['Code', 'Libellé', 'Cadrage', 'Objectifs'],
        rows=rows, filename='axes_strategiques.pdf',
    )


@login_required
def objectif_import(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from .models import ObjectifStrategique, AxeStrategique

    headers = ['Code', 'Libellé', 'Axe (code)', 'Responsable (email)', 'Description', 'Perspective BSC']
    if request.method == 'GET' and request.GET.get('download'):
        return build_xlsx_template(
            filename='modele_import_objectifs.xlsx', sheet_title='Objectifs',
            headers=headers,
            example_row=['OBJ1', 'Améliorer le taux de réussite', 'AXE1', '', 'Description libre', 'clients_etudiants'],
            notes=[
                'Perspective BSC — valeurs autorisées : financiere, clients_etudiants, processus_internes, apprentissage_innovation',
                '(laisser vide si non applicable)',
            ],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Objectifs stratégiques',
            'back_url': reverse('strategic_plan:objectif_list'),
            'columns_help': [
                ('Code', True, 'Doit être unique'),
                ('Libellé', True, ''),
                ('Axe (code)', True, 'Code exact d\'un axe existant'),
                ('Responsable (email)', False, 'Email d\'un utilisateur existant'),
                ('Description', False, ''),
                ('Perspective BSC', False, 'financiere / clients_etudiants / processus_internes / apprentissage_innovation'),
            ],
        })

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('strategic_plan:objectif_import')

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        code, libelle, axe_code, resp_email, description, perspective = row
        code = str(code or '').strip()
        libelle = str(libelle or '').strip()
        axe = AxeStrategique.objects.filter(code__iexact=str(axe_code or '').strip()).first()
        if not code or not libelle or not axe:
            skipped += 1
            errors.append(f"Ligne {line_num} : code, libellé et axe (existant) sont obligatoires.")
            continue
        if ObjectifStrategique.objects.filter(code__iexact=code).exists():
            skipped += 1
            errors.append(f"Ligne {line_num} : le code « {code} » est déjà utilisé.")
            continue
        perspective = str(perspective or '').strip()
        if perspective not in dict(ObjectifStrategique.PERSPECTIVE_CHOICES):
            perspective = ''
        responsable = _resolve_user_by_email(resp_email)
        ObjectifStrategique.objects.create(
            axe=axe, code=code, libelle=libelle, responsable=responsable,
            description=str(description or '').strip(), perspective_bsc=perspective,
        )
        created += 1

    return _import_summary(request, 'strategic_plan:objectif_list', created, skipped, errors)


@login_required
def objectif_pdf(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.pdf_utils import simple_list_pdf
    from .models import ObjectifStrategique

    objectifs = ObjectifStrategique.objects.select_related('axe', 'responsable')
    rows = [
        [o.code, o.libelle, o.axe.code, o.responsable.get_full_name() if o.responsable else '—']
        for o in objectifs
    ]
    return simple_list_pdf(
        request, title='Objectifs stratégiques',
        headers=['Code', 'Libellé', 'Axe', 'Responsable'],
        rows=rows, filename='objectifs_strategiques.pdf',
    )


@login_required
def programme_import(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from .models import Programme, ObjectifStrategique

    headers = ['Code', 'Libellé', 'Objectif (code)', 'Responsable (email)']
    if request.method == 'GET' and request.GET.get('download'):
        return build_xlsx_template(
            filename='modele_import_actions.xlsx', sheet_title='Actions',
            headers=headers,
            example_row=['ACT1', "Refonte de l'offre pédagogique", 'OBJ1', ''],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Actions',
            'back_url': reverse('strategic_plan:programme_list'),
            'columns_help': [
                ('Code', True, 'Doit être unique'),
                ('Libellé', True, ''),
                ('Objectif (code)', True, 'Code exact d\'un objectif existant'),
                ('Responsable (email)', False, 'Email d\'un utilisateur existant'),
            ],
        })

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('strategic_plan:programme_import')

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        code, libelle, objectif_code, resp_email = row
        code = str(code or '').strip()
        libelle = str(libelle or '').strip()
        objectif = ObjectifStrategique.objects.filter(code__iexact=str(objectif_code or '').strip()).first()
        if not code or not libelle or not objectif:
            skipped += 1
            errors.append(f"Ligne {line_num} : code, libellé et objectif (existant) sont obligatoires.")
            continue
        if Programme.objects.filter(code__iexact=code).exists():
            skipped += 1
            errors.append(f"Ligne {line_num} : le code « {code} » est déjà utilisé.")
            continue
        Programme.objects.create(
            objectif=objectif, code=code, libelle=libelle,
            responsable=_resolve_user_by_email(resp_email),
        )
        created += 1

    return _import_summary(request, 'strategic_plan:programme_list', created, skipped, errors)


@login_required
def programme_pdf(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.pdf_utils import simple_list_pdf
    from .models import Programme

    programmes = Programme.objects.select_related('objectif', 'responsable')
    rows = [
        [p.code, p.libelle, p.objectif.code, p.responsable.get_full_name() if p.responsable else '—', p.projets.count()]
        for p in programmes
    ]
    return simple_list_pdf(
        request, title='Actions',
        headers=['Code', 'Libellé', 'Objectif', 'Responsable', 'Activités'],
        rows=rows, filename='actions.pdf',
    )


@login_required
def projet_import(request):
    if not _budget_required(request.user):
        return _denied(request)
    from datetime import datetime
    from decimal import Decimal, InvalidOperation
    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from .models import Projet, Programme

    headers = ['Code', 'Libellé', 'Action (code)', 'Responsable (email)', 'Budget total',
               'Date début (AAAA-MM-JJ)', 'Date fin (AAAA-MM-JJ)']
    if request.method == 'GET' and request.GET.get('download'):
        return build_xlsx_template(
            filename='modele_import_activites.xlsx', sheet_title='Activités',
            headers=headers,
            example_row=['ACTV1', "Audit des maquettes existantes", 'ACT1', '', 500000, '2025-01-01', '2025-06-30'],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Activités',
            'back_url': reverse('strategic_plan:projet_list'),
            'columns_help': [
                ('Code', True, 'Doit être unique'),
                ('Libellé', True, ''),
                ('Action (code)', True, 'Code exact d\'une action existante'),
                ('Responsable (email)', False, 'Email d\'un utilisateur existant'),
                ('Budget total', False, 'Nombre, ex. 500000'),
                ('Date début (AAAA-MM-JJ)', False, ''),
                ('Date fin (AAAA-MM-JJ)', False, ''),
            ],
        })

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('strategic_plan:projet_import')

    def _parse_date(val):
        if not val:
            return None
        if hasattr(val, 'date'):
            return val.date() if hasattr(val, 'hour') else val
        try:
            return datetime.strptime(str(val).strip(), '%Y-%m-%d').date()
        except ValueError:
            return None

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        code, libelle, programme_code, resp_email, budget, date_debut, date_fin = row
        code = str(code or '').strip()
        libelle = str(libelle or '').strip()
        programme = Programme.objects.filter(code__iexact=str(programme_code or '').strip()).first()
        if not code or not libelle or not programme:
            skipped += 1
            errors.append(f"Ligne {line_num} : code, libellé et action (existante) sont obligatoires.")
            continue
        if Projet.objects.filter(code__iexact=code).exists():
            skipped += 1
            errors.append(f"Ligne {line_num} : le code « {code} » est déjà utilisé.")
            continue
        try:
            budget_total = Decimal(str(budget).replace(' ', '').replace(',', '.')) if budget not in (None, '') else Decimal('0')
        except InvalidOperation:
            budget_total = Decimal('0')
        Projet.objects.create(
            programme=programme, code=code, libelle=libelle,
            responsable=_resolve_user_by_email(resp_email),
            budget_total=budget_total,
            date_debut=_parse_date(date_debut), date_fin=_parse_date(date_fin),
        )
        created += 1

    return _import_summary(request, 'strategic_plan:projet_list', created, skipped, errors)


@login_required
def projet_pdf(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.pdf_utils import simple_list_pdf
    from .models import Projet

    projets = Projet.objects.select_related('programme', 'responsable')
    rows = [
        [p.code, p.libelle, p.programme.code, p.get_statut_display(),
         f"{p.budget_total:,.0f}".replace(',', ' '), f"{p.taux_avancement}%"]
        for p in projets
    ]
    return simple_list_pdf(
        request, title='Activités',
        headers=['Code', 'Libellé', 'Action', 'Statut', 'Budget (FCFA)', 'Avancement'],
        rows=rows, filename='activites.pdf',
    )
