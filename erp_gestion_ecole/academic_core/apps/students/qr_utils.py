"""Utilities for generating QR codes and student card PDFs."""
import io
import base64
import json

import qrcode
from PIL import Image

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from academic_core.pdf_utils import draw_watermark


# ── QR code helpers ───────────────────────────────────────────────────────────

def _make_qr_image(data: str, size_px: int = 200) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size_px, size_px), Image.LANCZOS)
    return img


def qr_image_to_base64(data: str, size_px: int = 200) -> str:
    """Return a base64-encoded PNG string suitable for <img src=data:...>."""
    img = _make_qr_image(data, size_px)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def student_qr_payload(student, enrollment=None) -> str:
    """JSON payload embedded in the student card QR code."""
    from django.utils import timezone

    today = timezone.now().date()
    months_status = {}

    if enrollment:
        for inst in enrollment.installments.order_by('due_date'):
            key = inst.due_date.strftime('%Y-%m')
            months_status[key] = 'paye' if inst.is_paid else 'impaye'

    # Determine current month status with grace period (10th)
    current_key = today.strftime('%Y-%m')
    if current_key in months_status:
        statut_mois = months_status[current_key]
    else:
        statut_mois = 'impaye'

    payload = {
        "type": "student",
        "id": student.pk,
        "mat": student.matricule,
        "nom": student.user.get_full_name(),
        "classe": enrollment.class_group.name if enrollment else "",
        "annee": str(enrollment.academic_year) if enrollment else "",
        "mois": months_status,
        "statut": statut_mois,
    }
    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False)


def student_qr_receipt_block(student, enrollment=None, size_mm=15,
                              caption="Vérification — QR Code carte étudiant"):
    """
    Flowables ReportLab (QR code de la carte étudiant + légende), à ajouter en
    bas des reçus de paiement PDF (inscription, mensualité, caisse) afin que le
    même QR code que celui de la carte d'apprenant y figure.

    Volontairement compact (taille + interlignage réduits) : ces reçus tiennent
    sur une seule page A5/A4 déjà bien remplie, et ce bloc doit y tenir sans
    faire déborder le contenu sur une deuxième page.
    """
    payload = student_qr_payload(student, enrollment)
    img = _make_qr_image(payload, size_px=300)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    size = size_mm * mm
    qr_img = RLImage(buf, width=size, height=size)
    qr_img.hAlign = "CENTER"

    # La légende est un flowable à part (pas une cellule de tableau large
    # comme le QR) afin qu'elle s'étale sur toute la largeur de la page et
    # ne se replie pas sur de nombreuses lignes, ce qui ferait déborder le
    # reçu sur une deuxième page.
    cap_style = ParagraphStyle(
        "qrReceiptCaption", fontSize=6, leading=7.2, alignment=TA_CENTER,
        textColor=colors.HexColor("#64748B"),
    )
    caption_para = Paragraph(f"{caption} — Mat. {student.matricule}", cap_style)

    return [Spacer(1, 4), qr_img, Spacer(1, 2), caption_para]


def session_qr_payload(sheet, base_url: str) -> str:
    """URL pointing to the student self-checkin endpoint."""
    return f"{base_url.rstrip('/')}/attendance/checkin/{sheet.session_qr_token}/"


def presence_card_payload(student) -> str:
    """Payload minimal encodé dans la carte présence de l'étudiant.
    Scanné par l'enseignant pour valider la présence à la séance active."""
    payload = {
        "type": "presence",
        "mat": student.matricule,
        "id": student.pk,
        "nom": student.user.get_full_name(),
        "genre": student.gender or "M",
    }
    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False)


# ── Payment status helper ─────────────────────────────────────────────────────

def _get_payment_status(student, enrollment):
    """
    Returns (is_valid: bool, label: str, detail: str).
    is_valid = True  → mois en cours payé (bande verte)
    is_valid = False → mois non payé après le 10 (bande rouge)
    """
    from django.utils import timezone

    today = timezone.now().date()
    grace_day = 10

    if not enrollment:
        return False, "INVALIDE", "Aucune inscription active"

    current_inst = enrollment.installments.filter(
        due_date__year=today.year,
        due_date__month=today.month,
    ).first()

    if current_inst and current_inst.is_paid:
        return True, "VALIDE", f"Mois de {today.strftime('%B %Y')} payé"

    # Grace period: before the 10th of the month, we allow
    if today.day <= grace_day and current_inst is None:
        # No installment recorded yet but still in grace
        last_paid = enrollment.installments.filter(is_paid=True).order_by('-due_date').first()
        if last_paid:
            return True, "VALIDE", f"Dernier paiement : {last_paid.due_date.strftime('%B %Y')}"

    # Non payé
    last_paid = enrollment.installments.filter(is_paid=True).order_by('-due_date').first()
    if last_paid:
        detail = f"Dernier paiement : {last_paid.due_date.strftime('%B %Y')}"
    else:
        detail = "Aucun paiement enregistré"
    return False, "INVALIDE", detail


# ── Card dimensions (CR-80 landscape) ────────────────────────────────────────

CARD_W = 85.6 * mm
CARD_H = 54 * mm

NAVY      = colors.HexColor("#0d2244")
NAVY2     = colors.HexColor("#1a3a6b")
SKY_BLUE  = colors.HexColor("#0ea5e9")   # bleu ciel principal
SKY_DARK  = colors.HexColor("#0369a1")   # bleu ciel foncé pour contraste
RED_ISI   = colors.HexColor("#cc0000")
BLUE_ISI  = colors.HexColor("#003399")
GREEN_OK  = colors.HexColor("#1a8c3e")
RED_KO    = colors.HexColor("#c0392b")
WHITE     = colors.white
GRAY      = colors.HexColor("#e0f2fe")   # bleu ciel très clair pour fond photo
DARK_GRAY = colors.HexColor("#1e293b")


def _wrap_text_lines(c, text, font_name, font_size, max_width, max_lines=2):
    """
    Découpe `text` en au plus `max_lines` lignes qui tiennent dans
    `max_width` (mesure réelle des glyphes via c.stringWidth), avec
    troncature « … » sur la dernière ligne si le texte est encore trop
    long — utilisé pour le nom de l'institut sur la carte, dont la longueur
    varie d'un institut à l'autre (contrairement à un texte figé sur 2 lignes).
    """
    words = (text or '').split()
    if not words:
        return []
    lines = []
    current = ''
    i = 0
    while i < len(words) and len(lines) < max_lines - 1:
        trial = (current + ' ' + words[i]).strip()
        if not current or c.stringWidth(trial, font_name, font_size) <= max_width:
            current = trial
            i += 1
        else:
            lines.append(current)
            current = ''
    remaining = (current + ' ' + ' '.join(words[i:])).strip()
    while remaining and c.stringWidth(remaining, font_name, font_size) > max_width:
        remaining = remaining[:-1]
    if remaining != (current + ' ' + ' '.join(words[i:])).strip() and remaining:
        remaining = remaining[:-1].rstrip() + '…'
    if remaining:
        lines.append(remaining)
    return lines[:max_lines]


# ── RECTO ─────────────────────────────────────────────────────────────────────

def _draw_recto(c, student, enrollment, inst_logo=None, inst_config=None):
    """Dessine le recto — mise en page fidèle à la carte physique ISI."""

    # ── Fond général blanc ─────────────────────────────────────────────────
    c.setFillColor(WHITE)
    c.rect(0, 0, CARD_W, CARD_H, fill=1, stroke=0)

    # ══════════════════════════════════════════════════════════════════════
    # EN-TÊTE (fond blanc, hauteur 14 mm)
    # ══════════════════════════════════════════════════════════════════════
    header_h = 14 * mm
    header_y = CARD_H - header_h

    # Fond en-tête blanc (déjà blanc, juste une légère séparation visuelle)
    c.setFillColor(WHITE)
    c.rect(0, header_y, CARD_W, header_h, fill=1, stroke=0)

    # ── Logo (haut gauche) ──────────────────────────────────────────────
    logo_w = 18 * mm
    logo_h = 13 * mm
    logo_x = 2 * mm
    logo_y = header_y + (header_h - logo_h) / 2

    if inst_logo:
        try:
            c.drawImage(
                ImageReader(inst_logo),
                logo_x, logo_y,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            inst_logo = None

    if not inst_logo:
        # Fallback texte style logo ISI
        c.setFillColor(SKY_DARK)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(logo_x, CARD_H - 7 * mm, "ISI")
        c.setFont("Helvetica-Bold", 5)
        c.drawString(logo_x, CARD_H - 10.5 * mm, "GROUPE")

    # ── Nom de l'école (centre-gauche après logo) — toujours celui de
    # l'institut réel de l'étudiant (jamais un nom figé) ────────────────
    school_x = logo_x + logo_w + 2 * mm
    school_max_w = CARD_W - school_x - 22 * mm  # laisse la place à "Carte d'apprenant" à droite
    c.setFillColor(DARK_GRAY)
    c.setFont("Helvetica-Bold", 5.5)
    inst_name = (inst_config.nom if inst_config and inst_config.nom else "Institut")
    name_lines = _wrap_text_lines(c, inst_name, "Helvetica-Bold", 5.5, school_max_w, max_lines=2)
    if name_lines:
        c.drawString(school_x, CARD_H - 5 * mm, name_lines[0])
    if len(name_lines) > 1:
        c.drawString(school_x, CARD_H - 8.5 * mm, name_lines[1])

    # ── Carte d'apprenant + année (haut droit) ────────────────────────
    c.setFillColor(DARK_GRAY)
    c.setFont("Helvetica-Bold", 5.5)
    c.drawRightString(CARD_W - 2 * mm, CARD_H - 5 * mm, "Carte d'apprenant")
    if enrollment:
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(SKY_DARK)
        c.drawRightString(CARD_W - 2 * mm, CARD_H - 10 * mm, str(enrollment.academic_year))

    # ══════════════════════════════════════════════════════════════════════
    # BANDE DÉCORATIVE (rouge / bleu / rouge — identique carte physique)
    # ══════════════════════════════════════════════════════════════════════
    stripe_y = header_y - 0.1 * mm
    c.setFillColor(RED_ISI)
    c.rect(0, stripe_y - 1.2 * mm, CARD_W, 1.2 * mm, fill=1, stroke=0)
    c.setFillColor(BLUE_ISI)
    c.rect(0, stripe_y - 2.0 * mm, CARD_W, 0.8 * mm, fill=1, stroke=0)
    c.setFillColor(RED_ISI)
    c.rect(0, stripe_y - 2.9 * mm, CARD_W, 0.9 * mm, fill=1, stroke=0)

    body_top = stripe_y - 3 * mm  # début de la zone infos

    # ══════════════════════════════════════════════════════════════════════
    # ZONE INFORMATIONS ÉTUDIANT
    # ══════════════════════════════════════════════════════════════════════
    footer_h = 8 * mm
    photo_w  = 19 * mm
    photo_h  = body_top - footer_h - 1 * mm
    photo_x  = CARD_W - photo_w - 2 * mm
    photo_y  = footer_h + 0.5 * mm

    info_x = 3 * mm
    info_max_w = photo_x - info_x - 1 * mm  # largeur disponible pour le texte
    info_y = body_top - 3 * mm

    # Programme (centré sur toute la largeur de la carte)
    if enrollment and enrollment.class_group.program:
        prog = enrollment.class_group.program.name
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(DARK_GRAY)
        if len(prog) > 32:
            prog = prog[:31] + "…"
        c.drawCentredString(CARD_W / 2, info_y, prog)
        info_y -= 4.2 * mm

    # Classe (centrée aussi)
    if enrollment:
        c.setFont("Helvetica", 6)
        c.setFillColor(DARK_GRAY)
        c.drawCentredString(CARD_W / 2, info_y, enrollment.class_group.name)
        info_y -= 4.5 * mm

    # Nom étudiant
    c.setFont("Helvetica", 5.5)
    c.setFillColor(DARK_GRAY)
    full_name = student.user.get_full_name()
    if len(full_name) > 30:
        full_name = full_name[:29] + "…"
    c.drawString(info_x, info_y, full_name)
    info_y -= 4 * mm

    # Matricule
    c.drawString(info_x, info_y, student.matricule)
    info_y -= 4 * mm

    # Date de naissance
    if student.date_of_birth:
        c.drawString(info_x, info_y, f"Né(e) le :  {student.date_of_birth.strftime('%d/%m/%Y')}")
        info_y -= 4 * mm

    # Lieu de naissance
    if student.place_of_birth:
        place = student.place_of_birth
        if len(place) > 24:
            place = place[:23] + "…"
        c.drawString(info_x, info_y, f"A :  {place}")

    # ══════════════════════════════════════════════════════════════════════
    # PHOTO (droite de la zone infos)
    # ══════════════════════════════════════════════════════════════════════
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)
    c.rect(photo_x, photo_y, photo_w, photo_h, fill=0, stroke=1)

    if student.photo:
        try:
            photo_buf = io.BytesIO(student.photo.read())
            pil_photo = Image.open(photo_buf).convert("RGB")
            tmp = io.BytesIO()
            pil_photo.save(tmp, format="JPEG")
            tmp.seek(0)
            c.drawImage(
                ImageReader(tmp),
                photo_x, photo_y,
                width=photo_w, height=photo_h,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass
        finally:
            try:
                student.photo.seek(0)
            except Exception:
                pass
    else:
        c.setFillColor(colors.HexColor("#f0f9ff"))
        c.rect(photo_x, photo_y, photo_w, photo_h, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#94a3b8"))
        c.setFont("Helvetica", 4)
        c.drawCentredString(photo_x + photo_w / 2, photo_y + photo_h / 2, "PHOTO")

    # ══════════════════════════════════════════════════════════════════════
    # FOOTER SOMBRE (contacts)
    # ══════════════════════════════════════════════════════════════════════
    c.setFillColor(NAVY)
    c.rect(0, 0, CARD_W, footer_h, fill=1, stroke=0)

    # Colonne gauche : adresse + tel — données réelles de l'institut de
    # l'étudiant (rien n'est affiché si l'institut n'a pas encore renseigné
    # ces informations, plutôt que d'afficher les coordonnées d'un autre
    # institut par défaut).
    adresse   = (inst_config.adresse if inst_config else '') or ''
    telephone = (inst_config.telephone if inst_config else '') or ''
    email     = (inst_config.email if inst_config else '') or ''
    site_web  = (inst_config.site_web if inst_config else '') or ''

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 4)
    if adresse:
        c.drawString(2 * mm, footer_h - 3 * mm, adresse.splitlines()[0][:45])
    if telephone:
        c.drawString(2 * mm, footer_h - 6 * mm, f"Tel: {telephone}")

    # Colonne droite : email + site
    if email:
        c.drawRightString(CARD_W - 2 * mm, footer_h - 3 * mm, f"E-Mail: {email}")
    if site_web:
        site_display = site_web.replace('https://', '').replace('http://', '').rstrip('/')
        c.drawRightString(CARD_W - 2 * mm, footer_h - 6 * mm, f"Site web: {site_display}")


# ── VERSO ─────────────────────────────────────────────────────────────────────

def _draw_verso(c, student, enrollment, inst_logo=None):
    """Dessine le verso de la carte d'étudiant : QR code + infos."""

    # Fond blanc
    c.setFillColor(WHITE)
    c.rect(0, 0, CARD_W, CARD_H, fill=1, stroke=0)

    # ── En-tête verso navy (même couleur que le footer du recto) ───────────
    header_h = 11 * mm
    c.setFillColor(NAVY)
    c.rect(0, CARD_H - header_h, CARD_W, header_h, fill=1, stroke=0)

    # Logo à gauche dans l'en-tête
    if inst_logo:
        try:
            c.drawImage(
                ImageReader(inst_logo),
                2 * mm, CARD_H - header_h + 1 * mm,
                width=9 * mm, height=9 * mm,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 6)
    c.drawCentredString(CARD_W / 2, CARD_H - 4.5 * mm, "Contrôle par QR Code")
    c.setFont("Helvetica", 4.5)
    c.drawCentredString(CARD_W / 2, CARD_H - 8.5 * mm, "Scanner pour vérifier le statut de paiement")

    # Ligne décorative sous l'en-tête
    c.setFillColor(SKY_BLUE)
    c.rect(0, CARD_H - header_h - 0.7 * mm, CARD_W, 0.7 * mm, fill=1, stroke=0)

    # ── QR Code (centré, grand) ────────────────────────────────────────────
    qr_payload = student_qr_payload(student, enrollment)
    qr_img = _make_qr_image(qr_payload, size_px=250)
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_buf.seek(0)

    qr_size = 32 * mm
    qr_x = (CARD_W - qr_size) / 2
    body_start = 7 * mm
    body_h = CARD_H - header_h - 0.7 * mm - body_start
    qr_y = body_start + (body_h - qr_size) / 2
    c.drawImage(
        ImageReader(qr_buf),
        qr_x, qr_y,
        width=qr_size, height=qr_size,
        preserveAspectRatio=True,
    )

    # ── Pied de page navy (même couleur que le recto) ──────────────────────
    footer_h = 7 * mm
    c.setFillColor(NAVY)
    c.rect(0, 0, CARD_W, footer_h, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 4.5)
    c.drawString(2 * mm, 4.5 * mm, student.matricule)
    if enrollment:
        c.drawString(2 * mm, 1.5 * mm, enrollment.class_group.name)

    phone = student.phone or ""
    if phone:
        c.drawRightString(CARD_W - 2 * mm, 4.5 * mm, f"Tel: {phone}")
    if enrollment:
        c.drawRightString(CARD_W - 2 * mm, 1.5 * mm, str(enrollment.academic_year))

    draw_watermark(c, CARD_W, y=3 * mm, font_size=3.5)


# ── Fonction principale ───────────────────────────────────────────────────────

def generate_student_card_pdf(student, enrollment, base_url: str, inst_logo=None, inst_config=None) -> bytes:
    """
    Génère un PDF recto/verso de la carte d'étudiant (format CB CR-80).
    `inst_config` (academic_structure.InstitutConfig) fournit le nom et les
    coordonnées réels de l'institut de l'étudiant — sans lui, le recto se
    limite à un intitulé générique plutôt que d'afficher les informations
    d'un autre institut par défaut.
    Returns raw PDF bytes.
    """
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(CARD_W, CARD_H))

    # Page 1 : RECTO
    _draw_recto(c, student, enrollment, inst_logo=inst_logo, inst_config=inst_config)
    c.showPage()

    # Page 2 : VERSO
    _draw_verso(c, student, enrollment, inst_logo=inst_logo)
    c.save()

    buf.seek(0)
    return buf.read()
