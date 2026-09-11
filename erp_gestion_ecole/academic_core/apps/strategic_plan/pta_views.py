"""
Plan de Travail Annuel (PTA) — voir models.py::PlanTravailAnnuel.

Même convention que le reste de l'app strategic_plan : vues function-based,
formulaires HTML bruts postés directement, imports de modèles locaux à
chaque vue.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from academic_core.apps.academic_structure.utils import resolve_academic_years


def _pta_required(request):
    if not request.user.can_manage_pta():
        messages.error(request, "Accès réservé aux titulaires d'un Plan de Travail Annuel.")
        return redirect('dashboard:index')
    return None


def _pta_oversight_required(user):
    """Rôles de supervision institut-wide pouvant consulter les PTA de tous
    les titulaires (pas seulement le leur) — sous-ensemble de can_manage_pta."""
    role = user.role_name
    return role in ('ADMIN', 'INST_ADMIN', 'SI_ADMIN', 'CONTROLEUR')


def _get_or_create_my_plan(user, academic_year):
    from .models import PlanTravailAnnuel
    plan, _created = PlanTravailAnnuel.objects.get_or_create(
        academic_year=academic_year, titulaire=user,
        defaults={'direction': user.direction},
    )
    return plan


@login_required
def pta_my_plan_view(request):
    """Le PTA du titulaire connecté pour l'année académique sélectionnée —
    créé automatiquement à la première visite (aucune ligne tant qu'il n'en
    ajoute pas)."""
    err = _pta_required(request)
    if err:
        return err

    academic_years, selected_year = resolve_academic_years(request)
    if not selected_year:
        messages.error(request, "Aucune année académique disponible.")
        return redirect('dashboard:index')

    plan = _get_or_create_my_plan(request.user, selected_year)
    return _render_plan_detail(request, plan, academic_years, selected_year, is_owner=True)


@login_required
def pta_plan_detail_view(request, pk):
    """Consultation d'un PTA précis — le titulaire lui-même, ou un rôle de
    supervision institut-wide (lecture des lignes ; les actions de
    création/modification/suppression restent réservées au titulaire)."""
    err = _pta_required(request)
    if err:
        return err

    from .models import PlanTravailAnnuel
    plan = get_object_or_404(
        PlanTravailAnnuel.objects.select_related('titulaire', 'direction', 'academic_year'), pk=pk,
    )
    is_owner = plan.titulaire_id == request.user.pk
    if not is_owner and not _pta_oversight_required(request.user):
        messages.error(request, "Ce Plan de Travail Annuel ne vous appartient pas.")
        return redirect('strategic_plan:pta_my_plan')

    academic_years, _ = resolve_academic_years(request)
    return _render_plan_detail(request, plan, academic_years, plan.academic_year, is_owner=is_owner)


def _render_plan_detail(request, plan, academic_years, selected_year, is_owner):
    from .models import AxeStrategique, ObjectifStrategique, PlanTravailAnnuelLigne

    lignes = list(
        plan.lignes.select_related('objectif_strategique', 'objectif_strategique__axe').order_by(
            'objectif_strategique__axe__code', 'objectif_strategique__code', 'ordre', 'pk',
        )
    )

    # Regroupement par Objectif stratégique (donc par Axe, via l'objectif),
    # pour un affichage fidèle à la maquette Excel (une section par objectif).
    groupes = {}
    for l in lignes:
        o = l.objectif_strategique
        entry = groupes.setdefault(o.pk, {'objectif': o, 'lignes': []})
        entry['lignes'].append(l)
    groupes_list = sorted(groupes.values(), key=lambda g: (g['objectif'].axe.code if g['objectif'].axe else '', g['objectif'].code))

    return render(request, 'strategic_plan/pta_detail.html', {
        'plan': plan,
        'is_owner': is_owner,
        'has_oversight': _pta_oversight_required(request.user),
        'academic_years': academic_years,
        'selected_year': selected_year,
        'groupes': groupes_list,
        'axes': AxeStrategique.objects.order_by('code'),
        'objectifs': ObjectifStrategique.objects.select_related('axe').order_by('axe__code', 'code'),
        'realisation_choices': PlanTravailAnnuelLigne.REALISATION_CHOICES,
    })


@login_required
def pta_all_plans_view(request):
    """Vue de supervision institut-wide : liste des PTA de tous les
    titulaires pour l'année académique sélectionnée."""
    if not _pta_oversight_required(request.user):
        messages.error(request, "Accès réservé aux rôles de supervision.")
        return redirect('dashboard:index')

    from .models import PlanTravailAnnuel

    academic_years, selected_year = resolve_academic_years(request)
    plans = PlanTravailAnnuel.objects.select_related('titulaire', 'titulaire__role', 'direction').filter(
        academic_year=selected_year,
    ).order_by('titulaire__last_name') if selected_year else PlanTravailAnnuel.objects.none()

    from django.db.models import Avg, Count

    plans = list(plans)
    for p in plans:
        agg = p.lignes.aggregate(nb=Count('pk'), taux=Avg('realisations'))
        p.nb_lignes = agg['nb'] or 0
        p.taux_realisation = round(agg['taux']) if agg['taux'] is not None else 0

    return render(request, 'strategic_plan/pta_all_plans.html', {
        'academic_years': academic_years,
        'selected_year': selected_year,
        'plans': plans,
    })


@login_required
def pta_line_create(request):
    err = _pta_required(request)
    if err:
        return err
    if request.method != 'POST':
        return redirect('strategic_plan:pta_my_plan')

    from .models import ObjectifStrategique, PlanTravailAnnuelLigne
    from academic_core.apps.academic_structure.models import AcademicYear

    academic_year = AcademicYear.objects.filter(pk=request.POST.get('academic_year')).first()
    if not academic_year:
        messages.error(request, "Année académique invalide.")
        return redirect('strategic_plan:pta_my_plan')
    plan = _get_or_create_my_plan(request.user, academic_year)

    objectif = ObjectifStrategique.objects.filter(pk=request.POST.get('objectif_strategique')).first()
    if not objectif:
        messages.error(request, "L'objectif stratégique est obligatoire.")
        return redirect(f"{_plan_url(plan)}?annee={academic_year.pk}")

    PlanTravailAnnuelLigne.objects.create(
        plan=plan, objectif_strategique=objectif,
        activites=request.POST.get('activites', '').strip(),
        date_debut_activite=request.POST.get('date_debut_activite') or None,
        date_fin_activite=request.POST.get('date_fin_activite') or None,
        indicateur_performance=request.POST.get('indicateur_performance', '').strip(),
        element_preuve=request.POST.get('element_preuve', '').strip(),
        realisations=_parse_realisations(request.POST.get('realisations')),
    )
    messages.success(request, "Ligne ajoutée au Plan de Travail Annuel.")
    return redirect(f"{_plan_url(plan)}?annee={academic_year.pk}")


@login_required
def pta_line_edit(request, pk):
    err = _pta_required(request)
    if err:
        return err
    from .models import PlanTravailAnnuelLigne, ObjectifStrategique
    ligne = get_object_or_404(PlanTravailAnnuelLigne.objects.select_related('plan'), pk=pk)
    if ligne.plan.titulaire_id != request.user.pk:
        messages.error(request, "Vous ne pouvez modifier que votre propre Plan de Travail Annuel.")
        return redirect('strategic_plan:pta_my_plan')
    if request.method != 'POST':
        return redirect(_plan_url(ligne.plan))

    objectif = ObjectifStrategique.objects.filter(pk=request.POST.get('objectif_strategique')).first()
    if not objectif:
        messages.error(request, "L'objectif stratégique est obligatoire.")
        return redirect(_plan_url(ligne.plan))

    ligne.objectif_strategique = objectif
    ligne.activites = request.POST.get('activites', '').strip()
    ligne.date_debut_activite = request.POST.get('date_debut_activite') or None
    ligne.date_fin_activite = request.POST.get('date_fin_activite') or None
    ligne.indicateur_performance = request.POST.get('indicateur_performance', '').strip()
    ligne.element_preuve = request.POST.get('element_preuve', '').strip()
    ligne.realisations = _parse_realisations(request.POST.get('realisations'))
    ligne.save()
    messages.success(request, "Ligne modifiée.")
    return redirect(_plan_url(ligne.plan))


@login_required
def pta_line_delete(request, pk):
    err = _pta_required(request)
    if err:
        return err
    from .models import PlanTravailAnnuelLigne
    ligne = get_object_or_404(PlanTravailAnnuelLigne.objects.select_related('plan'), pk=pk)
    if ligne.plan.titulaire_id != request.user.pk:
        messages.error(request, "Vous ne pouvez modifier que votre propre Plan de Travail Annuel.")
        return redirect('strategic_plan:pta_my_plan')
    if request.method != 'POST':
        return redirect(_plan_url(ligne.plan))
    plan = ligne.plan
    ligne.delete()
    messages.success(request, "Ligne supprimée.")
    return redirect(_plan_url(plan))


def _plan_url(plan):
    from django.urls import reverse
    return reverse('strategic_plan:pta_plan_detail', args=[plan.pk])


def _parse_realisations(raw):
    """Arrondit au palier de 10% valide le plus proche — 0 par défaut si vide/invalide."""
    from .models import PlanTravailAnnuelLigne
    valid = dict(PlanTravailAnnuelLigne.REALISATION_CHOICES)
    try:
        val = int(float(str(raw).strip().rstrip('%'))) if raw not in (None, '') else 0
    except (TypeError, ValueError):
        return 0
    if val in valid:
        return val
    nearest = min(valid.keys(), key=lambda v: abs(v - val))
    return nearest


def _parse_excel_date(val):
    """Convertit une cellule Excel (datetime déjà typée par openpyxl, ou
    texte AAAA-MM-JJ) en date Python — None si vide/invalide."""
    if not val:
        return None
    if hasattr(val, 'date'):
        return val.date() if hasattr(val, 'hour') else val
    from datetime import datetime as _dt
    try:
        return _dt.strptime(str(val).strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


@login_required
def pta_import(request):
    """Import Excel des lignes du PTA du titulaire connecté, pour l'année
    académique sélectionnée — colonnes reprises de la maquette Excel fournie
    (Objectifs stratégiques, Activités, dates de début/fin d'activité,
    Indicateur de performance, Élément de preuve)."""
    err = _pta_required(request)
    if err:
        return err

    from academic_core.excel_utils import build_xlsx_template, read_xlsx_upload
    from academic_core.apps.academic_structure.models import AcademicYear
    from .models import ObjectifStrategique, PlanTravailAnnuelLigne

    academic_years, selected_year = resolve_academic_years(request)

    headers = [
        'Objectifs stratégiques (code)', 'Activités',
        'Date de début (AAAA-MM-JJ)', 'Date de fin (AAAA-MM-JJ)',
        'Indicateur de performance', 'Élément de preuve', 'Réalisations (%)',
    ]
    if request.method == 'GET' and request.GET.get('download'):
        premier_objectif = ObjectifStrategique.objects.first()
        return build_xlsx_template(
            filename='modele_import_pta.xlsx', sheet_title='PTA',
            headers=headers,
            example_row=[
                premier_objectif.code if premier_objectif else 'OBJ1',
                "- Réviser les contenus pédagogiques\n\n- Organiser des conférences et webinaires",
                '2026-01-01', '2026-06-30',
                '100% des syllabus mis à jour',
                "Rapport d'activité",
                50,
            ],
            notes=[
                "Objectifs stratégiques (code) : doit correspondre exactement au code d'un objectif "
                "stratégique existant (voir « Objectifs stratégiques » sous Plan stratégique — son Axe "
                "stratégique en est déduit automatiquement).",
                "Réalisations (%) : palier de 10 en 10 — 0, 10, 20, 30, 40, 50, 60, 70, 80, 90 ou 100. "
                "Vide ou invalide = 0%.",
            ],
        )
    if request.method != 'POST':
        return render(request, 'strategic_plan/import_generic.html', {
            'entity_label': 'Plan de Travail Annuel',
            'back_url': f"/plan-strategique/pta/mon-pta/?annee={selected_year.pk}" if selected_year else '/plan-strategique/pta/mon-pta/',
            'columns_help': [
                ('Objectifs stratégiques (code)', True, "Code exact d'un objectif stratégique existant — son Axe stratégique en est déduit"),
                ('Activités', False, 'Une activité par ligne dans la cellule'),
                ('Date de début (AAAA-MM-JJ)', False, "Date de début de l'activité"),
                ('Date de fin (AAAA-MM-JJ)', False, "Date de fin de l'activité"),
                ('Indicateur de performance', False, ''),
                ('Élément de preuve', False, ''),
                ('Réalisations (%)', False, 'Palier de 10 en 10, de 0 à 100 — vide = 0%'),
            ],
        })

    if not selected_year:
        messages.error(request, "Aucune année académique sélectionnée.")
        return redirect('strategic_plan:pta_import')

    xlsx_file = request.FILES.get('xlsx_file')
    if not xlsx_file or not xlsx_file.name.endswith('.xlsx'):
        messages.error(request, "Merci de déposer un fichier .xlsx (utilisez le modèle fourni).")
        return redirect('strategic_plan:pta_import')

    plan = _get_or_create_my_plan(request.user, selected_year)

    created, skipped, errors = 0, 0, []
    for line_num, row in read_xlsx_upload(xlsx_file, len(headers)):
        (objectif_code, activites, date_debut, date_fin,
         indicateur, preuve, realisations) = row
        objectif = ObjectifStrategique.objects.filter(code__iexact=str(objectif_code or '').strip()).first()
        if not objectif:
            skipped += 1
            errors.append(f"Ligne {line_num} : l'objectif stratégique (existant) est obligatoire.")
            continue
        PlanTravailAnnuelLigne.objects.create(
            plan=plan, objectif_strategique=objectif,
            activites=str(activites or '').strip(),
            date_debut_activite=_parse_excel_date(date_debut),
            date_fin_activite=_parse_excel_date(date_fin),
            indicateur_performance=str(indicateur or '').strip(),
            element_preuve=str(preuve or '').strip(),
            realisations=_parse_realisations(realisations),
        )
        created += 1

    if created:
        messages.success(request, f"{created} ligne(s) importée(s) dans votre Plan de Travail Annuel {selected_year}.")
    if skipped:
        messages.warning(request, f"{skipped} ligne(s) ignorée(s).")
    for e in errors[:8]:
        messages.error(request, e)
    if len(errors) > 8:
        messages.error(request, f"... et {len(errors) - 8} autre(s) erreur(s).")
    return redirect(f"{_plan_url(plan)}?annee={selected_year.pk}")


@login_required
def pta_pdf(request, pk):
    """Export PDF d'un PTA, dans le même format que la maquette Excel
    (une section par Objectif stratégique)."""
    from .models import PlanTravailAnnuel
    plan = get_object_or_404(
        PlanTravailAnnuel.objects.select_related('titulaire', 'academic_year'), pk=pk,
    )
    if plan.titulaire_id != request.user.pk and not _pta_oversight_required(request.user):
        messages.error(request, "Ce Plan de Travail Annuel ne vous appartient pas.")
        return redirect('strategic_plan:pta_my_plan')

    import io
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from django.http import HttpResponse
    from django.utils.html import escape
    from academic_core.pdf_utils import get_institut_config_for_request, logo_image, watermark_canvas

    lignes = list(
        plan.lignes.select_related('objectif_strategique', 'objectif_strategique__axe').order_by(
            'objectif_strategique__axe__code', 'objectif_strategique__code', 'ordre', 'pk',
        )
    )
    groupes = {}
    for l in lignes:
        o = l.objectif_strategique
        entry = groupes.setdefault(o.pk, {'objectif': o, 'lignes': []})
        entry['lignes'].append(l)
    groupes_list = sorted(groupes.values(), key=lambda g: (g['objectif'].axe.code if g['objectif'].axe else '', g['objectif'].code))

    config = get_institut_config_for_request(request)
    institut_nom = (config.nom or config.sigle) if config else 'Plateforme de Gestion Académique'

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('pta_title', parent=styles['Heading1'], alignment=TA_CENTER,
                                  fontSize=14, textColor=colors.HexColor('#003D82'))
    subtitle_style = ParagraphStyle('pta_subtitle', parent=styles['Normal'], alignment=TA_CENTER,
                                     fontSize=9, textColor=colors.HexColor('#64748B'))
    obj_style = ParagraphStyle('pta_obj', parent=styles['Normal'], fontSize=9.5, leading=12,
                                textColor=colors.white, fontName='Helvetica-Bold')
    header_style = ParagraphStyle('pta_header', parent=styles['Normal'], fontSize=8, leading=10,
                                   textColor=colors.white, fontName='Helvetica-Bold')
    cell_style = ParagraphStyle('pta_cell', parent=styles['Normal'], fontSize=7.5, leading=9.5)

    story = []
    logo = logo_image(width=1.6 * cm, height=1.6 * cm, config=config)
    if logo:
        head_tbl = Table([[logo, Paragraph(f"<b>{escape(institut_nom)}</b>", title_style)]], colWidths=[2 * cm, None])
        head_tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (1, 0), (1, 0), 'CENTER')]))
        story.append(head_tbl)
    else:
        story.append(Paragraph(escape(institut_nom), title_style))
    story.append(Paragraph(f"PLAN DE TRAVAIL ANNUEL — {plan.academic_year}", title_style))
    story.append(Paragraph(escape(plan.titulaire.get_full_name()), subtitle_style))
    story.append(Spacer(1, 0.4 * cm))

    col_widths = [6.5 * cm, 2 * cm, 2 * cm, 4.5 * cm, 4.5 * cm, 1.8 * cm]
    for g in groupes_list:
        o = g['objectif']
        heading = f"{o.code} — {o.libelle}"
        if o.axe:
            heading += f" (Axe : {o.axe.code} — {o.axe.libelle})"
        story.append(Table([[Paragraph(escape(heading), obj_style)]], colWidths=[sum(col_widths)],
                            style=TableStyle([
                                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#003D82')),
                                ('LEFTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 5),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                            ])))
        table_data = [[
            Paragraph(h, header_style) for h in
            ['Activités', 'Début', 'Fin', 'Indicateur de performance', 'Élément de preuve', 'Réalisations']
        ]]
        for l in g['lignes']:
            table_data.append([
                Paragraph(escape(l.activites).replace('\n', '<br/>'), cell_style),
                Paragraph(l.date_debut_activite.strftime('%d/%m/%Y') if l.date_debut_activite else '—', cell_style),
                Paragraph(l.date_fin_activite.strftime('%d/%m/%Y') if l.date_fin_activite else '—', cell_style),
                Paragraph(escape(l.indicateur_performance).replace('\n', '<br/>'), cell_style),
                Paragraph(escape(l.element_preuve).replace('\n', '<br/>'), cell_style),
                Paragraph(f"{l.realisations}%", cell_style),
            ])
        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1d4ed8')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F1F5F9')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.4 * cm))

    if not groupes_list:
        story.append(Paragraph("Aucune ligne renseignée.", cell_style))

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="PTA_{plan.academic_year}_{plan.titulaire.last_name}.pdf"'
    return response
