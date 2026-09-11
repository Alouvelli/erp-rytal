"""
Indicateurs KPI — Pilotage et Suivi Budgétaire.
Même convention que accounting/budget_views.py.
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse


def _budget_required(user):
    role = user.role_name
    return role in ('CONTROLEUR', 'INST_ADMIN', 'SI_ADMIN', 'ADMIN_DAF', 'ADMIN')


def _denied(request):
    messages.error(request, "Accès réservé au Pilotage et Suivi Budgétaire.")
    return redirect('dashboard:index')


def _rattachement_queryset():
    """(label, ContentType, queryset) pour les 4 types d'objets du PSD auxquels un indicateur peut se rattacher."""
    from academic_core.apps.strategic_plan.models import AxeStrategique, ObjectifStrategique, Programme, Projet
    return [
        ('Axe stratégique', ContentType.objects.get_for_model(AxeStrategique), AxeStrategique.objects.all()),
        ('Objectif stratégique', ContentType.objects.get_for_model(ObjectifStrategique), ObjectifStrategique.objects.all()),
        ('Programme', ContentType.objects.get_for_model(Programme), Programme.objects.all()),
        ('Projet', ContentType.objects.get_for_model(Projet), Projet.objects.all()),
    ]


@login_required
def indicateur_list(request):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Indicateur
    # Pas de select_related('content_type') : ContentType vit uniquement dans
    # la base 'default' (modèle MASTER), un JOIN SQL cross-DB est impossible.
    indicateurs = Indicateur.objects.select_related('responsable')
    return render(request, 'indicators/indicateur_list.html', {
        'indicateurs': indicateurs,
        'rattachements': _rattachement_queryset(),
        'PERIODICITE_CHOICES': Indicateur.PERIODICITE_CHOICES,
        'SENS_CHOICES': Indicateur.SENS_CHOICES,
        'users': _users_queryset(),
    })


def _users_queryset():
    from academic_core.apps.accounts.models import User
    return User.objects.filter(is_active=True).order_by('first_name', 'last_name')


@login_required
def indicateur_detail(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    import json
    from .models import Indicateur
    indicateur = get_object_or_404(Indicateur.objects.select_related('responsable'), pk=pk)
    mesures = list(indicateur.historique.order_by('date_mesure')[:24])
    return render(request, 'indicators/indicateur_detail.html', {
        'indicateur': indicateur,
        'mesures': list(reversed(mesures)),
        'chart_labels_json': json.dumps([m.date_mesure.isoformat() for m in mesures]),
        'chart_values_json': json.dumps([float(m.valeur) for m in mesures]),
        'users': _users_queryset(),
    })


@login_required
def indicateur_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('indicators:indicateur_list')
    from .models import Indicateur

    code = request.POST.get('code', '').strip()
    libelle = request.POST.get('libelle', '').strip()
    if not code or not libelle:
        messages.error(request, "Code et libellé sont obligatoires.")
        return redirect('indicators:indicateur_list')
    if Indicateur.objects.filter(code__iexact=code).exists():
        messages.error(request, f"Le code « {code} » est déjà utilisé.")
        return redirect('indicators:indicateur_list')

    try:
        valeur_cible = Decimal(request.POST.get('valeur_cible', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        valeur_cible = Decimal('0')

    periodicite = request.POST.get('periodicite', Indicateur.PERIODICITE_TRIMESTRIELLE)
    if periodicite not in dict(Indicateur.PERIODICITE_CHOICES):
        periodicite = Indicateur.PERIODICITE_TRIMESTRIELLE
    sens = request.POST.get('sens_amelioration', Indicateur.SENS_HAUSSE_SOUHAITEE)
    if sens not in dict(Indicateur.SENS_CHOICES):
        sens = Indicateur.SENS_HAUSSE_SOUHAITEE

    content_type = None
    object_id = None
    rattachement = request.POST.get('rattachement', '')
    if '|' in rattachement:
        ct_id, obj_id = rattachement.split('|', 1)
        if ct_id.isdigit() and obj_id.isdigit():
            content_type = ContentType.objects.filter(pk=int(ct_id)).first()
            object_id = int(obj_id)

    Indicateur.objects.create(
        code=code, libelle=libelle,
        formule=request.POST.get('formule', '').strip(),
        source=request.POST.get('source', '').strip(),
        responsable_id=request.POST.get('responsable') or None,
        periodicite=periodicite,
        unite=request.POST.get('unite', '').strip(),
        sens_amelioration=sens,
        valeur_cible=valeur_cible,
        content_type=content_type,
        object_id=object_id,
    )
    messages.success(request, f"Indicateur « {libelle} » créé.")
    return redirect('indicators:indicateur_list')


@login_required
def indicateur_edit(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Indicateur
    indicateur = get_object_or_404(Indicateur, pk=pk)
    if request.method != 'POST':
        return redirect('indicators:indicateur_list')

    indicateur.libelle = request.POST.get('libelle', indicateur.libelle).strip()
    indicateur.formule = request.POST.get('formule', '').strip()
    indicateur.source = request.POST.get('source', '').strip()
    indicateur.responsable_id = request.POST.get('responsable') or None
    indicateur.unite = request.POST.get('unite', '').strip()

    periodicite = request.POST.get('periodicite', '')
    if periodicite in dict(Indicateur.PERIODICITE_CHOICES):
        indicateur.periodicite = periodicite
    sens = request.POST.get('sens_amelioration', '')
    if sens in dict(Indicateur.SENS_CHOICES):
        indicateur.sens_amelioration = sens
    try:
        indicateur.valeur_cible = Decimal(request.POST.get('valeur_cible', '0').replace(' ', '').replace(',', '.') or '0')
    except InvalidOperation:
        pass
    indicateur.save()
    messages.success(request, "Indicateur modifié.")
    return redirect('indicators:indicateur_list')


@login_required
def indicateur_delete(request, pk):
    if not _budget_required(request.user):
        return _denied(request)
    from .models import Indicateur
    indicateur = get_object_or_404(Indicateur, pk=pk)
    if request.method != 'POST':
        return redirect('indicators:indicateur_list')
    indicateur.delete()
    messages.success(request, "Indicateur supprimé.")
    return redirect('indicators:indicateur_list')


def _resolve_user_by_email(email):
    if not email:
        return None
    from academic_core.apps.accounts.models import User
    return User.objects.filter(email__iexact=str(email).strip()).first()


@login_required
def indicateur_import(request):
    if not _budget_required(request.user):
        return _denied(request)
    from decimal import Decimal, InvalidOperation
    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from .models import Indicateur

    headers = ['Code', 'Libellé', 'Valeur cible', 'Formule', 'Source', 'Responsable (email)',
               'Périodicité', 'Unité', "Sens d'amélioration", 'Seuil orange', 'Seuil rouge']
    if request.method == 'GET' and request.GET.get('download'):
        return build_xlsx_template(
            filename='modele_import_indicateurs.xlsx', sheet_title='Indicateurs',
            headers=headers,
            example_row=[
                'IND1', 'Taux de réussite global', 85, 'Nb admis / Nb inscrits', 'Scolarité',
                '', 'annuelle', '%', 'hausse_souhaitee', 0.80, 0.60,
            ],
            notes=[
                'Périodicité — valeurs autorisées : mensuelle, trimestrielle, semestrielle, annuelle',
                "Sens d'amélioration — valeurs autorisées : hausse_souhaitee, baisse_souhaitee",
                'Seuil orange / Seuil rouge — nombre décimal entre 0 et 1 (ex. 0.80 = 80% de la cible)',
            ],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Indicateurs',
            'back_url': reverse('indicators:indicateur_list'),
            'columns_help': [
                ('Code', True, 'Doit être unique'),
                ('Libellé', True, ''),
                ('Valeur cible', True, 'Nombre'),
                ('Formule', False, ''),
                ('Source', False, ''),
                ('Responsable (email)', False, "Email d'un utilisateur existant"),
                ('Périodicité', False, 'mensuelle / trimestrielle / semestrielle / annuelle'),
                ('Unité', False, 'ex. %, FCFA, nombre'),
                ("Sens d'amélioration", False, 'hausse_souhaitee / baisse_souhaitee'),
                ('Seuil orange', False, 'Nombre décimal entre 0 et 1'),
                ('Seuil rouge', False, 'Nombre décimal entre 0 et 1'),
            ],
        })

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('indicators:indicateur_import')

    def _to_decimal(val, default):
        if val in (None, ''):
            return default
        try:
            return Decimal(str(val).replace(' ', '').replace(',', '.'))
        except InvalidOperation:
            return default

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        (code, libelle, valeur_cible, formule, source, resp_email,
         periodicite, unite, sens, seuil_orange, seuil_rouge) = row
        code = str(code or '').strip()
        libelle = str(libelle or '').strip()
        if not code or not libelle or valeur_cible in (None, ''):
            skipped += 1
            errors.append(f"Ligne {line_num} : code, libellé et valeur cible sont obligatoires.")
            continue
        if Indicateur.objects.filter(code__iexact=code).exists():
            skipped += 1
            errors.append(f"Ligne {line_num} : le code « {code} » est déjà utilisé.")
            continue
        periodicite = str(periodicite or '').strip()
        if periodicite not in dict(Indicateur.PERIODICITE_CHOICES):
            periodicite = Indicateur.PERIODICITE_TRIMESTRIELLE
        sens = str(sens or '').strip()
        if sens not in dict(Indicateur.SENS_CHOICES):
            sens = Indicateur.SENS_HAUSSE_SOUHAITEE
        Indicateur.objects.create(
            code=code, libelle=libelle,
            valeur_cible=_to_decimal(valeur_cible, Decimal('0')),
            formule=str(formule or '').strip(), source=str(source or '').strip(),
            responsable=_resolve_user_by_email(resp_email),
            periodicite=periodicite, unite=str(unite or '').strip(), sens_amelioration=sens,
            seuil_orange=_to_decimal(seuil_orange, Decimal('0.80')),
            seuil_rouge=_to_decimal(seuil_rouge, Decimal('0.60')),
        )
        created += 1

    if created:
        messages.success(request, f"{created} indicateur(s) importé(s).")
    if skipped:
        messages.warning(request, f"{skipped} ligne(s) ignorée(s).")
    for err in errors[:8]:
        messages.error(request, err)
    if len(errors) > 8:
        messages.error(request, f"... et {len(errors) - 8} autre(s) erreur(s).")
    return redirect('indicators:indicateur_list')


@login_required
def indicateur_pdf(request):
    if not _budget_required(request.user):
        return _denied(request)
    from academic_core.pdf_utils import simple_list_pdf
    from .models import Indicateur

    indicateurs = Indicateur.objects.select_related('responsable')
    rows = [
        [i.code, i.libelle, f"{i.valeur_actuelle} / {i.valeur_cible}" + (f" {i.unite}" if i.unite else ''),
         i.get_periodicite_display(), i.responsable.get_full_name() if i.responsable else '—']
        for i in indicateurs
    ]
    return simple_list_pdf(
        request, title='Indicateurs',
        headers=['Code', 'Libellé', 'Valeur actuelle / Cible', 'Périodicité', 'Responsable'],
        rows=rows, filename='indicateurs.pdf',
    )


@login_required
def valeur_create(request):
    if not _budget_required(request.user):
        return _denied(request)
    if request.method != 'POST':
        return redirect('indicators:indicateur_list')
    from .models import Indicateur, ValeurIndicateur

    indicateur = Indicateur.objects.filter(pk=request.POST.get('indicateur')).first()
    date_mesure = request.POST.get('date_mesure') or None
    try:
        valeur = Decimal(request.POST.get('valeur', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        valeur = None

    if not indicateur or not date_mesure or valeur is None:
        messages.error(request, "Indicateur, date de mesure et valeur sont obligatoires.")
        return redirect('indicators:indicateur_detail', pk=indicateur.pk) if indicateur else redirect('indicators:indicateur_list')

    ValeurIndicateur.objects.create(
        indicateur=indicateur, date_mesure=date_mesure, valeur=valeur,
        commentaire=request.POST.get('commentaire', '').strip(), saisi_par=request.user,
    )
    messages.success(request, "Mesure enregistrée.")
    return redirect('indicators:indicateur_detail', pk=indicateur.pk)
