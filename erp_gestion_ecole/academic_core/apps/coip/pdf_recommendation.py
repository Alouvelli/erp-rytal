"""Génération de la lettre de recommandation (PDF) — house style navy/or
établi cette session (voir accounting/views.py::diploma_supplement_pdf pour
le motif de référence), pas de dessin canvas brut (contrairement à
GestionCOIP)."""
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from academic_core.pdf_utils import (
    get_institut_config_for_request, logo_image, senegal_flag, watermark_canvas,
)


def generate_recommendation_pdf(request, recommendation):
    student = recommendation.student
    inst_cfg = get_institut_config_for_request(request)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.7*cm, bottomMargin=1.7*cm)

    navy = colors.HexColor('#00173B')
    gold = colors.HexColor('#D4AF37')
    ss = getSampleStyleSheet()
    sc = ParagraphStyle
    s_body = sc('rb', parent=ss['Normal'], fontSize=10.5, leading=16, alignment=TA_LEFT)
    s_sgn = sc('rsg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=10, fontName='Helvetica-Bold')
    s_ttl = sc('rtl', parent=ss['Normal'], alignment=TA_CENTER, fontSize=15, fontName='Helvetica-Bold', textColor=navy)

    inst_nom = inst_cfg.nom if inst_cfg else ''
    inst_sigle = (inst_cfg.sigle if inst_cfg else '') or inst_nom
    ville = (inst_cfg.ville if inst_cfg and inst_cfg.ville else 'Dakar')

    flag_el = senegal_flag(width=2.2*cm, height=1.5*cm)
    logo_el = logo_image(width=2.2*cm, height=1.5*cm, config=inst_cfg) or Paragraph(
        inst_sigle, sc('lb', parent=ss['Normal'], alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    rep_txt = Paragraph(
        '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="8">Un Peuple — Un But — Une Foi</font>'
        f'<br/><br/><font size="13"><b>{inst_sigle}</b></font><br/>'
        f"<font size='9'>{inst_nom}</font>",
        sc('rh', parent=ss['Normal'], alignment=TA_CENTER, leading=14),
    )
    hdr_tbl = Table([[flag_el, rep_txt, logo_el]], colWidths=[3*cm, 11*cm, 3*cm])
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    today_str = recommendation.date_livraison.strftime('%d/%m/%Y') if recommendation.date_livraison else ''
    signataire = recommendation.assigned_to.get_full_name() if recommendation.assigned_to else ''

    story = [
        hdr_tbl,
        Spacer(1, .3*cm), HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=14),
        Spacer(1, .4*cm),
        Paragraph("LETTRE DE RECOMMANDATION", s_ttl),
        Spacer(1, .6*cm),
        Paragraph(f"{ville}, le {today_str}", sc('date', parent=s_body, alignment=TA_RIGHT)),
        Spacer(1, .4*cm),
    ]
    if recommendation.destinataire:
        story.append(Paragraph(f"À l'attention de : {recommendation.destinataire}", s_body))
        story.append(Spacer(1, .4*cm))

    story.append(Paragraph("Madame, Monsieur,", s_body))
    story.append(Spacer(1, .3*cm))

    corps = (
        f"Je soussigné(e), au nom de la Cellule d'Orientation et d'Insertion Professionnelle de "
        f"{inst_nom or inst_sigle}, recommande {student.user.get_full_name()} "
        f"(matricule {student.matricule})"
    )
    if recommendation.programme_concerne:
        corps += f" pour {recommendation.programme_concerne}"
    corps += "."
    story.append(Paragraph(corps, s_body))
    story.append(Spacer(1, .3*cm))
    story.append(Paragraph(recommendation.motif, s_body))

    if recommendation.observations_etudiant:
        story.append(Spacer(1, .3*cm))
        story.append(Paragraph(f"<i>Observations complémentaires : {recommendation.observations_etudiant}</i>", s_body))

    story.append(Spacer(1, .3*cm))
    story.append(Paragraph(
        "Je reste à votre disposition pour tout complément d'information et vous prie d'agréer, "
        "Madame, Monsieur, l'expression de mes salutations distinguées.",
        s_body,
    ))
    story.append(Spacer(1, 1.5*cm))
    if signataire:
        story.append(Paragraph(signataire, s_sgn))
        story.append(Paragraph("Cellule d'Orientation et d'Insertion Professionnelle", s_sgn))

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    return buffer
