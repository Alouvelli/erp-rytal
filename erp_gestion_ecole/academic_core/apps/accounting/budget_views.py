"""
Pilotage et Suivi Budgétaire — Contrôleur Interne, Administrateur d'institut,
Directeur Administratif et Financier (ADMIN_DAF).

Style aligné sur le reste de accounting/views.py : gardes _require_* prenant
`user`, imports de modèles locaux à chaque vue, formulaires HTML bruts (pas de
ModelForm) postés directement, pagination/recherche minimales cohérentes avec
caisse_movement_list/demande_depense_list.
"""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404

from academic_core.apps.academic_structure.utils import resolve_academic_years


def _budget_required(user):
    """
    Pilotage et Suivi Budgétaire : Contrôleur Interne, Administrateur d'institut
    (INST_ADMIN/SI_ADMIN), Directeur Administratif et Financier (ADMIN_DAF), et
    le Super Admin pour dépannage. Volontairement PAS user.is_admin() — ce
    helper est large (inclut COMPTABLE/CAISSIER/TRESORIER_GENERAL/ADMIN_RH…)
    et dépasserait le périmètre des 3 rôles demandés pour ce module.
    """
    role = user.role_name
    return role in ('CONTROLEUR', 'INST_ADMIN', 'SI_ADMIN', 'ADMIN_DAF', 'ADMIN')


# ─────────────────────────────────────────────────────────────────────────────
# Tableau de bord — Pilotage
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def budget_dashboard(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès réservé au Pilotage et Suivi Budgétaire.")
        return redirect('dashboard:index')

    from .models import LigneBudgetaire

    academic_years, selected_year = resolve_academic_years(request)

    lignes = list(
        LigneBudgetaire.objects.select_related('direction', 'compte_comptable', 'source_financement')
        .filter(academic_year=selected_year)
    ) if selected_year else []

    totaux = {
        'revise':   sum((l.montant_revise for l in lignes), Decimal('0')),
        'engage':   sum((l.montant_engage for l in lignes), Decimal('0')),
        'execute':  sum((l.montant_execute for l in lignes), Decimal('0')),
    }
    totaux['disponible'] = totaux['revise'] - totaux['engage']
    totaux['taux'] = (totaux['execute'] / totaux['revise']) if totaux['revise'] else Decimal('0')

    # Répartition par Direction, pour le graphique Chart.js (révisé vs exécuté).
    par_direction = {}
    for l in lignes:
        d = par_direction.setdefault(l.direction.name, {'revise': Decimal('0'), 'execute': Decimal('0')})
        d['revise']  += l.montant_revise
        d['execute'] += l.montant_execute

    alertes = [l for l in lignes if l.statut_kpi in ('orange', 'rouge')]
    alertes.sort(key=lambda l: l.taux_execution, reverse=True)

    return render(request, 'accounting/budget/dashboard.html', {
        'academic_years': academic_years,
        'selected_year':  selected_year,
        'totaux':         totaux,
        'alertes':        alertes,
        'par_direction_labels_json':  json.dumps(list(par_direction.keys())),
        'par_direction_revise_json':  json.dumps([float(v['revise']) for v in par_direction.values()]),
        'par_direction_execute_json': json.dumps([float(v['execute']) for v in par_direction.values()]),
        'has_chart_data': bool(par_direction),
        'nb_lignes': len(lignes),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Balanced Scorecard
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def bsc_dashboard(request):
    """
    Reprend get_bsc_data() du projet de référence : regroupe les
    ObjectifStrategique par PerspectiveBSC, calcule un niveau_realisation par
    objectif à partir des Indicateur liés (generic FK) ou, à défaut, de la
    moyenne des Projet.taux_avancement rattachés (via Programme).
    """
    if not _budget_required(request.user):
        messages.error(request, "Accès réservé au Pilotage et Suivi Budgétaire.")
        return redirect('dashboard:index')

    from django.contrib.contenttypes.models import ContentType
    from academic_core.apps.strategic_plan.models import ObjectifStrategique
    from academic_core.apps.indicators.models import Indicateur

    from academic_core.apps.strategic_plan.models import Projet

    objectif_ct = ContentType.objects.get_for_model(ObjectifStrategique)
    objectifs = list(
        ObjectifStrategique.objects.select_related('axe', 'responsable').exclude(perspective_bsc='')
    )

    perspectives = []
    for code, label in ObjectifStrategique.PERSPECTIVE_CHOICES:
        cartes = []
        for o in objectifs:
            if o.perspective_bsc != code:
                continue
            indicateurs = list(Indicateur.objects.filter(content_type=objectif_ct, object_id=o.pk))
            projets = list(Projet.objects.filter(programme__objectif=o))
            if indicateurs:
                niveau = round(sum(i.taux_realisation for i in indicateurs) / len(indicateurs) * 100)
            elif projets:
                niveau = round(sum(p.taux_avancement for p in projets) / len(projets))
            else:
                niveau = 0
            budget_cumule = sum((p.budget_total for p in projets), Decimal('0'))
            cartes.append({
                'objectif': o, 'indicateurs': indicateurs, 'projets': projets,
                'niveau_realisation': niveau, 'budget_cumule': budget_cumule,
            })
        perspectives.append({'code': code, 'label': label, 'cartes': cartes})

    return render(request, 'accounting/budget/bsc_dashboard.html', {'perspectives': perspectives})


# ─────────────────────────────────────────────────────────────────────────────
# Sources de financement
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def source_financement_list(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import SourceFinancement
    sources = SourceFinancement.objects.order_by('libelle')
    return render(request, 'accounting/budget/source_financement_list.html', {
        'sources': sources,
        'TYPE_CHOICES': SourceFinancement.TYPE_CHOICES,
    })


@login_required
def source_financement_create(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('accounting:source_financement_list')

    from .models import SourceFinancement
    code    = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    type_source = request.POST.get('type_source', '').strip()

    if not code or not libelle or type_source not in dict(SourceFinancement.TYPE_CHOICES):
        messages.error(request, "Code, libellé et type sont obligatoires.")
        return redirect('accounting:source_financement_list')
    if SourceFinancement.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('accounting:source_financement_list')

    SourceFinancement.objects.create(
        code=code, libelle=libelle, type_source=type_source, created_by=request.user,
    )
    messages.success(request, f"Source de financement « {libelle} » créée.")
    return redirect('accounting:source_financement_list')


@login_required
def source_financement_edit(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import SourceFinancement
    source = get_object_or_404(SourceFinancement, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:source_financement_list')

    source.libelle = request.POST.get('libelle', source.libelle).strip()
    type_source = request.POST.get('type_source', '').strip()
    if type_source in dict(SourceFinancement.TYPE_CHOICES):
        source.type_source = type_source
    source.is_active = request.POST.get('is_active') == 'on'
    source.save()
    messages.success(request, f"Source « {source.libelle} » modifiée.")
    return redirect('accounting:source_financement_list')


@login_required
def source_financement_delete(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import SourceFinancement
    source = get_object_or_404(SourceFinancement, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:source_financement_list')
    if source.lignes_budgetaires.exists():
        messages.error(request, f"Impossible de supprimer « {source.libelle} » : utilisée par des lignes budgétaires.")
        return redirect('accounting:source_financement_list')
    libelle = source.libelle
    source.delete()
    messages.success(request, f"Source « {libelle} » supprimée.")
    return redirect('accounting:source_financement_list')


# ─────────────────────────────────────────────────────────────────────────────
# Lignes budgétaires
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def ligne_budgetaire_list(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import LigneBudgetaire, SourceFinancement, CompteComptable
    from academic_core.apps.accounts.models import Direction
    from academic_core.apps.strategic_plan.models import AxeStrategique, Projet

    academic_years, selected_year = resolve_academic_years(request)

    qs = LigneBudgetaire.objects.select_related(
        'direction', 'compte_comptable', 'source_financement', 'academic_year'
    ).filter(academic_year=selected_year) if selected_year else LigneBudgetaire.objects.none()

    direction_filt = request.GET.get('direction', '').strip()
    if direction_filt.isdigit():
        qs = qs.filter(direction_id=int(direction_filt))
    nature_filt = request.GET.get('nature', '').strip()
    if nature_filt in dict(LigneBudgetaire.NATURE_CHOICES):
        qs = qs.filter(nature=nature_filt)

    return render(request, 'accounting/budget/ligne_budgetaire_list.html', {
        'academic_years': academic_years,
        'selected_year':  selected_year,
        'lignes': qs.order_by('direction__name'),
        'directions': Direction.objects.filter(is_active=True).order_by('name'),
        'sources': SourceFinancement.objects.filter(is_active=True).order_by('libelle'),
        'comptes': CompteComptable.objects.filter(is_active=True).order_by('matricule'),
        'axes': AxeStrategique.objects.all(),
        'projets': Projet.objects.all(),
        'NATURE_CHOICES': LigneBudgetaire.NATURE_CHOICES,
        'direction_filter': direction_filt,
        'nature_filter': nature_filt,
    })


@login_required
def ligne_budgetaire_create(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('accounting:ligne_budgetaire_list')

    from .models import LigneBudgetaire, SourceFinancement, CompteComptable
    from academic_core.apps.academic_structure.models import AcademicYear
    from academic_core.apps.accounts.models import Direction

    academic_year = AcademicYear.objects.filter(pk=request.POST.get('academic_year')).first()
    direction     = Direction.objects.filter(pk=request.POST.get('direction')).first()
    compte        = CompteComptable.objects.filter(pk=request.POST.get('compte_comptable')).first()
    source        = SourceFinancement.objects.filter(pk=request.POST.get('source_financement')).first()
    nature        = request.POST.get('nature', LigneBudgetaire.NATURE_FONCTIONNEMENT)

    if not (academic_year and direction and compte and source):
        messages.error(request, "Exercice, Direction, compte comptable et source de financement sont obligatoires.")
        return redirect('accounting:ligne_budgetaire_list')

    try:
        montant_initial = Decimal(request.POST.get('montant_initial', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        montant_initial = Decimal('0')

    if LigneBudgetaire.objects.filter(
        academic_year=academic_year, direction=direction, compte_comptable=compte, source_financement=source,
    ).exists():
        messages.error(request, "Une ligne budgétaire existe déjà pour cette combinaison Exercice / Direction / Compte / Source.")
        return redirect('accounting:ligne_budgetaire_list')

    from academic_core.apps.strategic_plan.models import AxeStrategique, Projet
    axe = AxeStrategique.objects.filter(pk=request.POST.get('axe_strategique')).first()
    projet = Projet.objects.filter(pk=request.POST.get('projet')).first()

    ligne = LigneBudgetaire.objects.create(
        academic_year=academic_year, direction=direction, compte_comptable=compte,
        source_financement=source, nature=nature, montant_initial=montant_initial,
        axe_strategique=axe, projet=projet,
        notes=request.POST.get('notes', '').strip(), created_by=request.user,
    )
    messages.success(request, f"Ligne budgétaire créée pour {direction.name}.")
    return redirect('accounting:ligne_budgetaire_detail', pk=ligne.pk)


@login_required
def ligne_budgetaire_edit(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import LigneBudgetaire
    ligne = get_object_or_404(LigneBudgetaire, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:ligne_budgetaire_detail', pk=pk)

    try:
        montant_initial = Decimal(request.POST.get('montant_initial', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        montant_initial = ligne.montant_initial

    ligne.montant_initial = montant_initial
    nature = request.POST.get('nature', '')
    if nature in dict(LigneBudgetaire.NATURE_CHOICES):
        ligne.nature = nature
    ligne.notes = request.POST.get('notes', '').strip()
    ligne.save()
    messages.success(request, "Ligne budgétaire modifiée.")
    return redirect('accounting:ligne_budgetaire_detail', pk=pk)


@login_required
def ligne_budgetaire_detail(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import LigneBudgetaire
    ligne = get_object_or_404(
        LigneBudgetaire.objects.select_related('direction', 'compte_comptable', 'source_financement', 'academic_year'),
        pk=pk,
    )
    return render(request, 'accounting/budget/ligne_budgetaire_detail.html', {
        'ligne': ligne,
        'engagements': ligne.engagements.select_related('demandeur').order_by('-date_engagement'),
        'rectificatifs': ligne.rectificatifs.select_related('demande_par', 'valide_par').order_by('-demande_at'),
        'demandes_depense': ligne.demandes_depense.order_by('-requested_at'),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Suivi budgétaire par direction — rapproche le budget alloué (Lignes
# budgétaires, où Direction est déjà la dimension obligatoire) et les sorties
# de caisse réellement décaissées (Entrée & Sortie Caisse) : le bénéficiaire
# d'une sortie de caisse relève toujours d'une direction, donc du budget de
# cette direction (voir CaisseMovement.direction). Accessible au Pilotage et
# Suivi Budgétaire ET à la Direction Financière (Trésorier Général/Caissier).
# ─────────────────────────────────────────────────────────────────────────────

def _budget_or_caisse_required(user):
    return _budget_required(user) or user.is_tresorier() or user.is_caissier()


@login_required
def suivi_budget_directions(request):
    if not _budget_or_caisse_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import LigneBudgetaire, CaisseMovement
    from academic_core.apps.accounts.models import Direction

    academic_years, selected_year = resolve_academic_years(request)
    directions = list(Direction.objects.filter(is_active=True).order_by('name'))

    lignes_par_direction = {}
    non_rattaches = 0
    if selected_year:
        for l in LigneBudgetaire.objects.filter(academic_year=selected_year).only('direction_id', 'montant_revise'):
            lignes_par_direction[l.direction_id] = lignes_par_direction.get(l.direction_id, Decimal('0')) + l.montant_revise

        sorties_qs = CaisseMovement.objects.filter(
            movement_type=CaisseMovement.TYPE_SORTIE, is_executed=True, academic_year=selected_year,
            direction__isnull=False,
        ).values('direction_id').annotate(total=Sum('amount'))
        sorties_par_direction = {row['direction_id']: row['total'] for row in sorties_qs}

        # Sorties de caisse exécutées mais pas encore rattachées à une
        # direction — signalé pour inciter à compléter la saisie.
        non_rattaches = CaisseMovement.objects.filter(
            movement_type=CaisseMovement.TYPE_SORTIE, is_executed=True, academic_year=selected_year,
            direction__isnull=True,
        ).count()
    else:
        sorties_par_direction = {}

    rows = []
    for d in directions:
        budget = lignes_par_direction.get(d.pk, Decimal('0'))
        sorties = sorties_par_direction.get(d.pk, Decimal('0'))
        rows.append({
            'direction': d, 'budget': budget, 'sorties': sorties,
            'restant': budget - sorties,
            'taux': (sorties / budget) if budget else Decimal('0'),
        })

    return render(request, 'accounting/budget/suivi_directions.html', {
        'academic_years': academic_years,
        'selected_year': selected_year,
        'rows': rows,
        'non_rattaches': non_rattaches,
    })


@login_required
def suivi_budget_direction_detail(request, pk):
    # Lecture seule autorisée en plus des rôles budget/caisse habituels : un
    # utilisateur peut toujours consulter le suivi budgétaire de SA PROPRE
    # direction (User.direction), ex. le Responsable de la Direction
    # Pédagogique via le raccourci "Suivi budget Direction" — sans lui donner
    # accès aux autres directions ni aux écrans de gestion (lignes/engagements/
    # rectificatifs), qui restent strictement réservés à _budget_or_caisse_required.
    is_own_direction = request.user.direction_id and str(request.user.direction_id) == str(pk)
    if not (_budget_or_caisse_required(request.user) or is_own_direction):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from datetime import datetime as _dt
    from .models import LigneBudgetaire, CaisseMovement
    from academic_core.apps.accounts.models import Direction

    direction = get_object_or_404(Direction, pk=pk)
    academic_years, selected_year = resolve_academic_years(request)

    budget = Decimal('0')
    if selected_year:
        budget = LigneBudgetaire.objects.filter(
            academic_year=selected_year, direction=direction,
        ).aggregate(t=Sum('montant_revise'))['t'] or Decimal('0')

    date_from_raw = request.GET.get('from', '')
    date_to_raw   = request.GET.get('to', '')
    today = date.today()
    try:
        date_from = _dt.strptime(date_from_raw, '%Y-%m-%d').date() if date_from_raw else today.replace(day=1)
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = _dt.strptime(date_to_raw, '%Y-%m-%d').date() if date_to_raw else today
    except ValueError:
        date_to = today

    qs = CaisseMovement.objects.filter(
        direction=direction, movement_type=CaisseMovement.TYPE_SORTIE, is_executed=True,
        movement_date__gte=date_from, movement_date__lte=date_to,
    )
    if selected_year:
        qs = qs.filter(academic_year=selected_year)

    par_jour = {}
    for m in qs.order_by('movement_date'):
        par_jour[m.movement_date] = par_jour.get(m.movement_date, Decimal('0')) + m.amount

    total_sorties_annee = Decimal('0')
    if selected_year:
        total_sorties_annee = CaisseMovement.objects.filter(
            direction=direction, movement_type=CaisseMovement.TYPE_SORTIE, is_executed=True,
            academic_year=selected_year,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # Le cumul/restant affichés par jour se basent sur le cumul annuel déjà
    # consommé AVANT le début de la période affichée, pour rester exact même
    # si la période filtrée ne commence pas au 1er jour de l'exercice.
    cumul_avant_periode = Decimal('0')
    if selected_year:
        cumul_avant_periode = CaisseMovement.objects.filter(
            direction=direction, movement_type=CaisseMovement.TYPE_SORTIE, is_executed=True,
            academic_year=selected_year, movement_date__lt=date_from,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    cumul = cumul_avant_periode
    jours = []
    for jour in sorted(par_jour.keys()):
        cumul += par_jour[jour]
        jours.append({
            'date': jour, 'montant_jour': par_jour[jour],
            'cumul': cumul, 'restant': budget - cumul,
        })

    return render(request, 'accounting/budget/suivi_direction_detail.html', {
        'direction': direction,
        'academic_years': academic_years,
        'selected_year': selected_year,
        'budget': budget,
        'total_sorties_annee': total_sorties_annee,
        'restant_annee': budget - total_sorties_annee,
        'taux_annee': (total_sorties_annee / budget) if budget else Decimal('0'),
        'date_from': date_from,
        'date_to': date_to,
        'jours': jours,
        'total_periode': sum(par_jour.values(), Decimal('0')),
        'can_manage_budget': _budget_or_caisse_required(request.user),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Budgets rectificatifs
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def rectificatif_list(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import BudgetRectificatif, LigneBudgetaire

    academic_years, selected_year = resolve_academic_years(request)
    lignes = LigneBudgetaire.objects.filter(academic_year=selected_year) if selected_year else LigneBudgetaire.objects.none()

    rectificatifs = BudgetRectificatif.objects.select_related(
        'ligne_budgetaire__direction', 'ligne_budgetaire__compte_comptable', 'demande_par', 'valide_par'
    ).filter(ligne_budgetaire__in=lignes).order_by('-demande_at')

    return render(request, 'accounting/budget/rectificatif_list.html', {
        'academic_years': academic_years,
        'selected_year':  selected_year,
        'rectificatifs': rectificatifs,
        'lignes': lignes.select_related('direction', 'compte_comptable'),
    })


@login_required
def rectificatif_create(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('accounting:rectificatif_list')

    from .models import BudgetRectificatif, LigneBudgetaire
    ligne = LigneBudgetaire.objects.filter(pk=request.POST.get('ligne_budgetaire')).first()
    motif = request.POST.get('motif', '').strip()
    try:
        montant_ajustement = Decimal(request.POST.get('montant_ajustement', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        montant_ajustement = None

    if not ligne or montant_ajustement is None or not motif:
        messages.error(request, "Ligne budgétaire, montant d'ajustement et motif sont obligatoires.")
        return redirect('accounting:rectificatif_list')

    BudgetRectificatif.objects.create(
        ligne_budgetaire=ligne, montant_ajustement=montant_ajustement, motif=motif, demande_par=request.user,
    )
    messages.success(request, "Demande de rectificatif budgétaire créée.")
    return redirect('accounting:rectificatif_list')


@login_required
def rectificatif_valider(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import BudgetRectificatif
    from .budget_services import RectificatifService, TransitionWorkflowInvalideError
    rectificatif = get_object_or_404(BudgetRectificatif, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:rectificatif_list')
    try:
        RectificatifService.valider(rectificatif, request.user)
        messages.success(request, "Rectificatif validé — le montant révisé de la ligne a été mis à jour.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('accounting:rectificatif_list')


@login_required
def rectificatif_rejeter(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import BudgetRectificatif
    from .budget_services import RectificatifService, TransitionWorkflowInvalideError
    rectificatif = get_object_or_404(BudgetRectificatif, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:rectificatif_list')
    try:
        RectificatifService.rejeter(rectificatif, request.user, request.POST.get('commentaire', '').strip())
        messages.success(request, "Rectificatif rejeté.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('accounting:rectificatif_list')


# ─────────────────────────────────────────────────────────────────────────────
# Engagements budgétaires
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def engagement_list(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import EngagementBudgetaire, LigneBudgetaire

    academic_years, selected_year = resolve_academic_years(request)
    lignes = LigneBudgetaire.objects.filter(academic_year=selected_year) if selected_year else LigneBudgetaire.objects.none()

    statut_filt = request.GET.get('statut', '').strip()
    engagements = EngagementBudgetaire.objects.select_related(
        'ligne_budgetaire__direction', 'ligne_budgetaire__compte_comptable', 'demandeur'
    ).filter(ligne_budgetaire__in=lignes)
    if statut_filt in dict(EngagementBudgetaire.STATUT_CHOICES):
        engagements = engagements.filter(statut=statut_filt)

    return render(request, 'accounting/budget/engagement_list.html', {
        'academic_years': academic_years,
        'selected_year':  selected_year,
        'engagements': engagements.order_by('-date_engagement'),
        'lignes': lignes.select_related('direction', 'compte_comptable'),
        'STATUT_CHOICES': EngagementBudgetaire.STATUT_CHOICES,
        'statut_filter': statut_filt,
    })


@login_required
def engagement_create(request):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('accounting:engagement_list')

    from .models import EngagementBudgetaire, LigneBudgetaire
    ligne = LigneBudgetaire.objects.filter(pk=request.POST.get('ligne_budgetaire')).first()
    objet = request.POST.get('objet', '').strip()
    try:
        montant = Decimal(request.POST.get('montant', '').replace(' ', '').replace(',', '.'))
        if montant <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        montant = None

    if not ligne or not objet or montant is None:
        messages.error(request, "Ligne budgétaire, objet et montant sont obligatoires.")
        return redirect('accounting:engagement_list')

    engagement = EngagementBudgetaire.objects.create(
        ligne_budgetaire=ligne, objet=objet, montant=montant,
        demandeur=request.user, piece_justificative=request.FILES.get('piece_justificative'),
    )
    messages.success(request, f"Engagement {engagement.reference} créé en brouillon.")
    return redirect('accounting:engagement_list')


@login_required
def engagement_soumettre(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import EngagementBudgetaire
    from .budget_services import EngagementService, TransitionWorkflowInvalideError
    engagement = get_object_or_404(EngagementBudgetaire, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:engagement_list')
    try:
        EngagementService.soumettre(engagement, request.user)
        messages.success(request, f"Engagement {engagement.reference} soumis pour validation.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('accounting:engagement_list')


@login_required
def engagement_valider(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import EngagementBudgetaire
    from .budget_services import EngagementService, TransitionWorkflowInvalideError, BudgetInsuffisantError
    engagement = get_object_or_404(EngagementBudgetaire, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:engagement_list')
    try:
        EngagementService.valider(engagement, request.user)
        messages.success(request, f"Engagement {engagement.reference} validé — montant réservé sur la ligne budgétaire.")
    except BudgetInsuffisantError as exc:
        messages.error(request, str(exc))
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('accounting:engagement_list')


@login_required
def engagement_rejeter(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import EngagementBudgetaire
    from .budget_services import EngagementService, TransitionWorkflowInvalideError
    engagement = get_object_or_404(EngagementBudgetaire, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:engagement_list')
    try:
        EngagementService.rejeter(engagement, request.user, request.POST.get('commentaire', '').strip())
        messages.success(request, f"Engagement {engagement.reference} rejeté.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('accounting:engagement_list')


@login_required
def engagement_annuler(request, pk):
    if not _budget_required(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    from .models import EngagementBudgetaire
    from .budget_services import EngagementService, TransitionWorkflowInvalideError
    engagement = get_object_or_404(EngagementBudgetaire, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:engagement_list')
    try:
        EngagementService.annuler(engagement, request.user)
        messages.success(request, f"Engagement {engagement.reference} annulé.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('accounting:engagement_list')
