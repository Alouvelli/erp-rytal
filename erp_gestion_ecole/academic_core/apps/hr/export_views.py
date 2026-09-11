"""
Export PDF / Word des listes du module Ressources Humaines
(Gestion du personnel, Salaires, Bulletins de salaire, Présences/Absences,
Pointage du jour, Congés, Rapport mensuel de pointage).
"""
from datetime import date
from calendar import monthrange

from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import StaffPresence, DemandeConge, FichePersonnel, SalaireConfig, BulletinSalaire
from .views import _hr_required, _get_staff_queryset
from .export_utils import build_pdf_table_response, build_docx_table_response
from academic_core.pdf_utils import get_institut_config_for_request

MONTHS_FR = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
             'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def _fmt_amount(val):
    return f"{int(val):,}".replace(',', ' ') if val is not None else '—'


# ═══════════════════════════════════════════════════════════════════════════
# GESTION DU PERSONNEL
# ═══════════════════════════════════════════════════════════════════════════

def _personnel_headers_rows(request):
    staff_qs = _get_staff_queryset(request)
    fiches = {f.user_id: f for f in FichePersonnel.objects.filter(user__in=staff_qs)}
    headers = ['Nom & Prénom', 'Matricule', 'Rôle', 'Poste', 'Contrat', "Date d'embauche", 'Département / Direction']
    rows = []
    for emp in staff_qs:
        f = fiches.get(emp.pk)
        dept = emp.department.name if emp.department else (emp.direction.name if emp.direction else '—')
        rows.append([
            emp.get_full_name(),
            emp.matricule_employe or '—',
            emp.role.get_name_display() if emp.role else '—',
            f.poste if f and f.poste else '—',
            f.get_type_contrat_display() if f else '—',
            f.date_embauche.strftime('%d/%m/%Y') if f and f.date_embauche else '—',
            dept,
        ])
    return headers, rows


@login_required
@_hr_required
def personnel_pdf(request):
    headers, rows = _personnel_headers_rows(request)
    return build_pdf_table_response(
        "GESTION DU PERSONNEL", f"{len(rows)} employé(s)", headers, rows,
        "personnel", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def personnel_word(request):
    headers, rows = _personnel_headers_rows(request)
    return build_docx_table_response(
        "GESTION DU PERSONNEL", f"{len(rows)} employé(s)", headers, rows,
        "personnel", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# LISTE DES ENSEIGNANTS (par département)
# ═══════════════════════════════════════════════════════════════════════════

def _personnel_enseignants_headers_rows(request, department_id=None):
    staff_qs = _get_staff_queryset(request).filter(role__name='ENSEIGNANT')
    if department_id:
        staff_qs = staff_qs.filter(department_id=department_id)
    fiches = {f.user_id: f for f in FichePersonnel.objects.filter(user__in=staff_qs)}
    headers = ['Nom & Prénom', 'Matricule', 'Poste', 'Contrat', "Date d'embauche", 'Département']
    rows = []
    for emp in staff_qs:
        f = fiches.get(emp.pk)
        rows.append([
            emp.get_full_name(),
            emp.matricule_employe or '—',
            f.poste if f and f.poste else '—',
            f.get_type_contrat_display() if f else '—',
            f.date_embauche.strftime('%d/%m/%Y') if f and f.date_embauche else '—',
            emp.department.name if emp.department else '—',
        ])
    return headers, rows


def _dept_label(department_id):
    if not department_id:
        return ''
    from academic_core.apps.academic_structure.models import Department
    dept = Department.objects.filter(pk=department_id).first()
    return f" — {dept.name}" if dept else ''


@login_required
@_hr_required
def personnel_enseignants_pdf(request):
    department_id = request.GET.get('department_id') or None
    headers, rows = _personnel_enseignants_headers_rows(request, department_id)
    return build_pdf_table_response(
        f"LISTE DES ENSEIGNANTS{_dept_label(department_id)}", f"{len(rows)} enseignant(s)", headers, rows,
        "enseignants", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def personnel_enseignants_word(request):
    department_id = request.GET.get('department_id') or None
    headers, rows = _personnel_enseignants_headers_rows(request, department_id)
    return build_docx_table_response(
        f"LISTE DES ENSEIGNANTS{_dept_label(department_id)}", f"{len(rows)} enseignant(s)", headers, rows,
        "enseignants", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# GESTION DES SALAIRES
# ═══════════════════════════════════════════════════════════════════════════

def _salaire_headers_rows(request):
    staff_qs = _get_staff_queryset(request)
    configs = {c.user_id: c for c in SalaireConfig.objects.filter(user__in=staff_qs)}
    headers = ['Nom & Prénom', 'Rôle', 'Salaire de base', 'Primes', 'Retenues', 'Net', 'Statut']
    rows = []
    for emp in staff_qs:
        c = configs.get(emp.pk)
        rows.append([
            emp.get_full_name(),
            emp.role.get_name_display() if emp.role else '—',
            _fmt_amount(c.salaire_base) if c else '—',
            _fmt_amount(c.primes) if c else '—',
            _fmt_amount(c.retenues) if c else '—',
            _fmt_amount(c.salaire_net) if c else '—',
            ('Actif' if c.is_active else 'Inactif') if c else 'Non configuré',
        ])
    return headers, rows


@login_required
@_hr_required
def salaire_pdf(request):
    headers, rows = _salaire_headers_rows(request)
    return build_pdf_table_response(
        "GESTION DES SALAIRES", f"{len(rows)} employé(s)", headers, rows,
        "salaires", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def salaire_word(request):
    headers, rows = _salaire_headers_rows(request)
    return build_docx_table_response(
        "GESTION DES SALAIRES", f"{len(rows)} employé(s)", headers, rows,
        "salaires", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# BULLETINS DE SALAIRE (liste mensuelle)
# ═══════════════════════════════════════════════════════════════════════════

def _bulletin_headers_rows(request, year, month):
    staff_qs = _get_staff_queryset(request)
    bulletins = {
        b.user_id: b for b in BulletinSalaire.objects.filter(annee=year, mois=month, user__in=staff_qs)
    }
    headers = ['Nom & Prénom', 'Salaire de base', 'Primes', 'Retenues', 'Net à payer', 'Statut']
    rows = []
    for emp in staff_qs:
        b = bulletins.get(emp.pk)
        if not b:
            continue
        rows.append([
            emp.get_full_name(),
            _fmt_amount(b.salaire_base), _fmt_amount(b.primes), _fmt_amount(b.retenues),
            _fmt_amount(b.salaire_net), b.get_statut_display(),
        ])
    return headers, rows


@login_required
@_hr_required
def bulletin_list_pdf(request):
    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))
    headers, rows = _bulletin_headers_rows(request, year, month)
    return build_pdf_table_response(
        "BULLETINS DE SALAIRE", f"{MONTHS_FR[month]} {year} — {len(rows)} bulletin(s)", headers, rows,
        f"bulletins_{month:02d}_{year}", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def bulletin_list_word(request):
    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))
    headers, rows = _bulletin_headers_rows(request, year, month)
    return build_docx_table_response(
        "BULLETINS DE SALAIRE", f"{MONTHS_FR[month]} {year} — {len(rows)} bulletin(s)", headers, rows,
        f"bulletins_{month:02d}_{year}", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# LISTE DES PRÉSENCES / ABSENCES (mensuelle)
# ═══════════════════════════════════════════════════════════════════════════

def _presence_headers_rows(request, year, month, user_id):
    staff_qs = _get_staff_queryset(request)
    qs = StaffPresence.objects.filter(
        date__year=year, date__month=month, user__in=staff_qs,
    ).select_related('user__role').order_by('-date', 'user__last_name')
    if user_id:
        qs = qs.filter(user_id=user_id)

    headers = ['Date', 'Employé', 'Statut', 'Arrivée', 'Départ', 'Justification']
    rows = []
    for p in qs:
        rows.append([
            p.date.strftime('%d/%m/%Y'),
            p.user.get_full_name(),
            p.get_statut_display(),
            p.heure_arrivee.strftime('%H:%M') if p.heure_arrivee else '—',
            p.heure_depart.strftime('%H:%M') if p.heure_depart else '—',
            p.justification or '—',
        ])
    return headers, rows


@login_required
@_hr_required
def presence_pdf(request):
    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))
    user_id = request.GET.get('user_id', '')
    headers, rows = _presence_headers_rows(request, year, month, user_id)
    return build_pdf_table_response(
        "REGISTRE DES PRÉSENCES / ABSENCES", f"{MONTHS_FR[month]} {year} — {len(rows)} enregistrement(s)",
        headers, rows, f"presences_{month:02d}_{year}", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def presence_word(request):
    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))
    user_id = request.GET.get('user_id', '')
    headers, rows = _presence_headers_rows(request, year, month, user_id)
    return build_docx_table_response(
        "REGISTRE DES PRÉSENCES / ABSENCES", f"{MONTHS_FR[month]} {year} — {len(rows)} enregistrement(s)",
        headers, rows, f"presences_{month:02d}_{year}", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# POINTAGE DU JOUR
# ═══════════════════════════════════════════════════════════════════════════

def _pointage_jour_headers_rows(request, target_date):
    staff_qs = _get_staff_queryset(request)
    existing = {
        p.user_id: p
        for p in StaffPresence.objects.filter(date=target_date, user__in=staff_qs).select_related('user')
    }
    headers = ['Employé', 'Rôle', 'Statut', 'Arrivée', 'Départ']
    rows = []
    for emp in staff_qs:
        p = existing.get(emp.pk)
        rows.append([
            emp.get_full_name(),
            emp.role.get_name_display() if emp.role else '—',
            p.get_statut_display() if p else 'Non pointé',
            p.heure_arrivee.strftime('%H:%M') if p and p.heure_arrivee else '—',
            p.heure_depart.strftime('%H:%M') if p and p.heure_depart else '—',
        ])
    return headers, rows


def _parse_target_date(request):
    target_date_str = request.GET.get('date', '')
    try:
        return date.fromisoformat(target_date_str)
    except ValueError:
        return timezone.now().date()


@login_required
@_hr_required
def pointage_jour_pdf(request):
    target_date = _parse_target_date(request)
    headers, rows = _pointage_jour_headers_rows(request, target_date)
    return build_pdf_table_response(
        "FEUILLE DE POINTAGE", target_date.strftime('%d/%m/%Y'), headers, rows,
        f"pointage_{target_date.isoformat()}", orientation='portrait',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def pointage_jour_word(request):
    target_date = _parse_target_date(request)
    headers, rows = _pointage_jour_headers_rows(request, target_date)
    return build_docx_table_response(
        "FEUILLE DE POINTAGE", target_date.strftime('%d/%m/%Y'), headers, rows,
        f"pointage_{target_date.isoformat()}", orientation='portrait',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# CONGÉS
# ═══════════════════════════════════════════════════════════════════════════

def _conge_headers_rows(request, statut, user_id):
    staff_qs = _get_staff_queryset(request)
    qs = DemandeConge.objects.filter(user__in=staff_qs).select_related('user', 'valide_par').order_by('-created_at')
    if statut:
        qs = qs.filter(statut=statut)
    if user_id:
        qs = qs.filter(user_id=user_id)

    headers = ['Employé', 'Type', 'Début', 'Fin', 'Durée (j)', 'Statut', 'Traité par', 'Demandé le']
    rows = []
    for c in qs:
        rows.append([
            c.user.get_full_name(),
            c.get_type_conge_display(),
            c.date_debut.strftime('%d/%m/%Y'),
            c.date_fin.strftime('%d/%m/%Y'),
            c.nombre_jours,
            c.get_statut_display(),
            c.valide_par.get_full_name() if c.valide_par else '—',
            c.created_at.strftime('%d/%m/%Y'),
        ])
    return headers, rows


@login_required
@_hr_required
def conge_pdf(request):
    statut = request.GET.get('statut', '')
    user_id = request.GET.get('user_id', '')
    headers, rows = _conge_headers_rows(request, statut, user_id)
    return build_pdf_table_response(
        "DEMANDES DE CONGÉ", f"{len(rows)} demande(s)", headers, rows,
        "conges", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def conge_word(request):
    statut = request.GET.get('statut', '')
    user_id = request.GET.get('user_id', '')
    headers, rows = _conge_headers_rows(request, statut, user_id)
    return build_docx_table_response(
        "DEMANDES DE CONGÉ", f"{len(rows)} demande(s)", headers, rows,
        "conges", orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


# ═══════════════════════════════════════════════════════════════════════════
# RAPPORT MENSUEL DE POINTAGE
# ═══════════════════════════════════════════════════════════════════════════

def _rapport_mensuel_data(request):
    """Retourne (titre, sous_titre, headers, rows) pour le rapport mensuel."""
    from collections import defaultdict

    today = timezone.localdate()
    try:
        mois  = int(request.GET.get('mois',  today.month))
        annee = int(request.GET.get('annee', today.year))
    except (ValueError, TypeError):
        mois, annee = today.month, today.year
    mois  = max(1, min(12, mois))
    annee = max(2020, min(today.year + 1, annee))

    nb_days = monthrange(annee, mois)[1]
    jours_ouvres = sum(
        1 for d in range(1, nb_days + 1)
        if date(annee, mois, d).weekday() < 5
    )

    presences_qs = StaffPresence.objects.filter(
        date__year=annee, date__month=mois,
    ).select_related('user')

    par_employe = defaultdict(lambda: {'present': 0, 'retard': 0, 'absent': 0})
    for p in presences_qs:
        if p.statut == StaffPresence.STATUT_PRESENT:
            par_employe[p.user_id]['present'] += 1
        elif p.statut == StaffPresence.STATUT_RETARD:
            par_employe[p.user_id]['retard'] += 1
        elif p.statut == StaffPresence.STATUT_ABSENT:
            par_employe[p.user_id]['absent'] += 1

    staff_qs = _get_staff_queryset(request)
    headers = ['Nom & Prénom', 'Matricule', 'Rôle',
               'Jours ouvrés', 'Présences', 'Retards', 'Absences', 'Non enregistrés']
    rows = []
    for emp in staff_qs:
        stats = par_employe.get(emp.pk, {'present': 0, 'retard': 0, 'absent': 0})
        enr   = stats['present'] + stats['retard'] + stats['absent']
        rows.append([
            emp.get_full_name(),
            emp.matricule_employe or '—',
            emp.role.get_name_display() if emp.role else '—',
            jours_ouvres,
            stats['present'],
            stats['retard'],
            stats['absent'],
            max(0, jours_ouvres - enr),
        ])

    mois_label = MONTHS_FR[mois]
    titre      = f"RAPPORT MENSUEL DE POINTAGE — {mois_label} {annee}"
    sous_titre = f"{len(rows)} employé(s) · {jours_ouvres} jours ouvrés"
    return titre, sous_titre, headers, rows, f"rapport_pointage_{annee}_{mois:02d}"


@login_required
@_hr_required
def rapport_mensuel_pdf(request):
    titre, sous_titre, headers, rows, fname = _rapport_mensuel_data(request)
    return build_pdf_table_response(
        titre, sous_titre, headers, rows, fname,
        orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )


@login_required
@_hr_required
def rapport_mensuel_word(request):
    titre, sous_titre, headers, rows, fname = _rapport_mensuel_data(request)
    return build_docx_table_response(
        titre, sous_titre, headers, rows, fname,
        orientation='landscape',
        institut_config=get_institut_config_for_request(request),
    )
