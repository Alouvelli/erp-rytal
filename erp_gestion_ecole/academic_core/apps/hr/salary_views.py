"""
Gestion du personnel, des salaires et des bulletins de salaire (Ressources Humaines).
"""
import io
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import HttpResponse

from .models import FichePersonnel, SalaireConfig, BulletinSalaire
from .views import _hr_required, _HR_MANAGERS, _get_staff_queryset
from .export_utils import build_docx_table_response

MONTHS_FR = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
             'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


def _decimal(val, default='0'):
    try:
        return Decimal(str(val).replace(',', '.').strip() or default)
    except (InvalidOperation, AttributeError):
        return Decimal(default)


# ═══════════════════════════════════════════════════════════════════════════
# GESTION DU PERSONNEL
# ═══════════════════════════════════════════════════════════════════════════

@login_required
@_hr_required
def personnel_list(request):
    """Liste du personnel (groupée par département/direction, en accordéon) avec leur fiche employé."""
    staff_qs = _get_staff_queryset(request)

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        staff_qs = staff_qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(matricule_employe__icontains=q) | Q(email__icontains=q)
        )

    fiches = {
        f.user_id: f for f in FichePersonnel.objects.filter(user__in=staff_qs)
    }

    groups_map = {}
    teacher_dept_map = {}
    for emp in staff_qs:
        row = {'employe': emp, 'fiche': fiches.get(emp.pk)}
        # Les enseignants sont regroupés à part, sous le rôle "Enseignant",
        # eux-mêmes répartis par département (plutôt que mélangés aux groupes
        # Direction/Département du reste du personnel).
        if emp.is_enseignant():
            dept_key = (emp.department_id, emp.department.name if emp.department else 'Sans département')
            teacher_dept_map.setdefault(dept_key, []).append(row)
            continue
        # La direction prime sur le département : un utilisateur affecté à une
        # direction (onglet Utilisateurs) doit apparaître sous cette direction
        # ici, même s'il conserve par ailleurs un département historique.
        if emp.direction:
            label = emp.direction.name
        elif emp.department:
            label = emp.department.name
        else:
            label = 'Non affecté'
        groups_map.setdefault(label, []).append(row)

    # Inclure aussi les directions créées (Direction Générale > Directions),
    # même sans personnel actuellement affecté (via Utilisateurs), pour que
    # toute direction créée reste visible ici.
    from academic_core.apps.accounts.models import Direction
    faculty = getattr(request, 'active_faculty', None)
    direction_qs = Direction.objects.filter(is_active=True)
    if faculty:
        direction_qs = direction_qs.filter(faculty=faculty)
    for d in direction_qs:
        groups_map.setdefault(d.name, [])

    groups = [
        {'label': label, 'rows': rows}
        for label, rows in sorted(groups_map.items(), key=lambda kv: (kv[0] == 'Non affecté', kv[0]))
    ]

    teacher_groups = [
        {'label': label, 'dept_id': dept_id, 'rows': rows}
        for (dept_id, label), rows in sorted(
            teacher_dept_map.items(), key=lambda kv: (kv[0][1] == 'Sans département', kv[0][1])
        )
    ]
    teacher_total = sum(len(g['rows']) for g in teacher_groups)

    return render(request, 'hr/personnel_list.html', {
        'groups': groups,
        'teacher_groups': teacher_groups,
        'teacher_total': teacher_total,
        'total_count': staff_qs.count(),
        'q': q,
        'is_manager': _is_manager(request),
    })


@login_required
@_hr_required
def personnel_archive(request, pk):
    """Archive un membre du personnel : compte désactivé, accès à la plateforme immédiatement révoqué."""
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:personnel_list')
    staff_qs = _get_staff_queryset(request)
    employe = get_object_or_404(staff_qs, pk=pk)
    if employe == request.user:
        messages.error(request, "Vous ne pouvez pas archiver votre propre compte.")
        return redirect('hr:personnel_list')
    if request.method == 'POST':
        from academic_core.apps.accounts.db_utils import deactivate_user_everywhere
        deactivate_user_everywhere(employe)
        messages.success(
            request,
            f"« {employe.get_full_name() or employe.username} » a été archivé(e) : "
            f"il/elle n'a plus accès à la plateforme. Réactivable depuis Utilisateurs.",
        )
    return redirect('hr:personnel_list')


@login_required
@_hr_required
def personnel_delete(request, pk):
    """
    Supprime définitivement un membre du personnel de la plateforme (compte utilisateur
    et toutes les données qui en dépendent directement) — action irréversible.
    """
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:personnel_list')
    staff_qs = _get_staff_queryset(request)
    employe = get_object_or_404(staff_qs, pk=pk)
    if employe == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
        return redirect('hr:personnel_list')
    if request.method == 'POST':
        from academic_core.apps.accounts.db_utils import delete_user_everywhere
        name = employe.get_full_name() or employe.username
        delete_user_everywhere(employe)
        messages.success(request, f"« {name} » a été définitivement supprimé(e) de la plateforme.")
    return redirect('hr:personnel_list')


@login_required
@_hr_required
def personnel_fiche_edit(request, pk):
    """Créer/modifier la fiche employé (informations contractuelles) d'un membre du personnel."""
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:personnel_list')

    staff_qs = _get_staff_queryset(request)
    employe  = get_object_or_404(staff_qs, pk=pk)
    fiche, _created = FichePersonnel.objects.get_or_create(user=employe)

    if request.method == 'POST':
        fiche.poste                     = request.POST.get('poste', '').strip()
        fiche.type_contrat              = request.POST.get('type_contrat', FichePersonnel.CONTRAT_CDI)
        fiche.date_embauche             = request.POST.get('date_embauche') or None
        fiche.date_fin_contrat          = request.POST.get('date_fin_contrat') or None
        fiche.numero_cnss               = request.POST.get('numero_cnss', '').strip()
        fiche.numero_ipres              = request.POST.get('numero_ipres', '').strip()
        fiche.adresse                   = request.POST.get('adresse', '').strip()
        fiche.contact_urgence_nom       = request.POST.get('contact_urgence_nom', '').strip()
        fiche.contact_urgence_telephone = request.POST.get('contact_urgence_telephone', '').strip()
        fiche.notes                     = request.POST.get('notes', '').strip()
        fiche.save()
        messages.success(request, f"Fiche personnel de {employe.get_full_name()} mise à jour.")
        return redirect('hr:personnel_list')

    return render(request, 'hr/personnel_fiche_edit.html', {
        'employe': employe,
        'fiche':   fiche,
        'CONTRAT_CHOICES': FichePersonnel.CONTRAT_CHOICES,
    })


# ═══════════════════════════════════════════════════════════════════════════
# GESTION DES SALAIRES
# ═══════════════════════════════════════════════════════════════════════════

@login_required
@_hr_required
def salaire_list(request):
    """Liste du personnel avec leur configuration salariale (base / primes / retenues / net)."""
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:dashboard')

    staff_qs = _get_staff_queryset(request)
    configs = {c.user_id: c for c in SalaireConfig.objects.filter(user__in=staff_qs)}

    rows = []
    total_masse = Decimal('0')
    for emp in staff_qs:
        cfg = configs.get(emp.pk)
        if cfg:
            total_masse += cfg.salaire_net
        rows.append({'employe': emp, 'config': cfg})

    return render(request, 'hr/salaire_list.html', {
        'rows': rows,
        'total_masse': total_masse,
    })


@login_required
@_hr_required
def salaire_edit(request, pk):
    """Créer/modifier la configuration salariale d'un employé."""
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:salaire_list')

    staff_qs = _get_staff_queryset(request)
    employe  = get_object_or_404(staff_qs, pk=pk)
    config, _created = SalaireConfig.objects.get_or_create(user=employe)
    # L'ancienneté est dérivée de la date d'embauche (FichePersonnel.date_embauche,
    # source unique déjà utilisée par le bulletin de salaire) — pas un champ à part
    # sur SalaireConfig, pour éviter deux valeurs qui pourraient diverger.
    fiche, _fiche_created = FichePersonnel.objects.get_or_create(user=employe)

    if request.method == 'POST':
        config.salaire_base = _decimal(request.POST.get('salaire_base'))
        config.primes       = _decimal(request.POST.get('primes'))
        config.retenues     = _decimal(request.POST.get('retenues'))
        config.notes        = request.POST.get('notes', '').strip()
        config.is_active    = request.POST.get('is_active') == 'on'
        config.updated_by   = request.user
        config.save()

        fiche.date_embauche = request.POST.get('date_embauche') or None
        fiche.save()

        messages.success(request, f"Salaire de {employe.get_full_name()} mis à jour.")
        return redirect('hr:salaire_list')

    return render(request, 'hr/salaire_edit.html', {
        'employe': employe,
        'config':  config,
        'fiche':   fiche,
        'anciennete': fiche.anciennete(),
    })


# ═══════════════════════════════════════════════════════════════════════════
# BULLETINS DE SALAIRE
# ═══════════════════════════════════════════════════════════════════════════

@login_required
@_hr_required
def bulletin_list(request):
    """Liste des bulletins de salaire d'un mois donné, avec génération en masse."""
    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))

    staff_qs = _get_staff_queryset(request)
    bulletins = {
        b.user_id: b for b in BulletinSalaire.objects.filter(
            annee=year, mois=month, user__in=staff_qs
        )
    }
    configs = {c.user_id: c for c in SalaireConfig.objects.filter(user__in=staff_qs, is_active=True)}

    rows = []
    total_net = Decimal('0')
    for emp in staff_qs:
        b = bulletins.get(emp.pk)
        if b:
            total_net += b.salaire_net
        rows.append({'employe': emp, 'bulletin': b, 'has_config': emp.pk in configs})

    prev_month = month - 1 if month > 1 else 12
    prev_year  = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year  = year if month < 12 else year + 1

    return render(request, 'hr/bulletin_list.html', {
        'rows': rows,
        'year': year, 'month': month, 'month_label': MONTHS_FR[month],
        'total_net': total_net,
        'prev_month': prev_month, 'prev_year': prev_year,
        'next_month': next_month, 'next_year': next_year,
        'is_manager': _is_manager(request),
    })


@login_required
@_hr_required
def bulletin_generate(request):
    """Génère (en brouillon) les bulletins du mois pour tout le personnel ayant une config salariale active."""
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:bulletin_list')
    if request.method != 'POST':
        return redirect('hr:bulletin_list')

    year  = int(request.POST.get('year'))
    month = int(request.POST.get('month'))

    staff_qs = _get_staff_queryset(request)
    configs = SalaireConfig.objects.filter(user__in=staff_qs, is_active=True).select_related('user')

    count = 0
    for cfg in configs:
        bulletin, created = BulletinSalaire.objects.get_or_create(
            user=cfg.user, annee=year, mois=month,
            defaults={
                'salaire_base': cfg.salaire_base,
                'primes':       cfg.primes,
                'retenues':     cfg.retenues,
                'generated_by': request.user,
            }
        )
        if created:
            count += 1

    messages.success(request, f"{count} bulletin(s) généré(s) pour {MONTHS_FR[month]} {year}.")
    return redirect(f"{request.path.replace('generer/', '')}?year={year}&month={month}")


def _bulletin_reference_date(bulletin):
    """Dernier jour du mois du bulletin — date de référence pour l'ancienneté affichée dessus."""
    return date(bulletin.annee, bulletin.mois, monthrange(bulletin.annee, bulletin.mois)[1])


@login_required
@_hr_required
def bulletin_detail(request, pk):
    """Consulter / modifier (si brouillon) / valider un bulletin de salaire."""
    staff_qs = _get_staff_queryset(request)
    bulletin = get_object_or_404(BulletinSalaire, pk=pk, user__in=staff_qs)
    is_manager = _is_manager(request)

    if request.method == 'POST' and is_manager and bulletin.statut == BulletinSalaire.STATUT_BROUILLON:
        action = request.POST.get('action')
        if action == 'save':
            bulletin.salaire_base = _decimal(request.POST.get('salaire_base'))
            bulletin.primes       = _decimal(request.POST.get('primes'))
            bulletin.retenues     = _decimal(request.POST.get('retenues'))
            bulletin.notes        = request.POST.get('notes', '').strip()
            bulletin.save()
            messages.success(request, "Bulletin mis à jour.")
        elif action == 'validate':
            bulletin.statut       = BulletinSalaire.STATUT_VALIDE
            bulletin.validated_by = request.user
            bulletin.validated_at = timezone.now()
            bulletin.save()
            messages.success(request, "Bulletin validé.")
        return redirect('hr:bulletin_detail', pk=bulletin.pk)

    if request.method == 'POST' and is_manager and bulletin.statut == BulletinSalaire.STATUT_VALIDE:
        if request.POST.get('action') == 'mark_paid':
            bulletin.statut = BulletinSalaire.STATUT_PAYE
            bulletin.date_paiement = request.POST.get('date_paiement') or timezone.now().date()
            bulletin.save()
            messages.success(request, "Bulletin marqué comme payé.")
        return redirect('hr:bulletin_detail', pk=bulletin.pk)

    fiche = FichePersonnel.objects.filter(user=bulletin.user).first()
    anciennete = fiche.anciennete(_bulletin_reference_date(bulletin)) if fiche else None

    return render(request, 'hr/bulletin_detail.html', {
        'bulletin': bulletin,
        'fiche': fiche,
        'anciennete': anciennete,
        'is_manager': is_manager,
        'month_label': MONTHS_FR[bulletin.mois],
    })


@login_required
@_hr_required
def bulletin_delete(request, pk):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:bulletin_list')
    staff_qs = _get_staff_queryset(request)
    bulletin = get_object_or_404(BulletinSalaire, pk=pk, user__in=staff_qs)
    if bulletin.statut != BulletinSalaire.STATUT_BROUILLON:
        messages.error(request, "Seuls les bulletins en brouillon peuvent être supprimés.")
        return redirect('hr:bulletin_detail', pk=pk)
    year, month = bulletin.annee, bulletin.mois
    bulletin.delete()
    messages.success(request, "Bulletin supprimé.")
    return redirect(f"/hr/bulletins/?year={year}&month={month}")


@login_required
@_hr_required
def bulletin_pdf(request, pk):
    """Génère le PDF du bulletin de salaire."""
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from academic_core.pdf_utils import logo_image as _logo_img_fn, get_institut_config_for_request as _gcfr, watermark_canvas

    staff_qs = _get_staff_queryset(request)
    bulletin = get_object_or_404(BulletinSalaire, pk=pk, user__in=staff_qs)
    employe  = bulletin.user
    fiche    = FichePersonnel.objects.filter(user=employe).first()

    config = _gcfr(request)
    nom_inst = getattr(config, 'nom', None) or "Institut Supérieur d'Informatique"
    _logo_img = _logo_img_fn(config=config, width=2*cm, height=1.4*cm)

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    green = colors.HexColor('#166534')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A5,
        rightMargin=1.3*cm, leftMargin=1.3*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm,
    )
    ss = getSampleStyleSheet()
    sc = ParagraphStyle

    s_ttl = sc('t', parent=ss['Normal'], alignment=TA_CENTER, fontSize=13, fontName='Helvetica-Bold', textColor=navy)
    s_sub = sc('s', parent=ss['Normal'], alignment=TA_CENTER, fontSize=9, textColor=grey)
    s_lbl = sc('l', parent=ss['Normal'], fontSize=8.5, fontName='Helvetica-Bold', textColor=navy)
    s_val = sc('v', parent=ss['Normal'], fontSize=8.5)
    s_amt = sc('am', parent=ss['Normal'], alignment=TA_CENTER, fontSize=15, fontName='Helvetica-Bold', textColor=green)
    s_foot = sc('ft', parent=ss['Normal'], alignment=TA_CENTER, fontSize=7, textColor=grey)

    header_el = _logo_img or Paragraph('ISI', sc('lb', parent=ss['Normal'], fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    hdr_tbl = Table([[header_el, Paragraph(f"<b>{nom_inst}</b><br/><font size='8'>Bulletin de salaire</font>",
                     sc('rh', parent=ss['Normal'], alignment=TA_CENTER, leading=13))]], colWidths=[2.5*cm, 8.5*cm])
    hdr_tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    poste = fiche.poste if fiche and fiche.poste else (employe.role.get_name_display() if employe.role else '—')
    anciennete = fiche.anciennete(_bulletin_reference_date(bulletin)) if fiche else None

    story = [
        hdr_tbl,
        Spacer(1, .2*cm),
        HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=8),
        Paragraph("BULLETIN DE SALAIRE", s_ttl),
        Paragraph(f"{MONTHS_FR[bulletin.mois]} {bulletin.annee}", s_sub),
        Spacer(1, .4*cm),
        Table([
            [Paragraph("<b>Employé</b>", s_lbl), Paragraph(employe.get_full_name(), s_val)],
            [Paragraph("<b>Matricule</b>", s_lbl), Paragraph(employe.matricule_employe or '—', s_val)],
            [Paragraph("<b>Poste</b>", s_lbl), Paragraph(poste, s_val)],
            [Paragraph("<b>Type de contrat</b>", s_lbl), Paragraph(fiche.get_type_contrat_display() if fiche else '—', s_val)],
            [Paragraph("<b>Ancienneté</b>", s_lbl), Paragraph(anciennete or '—', s_val)],
        ], colWidths=[4*cm, 7*cm], style=TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), light),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ])),
        Spacer(1, .4*cm),
        Table([
            ['Élément', 'Montant (FCFA)'],
            ['Salaire de base', f'{int(bulletin.salaire_base):,}'.replace(',', ' ')],
            ['Primes / Indemnités', f'{int(bulletin.primes):,}'.replace(',', ' ')],
            ['Retenues / Cotisations', f'-{int(bulletin.retenues):,}'.replace(',', ' ')],
        ], colWidths=[7*cm, 4*cm], style=TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ])),
        Spacer(1, .4*cm),
        Table([['NET À PAYER', f'{int(bulletin.salaire_net):,} FCFA'.replace(',', ' ')]], colWidths=[7*cm, 4*cm],
              style=TableStyle([
                  ('BACKGROUND', (0, 0), (-1, -1), navy),
                  ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
                  ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                  ('FONTSIZE', (0, 0), (-1, -1), 9),
                  ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                  ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                  ('LEFTPADDING', (0, 0), (-1, -1), 7),
              ])),
        Spacer(1, .5*cm),
        HRFlowable(width='100%', thickness=0.5, color=colors.lightgrey),
        Spacer(1, .2*cm),
        Paragraph(
            f"Statut : {bulletin.get_statut_display()}"
            + (f" — Payé le {bulletin.date_paiement.strftime('%d/%m/%Y')}" if bulletin.date_paiement else ''),
            s_foot,
        ),
        Paragraph(
            f"Bulletin généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')} — {nom_inst}",
            s_foot,
        ),
    ]

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = (
        f'inline; filename="bulletin_salaire_{employe.matricule_employe or employe.pk}_'
        f'{bulletin.mois:02d}_{bulletin.annee}.pdf"'
    )
    return resp


@login_required
@_hr_required
def bulletin_word(request, pk):
    """Génère le bulletin de salaire individuel au format Word (.docx)."""
    from academic_core.pdf_utils import get_institut_config_for_request

    staff_qs = _get_staff_queryset(request)
    bulletin = get_object_or_404(BulletinSalaire, pk=pk, user__in=staff_qs)
    employe  = bulletin.user
    fiche    = FichePersonnel.objects.filter(user=employe).first()
    poste = fiche.poste if fiche and fiche.poste else (employe.role.get_name_display() if employe.role else '—')
    anciennete = fiche.anciennete(_bulletin_reference_date(bulletin)) if fiche else None

    headers = ['Élément', 'Détail']
    rows = [
        ['Employé', employe.get_full_name()],
        ['Matricule', employe.matricule_employe or '—'],
        ['Poste', poste],
        ['Type de contrat', fiche.get_type_contrat_display() if fiche else '—'],
        ['Ancienneté', anciennete or '—'],
        ['Salaire de base', f'{int(bulletin.salaire_base):,} FCFA'.replace(',', ' ')],
        ['Primes / Indemnités', f'{int(bulletin.primes):,} FCFA'.replace(',', ' ')],
        ['Retenues / Cotisations', f'-{int(bulletin.retenues):,} FCFA'.replace(',', ' ')],
        ['NET À PAYER', f'{int(bulletin.salaire_net):,} FCFA'.replace(',', ' ')],
        ['Statut', bulletin.get_statut_display()],
    ]
    if bulletin.date_paiement:
        rows.append(['Date de paiement', bulletin.date_paiement.strftime('%d/%m/%Y')])

    filename = f"bulletin_salaire_{employe.matricule_employe or employe.pk}_{bulletin.mois:02d}_{bulletin.annee}"
    return build_docx_table_response(
        "BULLETIN DE SALAIRE",
        f"{MONTHS_FR[bulletin.mois]} {bulletin.annee} — {employe.get_full_name()}",
        headers, rows, filename,
        institut_config=get_institut_config_for_request(request),
    )
