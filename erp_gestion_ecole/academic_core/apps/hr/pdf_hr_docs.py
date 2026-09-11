"""Génération PDF des documents RH : ordre de mission, attestations
(travail / salaire / certificat), attestation de stage.

Reprend le pattern déjà en place pour les attestations étudiants
(`academic_core/apps/accounting/views.py:attestation_passage_pdf`) : en-tête
drapeau + logo institut, table d'informations, formule de clôture, bloc
signature via `BulletinConfig.get()`.
"""
import io
from datetime import date as dt

from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from academic_core.pdf_utils import logo_image, senegal_flag, get_institut_config_for_request, watermark_canvas

NAVY  = colors.HexColor('#00173B')
GOLD  = colors.HexColor('#D4AF37')
LIGHT = colors.HexColor('#EFF6FF')
GREY  = colors.HexColor('#64748B')


def _styles():
    ss = getSampleStyleSheet()
    sc = ParagraphStyle
    return {
        'ctr': sc('c',  parent=ss['Normal'], alignment=TA_CENTER),
        'ttl': sc('t',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=17, fontName='Helvetica-Bold', textColor=NAVY),
        'sub': sc('s',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=10, textColor=GREY),
        'lbl': sc('l',  parent=ss['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=NAVY),
        'val': sc('v',  parent=ss['Normal'], fontSize=10),
        'sgn': sc('sg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=10, fontName='Helvetica-Bold'),
        'body': sc('bd', parent=ss['Normal'], fontSize=10, leading=16),
        'srv': sc('srv', parent=ss['Normal'], fontSize=10, fontName='Helvetica-BoldOblique', alignment=TA_CENTER),
        'dl':  sc('dl', parent=ss['Normal'], fontSize=9),
        'dn':  sc('dn', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, textColor=GREY),
    }


def _header(request, st):
    inst_cfg = get_institut_config_for_request(request)
    logo_el = logo_image(width=2.4 * cm, height=1.6 * cm, config=inst_cfg) or Paragraph(
        'ISI', ParagraphStyle('lb', parent=st['ctr'], fontSize=9, fontName='Helvetica-Bold', textColor=NAVY)
    )
    flag_el = senegal_flag(width=2.4 * cm, height=1.6 * cm)
    nom_institut = (inst_cfg.nom if inst_cfg and inst_cfg.nom else 'Institut')
    rep_txt = Paragraph(
        '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="8">Un Peuple — Un But — Une Foi</font>'
        f'<br/><br/><font size="13"><b>{nom_institut}</b></font>',
        ParagraphStyle('rh', parent=getSampleStyleSheet()['Normal'], alignment=TA_CENTER, leading=14),
    )
    hdr_tbl = Table([[flag_el, rep_txt, logo_el]], colWidths=[3 * cm, 11 * cm, 3 * cm])
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return [hdr_tbl, Spacer(1, .3 * cm), HRFlowable(width='100%', thickness=2, color=NAVY),
            HRFlowable(width='100%', thickness=1, color=GOLD, spaceAfter=8), Spacer(1, .5 * cm)]


def _signature_block(st):
    from academic_core.apps.academic_structure.models import BulletinConfig
    config = BulletinConfig.get()
    return Table([
        [Paragraph(f"Dakar, le {dt.today().strftime('%d/%m/%Y')}", st['dl']),
         Paragraph(config.director_title or "Le Directeur Général", st['sgn'])],
        ['', Paragraph(config.director_name or '', st['dn'])],
    ], colWidths=[9 * cm, 7.5 * cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')])


def _build(request, filename, title, subtitle, rows, body_text, closing="La présente attestation est délivrée pour servir et valoir ce que de droit."):
    st = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    story = _header(request, st)
    story += [
        Paragraph(title, st['ttl']), Spacer(1, .2 * cm),
        Paragraph(subtitle, st['sub']) if subtitle else Spacer(1, 0),
        Spacer(1, .6 * cm), HRFlowable(width='60%', thickness=1, color=GOLD, hAlign='CENTER'), Spacer(1, .7 * cm),
    ]
    if body_text:
        story += [Paragraph(body_text, st['body']), Spacer(1, .5 * cm)]
    if rows:
        table_rows = [[Paragraph(f"<b>{label}</b>", st['lbl']), Paragraph(str(val), st['val'])] for label, val in rows]
        story.append(Table(table_rows, colWidths=[5.5 * cm, 11 * cm], style=TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), LIGHT),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ])))
    story += [
        Spacer(1, .8 * cm),
        Paragraph(closing, st['srv']),
        Spacer(1, 1 * cm),
        _signature_block(st),
    ]
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{filename}"'
    return resp


def generate_ordre_mission_pdf(request, mission):
    rows = [
        ('Agent', mission.user.get_full_name()),
        ('Objet', mission.objet),
        ('Destination', mission.destination),
        ('Période', f"{mission.date_debut.strftime('%d/%m/%Y')} → {mission.date_fin.strftime('%d/%m/%Y')}"),
    ]
    body = (
        f"Il est délivré le présent ordre de mission à <b>{mission.user.get_full_name()}</b>, "
        f"autorisé(e) à se déplacer à <b>{mission.destination}</b> pour les besoins du service "
        f"décrits ci-dessous, pour la période indiquée."
    )
    return _build(
        request, f"ordre_mission_{mission.pk}.pdf",
        "ORDRE DE MISSION", '', rows, body,
        closing="Le présent ordre de mission est délivré pour servir et valoir ce que de droit.",
    )


def generate_stage_attestation_pdf(request, internship):
    rows = [
        ('Stagiaire', f"{internship.prenom} {internship.nom}"),
        ('École / Établissement', internship.ecole or '—'),
        ('Sujet de stage', internship.sujet or '—'),
        ('Période', f"{internship.date_debut.strftime('%d/%m/%Y')} → {internship.date_fin.strftime('%d/%m/%Y')}"),
        ('Tuteur', internship.tuteur.get_full_name() if internship.tuteur else '—'),
    ]
    body = (
        f"Nous soussignés attestons que <b>{internship.prenom} {internship.nom}</b> a effectué un "
        f"stage au sein de notre institut, dans les conditions décrites ci-dessous."
    )
    return _build(
        request, f"attestation_stage_{internship.pk}.pdf",
        "ATTESTATION DE STAGE", '', rows, body,
    )


_DOC_TYPE_TITLES = {
    'ATTESTATION_TRAVAIL': ("ATTESTATION DE TRAVAIL",
        "Nous soussignés attestons que {nom} occupe actuellement un poste au sein de notre institut, "
        "dans les conditions décrites ci-dessous."),
    'ATTESTATION_SALAIRE': ("ATTESTATION DE SALAIRE",
        "Nous soussignés attestons de la situation salariale de {nom}, décrite ci-dessous."),
    'CERTIFICAT_TRAVAIL': ("CERTIFICAT DE TRAVAIL",
        "Nous soussignés certifions que {nom} a été employé(e) au sein de notre institut, "
        "dans les conditions décrites ci-dessous."),
}


def generate_document_request_pdf(request, doc_request):
    employe = doc_request.user
    title, body_tpl = _DOC_TYPE_TITLES[doc_request.type_document]
    rows = [
        ('Employé', employe.get_full_name()),
        ('Poste', getattr(getattr(employe, 'fiche_personnel', None), 'poste', '') or '—'),
        ("Date d'embauche", getattr(getattr(employe, 'fiche_personnel', None), 'date_embauche', None) or '—'),
    ]
    if doc_request.type_document == 'ATTESTATION_SALAIRE':
        salaire_cfg = getattr(employe, 'salaire_config', None)
        rows.append(('Salaire net mensuel', f"{salaire_cfg.salaire_net:,.0f} FCFA".replace(',', ' ') if salaire_cfg else '—'))
    body = body_tpl.format(nom=f"<b>{employe.get_full_name()}</b>")
    return _build(
        request, f"{doc_request.type_document.lower()}_{employe.pk}.pdf",
        title, '', rows, body,
    )
