"""
Générateur de rapports PDF avec ReportLab.
Produit : bulletins, relevés de notes, statistiques d'absence, bilan horaire.
"""
import io
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, PageBreak, Image,
)
from academic_core.pdf_utils import logo_image as _pdf_logo_fn, watermark_canvas

# ── Palette ─────────────────────────────────────────────────────
PRIMARY   = colors.HexColor('#0d6efd')
SECONDARY = colors.HexColor('#6c757d')
LIGHT     = colors.HexColor('#f8f9fa')
DARK      = colors.HexColor('#212529')
SUCCESS   = colors.HexColor('#198754')
DANGER    = colors.HexColor('#dc3545')
WARNING   = colors.HexColor('#ffc107')


def _base_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('Title2',     parent=styles['Title'],   fontSize=16, textColor=PRIMARY,   spaceAfter=4))
    styles.add(ParagraphStyle('SubTitle',   parent=styles['Normal'],  fontSize=11, textColor=SECONDARY, spaceAfter=8))
    styles.add(ParagraphStyle('SectionHdr', parent=styles['Normal'],  fontSize=10, textColor=colors.white,
                              backColor=PRIMARY, leading=16, leftIndent=6, spaceAfter=4, spaceBefore=10))
    styles.add(ParagraphStyle('CellBold',   parent=styles['Normal'],  fontSize=9,  fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle('Cell',       parent=styles['Normal'],  fontSize=9))
    styles.add(ParagraphStyle('Footer',     parent=styles['Normal'],  fontSize=8,  textColor=SECONDARY, alignment=TA_CENTER))
    styles.add(ParagraphStyle('FooterWatermark', parent=styles['Normal'], fontSize=6, textColor=colors.HexColor('#94A3B8'), alignment=TA_CENTER))
    return styles


def _table_style_base():
    return [
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 9),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('GRID',       (0, 0), (-1, -1), 0.4, colors.HexColor('#dee2e6')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]


def _header_block(styles, title, subtitle='', institution=None, config=None):
    if institution is None:
        institution = config.nom if config else "Institut Supérieur d'Informatique - ISI"
    _logo = _pdf_logo_fn(width=2.2*cm, height=1.4*cm, config=config)
    sigle = (config.sigle if config else '') or ''
    _hdr = Table([[
        _logo or Paragraph(sigle or 'ISI', styles['SubTitle']),
        Paragraph(
            f'<b>{institution}</b><br/>'
            f'<font size="13"><b>{title}</b></font>'
            + (f'<br/><font size="9">{subtitle}</font>' if subtitle else ''),
            ParagraphStyle('hblk', fontSize=11, fontName='Helvetica-Bold', textColor=PRIMARY,
                           alignment=TA_CENTER, leading=16),
        ),
        _logo or Paragraph(sigle or 'ISI', styles['SubTitle']),
    ]], colWidths=[3*cm, 11*cm, 3*cm])
    _hdr.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return [
        _hdr,
        HRFlowable(width='100%', thickness=1.5, color=PRIMARY, spaceAfter=10),
    ]


# ═══════════════════════════════════════════════════════════════
# 1. Bulletin de notes
# ═══════════════════════════════════════════════════════════════

def generate_bulletin(student, semester, config=None):
    """Retourne un buffer BytesIO contenant le PDF du bulletin."""
    from academic_core.apps.grades.models import SubjectAverage, SemesterAverage, Grade

    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = _base_styles()
    story  = []

    enrollment = student.current_enrollment()
    class_name = enrollment.class_group.name if enrollment else '—'

    story += _header_block(
        styles,
        title=f"Bulletin de Notes — {semester.label}",
        subtitle=f"{student.full_name}  |  Matricule : {student.matricule}  |  Classe : {class_name}",
        config=config,
    )

    # Student info block
    info_data = [
        ['Étudiant', student.full_name,   'Matricule', student.matricule],
        ['Classe',   class_name,           'Semestre',  semester.label],
        ['Année',    str(semester.academic_year), 'Date', date.today().strftime('%d/%m/%Y')],
    ]
    info_tbl = Table(info_data, colWidths=[3*cm, 6*cm, 3*cm, 5*cm])
    info_tbl.setStyle(TableStyle([
        ('FONTSIZE',  (0, 0), (-1, -1), 8),
        ('FONTNAME',  (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME',  (2, 0), (2, -1), 'Helvetica-Bold'),
        ('BACKGROUND',(0, 0), (-1, -1), LIGHT),
        ('GRID',      (0, 0), (-1, -1), 0.4, colors.HexColor('#dee2e6')),
        ('TOPPADDING',(0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 0.4*cm))

    # Grades table
    story.append(Paragraph('Résultats par module (EC)', styles['SectionHdr']))
    headers = ['Code', 'Module (EC)', 'Coeff.', 'Crédits', 'CC', 'TP', 'Exam', 'Moyenne', 'Mention']
    rows    = [headers]

    subject_avgs = SubjectAverage.objects.filter(
        student=student, semester=semester
    ).select_related('subject').order_by('subject__code')

    total_coeff   = Decimal('0')
    weighted_sum  = Decimal('0')

    for sa in subject_avgs:
        s   = sa.subject
        avg = sa.average

        # Collect individual grades per type
        grades_qs = Grade.objects.filter(
            student=student,
            evaluation__subject=s,
            evaluation__semester=semester,
        ).select_related('evaluation__evaluation_type')

        def get_score(code):
            g = grades_qs.filter(evaluation__evaluation_type__code=code).first()
            return f"{g.score:.2f}" if g else '—'

        mention = (
            'TB' if avg >= 16 else 'B' if avg >= 14 else
            'AB' if avg >= 12 else 'P' if avg >= 10 else 'F'
        )
        rows.append([
            s.code, s.title[:35], str(s.coefficient), str(s.credits),
            get_score('CC'), get_score('TP'), get_score('EXAM'),
            f"{avg:.2f}/20", mention,
        ])
        total_coeff  += s.coefficient
        weighted_sum += avg * s.coefficient

    col_w = [1.5*cm, 5.5*cm, 1.5*cm, 1.5*cm, 1.5*cm, 1.5*cm, 1.5*cm, 2*cm, 1.5*cm]
    tbl   = Table(rows, colWidths=col_w, repeatRows=1)
    style = _table_style_base()
    # Colour averages
    for i, row in enumerate(rows[1:], 1):
        try:
            avg_val = float(row[7].split('/')[0])
            colour = SUCCESS if avg_val >= 10 else DANGER
            style += [('TEXTCOLOR', (7, i), (7, i), colour),
                      ('FONTNAME',  (7, i), (7, i), 'Helvetica-Bold')]
        except Exception:
            pass
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    # Semester summary
    story.append(Spacer(1, 0.5*cm))
    sem_avg_obj = SemesterAverage.objects.filter(student=student, semester=semester).first()
    if sem_avg_obj:
        moy = sem_avg_obj.average
        summary_data = [
            ['Moyenne semestrielle', f"{moy:.2f} / 20",
             'Rang', f"{sem_avg_obj.rank} / {sem_avg_obj.total_students}",
             'Mention', sem_avg_obj.mention],
        ]
        sum_tbl = Table(summary_data, colWidths=[4.5*cm, 3*cm, 2*cm, 3*cm, 2*cm, 2.5*cm])
        sum_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), PRIMARY),
            ('TEXTCOLOR',  (0, 0), (-1, -1), colors.white),
            ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, -1), 10),
            ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(sum_tbl)

    story.append(Spacer(1, 1*cm))
    footer_inst = config.nom if config else "Institut Supérieur d'Informatique - ISI"
    story.append(Paragraph(
        f"Document généré le {date.today().strftime('%d/%m/%Y')} — {footer_inst}",
        styles['Footer']
    ))
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════
# 2. Bilan des heures enseignées
# ═══════════════════════════════════════════════════════════════

def generate_teacher_report(teacher, academic_year, config=None):
    from academic_core.apps.attendance.models import AttendanceSheet

    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = _base_styles()
    story  = []

    story += _header_block(
        styles,
        title=f"Bilan des Heures Enseignées — {academic_year}",
        subtitle=f"{teacher.full_name}  |  Matricule : {teacher.matricule}  |  Grade : {teacher.grade}",
        config=config,
    )

    sheets = AttendanceSheet.objects.filter(
        timetable_entry__teacher=teacher,
        timetable_entry__semester__academic_year=academic_year,
        status='VALIDATED',
    ).select_related(
        'timetable_entry__subject', 'timetable_entry__class_group', 'timetable_entry__semester'
    ).order_by('session_date')

    headers = ['Date', 'Semestre', 'Module (EC)', 'Classe', 'Durée (h)', 'Statut']
    rows    = [headers]
    total_h = Decimal('0')

    for sh in sheets:
        entry = sh.timetable_entry
        dur   = Decimal(str(entry.duration_hours))
        total_h += dur
        rows.append([
            sh.session_date.strftime('%d/%m/%Y'),
            str(entry.semester),
            entry.subject.title[:40],
            entry.class_group.name,
            f"{dur:.2f}",
            sh.get_status_display(),
        ])

    rows.append(['', '', '', 'TOTAL', f"{total_h:.2f} h", ''])

    tbl   = Table(rows, colWidths=[2.5*cm, 3*cm, 6*cm, 3*cm, 2*cm, 2.5*cm], repeatRows=1)
    style = _table_style_base()
    style += [
        ('FONTNAME',   (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), LIGHT),
        ('TEXTCOLOR',  (3, -1), (4, -1), PRIMARY),
    ]
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    story.append(Spacer(1, 0.5*cm))
    contractual = teacher.contractual_hours
    taux = (total_h / contractual * 100) if contractual else Decimal('0')
    summary_data = [
        ['Heures contractuelles', f"{contractual:.0f} h",
         'Heures réalisées', f"{total_h:.2f} h",
         'Taux de réalisation', f"{taux:.1f} %"],
    ]
    sum_tbl = Table(summary_data, colWidths=[4.5*cm, 2.5*cm, 3.5*cm, 2.5*cm, 4*cm, 2.5*cm])
    sum_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PRIMARY),
        ('TEXTCOLOR',  (0, 0), (-1, -1), colors.white),
        ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 9),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(sum_tbl)
    story.append(Spacer(1, 1*cm))
    footer_inst = config.nom if config else "Institut Supérieur d'Informatique - ISI"
    story.append(Paragraph(
        f"Document généré le {date.today().strftime('%d/%m/%Y')} — {footer_inst}",
        styles['Footer']
    ))
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════
# 3. Rapport d'absences par classe
# ═══════════════════════════════════════════════════════════════

def generate_absence_report(class_group, semester, config=None):
    from academic_core.apps.attendance.models import StudentAttendance, AttendanceSheet
    from academic_core.apps.students.models import Enrollment

    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = _base_styles()
    story  = []

    story += _header_block(
        styles,
        title=f"Rapport d'Absences — {semester.label}",
        subtitle=f"Classe : {class_group.name}  |  Programme : {class_group.program.name}",
        config=config,
    )

    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user').order_by('student__user__last_name')

    sheets = AttendanceSheet.objects.filter(
        timetable_entry__class_group=class_group,
        timetable_entry__semester=semester,
    )
    total_sessions = sheets.count()

    headers = ['Matricule', 'Nom & Prénom', 'Présences', 'Absences', 'Justifiées', 'Taux abs. %', 'Alerte']
    rows    = [headers]

    for enr in enrollments:
        student = enr.student
        att_qs  = StudentAttendance.objects.filter(
            student=student,
            attendance_sheet__in=sheets,
        )
        present   = att_qs.filter(status='PRESENT').count()
        absent    = att_qs.filter(status='ABSENT').count()
        justified = att_qs.filter(status='JUSTIFIED').count()
        total_rec = att_qs.count()
        taux_abs  = (absent / total_rec * 100) if total_rec else 0
        alerte    = '⚠ DANGER' if taux_abs >= 30 else ('⚠ Attention' if taux_abs >= 20 else 'OK')
        rows.append([
            student.matricule,
            student.full_name[:35],
            str(present), str(absent), str(justified),
            f"{taux_abs:.1f} %", alerte,
        ])

    tbl = Table(rows, colWidths=[2.5*cm, 5.5*cm, 2*cm, 2*cm, 2*cm, 2.5*cm, 2.5*cm], repeatRows=1)
    style = _table_style_base()
    # Colour alert column
    for i, row in enumerate(rows[1:], 1):
        if 'DANGER' in row[6]:
            style += [('TEXTCOLOR', (6, i), (6, i), DANGER),
                      ('FONTNAME',  (6, i), (6, i), 'Helvetica-Bold')]
        elif 'Attention' in row[6]:
            style += [('TEXTCOLOR', (6, i), (6, i), WARNING),
                      ('FONTNAME',  (6, i), (6, i), 'Helvetica-Bold')]
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    story.append(Spacer(1, 0.5*cm))
    footer_inst = config.nom if config else "Institut Supérieur d'Informatique - ISI"
    story.append(Paragraph(
        f"Total séances : {total_sessions}  |  "
        f"Document généré le {date.today().strftime('%d/%m/%Y')} — {footer_inst}",
        styles['Footer']
    ))
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════
# 4. Rapport Annuel de la Direction (résultats par classe/genre/nationalité)
# ═══════════════════════════════════════════════════════════════

def generate_rapport_annuel_pdf(detail, config=None):
    """`detail` : dict retourné par grades.annual_report_services.compute_annual_department_report()."""
    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=1.8*cm, rightMargin=1.8*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = _base_styles()
    story  = []

    department = detail['department']
    academic_year = detail['academic_year']
    s = detail['summary']

    story += _header_block(
        styles,
        title="Rapport Annuel de la Direction",
        subtitle=f"Département : {department.name}  |  Année académique : {academic_year.label}",
        config=config,
    )

    taux = round(s['admis'] / s['total'] * 100, 1) if s['total'] else 0
    story.append(Paragraph(
        f"Effectif : <b>{s['total']}</b>  |  Admis : <b>{s['admis']}</b>  |  "
        f"Non admis : <b>{s['non_admis']}</b>  |  Absent examen : <b>{s['non_disponible']}</b>  |  "
        f"Taux de réussite : <b>{taux} %</b>",
        styles['SubTitle'],
    ))
    story.append(Spacer(1, 0.3*cm))

    def _bucket_table(title, bucket_dict):
        story.append(Paragraph(title, styles['SectionHdr']))
        rows = [['Catégorie', 'Effectif', 'Admis', 'Non admis', 'Absent examen']]
        for label, row in bucket_dict.items():
            rows.append([label, str(row['total']), str(row['admis']), str(row['non_admis']), str(row['non_disponible'])])
        tbl = Table(rows, colWidths=[6*cm, 2.5*cm, 2.5*cm, 2.5*cm, 3*cm], repeatRows=1)
        tbl.setStyle(TableStyle(_table_style_base()))
        story.append(tbl)
        story.append(Spacer(1, 0.4*cm))

    _bucket_table('Par genre', s['by_gender'])
    _bucket_table('Par nationalité', s['by_nationality'])

    story.append(Paragraph('Par classe', styles['SectionHdr']))
    rows = [['Classe', 'Effectif', 'Admis', 'Non admis', 'Absent examen', 'Taux réussite']]
    for row in detail['classes']:
        class_taux = round(row['admis'] / row['total'] * 100, 1) if row['total'] else 0
        rows.append([
            row['class_group'].name, str(row['total']), str(row['admis']),
            str(row['non_admis']), str(row['non_disponible']), f"{class_taux} %",
        ])
    tbl = Table(rows, colWidths=[5*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.8*cm, 2.6*cm], repeatRows=1)
    tbl.setStyle(TableStyle(_table_style_base()))
    story.append(tbl)

    story.append(Spacer(1, 0.5*cm))
    footer_inst = config.nom if config else "Institut Supérieur d'Informatique - ISI"
    story.append(Paragraph(
        f"Document généré le {date.today().strftime('%d/%m/%Y')} — {footer_inst}",
        styles['Footer']
    ))
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    return buf


def _class_results_pdf_groups(session_key):
    """(titre, colonnes H/F ?, clé du champ) — « Abandons » n'existe que côté
    Session Normale, « Réclamation » que côté Session de Rattrapage (voir
    class_results_services.py)."""
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


def _build_class_results_table(session_key, title_label, rows, navy_c, green_c, red_c, gray_c):
    FH = 7
    FS = 7
    purple_c = colors.HexColor('#5B21B6')
    field_colors = {
        'composes': colors.black, 'abandons': colors.grey, 'admis': green_c,
        'non_admis': red_c, 'absent_examen': colors.grey, 'reclamation': purple_c,
    }

    def P(text, bold=False, size=FS, color=colors.black, align=TA_CENTER):
        st = ParagraphStyle('_', fontSize=size, textColor=color,
                             fontName='Helvetica-Bold' if bold else 'Helvetica',
                             alignment=align, leading=size + 1.2, wordWrap='CJK')
        return Paragraph(str(text) if text is not None else '—', st)

    def _fmt_rate(v):
        return f"{v} %" if v is not None else '—'

    groups = _class_results_pdf_groups(session_key)

    W_NOM  = 3.6 * cm
    W_NUM  = 1.1 * cm
    W_TAUX = 1.9 * cm
    W_BEST = 3.4 * cm

    h1, h2, col_w, spans = [], [], [], []
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
            h1.append(P(title, True, FH, colors.white))
            h1.append('')
            h2.append(P('H', True, FH, colors.white))
            h2.append(P('F', True, FH, colors.white))
            spans.append(('SPAN', (ci, 0), (ci + 1, 0)))
            col_w += [w, w]
            ci += 2
        else:
            h1.append(P(title, True, FH, colors.white))
            h2.append('')
            spans.append(('SPAN', (ci, 0), (ci, 1)))
            col_w.append(w)
            ci += 1

    tdata = [h1, h2]

    def _row_cells(class_label, session, is_total=False):
        cells = [P(class_label, True, FS, align=TA_CENTER if is_total else TA_LEFT)]
        for title, has_gender, field in groups[1:]:
            if field == 'effectif_total':
                cells.append(P(session['effectif_total'], size=FS))
            elif field in ('taux_reussite', 'taux_h', 'taux_f'):
                cells.append(P(_fmt_rate(session[field]), True, FS, green_c))
            elif field == 'meilleure_moyenne':
                m = session['meilleure_moyenne']
                if m is not None:
                    best_txt = (
                        f"{float(m):.2f}/20<br/>"
                        f"{session['meilleure_moyenne_etudiant'].user.get_full_name()}"
                    )
                else:
                    best_txt = '—'
                cells.append(P(best_txt, size=FS))
            else:
                color = field_colors.get(field, colors.black)
                cells.append(P(session[field]['M'], size=FS, color=color))
                cells.append(P(session[field]['F'], size=FS, color=color))
        return cells

    for row in rows:
        tdata.append(_row_cells(row['class_group'].name, row[session_key]))

    ts = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 1), navy_c),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#CBD5E0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 2), (-1, -1), [colors.white, gray_c]),
    ] + spans)

    t = Table(tdata, colWidths=col_w, repeatRows=2)
    t.setStyle(ts)
    return t


def generate_class_results_pdf(data, config=None, sessions=(
        'normale', 'normale_reclamation', 'rattrapage', 'rattrapage_reclamation')):
    """
    `data` : dict retourné par grades.class_results_services.compute_class_results_table()
    — un tableau par session demandée (Session Normale / Session Normale
    après réclamation / Session de Rattrapage / Session de Rattrapage après
    réclamation, les 4 par défaut), ventilé H/F : paysage A3, en-têtes
    fusionnés (SPAN), même famille visuelle que conseil_export_pdf.
    `sessions` permet un export par rubrique (une seule session à la fois).
    """
    department = data['department']
    academic_year = data['academic_year']
    semester = data['semester']
    rows = data['rows']

    MARGIN = 0.8 * cm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A3),
                             leftMargin=MARGIN, rightMargin=MARGIN,
                             topMargin=1.2 * cm, bottomMargin=0.8 * cm)

    navy_c  = colors.HexColor('#1E3A5F')
    green_c = colors.HexColor('#166534')
    red_c   = colors.HexColor('#B91C1C')
    gray_c  = colors.HexColor('#F8FAFC')

    title_st = ParagraphStyle('T', fontSize=12, fontName='Helvetica-Bold',
                               textColor=navy_c, alignment=TA_CENTER, spaceAfter=3)
    sub_st = ParagraphStyle('S', fontSize=8, textColor=colors.HexColor('#64748B'),
                             alignment=TA_CENTER, spaceAfter=8)
    section_st = ParagraphStyle('SEC', fontSize=10, fontName='Helvetica-Bold',
                                 textColor=colors.white, alignment=TA_CENTER,
                                 backColor=colors.HexColor('#059669'), spaceAfter=6, spaceBefore=6)
    section_st_teal = ParagraphStyle('SECT', parent=section_st, backColor=colors.HexColor('#0F766E'))
    section_st_amber = ParagraphStyle('SECA', parent=section_st, backColor=colors.HexColor('#B45309'))
    section_st_purple = ParagraphStyle('SECP', parent=section_st, backColor=colors.HexColor('#5B21B6'))

    _logo = _pdf_logo_fn(width=1.6*cm, height=1.6*cm, config=config)
    inst_name = (config.nom if config else '') or "Institut Supérieur d'Informatique - ISI"
    logo_row = Table([[
        _logo or '',
        Paragraph(f'<b>{inst_name}</b>', ParagraphStyle(
            'InstName', fontSize=10, fontName='Helvetica-Bold',
            textColor=navy_c, alignment=TA_CENTER,
        )),
    ]], colWidths=[2.2*cm, None])
    logo_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    header = [
        logo_row,
        HRFlowable(width='100%', thickness=1, color=navy_c, spaceAfter=4),
        Paragraph("RÉSULTATS PAR CLASSE — RAPPORT ANNUEL DE LA DIRECTION", title_st),
        Paragraph(
            f"{department.name}  ·  {academic_year.label}  ·  "
            f"{semester.level.name if semester.level else ''} {semester.label}",
            sub_st,
        ),
    ]

    section_specs = {
        'normale': ("SESSION NORMALE", section_st, 'Session Normale'),
        'normale_reclamation': ("SESSION NORMALE — APRÈS RÉCLAMATION", section_st_teal,
                                 'Session Normale — après réclamation'),
        'rattrapage': ("SESSION DE RATTRAPAGE — AVANT RÉCLAMATION", section_st_amber,
                       'Session de Rattrapage — avant réclamation'),
        'rattrapage_reclamation': ("SESSION DE RATTRAPAGE — APRÈS RÉCLAMATION", section_st_purple,
                                    'Session de Rattrapage — après réclamation'),
    }

    story = []
    for i, session_key in enumerate(sessions):
        label, style, title_label = section_specs[session_key]
        if i > 0:
            story.append(PageBreak())
        story += header + [
            Paragraph(label, style),
            _build_class_results_table(session_key, title_label, rows, navy_c, green_c, red_c, gray_c),
        ]

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    return buf


def _financial_table_flowable(headers, rows, header_colors=None, default_color='#0D2244'):
    """Tableau générique (colonnes/lignes brutes de rapports_financiers.html
    ::_rf_compute) — en-têtes colorés individuellement si `header_colors`
    fourni (une couleur hex ou None par colonne), sinon couleur unique."""
    FS = 7
    style_cache = {}

    def P(text, bold=False, color=colors.black, align=TA_CENTER):
        key = (bold, color, align)
        st = style_cache.get(key)
        if not st:
            st = ParagraphStyle(f'_fin_{len(style_cache)}', fontSize=FS, textColor=color,
                                 fontName='Helvetica-Bold' if bold else 'Helvetica',
                                 alignment=align, leading=FS + 1.5, wordWrap='CJK')
            style_cache[key] = st
        return Paragraph(str(text) if text is not None else '—', st)

    tdata = [[P(h, True, colors.white) for h in headers]]
    for row in rows:
        tdata.append([P(cell) for cell in row])

    ts = [
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#CBD5E0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]
    if header_colors:
        for i, c in enumerate(header_colors):
            ts.append(('BACKGROUND', (i, 0), (i, 0), colors.HexColor(c or default_color)))
    else:
        ts.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(default_color)))

    t = Table(tdata, repeatRows=1)
    t.setStyle(TableStyle(ts))
    return t


def generate_financial_report_pdf(data, *, label, year, config=None, include_main=True, sections=None):
    """
    `data` : dict retourné par accounting.views._rf_compute() (générique à
    tous les types de rapports financiers). `include_main`/`sections`
    permettent un export par rubrique (voir _rf_filtered_data) ; par défaut
    (les deux fournis complets) l'export est global.
    """
    sections = sections if sections is not None else data.get('sections', [])

    MARGIN = 1 * cm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A3),
                             leftMargin=MARGIN, rightMargin=MARGIN,
                             topMargin=1.4 * cm, bottomMargin=1 * cm)

    navy_c = colors.HexColor('#0D2244')
    title_st = ParagraphStyle('T', fontSize=13, fontName='Helvetica-Bold',
                               textColor=navy_c, alignment=TA_CENTER, spaceAfter=3)
    sub_st = ParagraphStyle('S', fontSize=9, textColor=colors.HexColor('#64748B'),
                             alignment=TA_CENTER, spaceAfter=10)
    section_title_st = ParagraphStyle('SEC', fontSize=11, fontName='Helvetica-Bold',
                                       textColor=navy_c, spaceBefore=12, spaceAfter=6)
    kpi_st = ParagraphStyle('KPI', fontSize=9, textColor=colors.HexColor('#334155'), spaceAfter=8)

    _logo = _pdf_logo_fn(width=1.6*cm, height=1.6*cm, config=config)
    inst_name = (config.nom if config else '') or "Institut Supérieur d'Informatique - ISI"
    logo_row = Table([[
        _logo or '',
        Paragraph(f'<b>{inst_name}</b>', ParagraphStyle(
            'InstName2', fontSize=10, fontName='Helvetica-Bold',
            textColor=navy_c, alignment=TA_CENTER,
        )),
    ]], colWidths=[2.2*cm, None])
    logo_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    story = [
        logo_row,
        HRFlowable(width='100%', thickness=1, color=navy_c, spaceAfter=6),
        Paragraph(label.upper(), title_st),
        Paragraph(f"Année académique : {year.label if year else '—'}  ·  Généré le {date.today().strftime('%d/%m/%Y')}", sub_st),
    ]

    if data.get('summary'):
        kpi_text = '  |  '.join(f"<b>{v}</b> {lbl}" for lbl, v in data['summary'])
        story.append(Paragraph(kpi_text, kpi_st))

    if include_main:
        header_cells = data.get('header_cells')
        if header_cells:
            headers = [c['label'] for c in header_cells]
            header_colors = [c.get('color') for c in header_cells]
        else:
            headers = data.get('columns', [])
            header_colors = None
        if headers:
            story.append(_financial_table_flowable(headers, data.get('rows', []), header_colors))

    for section in sections:
        story.append(Paragraph(section.get('title', ''), section_title_st))
        if section.get('summary'):
            kpi_text = '  |  '.join(f"<b>{v}</b> {lbl}" for lbl, v in section['summary'])
            story.append(Paragraph(kpi_text, kpi_st))
        story.append(_financial_table_flowable(
            section.get('columns', []), section.get('rows', []),
            default_color=section.get('color') or '#0D2244',
        ))

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    return buf
