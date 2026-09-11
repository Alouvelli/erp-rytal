"""
PDF bulletin generator — reproduit exactement le bulletin ISI LMD.
Format : Portrait A4 (595×842 pt)

Structure du bulletin :
  1. En-tête  (année académique | BULLETIN DE NOTES | Semestre X)
  2. Info étudiant  (matricule, nom, sexe, naissance, domaine…)
  3. Tableau de notes  (UE + EC avec colonnes MCC/Exam/Rattrap/…)
  4. Résumé crédits & moyennes S1/S2
  5. Décision conseil de classe
  6. Récapitulatif UE par semestre
  7. Légende + signature
  8. Pied de page ISI

Polices agrandies et mises en gras pour la lisibilité à l'impression ; les
marges et interlignes/paddings ont été resserrés en compensation pour que le
bulletin tienne toujours sur une seule page.
"""
import io
import os
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# Chemin absolu vers le logo ISI
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGO_PATH = os.path.join(_BASE_DIR, 'static', 'img', 'logo_isi.png')

# ── Palette couleurs ──────────────────────────────────────────────────────────
NAVY     = colors.HexColor('#003D82')
LT_BLUE  = colors.HexColor('#EFF6FF')
LT_BLUE2 = colors.HexColor('#DBEAFE')
GREEN    = colors.HexColor('#15803D')
RED      = colors.HexColor('#DC2626')
GOLD     = colors.HexColor('#D97706')
GRAY     = colors.HexColor('#64748B')
LT_GRAY  = colors.HexColor('#F8FAFC')
BORDER   = colors.HexColor('#CBD5E1')
WHITE    = colors.white
BLACK    = colors.black


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt(val, decimals=2, na='—'):
    if val is None:
        return na
    try:
        return f'{float(val):.{decimals}f}'.replace('.', ',')
    except Exception:
        return na


def _col(avg):
    """Couleur selon la note (vert >= 10, rouge < 10)."""
    if avg is None:
        return GRAY
    return GREEN if float(avg) >= 10 else RED


# Facteur d'échelle appliqué à toutes les tailles de police du bulletin (toutes
# passent par _ps ci-dessous) — réduit uniformément le rendu sans avoir à
# retoucher chaque taille individuellement dans le fichier.
FONT_SCALE = 0.86


def _ps(name, font='Helvetica', size=8, color=BLACK, align=TA_CENTER,
        bold=True, leading=None):
    size = round(size * FONT_SCALE, 1)
    if leading:
        leading = round(leading * FONT_SCALE, 1)
    return ParagraphStyle(
        name,
        fontName='Helvetica-Bold' if bold else font,
        fontSize=size,
        textColor=color,
        alignment=align,
        leading=leading or (size + 1.6),
    )


# ── Générateur principal ───────────────────────────────────────────────────────
def generate_bulletin_pdf(data, is_sr=False, bulletin_config=None, institut_config=None):
    """
    Génère le PDF bulletin LMD.
    `data` : dict retourné par compute_bulletin_data().
    Retourne les bytes du PDF.
    """
    # Charger la configuration bulletin (singleton)
    if bulletin_config is None:
        from academic_core.apps.academic_structure.models import BulletinConfig
        bulletin_config = BulletinConfig.get()
    director_title = bulletin_config.director_title or 'Directrice des études'
    director_name  = bulletin_config.director_name  or ''

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=0.8 * cm, rightMargin=0.8 * cm,
        topMargin=0.5 * cm, bottomMargin=0.4 * cm,
    )

    student     = data['student']
    semester    = data['semester']
    program     = data['program']
    class_group = data['class_group']
    ue_list     = data['ue_list']
    sem_avg     = data['semester_average']
    mention     = data['mention']
    tot_cr_obt  = data['total_credits_obtained']
    tot_cr_pos  = data['total_credits_possible']

    # Nombre d'absences pour ce semestre
    try:
        from academic_core.apps.attendance.models import StudentAttendance as _SA
        absence_count = _SA.objects.filter(
            student=student,
            status__in=['ABSENT', 'JUSTIFIED'],
            attendance_sheet__timetable_entry__semester=semester,
        ).count()
    except Exception:
        absence_count = 0

    story = []

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. EN-TÊTE  (logo gauche | titre centre | semestre droite)
    # ═══════════════════════════════════════════════════════════════════════════
    acad_year = str(semester.academic_year)

    # Logo de l'institut (dynamique ou fallback statique)
    from academic_core.pdf_utils import get_logo_path, watermark_canvas
    _logo_path = get_logo_path(institut_config)
    if _logo_path:
        logo_cell = Image(_logo_path, width=2.8 * cm, height=1.75 * cm, kind='proportional')
    else:
        sigle = (institut_config.sigle if institut_config else '') or 'ISI'
        logo_cell = Paragraph(sigle, _ps('logo_fb', size=11, bold=True, color=NAVY))

    hdr_data = [[
        logo_cell,
        Paragraph(
            f'<b>BULLETIN DE NOTES</b><br/>'
            f'<font size="9">Année académique : {acad_year}</font>',
            _ps('bnt', size=12, bold=True, color=NAVY, align=TA_CENTER, leading=15),
        ),
        Paragraph(
            f'<b>Semestre {semester.number}</b>',
            _ps('sn', size=11, bold=True, color=NAVY, align=TA_CENTER),
        ),
    ]]
    # col 0 = col 2 = 3.2 cm → titre parfaitement centré sur la largeur totale (19.4 cm)
    hdr_t = Table(hdr_data, colWidths=[3.2 * cm, 13.0 * cm, 3.2 * cm])
    hdr_t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    story.append(hdr_t)
    story.append(Spacer(1, 0.03 * cm))

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. INFO ÉTUDIANT
    # ═══════════════════════════════════════════════════════════════════════════
    dob = getattr(student, 'date_of_birth', None)
    dob_str = dob.strftime('%d/%m/%Y') if dob else '—'
    birth_place = getattr(student, 'place_of_birth', '') or ''
    dob_full = f'{dob_str} à {birth_place}' if birth_place else dob_str

    sex = getattr(student, 'gender', '') or ''
    sex_str = 'Masculin' if sex in ('M', 'MALE') else ('Féminin' if sex in ('F', 'FEMALE') else '—')

    full_name = f'{student.user.last_name.upper()} {student.user.first_name.title()}'

    def _info_cell(label, value):
        return [
            Paragraph(f'{label} :', _ps('il', size=8, bold=False, color=GRAY, align=TA_LEFT)),
            Paragraph(str(value), _ps('iv', size=9, bold=True, color=BLACK, align=TA_LEFT)),
        ]

    abs_str = f'{absence_count} séance(s)'
    info_rows = [
        _info_cell('Matricule', student.matricule or '—') + _info_cell('NOM et Prénom', full_name),
        _info_cell('Sexe', sex_str) + _info_cell('Date et lieu de naissance', dob_full),
        _info_cell('Nb. absences', abs_str) + [Paragraph('', _ps('emp')), Paragraph('', _ps('emp2'))],
    ]
    info_t = Table(info_rows, colWidths=[2.8 * cm, 6.3 * cm, 3.2 * cm, 7.1 * cm])
    info_t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(info_t)

    # Domaine / Mention / Spécialité / Grade
    domaine    = getattr(class_group, 'domaine', '') or '—'
    mention_cl = getattr(class_group, 'mention', '') or '—'
    specialite = program.name if program else '—'
    grade_str  = 'Licence'

    dms_data = [
        [
            Paragraph('<b>Domaine</b>',    _ps('dh', size=7.5, bold=False, color=GRAY, align=TA_CENTER)),
            Paragraph('<b>Mention</b>',    _ps('mh2', size=7.5, bold=False, color=GRAY, align=TA_CENTER)),
            Paragraph('<b>Spécialité</b>', _ps('sh', size=7.5, bold=False, color=GRAY, align=TA_CENTER)),
            Paragraph('<b>Grade</b>',      _ps('gh', size=7.5, bold=False, color=GRAY, align=TA_CENTER)),
        ],
        [
            Paragraph(domaine,    _ps('dv', size=9, bold=True, align=TA_CENTER)),
            Paragraph(mention_cl, _ps('mv2', size=9, bold=True, align=TA_CENTER)),
            Paragraph(specialite, _ps('sv2', size=9, bold=True, align=TA_CENTER)),
            Paragraph(grade_str,  _ps('gv', size=9, bold=True, align=TA_CENTER)),
        ],
    ]
    dms_t = Table(dms_data, colWidths=[3.5 * cm, 3.5 * cm, 8.0 * cm, 4.4 * cm])
    dms_t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(dms_t)
    story.append(Spacer(1, 0.04 * cm))

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. TABLEAU DE NOTES
    #
    # Colonnes (10 au total) :
    #   0  UE / Éléments constitutifs
    #   1  MCC 40%
    #   2  Examen 60%
    #   3  Rattrap 60%
    #   4  Moy EC
    #   5  Coef EC
    #   6  Moy × Coef
    #   7  Crédit EC  (= Crédit UE dans la ligne totaux)
    #   8  Moyenne UE (cellule fusionnée verticalement sur tout le bloc UE)
    #   9  Appréciation
    # ═══════════════════════════════════════════════════════════════════════════
    COL_W = [
        6.75 * cm,  # 0 — EC name
        1.35 * cm,  # 1 — MCC 40%
        1.35 * cm,  # 2 — Examen 60%
        1.35 * cm,  # 3 — Rattrap 60%
        1.15 * cm,  # 4 — Moy EC
        1.1 * cm,   # 5 — Coef EC
        1.45 * cm,  # 6 — Moy×Coef — élargie (1.25→1.45) : « Moyenne » retombait
                    #     à la ligne au milieu du mot dans l'en-tête.
        1.05 * cm,  # 7 — Crédit EC
        1.45 * cm,  # 8 — Moyenne UE — même élargissement que la colonne 6.
        2.4 * cm,   # 9 — Appréciation
    ]

    # --- En-tête (2 lignes) ---------------------------------------------------
    def _hcell(text):
        return Paragraph(text, _ps('hc', bold=True, size=8, color=WHITE, align=TA_CENTER, leading=9.5))

    def _hcell_l(text):
        return Paragraph(text, _ps('hl2', bold=True, size=8, color=WHITE, align=TA_LEFT, leading=9.5))

    h0 = [
        _hcell_l('UE\nÉléments constitutifs'),
        _hcell('MCC'),
        _hcell('Examen'),
        _hcell('Rattrap'),
        _hcell('Moy'),
        _hcell('Coef'),
        _hcell('Moyenne'),
        _hcell('Crédit'),
        _hcell('Moyenne'),
        _hcell('Appréciation'),
    ]
    h1 = [
        _hcell(''),
        _hcell('40%'),
        _hcell('60%'),
        _hcell('60%'),
        _hcell('EC'),
        _hcell('EC'),
        _hcell('Coef'),
        _hcell('EC'),
        _hcell('UE'),
        _hcell(''),
    ]

    table_data = [h0, h1]
    spans = [
        ('SPAN', (0, 0), (0, 1)),   # col 0 : header span 2 lignes
        ('SPAN', (9, 0), (9, 1)),   # col 9 : Appréciation span 2 lignes
    ]

    current_row = 2  # 0 et 1 = entêtes

    # --- Lignes UE + EC -------------------------------------------------------
    for ue_entry in ue_list:
        ue          = ue_entry['ue']
        ue_avg      = ue_entry['average']
        ue_validated= ue_entry['is_validated']
        ue_cred_obt = ue_entry['credits_obtained']
        ue_cred_pos = ue_entry['credits_possible']
        ec_list_ue  = ue_entry['ec_list']
        n_ec        = len(ec_list_ue)

        # Positions dans la table
        ue_hdr_row   = current_row
        ue_first_ec  = current_row + 1
        ue_total_row = current_row + 1 + n_ec  # ligne totaux UE

        # Totaux UE
        coeff_sum     = sum(float(ec['coeff']) for ec in ec_list_ue)
        moy_coef_sum  = sum(
            float(ec['final_average']) * float(ec['coeff'])
            if ec['final_average'] is not None else 0.0
            for ec in ec_list_ue
        )
        avg_color = _col(ue_avg)
        cred_color = GREEN if ue_cred_obt > 0 else _col(None)

        # ── Ligne en-tête UE (col 0-6 fusionnées) ────────────────────────────
        # Police nettement plus grande que les lignes EC (10 vs 8) pour que
        # chaque bloc UE se distingue clairement des EC qu'il regroupe.
        ue_row = [
            Paragraph(
                f'<b>{ue.code} — {ue.title}</b>',
                _ps('uet', bold=True, size=10, color=NAVY, align=TA_LEFT),
            ),
            '', '', '', '', '', '',                  # cols 1–6 dans le span
            Paragraph(                               # col 7 = Crédits obtenus
                f'<b>{ue_cred_obt}</b>',
                _ps('cr_ue', bold=True, size=10, color=cred_color),
            ),
            Paragraph(                               # col 8 = Moy UE (début du span vertical)
                f'<b>{_fmt(ue_avg, 3)}</b>',
                _ps('ua', bold=True, size=10, color=avg_color),
            ),
            Paragraph('', _ps('uc')),               # col 9 = vide (Appréciation UE)
        ]
        table_data.append(ue_row)
        # Span horizontal : cols 0-6 de la ligne en-tête UE
        spans.append(('SPAN', (0, ue_hdr_row), (6, ue_hdr_row)))
        # Span vertical  : col 7 (Crédit UE) de l'en-tête jusqu'à la ligne totaux
        spans.append(('SPAN', (7, ue_hdr_row), (7, ue_total_row)))
        # Span vertical  : col 8 (Moy UE) de l'en-tête jusqu'à la ligne totaux
        spans.append(('SPAN', (8, ue_hdr_row), (8, ue_total_row)))
        current_row += 1

        # ── Lignes EC ─────────────────────────────────────────────────────────
        for ec in ec_list_ue:
            subj   = ec['subject']
            final  = ec['final_average']
            cc     = ec['cc_average']
            exam   = ec['exam_score']
            ratt   = ec['rattrapage_score']
            coeff  = ec['coeff']
            creds  = ec['credits']
            apprec = ec['appreciation']
            moy_x_coef = (float(final) * float(coeff)) if final is not None else None
            apprec_color = GREEN if apprec == 'Validé' else (GRAY if apprec == 'A faire' else RED)
            fc = apprec_color
            if ec.get('validated_by_rattrapage', False):
                apprec = 'Admis en SR'
                fc = GOLD

            ec_row = [
                Paragraph(
                    f'   {subj.title}',
                    _ps('ect', size=8, bold=True, color=BLACK, align=TA_LEFT),
                ),
                Paragraph(_fmt(cc, na=''),           _ps('cc', size=8, bold=True, color=_col(cc))),
                Paragraph(_fmt(exam, na=''),         _ps('ex', size=8, bold=True, color=_col(exam))),
                Paragraph(_fmt(ratt, na=''),  _ps('rt', size=8, bold=True, color=_col(ratt))),
                Paragraph(
                    f'<b>{_fmt(final, na="")}</b>',
                    _ps('fn', size=8.5, bold=True, color=fc),
                ),
                Paragraph(_fmt(coeff),        _ps('cf', size=8, bold=True, color=BLACK)),
                Paragraph(_fmt(moy_x_coef, na=''),   _ps('mc2', size=8, bold=True, color=BLACK)),
                Paragraph('', _ps('cr2')),    # col 7 : dans le span Crédit UE
                Paragraph('', _ps('e2')),     # col 8 : dans le span Moy UE
                Paragraph(apprec,             _ps('ap', size=7.5, bold=True, color=fc)),
            ]
            table_data.append(ec_row)
            current_row += 1

        # ── Ligne totaux UE ───────────────────────────────────────────────────
        ue_by_ratt   = ue_entry.get('validated_by_rattrapage', False)
        ue_apprec    = ue_entry.get('appreciation', 'EC à composer')
        if ue_validated and ue_by_ratt:
            status_color = GOLD
            status_txt   = 'Validée en SR'
        elif ue_apprec == 'Validée':
            status_color = GREEN
            status_txt   = 'Validée'
        elif ue_apprec == 'Non Validée':
            status_color = RED
            status_txt   = 'Non Validée'
        else:
            status_color = GRAY
            status_txt   = 'EC à composer'

        totals_row = [
            Paragraph('', _ps('te')),
            Paragraph('', _ps('te2')),
            Paragraph('', _ps('te3')),
            Paragraph('', _ps('te4')),
            Paragraph('', _ps('te5')),
            Paragraph(
                f'<b>{_fmt(coeff_sum)}</b>',
                _ps('ts', size=8, bold=True, color=BLACK),
            ),
            Paragraph(
                f'<b>{_fmt(moy_coef_sum)}</b>',
                _ps('tm2', size=8, bold=True, color=BLACK),
            ),
            Paragraph('', _ps('tc2')),  # col 7 : dans le span Crédit UE
            Paragraph('', _ps('e3')),   # col 8 : dans le span Moy UE
            Paragraph(
                status_txt,
                _ps('sv3', size=7.5, bold=True, color=status_color),
            ),
        ]
        table_data.append(totals_row)
        current_row += 1

    # --- Application du style tableau ----------------------------------------
    n_rows = len(table_data)
    ts = TableStyle([
        # En-têtes (lignes 0-1)
        ('BACKGROUND',   (0, 0), (-1, 1), NAVY),
        ('TEXTCOLOR',    (0, 0), (-1, 1), WHITE),
        # Alignement global
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN',        (0, 0), (0, -1),  'LEFT'),
        # Padding
        ('TOPPADDING',    (0, 0), (-1, -1), 0.6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 2),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
        # Grille
        ('GRID',  (0, 0), (-1, -1), 0.3, BORDER),
        ('BOX',   (0, 0), (-1, -1), 1,   NAVY),
    ])

    # Styles dynamiques par bloc UE
    row_ptr = 2
    for ue_entry in ue_list:
        n_ec = len(ue_entry['ec_list'])
        total_row_idx = row_ptr + 1 + n_ec

        # Fond en-tête UE
        ts.add('BACKGROUND', (0, row_ptr), (-1, row_ptr), LT_BLUE)
        ts.add('LINEBELOW',  (0, row_ptr), (-1, row_ptr), 0.5, NAVY)

        # Alternance EC
        for i in range(n_ec):
            bg = WHITE if i % 2 == 0 else LT_GRAY
            ts.add('BACKGROUND', (0, row_ptr + 1 + i), (-1, row_ptr + 1 + i), bg)

        # Fond ligne totaux UE
        ts.add('BACKGROUND', (0, total_row_idx), (-1, total_row_idx), LT_BLUE2)
        ts.add('LINEABOVE',  (0, total_row_idx), (-1, total_row_idx), 0.5, BORDER)
        ts.add('LINEBELOW',  (0, total_row_idx), (-1, total_row_idx), 1.0, NAVY)

        row_ptr += 2 + n_ec

    # Spans (header + UE)
    for sp in spans:
        ts.add(*sp)

    grades_t = Table(table_data, colWidths=COL_W, repeatRows=2)
    grades_t.setStyle(ts)
    story.append(grades_t)
    story.append(Spacer(1, 0.25 * cm))

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. RÉSUMÉ CRÉDITS / MOYENNES
    # ═══════════════════════════════════════════════════════════════════════════
    # Semestre "jumeau" (l'autre semestre du même cycle de niveau, ex: S3<->S4
    # pour une L2) : recherché par niveau + année académique, PAS par numéro
    # littéral 1/2 — la numérotation des semestres est à plat sur tout le
    # cursus (L1=1/2, L2=3/4, L3=5/6), donc "peer de S3" n'est jamais le
    # semestre numéro 1 (qui appartient à un autre niveau). Même pattern que
    # views.py:bulletin_detail (other_sem).
    peer_bul  = None
    peer_sem  = None
    try:
        from .models import Bulletin as _Bul
        from academic_core.apps.academic_structure.models import Semester as _Sem
        peer_sem = _Sem.objects.filter(
            academic_year=semester.academic_year,
            level=semester.level,
        ).exclude(pk=semester.pk).order_by('number').first()
        if peer_sem:
            peer_bul = _Bul.objects.filter(
                student=student, semester=peer_sem,
            ).first()
    except Exception:
        pass

    # Position dans la paire de semestres du cycle (S1/S3/S5 -> premier de la
    # paire, S2/S4/S6 -> second) : la parité du numéro suffit puisque la
    # numérotation à plat conserve toujours l'alternance impair->pair au sein
    # d'un même niveau. Détermine quel format de bulletin utiliser (S1/S3/S5
    # -> format "premier semestre" ; S2/S4/S6 -> format "second semestre"
    # avec récap complet), pour que S3/S5 reproduisent exactement le format
    # de S1 et S4/S6 celui de S2.
    is_first_of_pair = semester.number % 2 == 1
    # Numéros réels à afficher dans les libellés ("Crédits Semestre X", "Récap
    # du Xème semestre"...) : jamais "1"/"2" en dur, pour que S3/S4/S5/S6
    # affichent leur vrai numéro. Repli sur number+1/-1 si le semestre pair
    # n'existe pas encore en base (pas encore créé).
    own_num  = semester.number
    peer_num = peer_sem.number if peer_sem else (own_num + 1 if is_first_of_pair else own_num - 1)
    s1_num, s2_num = (own_num, peer_num) if is_first_of_pair else (peer_num, own_num)

    def _cr_str(obt, pos):
        return f'{obt},00 / {pos}' if isinstance(obt, int) else f'{obt} / {pos}'

    if is_first_of_pair:
        s1_cr_obt = tot_cr_obt
        s1_cr_pos = tot_cr_pos
        s1_avg    = sem_avg
        s2_cr_obt = peer_bul.total_credits_obtained if peer_bul else None
        s2_cr_pos = peer_bul.total_credits_possible if peer_bul else None
        s2_avg    = peer_bul.semester_average        if peer_bul else None
    else:
        s1_cr_obt = peer_bul.total_credits_obtained if peer_bul else None
        s1_cr_pos = peer_bul.total_credits_possible if peer_bul else None
        s1_avg    = peer_bul.semester_average        if peer_bul else None
        # Si bulletin S1 non sauvegardé, calculer à la volée
        if peer_sem and (s1_cr_obt is None or s1_avg is None):
            try:
                from .services import compute_bulletin_data as _cbd
                _s1 = _cbd(student, peer_sem, class_group)
                if _s1:
                    s1_cr_obt = _s1['total_credits_obtained']
                    s1_cr_pos = _s1['total_credits_possible']
                    s1_avg    = _s1['semester_average']
            except Exception:
                pass
        s2_cr_obt = tot_cr_obt
        s2_cr_pos = tot_cr_pos
        s2_avg    = sem_avg

    def _cr_disp(obt, pos=None):
        """Affiche les crédits : obtenus / possibles."""
        if obt is None:
            return f'— / {pos}' if pos else '— / —'
        try:
            obt_int = int(float(obt))
        except Exception:
            obt_int = obt
        return f'{obt_int} / {pos}' if pos is not None else str(obt_int)

    def _avg_disp(avg):
        if avg is None:
            return '— / 20'
        return f'{_fmt(avg)} / 20'

    # Moyenne générale : (S1 + S2) / 2, affichée uniquement au second semestre de la paire
    is_s2 = not is_first_of_pair
    try:
        if s1_avg is not None and s2_avg is not None:
            moy_gen = f'{(float(s1_avg) + float(s2_avg)) / 2:.2f}'.replace('.', ',') + ' / 20'
        elif is_s2 and s2_avg is not None:
            moy_gen = f'{_fmt(s2_avg)} / 20'
        elif not is_s2 and s1_avg is not None:
            moy_gen = f'{_fmt(s1_avg)} / 20'
        else:
            moy_gen = '— / 20'
    except Exception:
        moy_gen = '— / 20'

    # Total crédits obtenus (cumul S1 + S2)
    total_cr_obt_global = (s1_cr_obt or 0) + (s2_cr_obt or 0)
    if is_s2:
        total_cr_str = f'{int(total_cr_obt_global)} / 60'
    else:
        try:
            total_cr_str = str(int(float(tot_cr_obt)))
        except Exception:
            total_cr_str = str(tot_cr_obt)

    def _sc(text, bold=True, size=9, color=BLACK, align=TA_CENTER):
        return Paragraph(text, _ps(f's{hash(text)}', size=size, bold=bold, color=color, align=align))

    if is_first_of_pair:
        # S1 : Crédits S1 + Moyenne S1, pleine largeur, label à gauche / valeur à droite
        sum_data = [
            [
                Paragraph(f'Crédits Semestre {own_num} :', _ps('s1_lbl1', size=9, bold=True, color=NAVY, align=TA_LEFT)),
                Paragraph(_cr_disp(s1_cr_obt, s1_cr_pos), _ps('s1_val1', size=10, bold=True, color=BLACK, align=TA_RIGHT)),
            ],
            [
                Paragraph(f'Moyenne Semestre {own_num} :', _ps('s1_lbl2', size=9, bold=True, color=NAVY, align=TA_LEFT)),
                Paragraph(_avg_disp(s1_avg), _ps('s1_val2', size=10, bold=True, color=_col(s1_avg), align=TA_RIGHT)),
            ],
        ]
        sum_t = Table(sum_data, colWidths=[14.4 * cm, 5.0 * cm])
        sum_t.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.5, BORDER),
            ('BACKGROUND',    (0, 0), (-1, -1), LT_GRAY),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('BOX',           (0, 0), (-1, -1), 1, NAVY),
        ]))
    else:
        # S2 : afficher S1 + S2 + Total + Moy Générale
        sum_data = [
            [
                _sc(f'Crédits\nSemestre {s1_num}',   bold=True, size=8.5, color=NAVY),
                _sc(_cr_disp(s1_cr_obt, s1_cr_pos), bold=True, size=10),
                _sc(f'Crédits\nSemestre {s2_num}',   bold=True, size=8.5, color=NAVY),
                _sc(_cr_disp(s2_cr_obt, s2_cr_pos), bold=True, size=10),
                _sc('Total crédits',          bold=True, size=8.5, color=NAVY),
                _sc(total_cr_str,             bold=True, size=10, color=NAVY),
            ],
            [
                _sc(f'Moyenne\nSemestre {s1_num}',   bold=True, size=8.5, color=NAVY),
                _sc(_avg_disp(s1_avg),       bold=True, size=10),
                _sc(f'Moyenne\nSemestre {s2_num}',   bold=True, size=8.5, color=NAVY),
                _sc(_avg_disp(s2_avg),       bold=True, size=10),
                _sc('Moy Générale',          bold=True, size=8.5, color=NAVY),
                _sc(moy_gen,                 bold=True, size=10, color=_col(sem_avg)),
            ],
        ]
        sum_t = Table(sum_data, colWidths=[3.2 * cm, 3.1 * cm, 3.2 * cm, 3.1 * cm, 3.1 * cm, 3.3 * cm])
        sum_t.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.5, BORDER),
            ('BACKGROUND',    (0, 0), (-1, -1), LT_GRAY),
            ('BACKGROUND',    (4, 0), (5, 1),   LT_BLUE),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 1.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 3),
            ('BOX',           (0, 0), (-1, -1), 1, NAVY),
        ]))
    story.append(sum_t)
    story.append(Spacer(1, 0.25 * cm))

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. DÉCISION CONSEIL DE CLASSE
    # ═══════════════════════════════════════════════════════════════════════════
    jury_decision = data.get('jury_decision', '') or ''
    dec_txt = jury_decision if jury_decision else f'Mention : {mention}'

    dec_t = Table(
        [[Paragraph(
            f'<b>Décision conseil de classe :</b>  {dec_txt}',
            _ps('dec', size=11, bold=True, color=BLACK, align=TA_LEFT),
        )]],
        colWidths=[19.4 * cm],
    )
    dec_t.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.5, NAVY),
        ('BACKGROUND',    (0, 0), (-1, -1), LT_BLUE),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
    ]))
    story.append(dec_t)
    story.append(Spacer(1, 0.25 * cm))

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. RÉCAPITULATIF UE PAR SEMESTRE (S1 gauche | S2 droite)
    # ═══════════════════════════════════════════════════════════════════════════
    if is_first_of_pair:
        s1_ue_entries = ue_list          # dicts compute_bulletin_data
        s2_ue_entries = []
        # Récupérer S2 depuis BulletinUEResult si disponible
        if peer_bul:
            try:
                s2_ue_entries = list(peer_bul.ue_results.all().order_by('order'))
            except Exception:
                pass
    else:
        s2_ue_entries = ue_list          # dicts compute_bulletin_data
        s1_ue_entries = []
        if peer_bul:
            try:
                s1_ue_entries = list(peer_bul.ue_results.all().order_by('order'))
            except Exception:
                pass
        # Si pas de bulletin S1 sauvegardé, calculer à la volée
        if not s1_ue_entries and peer_sem:
            try:
                from .services import compute_bulletin_data as _cbd
                _s1_data = _cbd(student, peer_sem, class_group)
                if _s1_data:
                    s1_ue_entries = _s1_data['ue_list']
            except Exception:
                pass

    def _make_recap(ue_entries, label, is_db_objects=False):
        """Construit les lignes d'une mini-table récap."""
        n = len(ue_entries)
        if n == 0:
            # Placeholder vide
            ue_entries_placeholder = ue_list  # utiliser le nb d'UE du semestre courant
            n = len(ue_entries_placeholder)
            is_empty = True
        else:
            is_empty = False

        # En-tête et moyenne fusionnés dans une seule ligne (« UE X » suivi de
        # sa moyenne sur la ligne suivante, dans la même cellule) plutôt que
        # deux lignes séparées (en-tête puis moyenne) — demande explicite pour
        # tous les bulletins.
        hs = _ps('rh', bold=True, size=8.5, color=WHITE, align=TA_CENTER, leading=11)
        hs_l = _ps('rhl', bold=True, size=8.5, color=WHITE, align=TA_LEFT)
        cs = _ps('rc', size=8, bold=True, color=BLACK, align=TA_CENTER)

        hdr_row = [Paragraph(label, hs_l)]
        val_row = [Paragraph('Validations', cs)]
        cr_row  = [Paragraph('Crédits obtenus', cs)]

        def _appr(apprec, by_ratt=False):
            """
            Retourne (couleur, texte affiché) selon l'appréciation UE.
            <br/> (pas \n, ignoré par Paragraph) pour forcer un retour à la
            ligne volontaire plutôt qu'un retour au milieu d'un mot par
            ReportLab quand le texte ne tient pas dans la colonne (très
            étroite avec 5-6 UE sur la même ligne).
            """
            if by_ratt:
                return GOLD, 'Val.<br/>SR'
            if apprec == 'Validée':
                return GREEN, 'Validée'
            elif apprec == 'Non Validée':
                return RED, 'Non<br/>Validée'
            else:
                # "À faire" (même terme que l'appréciation EC individuelle plus
                # haut dans le bulletin) plutôt que "EC à composer" : bien plus
                # court, tient sur la colonne étroite (jusqu'à 6 UE par ligne)
                # sans retour à la ligne au milieu du mot "composer".
                return GRAY, 'À<br/>faire'

        for i in range(n):
            if is_empty:
                hdr_row.append(Paragraph(f'UE {i+1}<br/>—', hs))
                val_row.append(Paragraph('—', _ps('vv', size=8, bold=True, color=GRAY, align=TA_CENTER)))
                cr_row.append(Paragraph('—', _ps('cr', size=9, bold=True, color=NAVY, align=TA_CENTER)))
            elif is_db_objects:
                u = ue_entries[i]
                hdr_row.append(Paragraph(f'UE {i+1}<br/>{_fmt(u.average, 2, "0,00")}', hs))
                # L'UE est validée dès que sa moyenne est >= 10 (cf.
                # services.py) : on fait confiance à is_validated déjà
                # calculé/persisté plutôt que de re-dériver depuis les
                # appréciations EC individuelles — un EC faible ne doit pas
                # invalider une UE dont la moyenne pondérée est suffisante.
                # Seul un EC encore "A faire" laisse l'UE en attente.
                try:
                    ec_apprs = [ec.appreciation for ec in u.ec_results.all()]
                    db_apprec = 'EC à composer' if 'A faire' in ec_apprs else ('Validée' if u.is_validated else 'Non Validée')
                except Exception:
                    db_apprec = 'Validée' if u.is_validated else 'Non Validée'
                vc, vtx = _appr(db_apprec)
                val_row.append(Paragraph(vtx, _ps(f'vv2_{i}', size=8, bold=True, color=vc, align=TA_CENTER)))
                cr_row.append(Paragraph(str(u.credits_obtained), _ps(f'cr2_{i}', size=9, bold=True, color=NAVY, align=TA_CENTER)))
            else:
                u = ue_entries[i]
                hdr_row.append(Paragraph(f'UE {i+1}<br/>{_fmt(u["average"], 2, "0,00")}', hs))
                by_ratt = u.get('validated_by_rattrapage', False)
                vc, vtx = _appr(
                    u.get('appreciation', 'Validée' if u['is_validated'] else 'Non Validée'),
                    by_ratt=by_ratt,
                )
                val_row.append(Paragraph(vtx, _ps(f'vv3_{i}', size=8, bold=True, color=vc, align=TA_CENTER)))
                cr_row.append(Paragraph(str(u['credits_obtained']), _ps(f'cr3_{i}', size=9, bold=True, color=NAVY, align=TA_CENTER)))

        return [hdr_row, val_row, cr_row], n

    # Gouttière visible entre les deux récaps S1|S2 (sinon ils se touchent,
    # peu lisible) : rognée sur chaque moitié en amont, pour que la largeur
    # des tables construites par _build_recap_table() corresponde exactement
    # à celle de la cellule qui les accueille dans recap_wrapper ci-dessous.
    recap_gutter = 0.4 * cm
    half_w = 9.7 * cm - (recap_gutter / 2)
    label_w = 2.2 * cm

    def _build_recap_table(rows, n_ue):
        ue_col_w = (half_w - label_w) / max(n_ue, 1)
        col_ws = [label_w] + [ue_col_w] * n_ue
        t = Table(rows, colWidths=col_ws)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR',  (0, 0), (-1, 0), WHITE),
            ('GRID',       (0, 0), (-1, -1), 0.3, BORDER),
            ('BOX',        (0, 0), (-1, -1), 0.8, NAVY),
            ('TOPPADDING',    (0, 0), (-1, -1), 0.6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0.6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 1.5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 1.5),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN',         (0, 0), (0, -1),  'LEFT'),
        ]))
        return t

    # Déterminer si les entrées S1/S2 viennent de la BD (BulletinUEResult)
    s1_is_db = (not is_first_of_pair and peer_bul is not None and len(s1_ue_entries) > 0
                and hasattr(s1_ue_entries[0], 'average'))
    s2_is_db = (is_first_of_pair and peer_bul is not None and len(s2_ue_entries) > 0
                and hasattr(s2_ue_entries[0], 'average'))

    if is_first_of_pair:
        # S1/S3/S5 : uniquement le récap du semestre courant, pleine largeur
        s1_rows, s1_n = _make_recap(s1_ue_entries, f'Récap du semestre {own_num}', is_db_objects=s1_is_db)
        full_w = 19.4 * cm
        label_w_full = 2.2 * cm
        ue_col_w_full = (full_w - label_w_full) / max(s1_n, 1)
        t1_full = Table(s1_rows, colWidths=[label_w_full] + [ue_col_w_full] * s1_n)
        t1_full.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR',  (0, 0), (-1, 0), WHITE),
            ('GRID',       (0, 0), (-1, -1), 0.3, BORDER),
            ('BOX',        (0, 0), (-1, -1), 0.8, NAVY),
            ('TOPPADDING',    (0, 0), (-1, -1), 0.6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0.6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 1.5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 1.5),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN',         (0, 0), (0, -1),  'LEFT'),
        ]))
        story.append(t1_full)
    else:
        # S2/S4/S6 : récap du semestre précédent (gauche) + récap courant (droite)
        s1_rows, s1_n = _make_recap(s1_ue_entries, f'Récap du semestre {s1_num}', is_db_objects=s1_is_db)
        s2_rows, s2_n = _make_recap(s2_ue_entries, f'Récap du semestre {s2_num}', is_db_objects=s2_is_db)
        t1 = _build_recap_table(s1_rows, s1_n)
        t2 = _build_recap_table(s2_rows, s2_n)
        recap_wrapper = Table([[t1, '', t2]], colWidths=[half_w, recap_gutter, half_w])
        recap_wrapper.setStyle(TableStyle([
            ('LEFTPADDING',   (0, 0), (-1, -1), 0),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
            ('TOPPADDING',    (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(recap_wrapper)
    story.append(Spacer(1, 0.15 * cm))

    # ═══════════════════════════════════════════════════════════════════════════
    # 7 + 8. LÉGENDE + SIGNATURE + PIED DE PAGE  (bloc unique, 2 lignes)
    # ═══════════════════════════════════════════════════════════════════════════
    # Indicateurs en une phrase colorée
    def _ind(text, color):
        return Paragraph(
            f'<b>●</b> {text}',
            _ps(f'i{hash(text)}', size=9, color=color, bold=True, align=TA_CENTER),
        )

    # Abréviations sur une ligne compacte
    abbr_line = (
        '<b>MCC</b>=Moy. contrôles  '
        '<b>EC</b>=Élément constitutif  '
        '<b>Rattrap</b>=note rattrapage  '
        '<b>Moy</b>=moyenne EC'
    )

    # Total width : A4 - margins = 21 - 2×0.8 = 19.4 cm
    TW = 19.4 * cm

    # Ligne 1 : indicateurs (4 cols) + signature (1 col, span 2 lignes)
    # Ligne 2 : légende texte (4 cols fusionnées) + pied de page (dans sig span)
    # légend_label | ind1 | ind2 | ind3 | ind4 | signature
    # 2.1 + 2.6 + 2.5 + 2.2 + 2.6 + 7.4 = 19.4 ✓
    # Colonne « Légende » élargie (1.5→2.1cm) : à 9.5pt gras elle ne tenait
    # plus sur une seule ligne et retombait à la ligne au milieu du mot.
    LCOLS = [2.1 * cm, 2.6 * cm, 2.5 * cm, 2.2 * cm, 2.6 * cm, 7.4 * cm]

    leg_row1 = [
        Paragraph('<b>Légende</b>', _ps('lbl', size=9.5, color=GRAY, align=TA_LEFT, bold=True)),
        _ind('Examen(s) à faire', GRAY),
        _ind('UE invalidée',      RED),
        _ind('UE validée',        GREEN),
        _ind('Validée en SR',     GOLD),
        Paragraph(
            f'<b>{director_title}</b><br/><br/><font size="12"><b>{director_name}</b></font>',
            _ps('sig', size=10.5, color=NAVY, align=TA_CENTER, bold=True),
        ),
    ]

    leg_row2 = [
        Paragraph(abbr_line, _ps('abbr', size=8.5, color=GRAY, align=TA_CENTER, bold=True)),
        '', '', '', '',   # fusionné avec col 0 sur ligne 2 (SPAN 0-4)
        '',               # dans le SPAN signature
    ]

    # Pied de page : adresse de l'institut (dynamique si config fourni)
    if institut_config:
        _parts = []
        if institut_config.adresse:
            _parts.append(institut_config.adresse)
        if institut_config.telephone:
            _parts.append(f'Tél : {institut_config.telephone}')
        if institut_config.email:
            _parts.append(institut_config.email)
        if institut_config.site_web:
            _parts.append(institut_config.site_web)
        _footer_addr = '  ·  '.join(_parts) if _parts else institut_config.nom
    else:
        _footer_addr = ('Km1, avenue Cheikh Anta DIOP  ·  Tél : +221 33 822 19 81  ·  '
                        'contact@groupeisi.com  ·  www.groupeisi.com')

    foot_row = [
        Paragraph(
            _footer_addr,
            _ps('addr', size=8.5, color=GRAY, align=TA_CENTER, bold=True),
        ),
        '', '', '', '', '',   # cols 1-5 vides → fusionné ci-dessous
    ]

    # Table finale : 3 lignes × 6 colonnes
    # Ligne 0 : légende indicateurs + signature (col 5 span 0→1)
    # Ligne 1 : texte abréviations (col 0-4 fusionné) + (col 5 dans span)
    # Ligne 2 : adresse ISI (col 0-5 fusionné)
    story.append(Spacer(1, 0.25 * cm))
    final_t = Table(
        [leg_row1, leg_row2, foot_row],
        colWidths=LCOLS,
        rowHeights=[1.7 * cm, 1.5 * cm, None],
    )
    final_t.setStyle(TableStyle([
        # Bordure externe
        ('BOX',           (0, 0), (-1, 1), 0.5, BORDER),
        ('LINEABOVE',     (0, 2), (-1, 2), 0.5, BORDER),
        # Grille légère intérieure
        ('GRID',          (0, 0), (-1, 1), 0.3, BORDER),
        # Fusions
        ('SPAN', (5, 0), (5, 1)),           # Signature : ligne 0 → ligne 1
        ('SPAN', (0, 1), (4, 1)),           # Abréviations : col 0→4 ligne 1
        ('SPAN', (0, 2), (5, 2)),           # Adresse ISI : toute la ligne 2
        # Padding
        ('TOPPADDING',    (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        # Alignement
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN',         (0, 0), (0, -1),  'LEFT'),
        # Fond léger ligne abréviations
        ('BACKGROUND',    (0, 1), (4, 1), LT_GRAY),
    ]))
    story.append(final_t)

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    return buf.getvalue()
