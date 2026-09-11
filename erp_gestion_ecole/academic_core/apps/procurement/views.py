"""
Achats — Pilotage et Suivi Budgétaire. Même convention que
accounting/budget_views.py.
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from academic_core.apps.accounting.budget_services import BudgetInsuffisantError, TransitionWorkflowInvalideError


def _budget_required(user):
    role = user.role_name
    return role in ('CONTROLEUR', 'INST_ADMIN', 'SI_ADMIN', 'ADMIN_DAF', 'ADMIN')


def _denied(request):
    messages.error(request, "Accès réservé au Pilotage et Suivi Budgétaire.")
    return redirect('dashboard:index')


# ─────────────────────────────────────────────────────────────────────────────
# Fournisseurs
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def fournisseur_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Fournisseur
    return render(request, 'procurement/fournisseur_list.html', {'fournisseurs': Fournisseur.objects.all()})


@login_required
def fournisseur_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:fournisseur_list')
    from .models import Fournisseur
    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, "Le nom est obligatoire.")
        return redirect('procurement:fournisseur_list')
    Fournisseur.objects.create(
        nom=nom, contact_nom=request.POST.get('contact_nom', '').strip(),
        telephone=request.POST.get('telephone', '').strip(), email=request.POST.get('email', '').strip(),
        adresse=request.POST.get('adresse', '').strip(),
    )
    messages.success(request, f"Fournisseur « {nom} » créé.")
    return redirect('procurement:fournisseur_list')


@login_required
def fournisseur_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Fournisseur
    f = get_object_or_404(Fournisseur, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:fournisseur_list')
    f.nom = request.POST.get('nom', f.nom).strip()
    f.contact_nom = request.POST.get('contact_nom', '').strip()
    f.telephone = request.POST.get('telephone', '').strip()
    f.email = request.POST.get('email', '').strip()
    f.adresse = request.POST.get('adresse', '').strip()
    f.is_active = request.POST.get('is_active') == 'on'
    f.save()
    messages.success(request, "Fournisseur modifié.")
    return redirect('procurement:fournisseur_list')


@login_required
def fournisseur_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Fournisseur
    f = get_object_or_404(Fournisseur, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:fournisseur_list')
    if f.commandes.exists() or f.offres.exists():
        messages.error(request, f"Impossible de supprimer « {f.nom} » : utilisé par des offres/commandes.")
        return redirect('procurement:fournisseur_list')
    f.delete()
    messages.success(request, "Fournisseur supprimé.")
    return redirect('procurement:fournisseur_list')


# ─────────────────────────────────────────────────────────────────────────────
# Demandes d'achat
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def demande_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import DemandeAchat
    from academic_core.apps.accounts.models import Direction
    from academic_core.apps.accounting.models import LigneBudgetaire
    from academic_core.apps.academic_structure.utils import resolve_academic_years

    academic_years, selected_year = resolve_academic_years(request)
    lignes = LigneBudgetaire.objects.filter(academic_year=selected_year) if selected_year else LigneBudgetaire.objects.none()

    return render(request, 'procurement/demande_list.html', {
        'demandes': DemandeAchat.objects.select_related('centre_cout', 'ligne_budgetaire', 'demandeur'),
        'directions': Direction.objects.filter(is_active=True).order_by('name'),
        'lignes': lignes.select_related('direction', 'compte_comptable'),
        'TYPE_CHOICES': DemandeAchat.TYPE_CHOICES,
        'STATUT_CHOICES': DemandeAchat.STATUT_CHOICES,
    })


@login_required
def demande_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:demande_list')
    from .models import DemandeAchat
    from academic_core.apps.accounts.models import Direction
    from academic_core.apps.accounting.models import LigneBudgetaire

    objet = request.POST.get('objet', '').strip()
    centre_cout = Direction.objects.filter(pk=request.POST.get('centre_cout')).first()
    try:
        montant_estime = Decimal(request.POST.get('montant_estime', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        montant_estime = None
    if not objet or not centre_cout or montant_estime is None:
        messages.error(request, "Objet, centre de coût et montant estimé sont obligatoires.")
        return redirect('procurement:demande_list')

    ligne = LigneBudgetaire.objects.filter(pk=request.POST.get('ligne_budgetaire')).first()
    type_depense = request.POST.get('type_depense', DemandeAchat.TYPE_FOURNITURES)
    if type_depense not in dict(DemandeAchat.TYPE_CHOICES):
        type_depense = DemandeAchat.TYPE_FOURNITURES

    demande = DemandeAchat.objects.create(
        objet=objet, centre_cout=centre_cout, ligne_budgetaire=ligne, type_depense=type_depense,
        demandeur=request.user, montant_estime=montant_estime,
        justification=request.POST.get('justification', '').strip(),
    )
    messages.success(request, f"Demande d'achat {demande.reference} créée en brouillon.")
    return redirect('procurement:demande_list')


@login_required
def demande_soumettre(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import DemandeAchat
    from .services import DemandeAchatService
    demande = get_object_or_404(DemandeAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:demande_list')
    try:
        DemandeAchatService.soumettre(demande, request.user)
        messages.success(request, f"Demande {demande.reference} soumise pour validation.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('procurement:demande_list')


@login_required
def demande_valider(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import DemandeAchat
    from .services import DemandeAchatService
    demande = get_object_or_404(DemandeAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:demande_list')
    try:
        DemandeAchatService.valider(demande, request.user)
        messages.success(request, f"Demande {demande.reference} validée.")
    except (BudgetInsuffisantError, TransitionWorkflowInvalideError) as exc:
        messages.error(request, str(exc))
    return redirect('procurement:demande_list')


@login_required
def demande_rejeter(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import DemandeAchat
    from .services import DemandeAchatService
    demande = get_object_or_404(DemandeAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:demande_list')
    try:
        DemandeAchatService.rejeter(demande, request.user, request.POST.get('commentaire', '').strip())
        messages.success(request, f"Demande {demande.reference} rejetée.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('procurement:demande_list')


@login_required
def demande_annuler(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import DemandeAchat
    from .services import DemandeAchatService
    demande = get_object_or_404(DemandeAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:demande_list')
    try:
        DemandeAchatService.annuler(demande, request.user)
        messages.success(request, f"Demande {demande.reference} annulée.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('procurement:demande_list')


# ─────────────────────────────────────────────────────────────────────────────
# Appels d'offres / Offres fournisseurs
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def appel_offres_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import AppelOffres, DemandeAchat, Fournisseur
    return render(request, 'procurement/appel_offres_list.html', {
        'appels': AppelOffres.objects.select_related('demande_achat').prefetch_related('offres__fournisseur'),
        'demandes': DemandeAchat.objects.filter(statut=DemandeAchat.STATUT_VALIDEE, appel_offres__isnull=True),
        'fournisseurs': Fournisseur.objects.filter(is_active=True),
    })


@login_required
def appel_offres_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:appel_offres_list')
    from .models import AppelOffres, DemandeAchat
    demande = DemandeAchat.objects.filter(pk=request.POST.get('demande_achat')).first()
    if not demande:
        messages.error(request, "Demande d'achat obligatoire.")
        return redirect('procurement:appel_offres_list')
    if hasattr(demande, 'appel_offres'):
        messages.error(request, "Un appel d'offres existe déjà pour cette demande.")
        return redirect('procurement:appel_offres_list')
    AppelOffres.objects.create(
        demande_achat=demande, description=request.POST.get('description', '').strip(),
        date_limite=request.POST.get('date_limite') or None,
    )
    messages.success(request, "Appel d'offres créé.")
    return redirect('procurement:appel_offres_list')


@login_required
def offre_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:appel_offres_list')
    from .models import AppelOffres, Fournisseur, OffreFournisseur
    appel = AppelOffres.objects.filter(pk=request.POST.get('appel_offres')).first()
    fournisseur = Fournisseur.objects.filter(pk=request.POST.get('fournisseur')).first()
    try:
        montant = Decimal(request.POST.get('montant_propose', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        montant = None
    if not appel or not fournisseur or montant is None:
        messages.error(request, "Appel d'offres, fournisseur et montant proposé sont obligatoires.")
        return redirect('procurement:appel_offres_list')
    OffreFournisseur.objects.create(
        appel_offres=appel, fournisseur=fournisseur, montant_propose=montant,
        document=request.FILES.get('document'),
    )
    messages.success(request, "Offre enregistrée.")
    return redirect('procurement:appel_offres_list')


@login_required
def offre_retenir(request, pk):
    """Retient l'offre, clôture l'appel d'offres (statut=attribue) et rejette les autres offres."""
    if not _budget_required(request.user):
        return _denied(request)
    from .models import OffreFournisseur, AppelOffres
    offre = get_object_or_404(OffreFournisseur, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:appel_offres_list')
    offre.statut = OffreFournisseur.STATUT_RETENUE
    offre.save(update_fields=['statut'])
    offre.appel_offres.offres.exclude(pk=offre.pk).update(statut=OffreFournisseur.STATUT_REJETEE)
    offre.appel_offres.statut = AppelOffres.STATUT_ATTRIBUE
    offre.appel_offres.save(update_fields=['statut'])
    messages.success(request, f"Offre de {offre.fournisseur} retenue.")
    return redirect('procurement:appel_offres_list')


# ─────────────────────────────────────────────────────────────────────────────
# Commandes
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def commande_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CommandeAchat, DemandeAchat, Fournisseur
    return render(request, 'procurement/commande_list.html', {
        'commandes': CommandeAchat.objects.select_related('demande_achat', 'fournisseur'),
        'demandes': DemandeAchat.objects.filter(statut=DemandeAchat.STATUT_VALIDEE),
        'fournisseurs': Fournisseur.objects.filter(is_active=True),
        'STATUT_CHOICES': CommandeAchat.STATUT_CHOICES,
    })


@login_required
def commande_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:commande_list')
    from .models import CommandeAchat, DemandeAchat, Fournisseur
    demande = DemandeAchat.objects.filter(pk=request.POST.get('demande_achat')).first()
    fournisseur = Fournisseur.objects.filter(pk=request.POST.get('fournisseur')).first()
    try:
        montant = Decimal(request.POST.get('montant', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        montant = None
    if not demande or not fournisseur or montant is None:
        messages.error(request, "Demande d'achat, fournisseur et montant sont obligatoires.")
        return redirect('procurement:commande_list')
    CommandeAchat.objects.create(
        demande_achat=demande, fournisseur=fournisseur, montant=montant,
        date_livraison_prevue=request.POST.get('date_livraison_prevue') or None,
    )
    messages.success(request, "Commande créée.")
    return redirect('procurement:commande_list')


@login_required
def commande_livrer(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import CommandeAchat
    commande = get_object_or_404(CommandeAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:commande_list')
    commande.statut = CommandeAchat.STATUT_LIVREE
    commande.save(update_fields=['statut'])
    messages.success(request, f"Commande {commande.reference} marquée livrée.")
    return redirect('procurement:commande_list')


@login_required
def reception_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:commande_list')
    from .models import CommandeAchat, ReceptionAchat
    commande = CommandeAchat.objects.filter(pk=request.POST.get('commande')).first()
    if not commande:
        messages.error(request, "Commande obligatoire.")
        return redirect('procurement:commande_list')
    ReceptionAchat.objects.create(
        commande=commande, conforme=request.POST.get('conforme') == 'on',
        commentaire=request.POST.get('commentaire', '').strip(), recu_par=request.user,
    )
    commande.statut = CommandeAchat.STATUT_LIVREE
    commande.save(update_fields=['statut'])
    messages.success(request, "Réception enregistrée.")
    return redirect('procurement:commande_list')


# ─────────────────────────────────────────────────────────────────────────────
# Factures / Paiements
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def facture_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import FactureAchat, CommandeAchat, PaiementAchat
    return render(request, 'procurement/facture_list.html', {
        'factures': FactureAchat.objects.select_related('commande', 'commande__fournisseur').prefetch_related('paiements'),
        'commandes': CommandeAchat.objects.exclude(statut=CommandeAchat.STATUT_ANNULEE),
        'MODE_CHOICES': PaiementAchat.MODE_CHOICES,
    })


@login_required
def facture_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:facture_list')
    from .models import FactureAchat, CommandeAchat
    commande = CommandeAchat.objects.filter(pk=request.POST.get('commande')).first()
    numero = request.POST.get('numero_facture', '').strip()
    try:
        montant = Decimal(request.POST.get('montant', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        montant = None
    if not commande or not numero or montant is None:
        messages.error(request, "Commande, numéro de facture et montant sont obligatoires.")
        return redirect('procurement:facture_list')
    if FactureAchat.objects.filter(commande=commande, numero_facture=numero).exists():
        messages.error(request, "Cette facture existe déjà pour cette commande.")
        return redirect('procurement:facture_list')
    FactureAchat.objects.create(commande=commande, numero_facture=numero, montant=montant, piece_jointe=request.FILES.get('piece_jointe'))
    messages.success(request, f"Facture {numero} créée.")
    return redirect('procurement:facture_list')


@login_required
def facture_valider(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import FactureAchat
    facture = get_object_or_404(FactureAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:facture_list')
    facture.statut = FactureAchat.STATUT_VALIDEE
    facture.save(update_fields=['statut'])
    messages.success(request, f"Facture {facture.numero_facture} validée.")
    return redirect('procurement:facture_list')


@login_required
def paiement_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('procurement:facture_list')
    from .models import FactureAchat, PaiementAchat
    facture = FactureAchat.objects.filter(pk=request.POST.get('facture')).first()
    try:
        montant = Decimal(request.POST.get('montant', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        montant = None
    if not facture or montant is None:
        messages.error(request, "Facture et montant sont obligatoires.")
        return redirect('procurement:facture_list')
    mode = request.POST.get('mode_paiement', PaiementAchat.MODE_VIREMENT)
    if mode not in dict(PaiementAchat.MODE_CHOICES):
        mode = PaiementAchat.MODE_VIREMENT
    PaiementAchat.objects.create(
        facture=facture, montant=montant, mode_paiement=mode,
        reference_paiement=request.POST.get('reference_paiement', '').strip(),
    )
    messages.success(request, "Paiement planifié.")
    return redirect('procurement:facture_list')


@login_required
def paiement_effectuer(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import PaiementAchat
    from .services import PaiementService
    paiement = get_object_or_404(PaiementAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:facture_list')
    try:
        PaiementService.effectuer(paiement, request.user)
        messages.success(request, "Paiement effectué — dépense générée et budget mis à jour.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('procurement:facture_list')


@login_required
def paiement_annuler(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import PaiementAchat
    from .services import PaiementService
    paiement = get_object_or_404(PaiementAchat, pk=pk)
    if request.method != 'POST':
        return redirect('procurement:facture_list')
    try:
        PaiementService.annuler(paiement, request.user)
        messages.success(request, "Paiement annulé — dépense générée retirée, budget mis à jour.")
    except TransitionWorkflowInvalideError as exc:
        messages.error(request, str(exc))
    return redirect('procurement:facture_list')
