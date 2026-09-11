#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Générateur de PDF pour la documentation de la plateforme UniManager.

Convertit un fichier Markdown (sous-ensemble) en PDF paginé et mis en forme
avec ReportLab — sans dépendance externe (ni pandoc, ni LaTeX, ni navigateur).

Sous-ensemble Markdown pris en charge :
  # / ## / ### / ####      titres (le # démarre une nouvelle page)
  paragraphes              texte courant, avec **gras**, *italique*, `code`
  - / *                    listes à puces (indentation de 2 espaces = niveau)
  1.                       listes numérotées
  | a | b |                tableaux (ligne de séparation |---|---| obligatoire)
  ```                      blocs de code
  ---                      filet horizontal
  > texte                  encadré / note
  <!-- meta:title=... -->  métadonnées de page de garde (title, subtitle,
                           version, date, org)

Usage :
  python build_pdf.py source.md sortie.pdf
"""
import re
import sys
from datetime import date

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents


# ─────────────────────────────────────────────────────────────────────────────
# Polices Unicode (couverture complète du français ; repli automatique)
# ─────────────────────────────────────────────────────────────────────────────
def register_fonts():
    """Enregistre une famille sans-serif Unicode et une famille mono.

    Essaie Arial (Windows), sinon Bitstream Vera (livré avec ReportLab, donc
    toujours disponible). Renvoie (base, bold, italic, bolditalic, mono).
    """
    win = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        ("Main", os.path.join(win, "Fonts", "arial.ttf"),
         os.path.join(win, "Fonts", "arialbd.ttf"),
         os.path.join(win, "Fonts", "ariali.ttf"),
         os.path.join(win, "Fonts", "arialbi.ttf")),
    ]
    rl_fonts = os.path.join(os.path.dirname(
        pdfmetrics.__file__).replace("pdfbase", ""), "fonts")
    import reportlab
    rl_fonts = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    candidates.append(
        ("Main", os.path.join(rl_fonts, "Vera.ttf"),
         os.path.join(rl_fonts, "VeraBd.ttf"),
         os.path.join(rl_fonts, "VeraIt.ttf"),
         os.path.join(rl_fonts, "VeraBI.ttf")))

    base = bold = italic = bolditalic = None
    for name, reg, bd, it, bi in candidates:
        if all(os.path.exists(p) for p in (reg, bd, it, bi)):
            try:
                pdfmetrics.registerFont(TTFont("Main", reg))
                pdfmetrics.registerFont(TTFont("Main-Bold", bd))
                pdfmetrics.registerFont(TTFont("Main-Italic", it))
                pdfmetrics.registerFont(TTFont("Main-BoldItalic", bi))
                pdfmetrics.registerFontFamily(
                    "Main", normal="Main", bold="Main-Bold",
                    italic="Main-Italic", boldItalic="Main-BoldItalic")
                base, bold, italic, bolditalic = (
                    "Main", "Main-Bold", "Main-Italic", "Main-BoldItalic")
                break
            except Exception:
                continue

    if base is None:  # dernier repli : polices standard
        return ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique",
                "Helvetica-BoldOblique", "Courier")

    # Mono : VeraMono si présent, sinon Courier
    mono = "Courier"
    vmono = os.path.join(rl_fonts, "VeraMono.ttf")
    if os.path.exists(vmono):
        try:
            pdfmetrics.registerFont(TTFont("Mono", vmono))
            mono = "Mono"
        except Exception:
            pass
    return (base, bold, italic, bolditalic, mono)


F_BASE, F_BOLD, F_ITALIC, F_BOLDITALIC, F_MONO = register_fonts()

# ─────────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────────
NAVY = colors.HexColor("#1f3a5f")
BLUE = colors.HexColor("#2563eb")
LIGHT = colors.HexColor("#eef2f8")
GREY = colors.HexColor("#5b6472")
BORDER = colors.HexColor("#c8d2e0")
CODEBG = colors.HexColor("#f4f5f7")
NOTEBG = colors.HexColor("#fff8e1")
NOTEBAR = colors.HexColor("#f59e0b")

PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm


# ─────────────────────────────────────────────────────────────────────────────
# Styles
# ─────────────────────────────────────────────────────────────────────────────
def build_styles():
    ss = getSampleStyleSheet()
    styles = {}

    styles["body"] = ParagraphStyle(
        "body", parent=ss["Normal"], fontName=F_BASE, fontSize=9.5,
        leading=14, alignment=TA_JUSTIFY, spaceBefore=2, spaceAfter=6,
        textColor=colors.HexColor("#1a1a1a"),
    )
    styles["h1"] = ParagraphStyle(
        "h1", parent=ss["Heading1"], fontName=F_BOLD, fontSize=20,
        leading=24, textColor=NAVY, spaceBefore=0, spaceAfter=14,
    )
    styles["h2"] = ParagraphStyle(
        "h2", parent=ss["Heading2"], fontName=F_BOLD, fontSize=14,
        leading=18, textColor=NAVY, spaceBefore=16, spaceAfter=7,
    )
    styles["h3"] = ParagraphStyle(
        "h3", parent=ss["Heading3"], fontName=F_BOLD, fontSize=11.5,
        leading=15, textColor=BLUE, spaceBefore=12, spaceAfter=5,
    )
    styles["h4"] = ParagraphStyle(
        "h4", parent=ss["Heading4"], fontName=F_BOLDITALIC,
        fontSize=10, leading=13, textColor=GREY, spaceBefore=9, spaceAfter=3,
    )
    styles["bullet"] = ParagraphStyle(
        "bullet", parent=styles["body"], alignment=TA_LEFT, spaceAfter=3,
        leftIndent=14, bulletIndent=4,
    )
    styles["bullet2"] = ParagraphStyle(
        "bullet2", parent=styles["bullet"], leftIndent=30, bulletIndent=20,
        fontSize=9,
    )
    styles["ol"] = ParagraphStyle(
        "ol", parent=styles["body"], alignment=TA_LEFT, spaceAfter=3,
        leftIndent=20, bulletIndent=4,
    )
    styles["code"] = ParagraphStyle(
        "code", parent=ss["Code"], fontName=F_MONO, fontSize=8.2,
        leading=11, textColor=colors.HexColor("#111827"),
        backColor=CODEBG, borderPadding=(6, 6, 6, 6), spaceBefore=6,
        spaceAfter=8,
    )
    styles["note"] = ParagraphStyle(
        "note", parent=styles["body"], backColor=NOTEBG, borderColor=NOTEBAR,
        borderWidth=0, leftIndent=10, rightIndent=6, borderPadding=(6, 8, 6, 10),
        spaceBefore=6, spaceAfter=8, fontSize=9,
    )
    styles["tcell"] = ParagraphStyle(
        "tcell", parent=styles["body"], fontSize=8.3, leading=11,
        alignment=TA_LEFT, spaceBefore=0, spaceAfter=0,
    )
    styles["thead"] = ParagraphStyle(
        "thead", parent=styles["tcell"], fontName=F_BOLD,
        textColor=colors.white,
    )
    styles["cover_title"] = ParagraphStyle(
        "cover_title", parent=ss["Title"], fontName=F_BOLD,
        fontSize=30, leading=36, textColor=NAVY, alignment=TA_CENTER,
        spaceAfter=10,
    )
    styles["cover_sub"] = ParagraphStyle(
        "cover_sub", parent=ss["Normal"], fontName=F_BASE, fontSize=14,
        leading=20, textColor=GREY, alignment=TA_CENTER,
    )
    styles["cover_meta"] = ParagraphStyle(
        "cover_meta", parent=ss["Normal"], fontName=F_BASE, fontSize=10,
        leading=16, textColor=GREY, alignment=TA_CENTER,
    )
    styles["toc1"] = ParagraphStyle(
        "toc1", fontName=F_BOLD, fontSize=11, leading=18,
        textColor=NAVY,
    )
    styles["toc2"] = ParagraphStyle(
        "toc2", fontName=F_BASE, fontSize=9.5, leading=14,
        leftIndent=14, textColor=colors.HexColor("#333333"),
    )
    return styles


STYLES = build_styles()

# ─────────────────────────────────────────────────────────────────────────────
# Inline formatting
# ─────────────────────────────────────────────────────────────────────────────
def inline(text):
    """Convertit le markdown inline en balises mini-HTML de ReportLab."""
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    # code `...`
    text = re.sub(r"`([^`]+)`",
                  r'<font face="%s" size="8.5" backColor="#f4f5f7">\1</font>' % F_MONO,
                  text)
    # gras **...**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    # italique *...*
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", text)
    # liens [txt](url) -> txt (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'\1 (\2)', text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Parser Markdown -> flowables
# ─────────────────────────────────────────────────────────────────────────────
class DocBuilder:
    def __init__(self):
        self.story = []
        self.meta = {}
        self._h1_seen = False

    # -- helpers ------------------------------------------------------------
    def _bookmark(self, text, level):
        key = re.sub(r"\W+", "-", text.lower()).strip("-")
        return key

    def add_heading(self, text, level):
        style = STYLES[f"h{level}"]
        key = self._bookmark(text, level)
        frags = inline(text)
        if level == 1:
            if self._h1_seen:
                self.story.append(PageBreak())
            self._h1_seen = True
            self.story.append(HRFlowable(width="100%", thickness=2,
                                         color=NAVY, spaceAfter=8,
                                         spaceBefore=0))
        para = Paragraph(f'<a name="{key}"/>{frags}', style)
        para._toc_level = level
        # texte du sommaire : markdown retiré, pas d'interprétation de balises
        toc_text = text.replace("`", "").replace("**", "").replace("*", "")
        para._toc_text = toc_text
        para._toc_key = key
        self.story.append(para)
        if level == 1:
            self.story.append(HRFlowable(width="100%", thickness=0.75,
                                         color=BORDER, spaceAfter=10,
                                         spaceBefore=2))

    def add_paragraph(self, text):
        self.story.append(Paragraph(inline(text), STYLES["body"]))

    def add_bullet(self, text, level=1):
        st = STYLES["bullet"] if level == 1 else STYLES["bullet2"]
        bullet = "•" if level == 1 else "–"
        self.story.append(Paragraph(inline(text), st, bulletText=bullet))

    def add_ordered(self, text, num):
        self.story.append(Paragraph(inline(text), STYLES["ol"],
                                    bulletText=f"{num}."))

    def add_note(self, lines):
        joined = "<br/>".join(inline(l) for l in lines)
        self.story.append(Paragraph(joined, STYLES["note"]))

    def add_code(self, lines):
        safe = []
        for l in lines:
            l = (l.replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace(" ", "&nbsp;"))
            safe.append(l)
        self.story.append(Paragraph("<br/>".join(safe) or "&nbsp;",
                                    STYLES["code"]))

    def add_hr(self):
        self.story.append(HRFlowable(width="100%", thickness=0.75,
                                     color=BORDER, spaceBefore=6,
                                     spaceAfter=8))

    def add_table(self, rows):
        header, body = rows[0], rows[1:]
        ncols = len(header)
        data = [[Paragraph(inline(c), STYLES["thead"]) for c in header]]
        for r in body:
            r = (r + [""] * ncols)[:ncols]
            data.append([Paragraph(inline(c), STYLES["tcell"]) for c in r])

        avail = PAGE_W - 2 * MARGIN
        # largeur : première colonne un peu plus large si 2 colonnes
        col_w = [avail / ncols] * ncols
        t = Table(data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        self.story.append(Spacer(1, 2))
        self.story.append(t)
        self.story.append(Spacer(1, 8))

    # -- main parse -------------------------------------------------------
    def parse(self, text):
        lines = text.replace("\r\n", "\n").split("\n")
        i = 0
        n = len(lines)
        para_buf = []

        def flush_para():
            if para_buf:
                self.add_paragraph(" ".join(para_buf).strip())
                para_buf.clear()

        def _is_block_start(t):
            t = t.strip()
            return (not t or t.startswith("#") or t.startswith("```")
                    or t.startswith("|") or t.startswith(">")
                    or re.match(r"^(-{3,}|\*{3,}|_{3,})$", t)
                    or re.match(r"^[-*]\s", t) or re.match(r"^\d+\.\s", t))

        def gather_item(first, idx):
            """Recolle les lignes de continuation (repli doux) d'un élément."""
            parts = [first.strip()]
            while idx < n and lines[idx].strip() and not _is_block_start(lines[idx]):
                parts.append(lines[idx].strip())
                idx += 1
            return " ".join(parts), idx

        while i < n:
            line = lines[i]
            raw = line.rstrip()
            stripped = raw.strip()

            # métadonnées
            m = re.match(r"<!--\s*meta:(.+?)\s*-->", stripped)
            if m:
                for pair in m.group(1).split("|"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        self.meta[k.strip()] = v.strip()
                i += 1
                continue

            # commentaire
            if stripped.startswith("<!--"):
                i += 1
                continue

            # bloc de code
            if stripped.startswith("```"):
                flush_para()
                code_lines = []
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                i += 1
                self.add_code(code_lines)
                continue

            # ligne vide
            if not stripped:
                flush_para()
                i += 1
                continue

            # titres
            m = re.match(r"(#{1,4})\s+(.*)", stripped)
            if m:
                flush_para()
                self.add_heading(m.group(2).strip(), len(m.group(1)))
                i += 1
                continue

            # filet horizontal
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
                flush_para()
                self.add_hr()
                i += 1
                continue

            # citation / note
            if stripped.startswith(">"):
                flush_para()
                note_lines = []
                while i < n and lines[i].strip().startswith(">"):
                    note_lines.append(lines[i].strip()[1:].strip())
                    i += 1
                self.add_note(note_lines)
                continue

            # tableau
            if stripped.startswith("|") and i + 1 < n and re.match(
                    r"^\|?[\s:|-]+\|?$", lines[i + 1].strip()) and "-" in lines[i + 1]:
                flush_para()
                tbl = []
                header = [c.strip() for c in stripped.strip("|").split("|")]
                tbl.append(header)
                i += 2
                while i < n and lines[i].strip().startswith("|"):
                    row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    tbl.append(row)
                    i += 1
                self.add_table(tbl)
                continue

            # listes
            m = re.match(r"^(\s*)([-*])\s+(.*)", raw)
            if m:
                flush_para()
                indent = len(m.group(1))
                level = 2 if indent >= 2 else 1
                item, i = gather_item(m.group(3), i + 1)
                self.add_bullet(item, level)
                continue

            m = re.match(r"^(\s*)(\d+)\.\s+(.*)", raw)
            if m:
                flush_para()
                num = m.group(2)
                item, i = gather_item(m.group(3), i + 1)
                self.add_ordered(item, num)
                continue

            # paragraphe courant
            para_buf.append(stripped)
            i += 1

        flush_para()


# ─────────────────────────────────────────────────────────────────────────────
# Document (cover + TOC + corps), pagination
# ─────────────────────────────────────────────────────────────────────────────
class DocTemplate(BaseDocTemplate):
    def __init__(self, filename, meta, **kw):
        super().__init__(filename, pagesize=A4,
                         leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN + 6 * mm, bottomMargin=MARGIN,
                         title=meta.get("title", "Documentation"),
                         author=meta.get("org", "UniManager"))
        self.meta = meta
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="main")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self._cover_bg),
            PageTemplate(id="content", frames=[frame],
                         onPage=self._header_footer),
        ])

    def _cover_bg(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, PAGE_H - 4 * cm, PAGE_W, 4 * cm, fill=1, stroke=0)
        canvas.setFillColor(BLUE)
        canvas.rect(0, 0, PAGE_W, 1.2 * cm, fill=1, stroke=0)
        canvas.restoreState()

    def _header_footer(self, canvas, doc):
        canvas.saveState()
        # en-tête
        canvas.setFont(F_BASE, 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 2 * mm,
                          self.meta.get("title", ""))
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 2 * mm,
                               self.meta.get("org", ""))
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN)
        # pied de page
        canvas.line(MARGIN, MARGIN - 3 * mm, PAGE_W - MARGIN, MARGIN - 3 * mm)
        canvas.drawString(MARGIN, MARGIN - 9 * mm,
                          self.meta.get("footer", ""))
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 9 * mm,
                               f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if hasattr(flowable, "_toc_level"):
            lvl = flowable._toc_level
            if lvl <= 2:
                safe = (flowable._toc_text.replace("&", "&amp;")
                        .replace("<", "&lt;").replace(">", "&gt;"))
                self.notify("TOCEntry",
                            (lvl - 1, safe, self.page, flowable._toc_key))


def make_cover(meta):
    elems = [Spacer(1, 5.5 * cm)]
    elems.append(Paragraph(meta.get("title", "Documentation"),
                           STYLES["cover_title"]))
    if meta.get("subtitle"):
        elems.append(Spacer(1, 4 * mm))
        elems.append(Paragraph(meta["subtitle"], STYLES["cover_sub"]))
    elems.append(Spacer(1, 3 * cm))
    meta_bits = []
    if meta.get("org"):
        meta_bits.append(f"<b>{meta['org']}</b>")
    if meta.get("version"):
        meta_bits.append(f"Version&nbsp;{meta['version']}")
    meta_bits.append(meta.get("date", date.today().strftime("%d/%m/%Y")))
    elems.append(Paragraph("<br/>".join(meta_bits), STYLES["cover_meta"]))
    return elems


def make_toc():
    toc = TableOfContents()
    toc.levelStyles = [STYLES["toc1"], STYLES["toc2"]]
    heading = Paragraph("Sommaire", STYLES["h1"])
    return [heading,
            HRFlowable(width="100%", thickness=0.75, color=BORDER,
                       spaceAfter=12, spaceBefore=2),
            toc]


def build(src_path, out_path):
    with open(src_path, encoding="utf-8") as f:
        raw = f.read()

    b = DocBuilder()
    b.parse(raw)
    meta = {
        "title": "Documentation",
        "org": "UniManager",
        "footer": "Document interne — diffusion restreinte",
        "date": date.today().strftime("%d/%m/%Y"),
    }
    meta.update(b.meta)

    doc = DocTemplate(out_path, meta)

    story = []
    story += make_cover(meta)
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())
    story += make_toc()
    story.append(PageBreak())
    story += b.story

    doc.multiBuild(story)
    print(f"[OK] {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python build_pdf.py source.md sortie.pdf")
        sys.exit(1)
    build(sys.argv[1], sys.argv[2])
