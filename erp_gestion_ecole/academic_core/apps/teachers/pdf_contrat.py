"""
Génération du "Contrat de prestation de service" enseignant.

Le texte du contrat (titre, introduction de l'Article 1, paragraphe "cahier de
charge", articles 2 à N) est modifiable par institut — voir InstitutConfig et
ContratArticle (academic_structure.models) et l'écran teachers:contrat_modele.
Seuls restent calculés en direct : l'en-tête (logo/nom institut), la clause
"Entre"/"ET" (institut + informations civiles de l'enseignant), la période et
le tableau des modules de l'Article 1 (voir ContratEnseignant.modules_rows()),
et le bloc de signature.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)

from academic_core.pdf_utils import get_logo_path

NAVY   = colors.HexColor('#003D82')
BLACK  = colors.black
GRAY   = colors.HexColor('#64748B')
BORDER = colors.HexColor('#CBD5E1')


def _ps(name, size=9.5, color=BLACK, align=TA_LEFT, bold=False, italic=False, leading=None):
    font = 'Helvetica'
    if bold and italic:
        font = 'Helvetica-BoldOblique'
    elif bold:
        font = 'Helvetica-Bold'
    elif italic:
        font = 'Helvetica-Oblique'
    return ParagraphStyle(
        name, fontName=font, fontSize=size, textColor=color,
        alignment=align, leading=leading or (size + 4), spaceAfter=6,
    )


def _fmt_date(d):
    return d.strftime('%d/%m/%Y') if d else '. . . . . . . . . .'


def _fmt_hours(volume):
    if volume is None:
        return '—'
    v = float(volume)
    if v == int(v):
        return f'{int(v)}H'
    return f'{v:.2f}'.rstrip('0').rstrip('.') + 'H'


def _situation_display(teacher):
    return teacher.get_situation_matrimoniale_display() if teacher.situation_matrimoniale else '. . . . . . . . . .'


def generate_contrat_pdf(contrat, institut_config=None):
    """Génère le PDF du contrat (bytes). `contrat` : instance de ContratEnseignant."""
    teacher = contrat.teacher
    department = contrat.department

    if institut_config is None:
        from academic_core.apps.academic_structure.models import InstitutConfig
        try:
            institut_config = InstitutConfig.objects.using('default').get(faculty=department.faculty)
        except InstitutConfig.DoesNotExist:
            institut_config = None

    institut_nom = (institut_config.nom if institut_config else None) or 'Institut'
    institut_adresse = (institut_config.adresse if institut_config else '') or ''
    de_titre = (institut_config.de_titre if institut_config else None) or 'Directeur des Études'
    de_nom = (institut_config.de_nom if institut_config else '') or '. . . . . . . . . .'
    _logo_path = get_logo_path(institut_config)

    contrat_titre = (institut_config.contrat_titre if institut_config else None) or 'CONTRAT DE PRESTATION DE SERVICE'
    article1_template = (
        (institut_config.contrat_article1_texte if institut_config else None)
        or "le prestataire s'engage à dispenser des enseignements pour la période : {periode}. "
           "Les enseignements portent sur les modules suivants :"
    )
    try:
        article1_texte = article1_template.format(periode=contrat.academic_year.label)
    except (KeyError, IndexError, ValueError):
        # Texte personnalisé sans repère {periode} valide : affiché tel quel.
        article1_texte = article1_template
    cahier_charge_texte = (institut_config.contrat_cahier_charge_texte if institut_config else None) or ''
    articles = (
        institut_config.contrat_articles.filter(actif=True).order_by('numero')
        if institut_config else []
    )

    def _header_footer(canvas, doc):
        canvas.saveState()
        text_x = 1.0 * cm
        if _logo_path:
            try:
                logo_h = 1.1 * cm
                canvas.drawImage(
                    _logo_path, 1.0 * cm, A4[1] - 1.55 * cm, height=logo_h, width=logo_h,
                    preserveAspectRatio=True, mask='auto', anchor='sw',
                )
                text_x = 1.0 * cm + logo_h + 0.25 * cm
            except Exception:
                pass
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(GRAY)
        canvas.drawString(text_x, A4[1] - 1.1 * cm, institut_nom)
        canvas.drawRightString(A4[0] - 1.0 * cm, A4[1] - 1.1 * cm, 'Contrat de prestation de service')
        canvas.setStrokeColor(BORDER)
        canvas.line(1.0 * cm, A4[1] - 1.7 * cm, A4[0] - 1.0 * cm, A4[1] - 1.7 * cm)
        canvas.setFont('Helvetica', 8)
        canvas.drawCentredString(A4[0] / 2, 0.8 * cm, str(doc.page))
        canvas.setFont('Helvetica', 6)
        canvas.setFillColor(colors.HexColor('#94A3B8'))
        canvas.drawRightString(A4[0] - 1.0 * cm, 0.8 * cm, 'ERP-RYTAL, App-GEST V1.0')
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=2.1 * cm, bottomMargin=1.5 * cm,
    )

    story = []

    story.append(Paragraph(contrat_titre, _ps('title', size=15, bold=True, align=TA_CENTER)))
    story.append(HRFlowable(width='100%', thickness=1, color=BLACK, spaceBefore=4, spaceAfter=14))

    story.append(Paragraph('<b>Entre</b>', _ps('h1', bold=True)))
    story.append(Paragraph(
        f"L'entreprise <b>{institut_nom}</b> dont le siège se trouve à <b>{institut_adresse}</b>, "
        f"représentée aux fins des présentes par <b>{de_nom}</b> en sa qualité de <b>{de_titre}</b>.",
        _ps('entre'),
    ))
    story.append(Paragraph('<i>Dénommé ici le client,</i>', _ps('client', italic=True)))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>D'autre part</b>", _ps('dautrepart', bold=True)))
    story.append(Paragraph('<b>ET</b>', _ps('et', bold=True)))

    civil_lines = [
        f"M/Mme <b>{teacher.full_name}</b> né(e) le <b>{_fmt_date(teacher.date_naissance)}</b> "
        f"à <b>{teacher.lieu_naissance or '. . . . . . . . . .'}</b>",
        f"Nationalité : <b>{teacher.nationalite or '. . . . . . . . . .'}</b>",
        f"Numéro CIN ou numéro Passeport (pour les étrangers) : <b>{teacher.num_cin_passeport or '. . . . . . . . . .'}</b>",
        f"Situation matrimoniale : <b>{_situation_display(teacher)}</b>",
        f"Adresse complète : <b>{teacher.adresse or '. . . . . . . . . .'}</b>",
        f"Lieu de résidence habituelle : <b>{teacher.lieu_residence or '. . . . . . . . . .'}</b>",
        f"Profession : <b>{teacher.profession or '. . . . . . . . . .'}</b>",
        f"Numéro d'immatriculation, NINEA : <b>{teacher.ninea or ''}</b>",
    ]
    for line in civil_lines:
        story.append(Paragraph(line, _ps('civil', leading=15)))

    story.append(Paragraph('<i>Ci-après dénommé(e) "prestataire"</i>', _ps('prestataire', italic=True)))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>D'autre part,</b>", _ps('dautrepart2', bold=True)))
    story.append(Paragraph("<i>Il a été arrêté ce qui suit :</i>", _ps('arrete', italic=True)))
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        f"<b>Article 1 :</b> {article1_texte}",
        _ps('art1', leading=15),
    ))
    story.append(Spacer(1, 6))

    rows = contrat.modules_rows()
    table_data = [['Module', 'Semestre', 'Classe', 'Volume (H)']]
    cell_style = _ps('cell', size=8.5, leading=11)
    header_style = _ps('cellh', size=8.5, bold=True, align=TA_CENTER, leading=11)
    if rows:
        for r in rows:
            table_data.append([
                Paragraph(r['module'], cell_style),
                Paragraph(r['semestre'], cell_style),
                Paragraph(r['classes'], cell_style),
                Paragraph(_fmt_hours(r['volume']), cell_style),
            ])
    else:
        table_data.append([Paragraph('Aucun module affecté pour le moment.', cell_style), '', '', ''])
    table_data[0] = [Paragraph(c, header_style) for c in table_data[0]]

    modules_table = Table(table_data, colWidths=[6.6 * cm, 2.2 * cm, 5.8 * cm, 2.4 * cm], repeatRows=1)
    modules_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(modules_table)
    story.append(Spacer(1, 10))

    if cahier_charge_texte:
        story.append(Paragraph(cahier_charge_texte, _ps('art1b', leading=14)))

    for article in articles:
        story.append(Paragraph(
            f'<b>Article {article.numero} :</b> {article.texte}',
            _ps(f'art{article.numero}', leading=14),
        ))

    story.append(Spacer(1, 16))
    sig_data = [
        [Paragraph('<b>Le prestataire</b>', _ps('sig_h', bold=True)),
         Paragraph(f'<b>{de_titre}</b>', _ps('sig_h2', bold=True))],
        [Spacer(1, 28), Spacer(1, 28)],
        [Paragraph(f'<i>{teacher.full_name}</i>', _ps('sig_n', italic=True)),
         Paragraph(f'<i>{de_nom}</i>', _ps('sig_n2', italic=True))],
    ]
    sig_table = Table(sig_data, colWidths=[9.5 * cm, 9.5 * cm])
    story.append(sig_table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"<b>Fait à {contrat.lieu_signature or 'Dakar'}</b> le, "
        f"<b>{_fmt_date(contrat.date_signature)}</b>.",
        _ps('fait'),
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
