"""Word (.docx) bulletin — structure identique au PDF."""
import io
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ── Couleurs (identiques au PDF) ──────────────────────────────────────────────
NAVY       = RGBColor(0x00, 0x3D, 0x82)
GREEN      = RGBColor(0x16, 0xA3, 0x4A)
RED        = RGBColor(0xDC, 0x26, 0x26)
AMBER      = RGBColor(0xB4, 0x53, 0x09)
GRAY       = RGBColor(0x64, 0x74, 0x8B)
LIGHT_GRAY = RGBColor(0x94, 0xA3, 0xB8)
LT_BLUE    = RGBColor(0xEF, 0xF6, 0xFF)
DBLUE      = RGBColor(0xDB, 0xEA, 0xFE)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
BLACK      = RGBColor(0x00, 0x00, 0x00)
NAVY_HEX   = '003D82'
LTBLUE_HEX = 'EFF6FF'
DBLUE_HEX  = 'DBEAFE'
WHITE_HEX  = 'FFFFFF'
GRAY_BG    = 'F8FAFC'


def _fmt(val, decimals=2, na='—'):
    if val is None:
        return na
    return f"{float(val):.{decimals}f}".replace('.', ',')


def _set_cell_bg(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def _set_borders(cell, top=None, bottom=None, left=None, right=None, color='B0C4DE', sz='4'):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBdr = tcPr.find(qn('w:tcBdr'))
    if tcBdr is None:
        tcBdr = OxmlElement('w:tcBdr')
        tcPr.append(tcBdr)
    sides = {'top': top, 'bottom': bottom, 'left': left, 'right': right}
    for side, val in sides.items():
        if val is None:
            continue
        el = tcBdr.find(qn(f'w:{side}'))
        if el is None:
            el = OxmlElement(f'w:{side}')
            tcBdr.append(el)
        el.set(qn('w:val'), val)
        el.set(qn('w:sz'), sz)
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color)


def _cell_para(cell, text='', bold=False, color=None, size=7.5, align='center',
               italic=False, space_before=20, space_after=20):
    cell.text = ''
    p = cell.paragraphs[0]
    pPr = p._p.get_or_add_pPr()
    pPr_spacing = pPr.find(qn('w:spacing'))
    if pPr_spacing is None:
        pPr_spacing = OxmlElement('w:spacing')
        pPr.append(pPr_spacing)
    pPr_spacing.set(qn('w:before'), str(space_before))
    pPr_spacing.set(qn('w:after'), str(space_after))
    p.alignment = {
        'center': WD_ALIGN_PARAGRAPH.CENTER,
        'left':   WD_ALIGN_PARAGRAPH.LEFT,
        'right':  WD_ALIGN_PARAGRAPH.RIGHT,
        'justify': WD_ALIGN_PARAGRAPH.JUSTIFY,
    }.get(align, WD_ALIGN_PARAGRAPH.CENTER)
    if not text:
        return p
    run = p.add_run(str(text))
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = color
    return p


def _set_col_width(col, cm_val):
    """Force column width."""
    for cell in col.cells:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        w_el = tcPr.find(qn('w:tcW'))
        if w_el is None:
            w_el = OxmlElement('w:tcW')
            tcPr.append(w_el)
        twips = int(cm_val * 567)
        w_el.set(qn('w:w'), str(twips))
        w_el.set(qn('w:type'), 'dxa')


def _merge_row_cells(row, start_col, end_col):
    """Merge cells horizontally."""
    cells = row.cells
    for i in range(end_col, start_col, -1):
        cells[i].merge(cells[i - 1])


def _merge_col_cells(table, start_row, end_row, col_idx):
    """Merge cells vertically."""
    for i in range(end_row, start_row, -1):
        table.cell(i, col_idx).merge(table.cell(i - 1, col_idx))


def _add_run(para, text, bold=False, color=None, size=7.5, italic=False, newline_before=False):
    if newline_before:
        para.add_run('\n')
    run = para.add_run(str(text))
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = color
    return run


def _grade_color(val):
    if val is None:
        return LIGHT_GRAY
    return GREEN if float(val) >= 10 else RED


def _no_space(doc):
    """Paragraph with zero spacing."""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    sp = pPr.find(qn('w:spacing'))
    if sp is None:
        sp = OxmlElement('w:spacing')
        pPr.append(sp)
    sp.set(qn('w:before'), '0')
    sp.set(qn('w:after'), '0')
    return p


def generate_bulletin_word(data, institut_config=None):
    """Returns bytes of the .docx bulletin, structure identique au PDF."""
    from academic_core.pdf_utils import get_logo_path

    doc = Document()

    # ── Mise en page portrait A4 ──────────────────────────────────────────────
    section = doc.sections[0]
    section.page_width  = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin   = Cm(1.5)
    section.right_margin  = Cm(1.5)
    section.top_margin    = Cm(1.2)
    section.bottom_margin = Cm(1.2)

    # Réduire l'espacement par défaut pour tous les styles
    style = doc.styles['Normal']
    style.font.size = Pt(8)
    pf = style.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after  = Pt(0)

    student    = data['student']
    semester   = data['semester']
    program    = data.get('program')
    class_group = data.get('class_group')
    ue_list    = data.get('ue_list', [])

    inst_nom = (getattr(institut_config, 'nom', None)) or "Institut Supérieur d'Informatique — ISI"
    logo_path = get_logo_path(institut_config)

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. EN-TÊTE : logo | BULLETIN DE NOTES + année | Semestre X
    # ═══════════════════════════════════════════════════════════════════════════
    # Largeur utile ≈ 18 cm (21 - 1.5 - 1.5)
    hdr = doc.add_table(rows=1, cols=3)
    hdr.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr.style = 'Table Grid'

    # Largeurs : 2.7 | 12.6 | 2.7
    col_widths_hdr = [2.7, 12.6, 2.7]
    for ci, cw in enumerate(col_widths_hdr):
        for cell in hdr.columns[ci].cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            w_el = OxmlElement('w:tcW')
            w_el.set(qn('w:w'), str(int(cw * 567)))
            w_el.set(qn('w:type'), 'dxa')
            tcPr.append(w_el)

    # Logo gauche
    cell_logo = hdr.cell(0, 0)
    cell_logo.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_logo = cell_logo.paragraphs[0]
    p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if logo_path and os.path.exists(logo_path):
        p_logo.add_run().add_picture(logo_path, height=Cm(1.6))

    # Titre centre
    cell_title = hdr.cell(0, 1)
    cell_title.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_title = cell_title.paragraphs[0]
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p_title.add_run('BULLETIN DE NOTES')
    r1.font.size = Pt(12)
    r1.font.bold = True
    r1.font.color.rgb = NAVY
    p_title.add_run('\n')
    r2 = p_title.add_run(f"Année académique : {semester.academic_year}")
    r2.font.size = Pt(8)
    r2.font.color.rgb = GRAY

    # Semestre droite
    cell_sem = hdr.cell(0, 2)
    cell_sem.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_sem = cell_sem.paragraphs[0]
    p_sem.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_sem = p_sem.add_run(f"Semestre {semester.number}")
    r_sem.font.size = Pt(11)
    r_sem.font.bold = True
    r_sem.font.color.rgb = NAVY

    # Fond bleu nuit pour le header
    for ci in range(3):
        _set_cell_bg(hdr.cell(0, ci), NAVY_HEX)
        for run in hdr.cell(0, ci).paragraphs[0].runs:
            run.font.color.rgb = WHITE
    # Ré-écrire les couleurs
    r1.font.color.rgb = WHITE
    r2.font.color.rgb = RGBColor(0xBF, 0xDB, 0xFE)
    r_sem.font.color.rgb = WHITE

    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. INFO ÉTUDIANT (4 colonnes × 2 lignes)
    # ═══════════════════════════════════════════════════════════════════════════
    info = doc.add_table(rows=2, cols=4)
    info.alignment = WD_TABLE_ALIGNMENT.CENTER
    info.style = 'Table Grid'
    for ci, cw in enumerate([3.5, 5.5, 3.5, 5.5]):
        for cell in info.columns[ci].cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            w_el = OxmlElement('w:tcW')
            w_el.set(qn('w:w'), str(int(cw * 567)))
            w_el.set(qn('w:type'), 'dxa')
            tcPr.append(w_el)

    info_data = [
        [('Matricule :', True), (student.matricule or '—', False, True),
         ('NOM et Prénom :', True), (f"{student.user.last_name.upper()} {student.user.first_name.title()}", False, True)],
        [('Sexe :', True),
         ({'M': 'Masculin', 'MALE': 'Masculin', 'F': 'Féminin', 'FEMALE': 'Féminin'}.get(getattr(student, 'gender', ''), '—'), False),
         ('Date & lieu naissance :', True),
         (f"{student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '—'}"
          f"{f' — {student.place_of_birth}' if getattr(student, 'place_of_birth', None) else ''}", False)],
    ]
    for ri, row_data in enumerate(info_data):
        for ci, cell_data in enumerate(row_data):
            c = info.cell(ri, ci)
            lbl = cell_data[0]
            bold = cell_data[1] if len(cell_data) > 1 else False
            navy = len(cell_data) > 2 and cell_data[2]
            _cell_para(c, lbl, bold=bold, color=NAVY if bold else (NAVY if navy else BLACK),
                       size=7.5, align='left', space_before=30, space_after=30)
            if bold:
                _set_cell_bg(c, GRAY_BG)

    doc.add_paragraph().paragraph_format.space_after = Pt(1)

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. DOMAINE / MENTION / SPÉCIALITÉ / GRADE
    # ═══════════════════════════════════════════════════════════════════════════
    dom = doc.add_table(rows=1, cols=4)
    dom.alignment = WD_TABLE_ALIGNMENT.CENTER
    dom.style = 'Table Grid'
    for ci, cw in enumerate([4.5, 4.5, 6.0, 3.0]):
        for cell in dom.columns[ci].cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            w_el = OxmlElement('w:tcW')
            w_el.set(qn('w:w'), str(int(cw * 567)))
            w_el.set(qn('w:type'), 'dxa')
            tcPr.append(w_el)

    dom_data = [
        ('Domaine', getattr(class_group, 'domaine', None) or 'Sciences & Technologies'),
        ('Mention', getattr(class_group, 'mention', None) or '—'),
        ('Spécialité', getattr(program, 'name', None) or '—'),
        ('Grade', 'Licence'),
    ]
    for ci, (label, value) in enumerate(dom_data):
        c = dom.cell(0, ci)
        _set_cell_bg(c, LTBLUE_HEX)
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pPr = p._p.get_or_add_pPr()
        sp = OxmlElement('w:spacing')
        sp.set(qn('w:before'), '20')
        sp.set(qn('w:after'), '20')
        pPr.append(sp)
        r_lbl = p.add_run(label + '\n')
        r_lbl.font.size = Pt(6.5)
        r_lbl.font.color.rgb = LIGHT_GRAY
        r_val = p.add_run(value)
        r_val.font.size = Pt(8)
        r_val.font.bold = True
        r_val.font.color.rgb = NAVY

    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. TABLEAU DES NOTES — 10 colonnes (identique au PDF)
    # Col: 0=UE/EC  1=MCC40%  2=Exam60%  3=Rattrap  4=MoyEC  5=CoefEC
    #      6=Moy×Coef  7=CréditEC  8=MoyUE  9=Appréciation
    # ═══════════════════════════════════════════════════════════════════════════
    COL_W = [5.8, 1.6, 1.5, 1.5, 1.4, 1.2, 1.5, 1.2, 1.5, 2.3]
    N_COLS = len(COL_W)

    # Compter le nombre total de lignes nécessaires
    n_rows = 2  # 2 lignes d'en-têtes
    for ue_entry in ue_list:
        n_rows += 1                           # ligne UE
        n_rows += len(ue_entry['ec_list'])    # lignes EC
        n_rows += 1                           # ligne totaux UE

    notes = doc.add_table(rows=n_rows, cols=N_COLS)
    notes.alignment = WD_TABLE_ALIGNMENT.CENTER
    notes.style = 'Table Grid'

    # Largeurs des colonnes
    for ci, cw in enumerate(COL_W):
        for cell in notes.columns[ci].cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            w_el = OxmlElement('w:tcW')
            w_el.set(qn('w:w'), str(int(cw * 567)))
            w_el.set(qn('w:type'), 'dxa')
            tcPr.append(w_el)

    # ── En-têtes ligne 1 ──────────────────────────────────────────────────────
    HDR1 = [
        ('UE / Éléments constitutifs', 2, 'left'),
        ('MCC', 1, 'center'),
        ('Examen', 1, 'center'),
        ('Rattrap', 1, 'center'),
        ('Moy', 1, 'center'),
        ('Coef', 1, 'center'),
        ('Moyenne', 1, 'center'),
        ('Crédit', 1, 'center'),
        ('Moyenne', 1, 'center'),
        ('Appréciation', 2, 'center'),
    ]
    for ci, (txt, rs, al) in enumerate(HDR1):
        c = notes.cell(0, ci)
        _set_cell_bg(c, NAVY_HEX)
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _cell_para(c, txt, bold=True, color=WHITE, size=7, align=al, space_before=40, space_after=40)

    # Fusionner UE/EC (rowspan=2) et Appréciation (rowspan=2)
    notes.cell(1, 0).merge(notes.cell(0, 0))
    notes.cell(1, 9).merge(notes.cell(0, 9))

    # ── En-têtes ligne 2 (sous-en-têtes) ────────────────────────────────────
    HDR2 = ['', '40%', '60%', '60%', 'EC', 'EC', 'Coef', 'EC', 'UE', '']
    for ci, txt in enumerate(HDR2):
        if ci in (0, 9):
            continue
        c = notes.cell(1, ci)
        _set_cell_bg(c, NAVY_HEX)
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _cell_para(c, txt, bold=False, color=RGBColor(0xBF, 0xDB, 0xFE), size=6.5, align='center',
                   space_before=20, space_after=20)

    # ── Remplissage des lignes UE/EC ──────────────────────────────────────────
    current_row = 2

    for ue_entry in ue_list:
        ue      = ue_entry['ue']
        ec_list = ue_entry['ec_list']
        n_ec    = len(ec_list)
        ue_avg  = ue_entry.get('average')
        ue_val  = ue_entry.get('is_validated', False)
        ue_ratt = ue_entry.get('validated_by_rattrapage', False)
        ue_cred_obt  = ue_entry.get('credits_obtained', 0)
        ue_cred_poss = getattr(ue, 'credits', 0)

        row_span = n_ec + 2  # UE header + EC rows + UE total

        # ── Ligne UE (cols 0–6 fusionnées horizontalement) ──
        ue_row = notes.row_cells(current_row)

        # Fusionner cols 0-6 horizontalement pour le titre UE
        for ci in range(6, 0, -1):
            ue_row[ci].merge(ue_row[ci - 1])

        _set_cell_bg(ue_row[0], LTBLUE_HEX)
        p_ue = ue_row[0].paragraphs[0]
        p_ue.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pPr = p_ue._p.get_or_add_pPr()
        sp = OxmlElement('w:spacing')
        sp.set(qn('w:before'), '40')
        sp.set(qn('w:after'), '40')
        pPr.append(sp)
        ru = p_ue.add_run(f"{ue.code} — {ue.title}")
        ru.font.size = Pt(8)
        ru.font.bold = True
        ru.font.color.rgb = NAVY

        # Cols 7 (Crédits obtenus) et 8 (Moy UE) : seront fusionnées verticalement
        _set_cell_bg(ue_row[7], LTBLUE_HEX)
        cred_color = GREEN if ue_cred_obt > 0 else RED
        _cell_para(ue_row[7], str(ue_cred_obt), bold=True, color=cred_color, size=8, space_before=40, space_after=40)

        _set_cell_bg(ue_row[8], LTBLUE_HEX)
        avg_color = _grade_color(ue_avg) if ue_avg is not None else LIGHT_GRAY
        _cell_para(ue_row[8], _fmt(ue_avg, 3), bold=True, color=avg_color, size=9, space_before=40, space_after=40)

        _set_cell_bg(ue_row[9], LTBLUE_HEX)

        # ── Lignes EC ──────────────────────────────────────────────────────────
        coeff_sum = 0.0
        moy_coef_sum = 0.0
        for ec_idx, ec in enumerate(ec_list):
            ri = current_row + 1 + ec_idx
            ec_row = notes.row_cells(ri)
            bg = WHITE_HEX if ec_idx % 2 == 0 else GRAY_BG

            cc    = ec.get('cc_average')
            exam  = ec.get('exam_score')
            ratt  = ec.get('rattrapage_score')
            final = ec.get('final_average')
            coef  = float(ec.get('coeff') or 1)
            cred  = ec.get('credits', 0)
            ec_val   = ec.get('is_validated', False)
            ec_ratt  = ec.get('validated_by_rattrapage', False)
            coeff_sum   += coef
            moy_coef_sum += (float(final) * coef) if final is not None else 0.0

            _set_cell_bg(ec_row[0], bg)
            _cell_para(ec_row[0], f"  {ec['subject'].title}", align='left', size=7.5,
                       color=BLACK, space_before=30, space_after=30)

            _set_cell_bg(ec_row[1], bg)
            _cell_para(ec_row[1], _fmt(cc, na=''), color=_grade_color(cc), bold=cc is not None, size=7.5)

            _set_cell_bg(ec_row[2], bg)
            _cell_para(ec_row[2], _fmt(exam, na=''), color=_grade_color(exam), bold=exam is not None, size=7.5)

            _set_cell_bg(ec_row[3], bg)
            ratt_color = _grade_color(ratt) if ratt else LIGHT_GRAY
            _cell_para(ec_row[3], _fmt(ratt, na=''), color=ratt_color, size=7.5)

            _set_cell_bg(ec_row[4], bg)
            _cell_para(ec_row[4], _fmt(final, na=''), color=_grade_color(final), bold=True, size=8)

            _set_cell_bg(ec_row[5], bg)
            _cell_para(ec_row[5], str(coef), size=7.5, color=BLACK)

            _set_cell_bg(ec_row[6], bg)
            mxc = (float(final) * coef) if final is not None else None
            _cell_para(ec_row[6], _fmt(mxc, na=''), size=7.5, color=GRAY)

            # cols 7 et 8 seront dans le rowspan vertical — laisser vide
            _set_cell_bg(ec_row[7], bg)
            _set_cell_bg(ec_row[8], bg)

            _set_cell_bg(ec_row[9], bg)
            if ec_ratt:
                appr_txt = 'Admis SR'
                appr_clr = AMBER
            elif ec_val:
                appr_txt = 'Validé'
                appr_clr = GREEN
            else:
                appr_txt = 'A faire'
                appr_clr = LIGHT_GRAY
            _cell_para(ec_row[9], appr_txt, color=appr_clr, bold=True, size=7)

        # ── Ligne totaux UE ───────────────────────────────────────────────────
        tot_ri  = current_row + 1 + n_ec
        tot_row = notes.row_cells(tot_ri)
        for ci in range(N_COLS):
            _set_cell_bg(tot_row[ci], DBLUE_HEX)

        _cell_para(tot_row[5], str(round(coeff_sum, 2)), bold=True, color=NAVY, size=7.5)
        _cell_para(tot_row[6], _fmt(moy_coef_sum), bold=True, color=NAVY, size=7.5)

        if ue_ratt:
            val_txt, val_clr = 'Validée en SR', AMBER
        elif ue_val:
            val_txt, val_clr = 'Validée', GREEN
        else:
            val_txt, val_clr = 'Non Validée', RED
        _cell_para(tot_row[9], val_txt, bold=True, color=val_clr, size=7)

        # ── Fusion verticale cols 7 et 8 sur row_span lignes ─────────────────
        if row_span > 1:
            last_ri = current_row + row_span - 1
            for col_i in (7, 8):
                bot_cell = notes.cell(last_ri, col_i)
                top_cell = notes.cell(current_row, col_i)
                bot_cell.merge(top_cell)

        current_row += row_span

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. RÉSUMÉ CRÉDITS / MOYENNES
    # ═══════════════════════════════════════════════════════════════════════════
    doc.add_paragraph().paragraph_format.space_after = Pt(3)

    sem_num          = semester.number
    total_cred_obt   = data.get('total_credits_obtained', 0)
    total_cred_poss  = data.get('total_credits_possible', 0)
    sem_avg          = data.get('semester_average')

    if sem_num % 2 == 1:
        # S1 : 2 lignes simples
        res = doc.add_table(rows=2, cols=2)
        res.alignment = WD_TABLE_ALIGNMENT.CENTER
        res.style = 'Table Grid'
        for ci, cw in enumerate([13.0, 5.0]):
            for c in res.columns[ci].cells:
                tc = c._tc
                tcPr = tc.get_or_add_tcPr()
                w_el = OxmlElement('w:tcW')
                w_el.set(qn('w:w'), str(int(cw * 567)))
                w_el.set(qn('w:type'), 'dxa')
                tcPr.append(w_el)
        _set_cell_bg(res.cell(0, 0), GRAY_BG)
        _set_cell_bg(res.cell(1, 0), WHITE_HEX)
        _set_cell_bg(res.cell(0, 1), WHITE_HEX)
        _set_cell_bg(res.cell(1, 1), WHITE_HEX)
        _cell_para(res.cell(0, 0), 'Crédits Semestre 1 :', bold=True, color=NAVY, size=8, align='left',
                   space_before=50, space_after=50)
        cred_clr = GREEN if total_cred_obt else RED
        _cell_para(res.cell(0, 1), f"{total_cred_obt} / {total_cred_poss}", bold=True, color=cred_clr,
                   size=9, space_before=50, space_after=50)
        _cell_para(res.cell(1, 0), 'Moyenne Semestre 1 :', bold=True, color=NAVY, size=8, align='left',
                   space_before=50, space_after=50)
        avg_clr = _grade_color(sem_avg) if sem_avg else LIGHT_GRAY
        _cell_para(res.cell(1, 1), f"{_fmt(sem_avg)} / 20", bold=True, color=avg_clr,
                   size=9, space_before=50, space_after=50)
    else:
        # S2 : tableau 6 colonnes (Crédits S1 | val | Crédits S2 | val | Total | Moy Gén)
        s1_cred_obt  = data.get('s1_credits_obtained', '—')
        s1_cred_poss = data.get('s1_credits_possible', '—')
        s2_cred_obt  = data.get('s2_credits_obtained', total_cred_obt)
        s2_cred_poss = data.get('s2_credits_possible', total_cred_poss)
        ann_cred_obt = data.get('annual_credits_obtained', '—')
        ann_cred_poss= data.get('annual_credits_possible', '—')
        s1_avg       = data.get('s1_average')
        s2_avg       = data.get('s2_average')
        ann_avg      = data.get('annual_average')

        res = doc.add_table(rows=2, cols=6)
        res.alignment = WD_TABLE_ALIGNMENT.CENTER
        res.style = 'Table Grid'
        for ci, cw in enumerate([3.0, 3.0, 3.0, 3.0, 3.0, 3.0]):
            for c in res.columns[ci].cells:
                tc = c._tc
                tcPr = tc.get_or_add_tcPr()
                w_el = OxmlElement('w:tcW')
                w_el.set(qn('w:w'), str(int(cw * 567)))
                w_el.set(qn('w:type'), 'dxa')
                tcPr.append(w_el)

        def _cval(obt, pos): return f"{int(float(obt))} / {pos}" if obt is not None else f"— / {pos}"
        hdrs2 = ['Crédits S1', 'Crédits S2', 'Total crédits', 'Moyenne S1', 'Moyenne S2', 'Moy Générale']
        vals2 = [
            _cval(s1_cred_obt, s1_cred_poss),
            _cval(s2_cred_obt, s2_cred_poss),
            _cval(ann_cred_obt, ann_cred_poss),
            f"{_fmt(s1_avg)} / 20",
            f"{_fmt(s2_avg)} / 20",
            f"{_fmt(ann_avg)} / 20",
        ]
        clrs2 = [
            GREEN if s1_cred_obt else LIGHT_GRAY,
            GREEN if s2_cred_obt else RED,
            NAVY,
            _grade_color(s1_avg) if s1_avg else LIGHT_GRAY,
            _grade_color(s2_avg) if s2_avg else LIGHT_GRAY,
            _grade_color(ann_avg) if ann_avg else LIGHT_GRAY,
        ]
        for ci, hdr_txt in enumerate(hdrs2):
            _set_cell_bg(res.cell(0, ci), GRAY_BG)
            _cell_para(res.cell(0, ci), hdr_txt, bold=True, color=NAVY, size=7.5,
                       space_before=40, space_after=40)
            bg = 'EFF6FF' if ci == 5 else WHITE_HEX
            _set_cell_bg(res.cell(1, ci), bg)
            _cell_para(res.cell(1, ci), vals2[ci], bold=True, color=clrs2[ci], size=9,
                       space_before=50, space_after=50)

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. DÉCISION CONSEIL DE CLASSE
    # ═══════════════════════════════════════════════════════════════════════════
    doc.add_paragraph().paragraph_format.space_after = Pt(3)

    jury_decision = data.get('jury_decision') or f"Mention : {data.get('mention', '—')}"
    dec = doc.add_table(rows=1, cols=1)
    dec.alignment = WD_TABLE_ALIGNMENT.CENTER
    dec.style = 'Table Grid'
    dec.cell(0, 0).width = Cm(18.0)
    _set_cell_bg(dec.cell(0, 0), LTBLUE_HEX)
    p_dec = dec.cell(0, 0).paragraphs[0]
    p_dec.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pPr_dec = p_dec._p.get_or_add_pPr()
    sp_dec = OxmlElement('w:spacing')
    sp_dec.set(qn('w:before'), '60')
    sp_dec.set(qn('w:after'), '60')
    pPr_dec.append(sp_dec)
    r_label = p_dec.add_run('Décision conseil de classe : ')
    r_label.font.size = Pt(8.5)
    r_label.font.bold = True
    r_label.font.color.rgb = NAVY
    r_val = p_dec.add_run(jury_decision)
    r_val.font.size = Pt(8.5)
    r_val.font.color.rgb = BLACK

    # ═══════════════════════════════════════════════════════════════════════════
    # 7. RÉCAPITULATIF UE PAR SEMESTRE
    # ═══════════════════════════════════════════════════════════════════════════
    doc.add_paragraph().paragraph_format.space_after = Pt(3)

    def _build_recap(table_doc, ue_entries, title):
        n = len(ue_entries)
        if n == 0:
            return
        # En-tête et moyenne fusionnés dans une seule ligne (« UE X » puis sa
        # moyenne juste en dessous, dans la même cellule) plutôt que deux
        # lignes séparées — demande explicite pour tous les bulletins.
        recap = table_doc.add_table(rows=3, cols=n + 1)
        recap.alignment = WD_TABLE_ALIGNMENT.CENTER
        recap.style = 'Table Grid'
        lbl_w = 3.0
        col_w = (18.0 - lbl_w) / max(n, 1)
        for ci in range(n + 1):
            cw = lbl_w if ci == 0 else col_w
            for c in recap.columns[ci].cells:
                tc = c._tc
                tcPr = tc.get_or_add_tcPr()
                w_el = OxmlElement('w:tcW')
                w_el.set(qn('w:w'), str(int(cw * 567)))
                w_el.set(qn('w:type'), 'dxa')
                tcPr.append(w_el)

        # Ligne 0 : en-tête + moyenne fusionnés
        _set_cell_bg(recap.cell(0, 0), NAVY_HEX)
        _cell_para(recap.cell(0, 0), title, bold=True, color=WHITE, size=7.5,
                   align='left', space_before=40, space_after=40)
        for ci, ue_e in enumerate(ue_entries, 1):
            _set_cell_bg(recap.cell(0, ci), NAVY_HEX)
            cell = recap.cell(0, ci)
            cell.text = ''
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pPr = p._p.get_or_add_pPr()
            spacing = OxmlElement('w:spacing')
            spacing.set(qn('w:before'), '40')
            spacing.set(qn('w:after'), '40')
            pPr.append(spacing)
            r1 = p.add_run(f"UE {ci}")
            r1.font.size = Pt(7.5)
            r1.font.bold = True
            r1.font.color.rgb = WHITE
            r1.add_break()
            av = ue_e.get('average')
            r2 = p.add_run(_fmt(av, 2))
            r2.font.size = Pt(8)
            r2.font.bold = True
            r2.font.color.rgb = WHITE

        # Ligne 1 : validations
        _set_cell_bg(recap.cell(1, 0), WHITE_HEX)
        _cell_para(recap.cell(1, 0), 'Validation', bold=False, color=GRAY, size=7, align='left', space_before=30, space_after=30)
        for ci, ue_e in enumerate(ue_entries, 1):
            ratt = ue_e.get('validated_by_rattrapage', False)
            val  = ue_e.get('is_validated', False)
            if ratt:
                txt, clr = 'Val. SR', AMBER
            elif val:
                txt, clr = 'Validée', GREEN
            else:
                txt, clr = 'Non Val.', RED
            _cell_para(recap.cell(1, ci), txt, bold=True, color=clr, size=7)

        # Ligne 2 : crédits
        _set_cell_bg(recap.cell(2, 0), GRAY_BG)
        _cell_para(recap.cell(2, 0), 'Crédits', bold=False, color=GRAY, size=7, align='left', space_before=30, space_after=30)
        for ci, ue_e in enumerate(ue_entries, 1):
            cred_obt = ue_e.get('credits_obtained', 0)
            cred_pos = getattr(ue_e.get('ue'), 'credits', 0)
            _cell_para(recap.cell(2, ci), f"{cred_obt} / {cred_pos}", bold=True, color=NAVY, size=7.5)

    if sem_num % 2 == 1:
        _build_recap(doc, ue_list, 'Récapitulatif S1')
    else:
        s1_ue_list = data.get('s1_ue_list', [])
        _build_recap(doc, s1_ue_list if s1_ue_list else ue_list, 'Récapitulatif S1')
        doc.add_paragraph().paragraph_format.space_after = Pt(2)
        _build_recap(doc, ue_list, 'Récapitulatif S2')

    # ═══════════════════════════════════════════════════════════════════════════
    # 8. LÉGENDE + SIGNATURE + PIED DE PAGE
    # ═══════════════════════════════════════════════════════════════════════════
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    foot = doc.add_table(rows=3, cols=6)
    foot.alignment = WD_TABLE_ALIGNMENT.CENTER
    foot.style = 'Table Grid'
    for ci, cw in enumerate([2.5, 3.2, 2.5, 2.5, 3.8, 3.5]):
        for c in foot.columns[ci].cells:
            tc = c._tc
            tcPr = tc.get_or_add_tcPr()
            w_el = OxmlElement('w:tcW')
            w_el.set(qn('w:w'), str(int(cw * 567)))
            w_el.set(qn('w:type'), 'dxa')
            tcPr.append(w_el)

    # Ligne 0 : légende + titre directeur
    legend_items = [
        ('●', LIGHT_GRAY, 'À composer'),
        ('●', RED,        'UE invalidée'),
        ('●', GREEN,      'UE validée'),
        ('●', AMBER,      'Validée en SR'),
    ]
    for ci, (dot, clr, txt) in enumerate(legend_items):
        c = foot.cell(0, ci)
        _set_cell_bg(c, GRAY_BG)
        p = c.paragraphs[0]
        pPr = p._p.get_or_add_pPr()
        sp = OxmlElement('w:spacing')
        sp.set(qn('w:before'), '30')
        sp.set(qn('w:after'), '30')
        pPr.append(sp)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r_dot = p.add_run(dot + ' ')
        r_dot.font.size = Pt(8)
        r_dot.font.color.rgb = clr
        r_txt = p.add_run(txt)
        r_txt.font.size = Pt(7)
        r_txt.font.color.rgb = BLACK

    # Colonne 5 : titre directeur (span lignes 0 et 1)
    c_dir = foot.cell(0, 5)
    foot.cell(1, 5).merge(c_dir)
    _set_cell_bg(c_dir, GRAY_BG)
    c_dir.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_dir = c_dir.paragraphs[0]
    p_dir.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pPr_dir = p_dir._p.get_or_add_pPr()
    sp_dir = OxmlElement('w:spacing')
    sp_dir.set(qn('w:before'), '60')
    sp_dir.set(qn('w:after'), '200')
    pPr_dir.append(sp_dir)
    r_dir = p_dir.add_run('Directeur/rice des études\n\nSignature et Cachet')
    r_dir.font.size = Pt(7.5)
    r_dir.font.bold = True
    r_dir.font.color.rgb = NAVY

    # Ligne 1 : abréviations (cols 0-4)
    for ci in range(4, 0, -1):
        foot.cell(1, ci).merge(foot.cell(1, ci - 1))

    _set_cell_bg(foot.cell(1, 0), WHITE_HEX)
    abbrev = 'MCC = Moy. Contrôles Continus  |  EC = Élément Constitutif  |  Rattrap = Note de Rattrapage'
    _cell_para(foot.cell(1, 0), abbrev, color=GRAY, size=6.5, align='left', space_before=30, space_after=30)

    # Ligne 2 : pied de page (toutes colonnes fusionnées)
    for ci in range(5, 0, -1):
        foot.cell(2, ci).merge(foot.cell(2, ci - 1))

    _set_cell_bg(foot.cell(2, 0), GRAY_BG)
    if institut_config:
        addr_parts = [inst_nom]
        if getattr(institut_config, 'adresse', None):
            addr_parts.append(institut_config.adresse)
        if getattr(institut_config, 'telephone', None):
            addr_parts.append(f"Tél : {institut_config.telephone}")
        if getattr(institut_config, 'email', None):
            addr_parts.append(institut_config.email)
        footer_txt = '  ·  '.join(addr_parts)
    else:
        footer_txt = "Km1, avenue Cheikh Anta DIOP  ·  Tél : +221 33 822 19 81  ·  contact@groupeisi.com  ·  www.groupeisi.com"
    _cell_para(foot.cell(2, 0), footer_txt, color=LIGHT_GRAY, size=6.5, space_before=30, space_after=30)

    # Filigrane dans le VRAI pied de page Word (section.footer), pas dans une
    # cellule du tableau de contenu : ce tableau s'arrête là où le contenu
    # s'arrête (souvent avant le bas physique de la page sur un bulletin
    # court), alors qu'un pied de page Word reste ancré au bas de CHAQUE page.
    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)

    # ── Sérialiser ────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()
