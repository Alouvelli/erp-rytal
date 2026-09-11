"""
Export Word (python-docx) du tableau "Résultats par classe" du Rapport Annuel
de la Direction — deux tableaux (Session Normale / Session de Rattrapage),
même famille visuelle et mêmes helpers que `conseil_views.conseil_export_word`
(paysage A3, cellules colorées à la main).
"""
import io
import os

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from academic_core.pdf_utils import add_docx_watermark, get_logo_path


def _rgb(h):
    h = h.lstrip('#')
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _set_cell_shd(cell, hex_fill):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn('w:shd')):
        tcPr.remove(old)
    s = OxmlElement('w:shd')
    s.set(qn('w:val'), 'clear')
    s.set(qn('w:color'), 'auto')
    s.set(qn('w:fill'), hex_fill.lstrip('#'))
    tcPr.append(s)


def _set_col_w(cell, width_cm):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn('w:tcW')):
        tcPr.remove(old)
    tcW = OxmlElement('w:tcW')
    tcW.set(qn('w:w'), str(int(width_cm * 567)))
    tcW.set(qn('w:type'), 'dxa')
    tcPr.append(tcW)


def _wc(cell, text, bold=False, size=7, color='000000', align='center', fill=None):
    cell.text = ''
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER if align == 'center' else WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(str(text) if text is not None else '—')
    run.bold = bold
    run.font.size = Pt(size)
    run.font.color.rgb = _rgb(color)
    if fill:
        _set_cell_shd(cell, fill)


def _fmt_rate(v):
    return f"{v} %" if v is not None else '—'


FIELD_COLORS = {
    'composes': '000000', 'abandons': '6B7280', 'admis': '166534',
    'non_admis': 'B91C1C', 'absent_examen': '6B7280', 'reclamation': '5B21B6',
}


def _class_results_docx_groups(session_key):
    """(titre, colonnes H/F ?, clé du champ) — « Abandons » n'existe que côté
    Session Normale, « Réclamation » que côté Session de Rattrapage."""
    common_tail = [('Non Admis', True, 'non_admis'), ('Absent Examen', True, 'absent_examen')]
    if session_key in ('normale', 'normale_reclamation'):
        return (
            [('Classe', False, None), ('Effectif Total', False, 'effectif_total'),
             ('Effectif Composé', True, 'composes'), ('Abandons', True, 'abandons'),
             ('Admis', True, 'admis')]
            + common_tail
            + [('Taux réussite', False, 'taux_reussite'), ('Taux H', False, 'taux_h'),
               ('Taux F', False, 'taux_f'), ('Meilleure moyenne', False, 'meilleure_moyenne')]
        )
    return (
        [('Classe', False, None), ('Effectif Total', False, 'effectif_total'),
         ('Effectif Composé', True, 'composes'), ('Admis', True, 'admis')]
        + common_tail
        + [('Réclamation', True, 'reclamation'),
           ('Taux réussite', False, 'taux_reussite'), ('Taux H', False, 'taux_h'),
           ('Taux F', False, 'taux_f'), ('Meilleure moyenne', False, 'meilleure_moyenne')]
    )


def _add_class_results_table(doc, session_key, heading_text, heading_fill, rows):
    hp = doc.add_paragraph()
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = hp.add_run(heading_text)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = _rgb(heading_fill)

    groups = _class_results_docx_groups(session_key)
    W_NOM, W_NUM, W_TAUX, W_BEST = 4.5, 1.4, 2.4, 4.2

    n_cols = sum(2 if has_gender else 1 for _, has_gender, _ in groups)
    n_data_rows = len(rows)
    table = doc.add_table(rows=2 + n_data_rows, cols=n_cols)
    table.style = 'Table Grid'

    r0, r1 = table.rows[0], table.rows[1]
    ci = 0
    for title, has_gender_cols, _field in groups:
        if title == 'Classe':
            w = W_NOM
        elif title == 'Meilleure moyenne':
            w = W_BEST
        elif not has_gender_cols:
            w = W_TAUX
        else:
            w = W_NUM

        if has_gender_cols:
            merged = r0.cells[ci]
            merged.merge(r0.cells[ci + 1])
            _wc(merged, title, True, 7, 'FFFFFF', fill=heading_fill)
            _wc(r1.cells[ci], 'H', True, 7, 'FFFFFF', fill=heading_fill)
            _wc(r1.cells[ci + 1], 'F', True, 7, 'FFFFFF', fill=heading_fill)
            _set_col_w(r0.cells[ci], w)
            _set_col_w(r0.cells[ci + 1], w)
            ci += 2
        else:
            merged = r0.cells[ci]
            merged.merge(r1.cells[ci])
            _wc(merged, title, True, 7, 'FFFFFF', fill=heading_fill)
            _set_col_w(r0.cells[ci], w)
            ci += 1

    def _write_row(tr, class_label, session, is_total=False):
        bg = 'F1F5F9' if is_total else 'FFFFFF'
        ci = 0
        _wc(tr.cells[ci], class_label, bold=True, size=7,
            align='center' if is_total else 'left', fill=bg)
        ci += 1

        for title, has_gender, field in groups[1:]:
            if field == 'effectif_total':
                _wc(tr.cells[ci], session['effectif_total'], size=7, fill=bg); ci += 1
            elif field in ('taux_reussite', 'taux_h', 'taux_f'):
                _wc(tr.cells[ci], _fmt_rate(session[field]), True, 7, '166534', fill=bg); ci += 1
            elif field == 'meilleure_moyenne':
                m = session['meilleure_moyenne']
                if m is not None:
                    best_txt = (
                        f"{float(m):.2f}/20 — "
                        f"{session['meilleure_moyenne_etudiant'].user.get_full_name()}"
                    )
                else:
                    best_txt = '—'
                _wc(tr.cells[ci], best_txt, size=7, fill=bg); ci += 1
            else:
                color = FIELD_COLORS.get(field, '000000')
                _wc(tr.cells[ci], session[field]['M'], size=7, color=color, fill=bg); ci += 1
                _wc(tr.cells[ci], session[field]['F'], size=7, color=color, fill=bg); ci += 1

    for idx, row in enumerate(rows):
        _write_row(table.rows[2 + idx], row['class_group'].name, row[session_key])

    for row_obj in table.rows:
        trPr = row_obj._tr.get_or_add_trPr()
        trH = OxmlElement('w:trHeight')
        trH.set(qn('w:val'), '280')
        trH.set(qn('w:hRule'), 'atLeast')
        trPr.append(trH)


def generate_class_results_word(data, config=None, sessions=(
        'normale', 'normale_reclamation', 'rattrapage', 'rattrapage_reclamation')):
    """
    `data` : dict retourné par grades.class_results_services.compute_class_results_table().
    `sessions` permet un export par rubrique (une seule session à la fois).
    """
    department = data['department']
    academic_year = data['academic_year']
    semester = data['semester']
    rows = data['rows']

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width = Cm(42)
    sec.page_height = Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(0.7)
    sec.top_margin = sec.bottom_margin = Cm(1.0)

    # ── En-tête : logo institut + nom ─────────────────────────────────────────
    inst_nom = (getattr(config, 'nom', None)) or "Institut Supérieur d'Informatique — ISI"
    logo_path = get_logo_path(config)
    hdr = doc.add_table(rows=1, cols=2)
    hdr.autofit = False
    hdr.columns[0].width = Cm(2.2)
    cell_logo = hdr.cell(0, 0)
    cell_logo.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_logo = cell_logo.paragraphs[0]
    p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if logo_path and os.path.exists(logo_path):
        p_logo.add_run().add_picture(logo_path, height=Cm(1.4))
    cell_nom = hdr.cell(0, 1)
    cell_nom.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_nom = cell_nom.paragraphs[0]
    run_nom = p_nom.add_run(inst_nom)
    run_nom.bold = True
    run_nom.font.size = Pt(11)
    run_nom.font.color.rgb = _rgb('1E3A5F')
    doc.add_paragraph()

    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = tp.add_run(
        f"RÉSULTATS PAR CLASSE — {department.name} — {academic_year.label} — "
        f"{semester.level.name if semester.level else ''} {semester.label}"
    )
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = _rgb('1E3A5F')

    section_specs = {
        'normale': ('SESSION NORMALE', '059669'),
        'normale_reclamation': ('SESSION NORMALE — APRÈS RÉCLAMATION', '0F766E'),
        'rattrapage': ('SESSION DE RATTRAPAGE — AVANT RÉCLAMATION', 'B45309'),
        'rattrapage_reclamation': ('SESSION DE RATTRAPAGE — APRÈS RÉCLAMATION', '5B21B6'),
    }
    for i, session_key in enumerate(sessions):
        heading_text, heading_fill = section_specs[session_key]
        if i > 0:
            doc.add_paragraph()
        _add_class_results_table(doc, session_key, heading_text, heading_fill, rows)

    add_docx_watermark(doc)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
