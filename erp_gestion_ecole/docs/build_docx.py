#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Générateur de document Word (.docx) pour la documentation UniManager.

Convertit le même sous-ensemble Markdown que build_pdf.py en .docx à l'aide de
python-docx (aucune autre dépendance : ni pandoc, ni LibreOffice, ni Word).

Usage :
  python build_docx.py source.md sortie.docx
"""
import re
import sys
from datetime import date

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLUE = RGBColor(0x25, 0x63, 0xEB)
GREY = RGBColor(0x5B, 0x64, 0x72)
CODEBG = "F4F5F7"
HEADBG = "1F3A5F"
ALTBG = "EEF2F8"
NOTEBG = "FFF8E1"


# ─────────────────────────────────────────────────────────────────────────────
# Bas niveau
# ─────────────────────────────────────────────────────────────────────────────
def _shade(el, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    el.append(shd)


def _p_shade(paragraph, fill):
    _shade(paragraph.paragraph_format.element.get_or_add_pPr(), fill)


def _cell_shade(cell, fill):
    _shade(cell._tc.get_or_add_tcPr(), fill)


def _bottom_border(paragraph, size=6, color="C8D2E0"):
    pPr = paragraph.paragraph_format.element.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    pPr.append(pbdr)


def _field(paragraph, instr):
    """Insère un champ Word (ex: PAGE, TOC)."""
    run = paragraph.add_run()
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = instr
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    run._r.append(b); run._r.append(it); run._r.append(sep); run._r.append(end)


def _enable_update_fields(document):
    settings = document.settings.element
    el = OxmlElement("w:updateFields")
    el.set(qn("w:val"), "true")
    settings.append(el)


# ─────────────────────────────────────────────────────────────────────────────
# Inline
# ─────────────────────────────────────────────────────────────────────────────
# liens d'abord, puis gras, italique, code (le gras peut contenir du code)
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RULES = [
    ("bold", re.compile(r"\*\*(.+?)\*\*", re.S)),
    ("italic", re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")),
    ("code", re.compile(r"`([^`]+)`")),
]


def _emit(paragraph, text, bold, italic, code, base_size, base_color):
    if not text:
        return
    run = paragraph.add_run(text)
    if bold:
        run.bold = True
    if italic:
        run.italic = True
    if code:
        run.font.name = "Consolas"
        run.font.size = Pt(9)
    if base_size and not code:
        run.font.size = Pt(base_size)
    if base_color is not None:
        run.font.color.rgb = base_color


def add_inline(paragraph, text, base_size=None, base_color=None,
               bold=False, italic=False, code=False, _depth=0):
    text = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    if _depth > 60:
        _emit(paragraph, text, bold, italic, code, base_size, base_color)
        return
    for kind, rx in _RULES:
        m = rx.search(text)
        if not m:
            continue
        # préfixe / suffixe : n'incrémentent pas la profondeur (ils ne font
        # que raccourcir le texte) ; seul le contenu du marqueur imbrique.
        add_inline(paragraph, text[:m.start()], base_size, base_color,
                   bold, italic, code, _depth + 1)
        add_inline(paragraph, m.group(1), base_size, base_color,
                   bold or kind == "bold", italic or kind == "italic",
                   code or kind == "code", _depth + 1)
        add_inline(paragraph, text[m.end():], base_size, base_color,
                   bold, italic, code, _depth)
        return
    _emit(paragraph, text, bold, italic, code, base_size, base_color)


# ─────────────────────────────────────────────────────────────────────────────
# Construction
# ─────────────────────────────────────────────────────────────────────────────
class Builder:
    def __init__(self):
        self.doc = Document()
        self.meta = {}
        self._styled()

    def _styled(self):
        st = self.doc.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10.5)
        self.doc.styles["Normal"].paragraph_format.space_after = Pt(6)
        for name, size, color, bold in [
            ("Heading 1", 19, NAVY, True),
            ("Heading 2", 14, NAVY, True),
            ("Heading 3", 12, BLUE, True),
            ("Heading 4", 10.5, GREY, True),
        ]:
            s = self.doc.styles[name]
            s.font.name = "Calibri"
            s.font.size = Pt(size)
            s.font.color.rgb = color
            s.font.bold = bold

        sec = self.doc.sections[0]
        sec.page_width = Cm(21)
        sec.page_height = Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(2.3)
        sec.top_margin = sec.bottom_margin = Cm(2.2)

    # -- éléments -----------------------------------------------------------
    def heading(self, text, level):
        if level == 1:
            self.doc.add_page_break()
        p = self.doc.add_heading(level=level)
        add_inline(p, text)
        if level == 1:
            _bottom_border(p, size=12, color="1F3A5F")

    def paragraph(self, text):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        add_inline(p, text)

    def bullet(self, text, level=1):
        style = "List Bullet" if level == 1 else "List Bullet 2"
        try:
            p = self.doc.add_paragraph(style=style)
        except KeyError:
            p = self.doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Cm(1 + 0.6 * (level - 1))
        add_inline(p, text)

    def ordered(self, text):
        p = self.doc.add_paragraph(style="List Number")
        add_inline(p, text)

    def note(self, lines):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.right_indent = Cm(0.2)
        _p_shade(p, NOTEBG)
        for i, ln in enumerate(lines):
            if i:
                p.add_run().add_break()
            add_inline(p, ln)

    def code(self, lines):
        p = self.doc.add_paragraph()
        _p_shade(p, CODEBG)
        p.paragraph_format.left_indent = Cm(0.2)
        for i, ln in enumerate(lines):
            if i:
                p.add_run().add_break()
            r = p.add_run(ln if ln else "")
            r.font.name = "Consolas"
            r.font.size = Pt(8.5)

    def hr(self):
        p = self.doc.add_paragraph()
        _bottom_border(p)

    def table(self, rows):
        header, body = rows[0], rows[1:]
        ncols = len(header)
        t = self.doc.add_table(rows=1, cols=ncols)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.style = "Table Grid"
        t.autofit = True
        hdr = t.rows[0].cells
        for j, txt in enumerate(header):
            hdr[j].text = ""
            pr = hdr[j].paragraphs[0]
            add_inline(pr, txt)
            for run in pr.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                run.font.size = Pt(9)
            _cell_shade(hdr[j], HEADBG)
        for ridx, r in enumerate(body):
            r = (r + [""] * ncols)[:ncols]
            cells = t.add_row().cells
            for j, txt in enumerate(r):
                cells[j].text = ""
                pr = cells[j].paragraphs[0]
                add_inline(pr, txt)
                for run in pr.runs:
                    run.font.size = Pt(9)
                if ridx % 2 == 1:
                    _cell_shade(cells[j], ALTBG)
        self.doc.add_paragraph()

    # -- parse ------------------------------------------------------------
    def parse(self, text):
        lines = text.replace("\r\n", "\n").split("\n")
        i, n = 0, len(lines)
        buf = []

        def _is_block_start(t):
            t = t.strip()
            return (not t or t.startswith("#") or t.startswith("```")
                    or t.startswith("|") or t.startswith(">")
                    or re.match(r"^(-{3,}|\*{3,}|_{3,})$", t)
                    or re.match(r"^[-*]\s", t) or re.match(r"^\d+\.\s", t))

        def gather_item(first, idx):
            """Recolle les lignes de continuation (repli doux) d'un élément."""
            parts = [first.strip()]
            while idx < n and not _is_block_start(lines[idx]) and lines[idx].strip():
                parts.append(lines[idx].strip())
                idx += 1
            return " ".join(parts), idx

        def flush():
            if buf:
                self.paragraph(" ".join(buf).strip())
                buf.clear()

        while i < n:
            raw = lines[i].rstrip()
            s = raw.strip()

            m = re.match(r"<!--\s*meta:(.+?)\s*-->", s)
            if m:
                for pair in m.group(1).split("|"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        self.meta[k.strip()] = v.strip()
                i += 1
                continue
            if s.startswith("<!--"):
                i += 1
                continue

            if s.startswith("```"):
                flush()
                cl = []
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    cl.append(lines[i])
                    i += 1
                i += 1
                self.code(cl)
                continue

            if not s:
                flush()
                i += 1
                continue

            m = re.match(r"(#{1,4})\s+(.*)", s)
            if m:
                flush()
                self.heading(m.group(2).strip(), len(m.group(1)))
                i += 1
                continue

            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
                flush()
                self.hr()
                i += 1
                continue

            if s.startswith(">"):
                flush()
                nl = []
                while i < n and lines[i].strip().startswith(">"):
                    nl.append(lines[i].strip()[1:].strip())
                    i += 1
                self.note(nl)
                continue

            if s.startswith("|") and i + 1 < n and re.match(
                    r"^\|?[\s:|-]+\|?$", lines[i + 1].strip()) and "-" in lines[i + 1]:
                flush()
                tbl = [[c.strip() for c in s.strip("|").split("|")]]
                i += 2
                while i < n and lines[i].strip().startswith("|"):
                    tbl.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                    i += 1
                self.table(tbl)
                continue

            m = re.match(r"^(\s*)([-*])\s+(.*)", raw)
            if m:
                flush()
                lvl = 2 if len(m.group(1)) >= 2 else 1
                item, i = gather_item(m.group(3), i + 1)
                self.bullet(item, lvl)
                continue

            m = re.match(r"^(\s*)\d+\.\s+(.*)", raw)
            if m:
                flush()
                item, i = gather_item(m.group(2), i + 1)
                self.ordered(item)
                continue

            buf.append(s)
            i += 1
        flush()

    # -- assemblage ------------------------------------------------------
    def cover_and_toc(self):
        body = self.doc.element.body
        # tout ce qui a été ajouté va APRÈS cover+toc : on insère au début
        anchor = []

        title = self.doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.paragraph_format.space_before = Pt(160)
        r = title.add_run(self.meta.get("title", "Documentation"))
        r.bold = True
        r.font.size = Pt(28)
        r.font.color.rgb = NAVY
        anchor.append(title._p)

        if self.meta.get("subtitle"):
            sub = self.doc.add_paragraph()
            sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
            rr = sub.add_run(self.meta["subtitle"])
            rr.font.size = Pt(13)
            rr.font.color.rgb = GREY
            anchor.append(sub._p)

        meta_bits = []
        if self.meta.get("org"):
            meta_bits.append(self.meta["org"])
        if self.meta.get("version"):
            meta_bits.append("Version " + self.meta["version"])
        meta_bits.append(self.meta.get("date", date.today().strftime("%d/%m/%Y")))
        mp = self.doc.add_paragraph()
        mp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        mp.paragraph_format.space_before = Pt(220)
        for k, bit in enumerate(meta_bits):
            if k:
                mp.add_run().add_break()
            rr = mp.add_run(bit)
            rr.font.size = Pt(10)
            rr.font.color.rgb = GREY
        anchor.append(mp._p)

        pb = self.doc.add_paragraph()
        pb.add_run().add_break(WD_BREAK.PAGE)
        anchor.append(pb._p)

        toc_h = self.doc.add_heading("Sommaire", level=1)
        anchor.append(toc_h._p)
        toc_p = self.doc.add_paragraph()
        _field(toc_p, 'TOC \\o "1-2" \\h \\z \\u')
        anchor.append(toc_p._p)
        hint = self.doc.add_paragraph()
        hr = hint.add_run("(Sommaire : clic droit → « Mettre à jour les "
                          "champs » si les numéros ne s'affichent pas.)")
        hr.italic = True
        hr.font.size = Pt(8)
        hr.font.color.rgb = GREY
        anchor.append(hint._p)

        pb2 = self.doc.add_paragraph()
        pb2.add_run().add_break(WD_BREAK.PAGE)
        anchor.append(pb2._p)

        # déplacer ces éléments tout au début du corps
        for el in reversed(anchor):
            body.remove(el)
            body.insert(0, el)

    def footer(self):
        sec = self.doc.sections[0]
        p = sec.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(self.meta.get("footer", "") + "    —    Page ")
        _field(p, "PAGE")


def build(src, out):
    with open(src, encoding="utf-8") as f:
        raw = f.read()
    b = Builder()
    b.parse(raw)
    b.cover_and_toc()
    b.footer()
    _enable_update_fields(b.doc)
    b.doc.save(out)
    print(f"[OK] {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python build_docx.py source.md sortie.docx")
        sys.exit(1)
    build(sys.argv[1], sys.argv[2])
