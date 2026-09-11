import io
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models as db_models
from django.http import HttpResponse, FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import HourlyRate, PartenaireBourse
from .forms import HourlyRateForm, PartenaireBourseForm
from academic_core.apps.attendance.models import AttendanceSheet
from academic_core.apps.teachers.models import Teacher
from academic_core.apps.academic_structure.models import AcademicYear, Department


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_accounting_access(user):
    return (user.is_admin() or user.is_ciaq() or user.is_responsable()
            or user.is_controleur() or user.is_comptable())


def _require_rate_access(user):
    return user.can_manage_dept()


def _require_partenaire_bourse_access(user):
    """Le trésorier général gère les partenaires de bourse (+ admins par sécurité)."""
    return user.is_tresorier() or user.is_admin() or user.is_inst_admin()


def _get_sessions_for_month(year: int, month: int, teacher=None, department=None):
    """Retourne les feuilles validées pour un mois, avec calcul du montant."""
    qs = AttendanceSheet.objects.filter(
        status=AttendanceSheet.STATUS_VALIDATED,
        session_date__year=year,
        session_date__month=month,
    ).select_related(
        'timetable_entry__teacher__user',
        'timetable_entry__class_group__level',
        'timetable_entry__class_group__program__department',
        'timetable_entry__subject',
        'timetable_entry__semester__academic_year',
    ).order_by('timetable_entry__teacher__user__last_name', 'session_date')

    if teacher:
        qs = qs.filter(timetable_entry__teacher=teacher)
    if department:
        qs = qs.filter(timetable_entry__class_group__program__department=department)

    results = []
    for sheet in qs:
        entry = sheet.timetable_entry
        dept = entry.class_group.program.department
        level = entry.class_group.level
        acad_year = entry.semester.academic_year

        duration = Decimal(str(entry.duration_hours))
        try:
            rate_obj = HourlyRate.objects.get(
                department=dept, level=level, academic_year=acad_year
            )
            rate = rate_obj.rate_per_hour
            amount = rate_obj.amount_for_session(duration)
        except HourlyRate.DoesNotExist:
            rate = Decimal('0')
            amount = Decimal('0')

        from decimal import ROUND_HALF_UP
        impots = (amount * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        results.append({
            'sheet': sheet,
            'teacher': entry.teacher,
            'dept': dept,
            'level': level,
            'subject': entry.subject,
            'class_group': entry.class_group,
            'date': sheet.session_date,
            'hours': duration,
            'rate': rate,
            'amount': amount,
            'impots': impots,
            'net': amount - impots,
        })
    return results


def _group_by_teacher(sessions):
    """Regroupe les séances par enseignant et calcule les totaux."""
    groups = defaultdict(lambda: {
        'sessions': [], 'total': Decimal('0'),
        'total_impots': Decimal('0'), 'total_net': Decimal('0'),
        'total_hours': Decimal('0'),
        'teacher': None,
    })
    for s in sessions:
        key = s['teacher'].pk
        groups[key]['sessions'].append(s)
        groups[key]['total']        += s['amount']
        groups[key]['total_impots'] += s['impots']
        groups[key]['total_net']    += s['net']
        groups[key]['total_hours']  += s['hours']
        groups[key]['teacher'] = s['teacher']
    return dict(sorted(groups.items(), key=lambda x: x[1]['teacher'].user.last_name))


def _build_recap_by_dept(groups, grand_total):
    """
    À partir de groups (résultat de _group_by_teacher), construit une liste
    de dicts par département pour le tableau récapitulatif des exports.
    """
    dept_map = defaultdict(lambda: {
        'dept': None, 'teachers': [], 'seances': 0,
        'heures': Decimal('0'), 'total': Decimal('0'),
        'impots': Decimal('0'), 'net': Decimal('0'),
    })
    for g in groups.values():
        # Déduire le département depuis la première séance
        if not g['sessions']:
            continue
        dept = g['sessions'][0]['dept']
        dk = dept.pk
        dept_map[dk]['dept'] = dept
        dept_map[dk]['teachers'].append(g['teacher'].full_name)
        dept_map[dk]['seances'] += len(g['sessions'])
        dept_map[dk]['heures']  += g['total_hours']
        dept_map[dk]['total']   += g['total']
        dept_map[dk]['impots']  += g['total_impots']
        dept_map[dk]['net']     += g['total_net']

    result = list(dept_map.values())
    for r in result:
        r['pct'] = round(float(r['total']) / float(grand_total) * 100) if grand_total else 0
    return result


# ---------------------------------------------------------------------------
# Taux horaires — configuration
# ---------------------------------------------------------------------------

@login_required
def hourly_rate_list(request):
    if not _require_rate_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    dept = request.active_department
    if not dept:
        messages.warning(request, "Veuillez sélectionner un département.")
        return redirect('academic_structure:select_department')

    rates = HourlyRate.objects.filter(department=dept).select_related(
        'level', 'academic_year'
    ).order_by('-academic_year__start_date', 'level__order')
    return render(request, 'accounting/hourly_rate_list.html', {
        'rates': rates,
        'dept': dept,
    })


@login_required
def hourly_rate_create(request):
    if not _require_rate_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    dept = request.active_department
    if not dept:
        messages.warning(request, "Veuillez sélectionner un département.")
        return redirect('academic_structure:select_department')

    form = HourlyRateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        rate = form.save(commit=False)
        rate.department = dept
        rate.created_by = request.user
        rate.save()
        messages.success(request, "Taux horaire créé avec succès.")
        return redirect('accounting:rate_list')

    return render(request, 'accounting/hourly_rate_form.html', {
        'form': form, 'dept': dept, 'action': 'Créer',
    })


@login_required
def hourly_rate_edit(request, pk):
    if not _require_rate_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    rate = get_object_or_404(HourlyRate, pk=pk)
    form = HourlyRateForm(request.POST or None, instance=rate)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Taux horaire modifié avec succès.")
        return redirect('accounting:rate_list')

    return render(request, 'accounting/hourly_rate_form.html', {
        'form': form, 'rate': rate, 'dept': rate.department, 'action': 'Modifier',
    })


@login_required
def hourly_rate_delete(request, pk):
    if not _require_rate_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    rate = get_object_or_404(HourlyRate, pk=pk)
    if request.method == 'POST':
        rate.delete()
        messages.success(request, "Taux horaire supprimé.")
        return redirect('accounting:rate_list')

    return render(request, 'accounting/hourly_rate_confirm_delete.html', {'rate': rate})


# ---------------------------------------------------------------------------
# Budget honoraires mensuels (Direction Pédagogique)
# ---------------------------------------------------------------------------

def _can_view_all_departments_budget(user):
    """Directeur des Études (ou tout admin/direction plus large) : vue globale
    tous départements. Pas de helper is_admin_de() dédié dans le modèle User —
    ADMIN_DE n'est couvert par aucun des is_xxx() existants, d'où le check
    direct sur role_name (même esprit que _admissions_department_scope)."""
    role_name = user.role.name if user.role else ''
    return role_name == 'ADMIN_DE' or user.is_admin_direction() or user.is_admin() or user.is_inst_admin()


def _cycle_label(level_name):
    """Regroupement Licence/Master par préfixe du nom de niveau — Level n'a
    pas de champ « cycle » dédié dans ce système."""
    name = (level_name or '').strip().lower()
    if name.startswith('licence') or name.startswith('l1') or name.startswith('l2') or name.startswith('l3'):
        return 'PREMIER CYCLE'
    if name.startswith('master') or name.startswith('m1') or name.startswith('m2'):
        return 'SECOND CYCLE'
    return 'AUTRE'


def _build_budget_department_rows(dept, academic_year):
    """Une ligne par classe du département pour l'année donnée : taux (depuis
    HourlyRate), VHA, détail mensuel (volume + honoraires calculé), HT.
    Retourne (rows, all_months) — all_months est l'union chronologique des
    mois de toutes les classes, utilisée comme en-têtes de colonnes communes
    (une classe dont le calendrier ne couvre pas un mois donné affiche une
    cellule vide alignée sur cette même colonne plutôt que de décaler la
    grille)."""
    from academic_core.apps.academic_structure.models import Class
    from .models import HonoraireBudgetLine
    from .services import month_schedule_for, MOIS_FR, month_color

    classes = Class.objects.filter(
        program__department=dept, academic_year=academic_year
    ).select_related('level', 'program').order_by('level__order', 'name')

    lines_by_class = {
        l.class_group_id: l for l in
        HonoraireBudgetLine.objects.filter(department=dept, academic_year=academic_year)
        .prefetch_related('months')
    }
    rates_by_level = {
        r.level_id: r for r in
        HourlyRate.objects.filter(department=dept, academic_year=academic_year)
    }

    per_class = []
    all_months_set = set()
    for cls in classes:
        line = lines_by_class.get(cls.pk)
        months_map = {(m.year, m.month): m for m in line.months.all()} if line else {}
        rate = rates_by_level.get(cls.level_id)
        schedule = month_schedule_for(academic_year, cls)
        all_months_set.update(schedule)

        by_key = {}
        ht = Decimal('0')
        for (y, m) in schedule:
            month_row = months_map.get((y, m))
            volume = month_row.volume_heures if month_row else Decimal('0')
            honoraires = (volume * rate.rate_per_hour) if rate else None
            if honoraires:
                ht += honoraires
            by_key[(y, m)] = {
                'year': y, 'month': m, 'label': MOIS_FR[m],
                'volume': volume, 'honoraires': honoraires,
                'bg': month_color(m, 'bg'), 'header_color': month_color(m, 'header'),
            }

        per_class.append({
            'class_group': cls,
            'cycle': _cycle_label(cls.level.name if cls.level else ''),
            'rate': rate,
            'vha': line.vha if line else Decimal('0'),
            'by_key': by_key,
            'ht': ht,
        })

    all_months = sorted(all_months_set)
    rows = []
    for r in per_class:
        r['months'] = [r['by_key'].get((y, m)) for (y, m) in all_months]
        del r['by_key']
        rows.append(r)

    all_months_data = [
        {'year': y, 'month': m, 'label': MOIS_FR[m],
         'bg': month_color(m, 'bg'), 'header_color': month_color(m, 'header')}
        for (y, m) in all_months
    ]
    return rows, all_months_data


@login_required
def budget_honoraires_view(request):
    """
    Budget prévisionnel des honoraires mensuels (onglet Direction Pédagogique).
    - Chef de département : grille éditable pour son propre département.
    - Directeur des Études / admin : vue globale croisée départements × mois,
      avec bascule vers le détail d'un département (même mécanique que
      honoraires_annuels : absence du paramètre department -> département actif ;
      présence explicite -> respect du choix, vide = vue globale).
    """
    from academic_core.apps.academic_structure.models import Class
    from .models import HonoraireBudgetLine, HonoraireBudgetMonth
    from .services import month_schedule_for

    can_view_all = _can_view_all_departments_budget(request.user)
    if not (request.user.can_manage_dept() or can_view_all):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    academic_years = AcademicYear.objects.order_by('-start_date')
    acad_year_id = request.GET.get('academic_year')
    academic_year = (
        AcademicYear.objects.filter(pk=acad_year_id).first() if acad_year_id
        else academic_years.filter(is_current=True).first()
    )

    dept_id = request.GET.get('department')
    if dept_id is None and 'department' not in request.GET:
        dept_filter = getattr(request, 'active_department', None)
    else:
        dept_filter = Department.objects.filter(pk=dept_id).first() if dept_id else None

    if not dept_filter and not can_view_all:
        messages.warning(request, "Veuillez sélectionner un département.")
        return redirect('academic_structure:select_department')

    # ── Vue globale (Directeur des Études / admin, aucun département choisi) ──
    if not dept_filter:
        departments = Department.objects.filter(is_active=True).order_by('name')
        dept_summaries = []
        grand_total = Decimal('0')
        for dept in departments:
            rows, _months = _build_budget_department_rows(dept, academic_year) if academic_year else ([], [])
            dept_total = sum((r['ht'] for r in rows), Decimal('0'))
            grand_total += dept_total
            dept_summaries.append({'department': dept, 'total': dept_total, 'nb_classes': len(rows)})
        return render(request, 'accounting/budget_honoraires_global.html', {
            'academic_years': academic_years,
            'academic_year': academic_year,
            'dept_summaries': dept_summaries,
            'grand_total': grand_total,
        })

    # ── Vue département (chef de département, ou drill-down du DE) ──
    if request.method == 'POST':
        if not (request.user.can_manage_dept() and getattr(request, 'active_department', None) == dept_filter) and not can_view_all:
            messages.error(request, "Accès refusé.")
            return redirect('dashboard:index')
        if not academic_year:
            messages.error(request, "Année académique invalide.")
            return redirect('accounting:budget_honoraires')

        classes = Class.objects.filter(program__department=dept_filter, academic_year=academic_year)
        for cls in classes:
            vha_raw = request.POST.get(f'vha_{cls.pk}', '0').replace(',', '.').strip() or '0'
            try:
                vha_val = Decimal(vha_raw)
            except Exception:
                vha_val = Decimal('0')
            line, _ = HonoraireBudgetLine.objects.update_or_create(
                department=dept_filter, academic_year=academic_year, class_group=cls,
                defaults={'vha': vha_val, 'created_by': request.user},
            )
            for (y, m) in month_schedule_for(academic_year, cls):
                vol_raw = request.POST.get(f'vol_{cls.pk}_{y}_{m}', '0').replace(',', '.').strip() or '0'
                try:
                    vol_val = Decimal(vol_raw)
                except Exception:
                    vol_val = Decimal('0')
                HonoraireBudgetMonth.objects.update_or_create(
                    line=line, year=y, month=m, defaults={'volume_heures': vol_val},
                )
        try:
            sync_honoraires_budget_lines(academic_year)
        except Exception:
            pass  # le budget honoraires reste enregistré même si la synchro échoue
        messages.success(request, f"Budget honoraires enregistré pour {dept_filter.name}.")
        redirect_url = reverse('accounting:budget_honoraires')
        return redirect(f"{redirect_url}?department={dept_filter.pk}&academic_year={academic_year.pk}")

    rows, all_months = _build_budget_department_rows(dept_filter, academic_year) if academic_year else ([], [])
    dept_ht = sum((r['ht'] for r in rows), Decimal('0'))
    return render(request, 'accounting/budget_honoraires_detail.html', {
        'academic_years': academic_years,
        'academic_year': academic_year,
        'department': dept_filter,
        'rows': rows,
        'all_months': all_months,
        'dept_ht': dept_ht,
        'can_view_all': can_view_all,
        'cycle_row_colspan': 4 + 2 * len(all_months),
        'total_row_colspan': 3 + 2 * len(all_months),
    })


def _resolve_budget_honoraires_export_params(request):
    """Résout academic_year/department pour les exports Budget honoraires —
    lecture seule, même logique de résolution que budget_honoraires_view mais
    sans repli sur `active_department` (les exports sont toujours appelés
    avec des paramètres explicites depuis les boutons des templates)."""
    academic_years = AcademicYear.objects.order_by('-start_date')
    acad_year_id = request.GET.get('academic_year')
    academic_year = (
        AcademicYear.objects.filter(pk=acad_year_id).first() if acad_year_id
        else academic_years.filter(is_current=True).first()
    )
    dept_id = request.GET.get('department')
    dept_filter = Department.objects.filter(pk=dept_id).first() if dept_id else None
    return academic_year, dept_filter


HONORAIRES_MENSUELS_MATRICULE = '62260001'
HONORAIRES_ANNUELS_MATRICULE = '62260002'


def _get_or_create_honoraires_comptes():
    """Rubriques comptables « Honoraires mensuels/annuels enseignants » du
    budget de la Direction des Études — auto-provisionnées si absentes (elles
    ne le sont pas dans un institut qui vient d'être créé), pour que le
    Budget honoraires mensuels (Direction Pédagogique) ait toujours une
    rubrique où s'agréger, sans étape de configuration manuelle préalable."""
    from .models import CompteComptable
    mensuel, _c = CompteComptable.objects.get_or_create(
        matricule=HONORAIRES_MENSUELS_MATRICULE,
        defaults={
            'libelle': 'Honoraires mensuels enseignants',
            'classe': CompteComptable.CLASSE_6,
            'nature': CompteComptable.NATURE_CHARGE,
            'sens': CompteComptable.SENS_SORTIE,
        },
    )
    annuel, _c = CompteComptable.objects.get_or_create(
        matricule=HONORAIRES_ANNUELS_MATRICULE,
        defaults={
            'libelle': 'Honoraires annuels enseignants',
            'classe': CompteComptable.CLASSE_6,
            'nature': CompteComptable.NATURE_CHARGE,
            'sens': CompteComptable.SENS_SORTIE,
        },
    )
    return mensuel, annuel


def _get_or_create_default_source_financement():
    """Source de financement par défaut pour les rubriques honoraires
    auto-provisionnées — un institut fraîchement créé n'a généralement encore
    configuré aucune SourceFinancement ; sans repli, la synchronisation des
    rubriques honoraires resterait bloquée indéfiniment (LigneBudgetaire
    exige ce FK) alors que l'utilisateur a explicitement demandé que ces
    rubriques soient prises en compte même si rien n'est encore prévu."""
    from .models import SourceFinancement
    source = SourceFinancement.objects.filter(is_active=True).first()
    if source:
        return source
    return SourceFinancement.objects.create(
        code='frais-scolarite', libelle='Frais de scolarité',
        type_source=SourceFinancement.TYPE_FRAIS_SCOLARITE,
    )


def sync_honoraires_budget_lines(academic_year):
    """
    Maintient à jour, pour l'année académique donnée, les rubriques
    « Honoraires mensuels/annuels enseignants » du budget de la Direction des
    Études (accounting.LigneBudgetaire) — appelée automatiquement après
    chaque sauvegarde du Budget honoraires mensuels (prévu) et après chaque
    validation d'une feuille d'émargement (réalisé), pour rester "liée
    directement et automatiquement" comme demandé, sans étape manuelle.

    PRÉVU (montant_initial/montant_revise à la création) = total du Budget
    honoraires mensuels (HonoraireBudgetLine/Month, VHA × taux horaire),
    agrégé sur TOUS les départements de l'institut :
      - rubrique « mensuels » : total du MOIS EN COURS.
      - rubrique « annuels »  : total de l'année entière.

    RÉALISÉ (montant_execute) = somme des paiements enseignants RÉELLEMENT
    enregistrés (accounting.TeacherHonoraire, alimenté à la validation des
    feuilles d'émargement — voir services.py::record_honoraire), PAS calculée
    depuis DemandeDepense comme les autres rubriques du budget (voir
    budget_services.recompute_montant_execute) : ces deux rubriques
    spécifiques ne passent jamais par le circuit de demande de dépense
    manuelle, leur montant_execute est donc entretenu directement ici plutôt
    que par ce mécanisme — sans risque de conflit, puisqu'aucune
    DemandeDepense n'est jamais rattachée à ces rubriques précises.
    """
    from decimal import Decimal as _Decimal
    from django.db.models import Sum
    from django.utils import timezone as dj_timezone
    from academic_core.apps.students.services import get_direction_etudes
    from .models import LigneBudgetaire, TeacherHonoraire

    if not academic_year:
        return

    direction = get_direction_etudes()
    if not direction:
        return
    source = _get_or_create_default_source_financement()

    mensuel_compte, annuel_compte = _get_or_create_honoraires_comptes()
    today = dj_timezone.localdate()

    annuel_prevu = _Decimal('0')
    mensuel_prevu = _Decimal('0')
    for dept in Department.objects.filter(is_active=True):
        rows, _months = _build_budget_department_rows(dept, academic_year)
        for r in rows:
            annuel_prevu += r['ht']
            for cell in r['months']:
                if cell and cell['year'] == today.year and cell['month'] == today.month and cell['honoraires']:
                    mensuel_prevu += cell['honoraires']

    annuel_realise = TeacherHonoraire.objects.filter(
        academic_year=academic_year,
    ).aggregate(total=Sum('amount'))['total'] or _Decimal('0')
    mensuel_realise = TeacherHonoraire.objects.filter(
        academic_year=academic_year, session_date__year=today.year, session_date__month=today.month,
    ).aggregate(total=Sum('amount'))['total'] or _Decimal('0')

    NOTE = (
        "Rubrique alimentée automatiquement depuis le Budget honoraires mensuels "
        "(Direction Pédagogique) : prévu recalculé à chaque modification du budget "
        "honoraires, réalisé recalculé depuis les paiements enseignants effectifs "
        "(TeacherHonoraire) — indépendant des demandes de dépense."
    )
    for compte, prevu, realise in (
        (mensuel_compte, mensuel_prevu, mensuel_realise),
        (annuel_compte, annuel_prevu, annuel_realise),
    ):
        ligne, created = LigneBudgetaire.objects.get_or_create(
            academic_year=academic_year, direction=direction,
            compte_comptable=compte, source_financement=source,
            defaults={
                'montant_initial': prevu, 'montant_revise': prevu,
                'montant_execute': realise, 'notes': NOTE,
            },
        )
        if not created:
            ligne.montant_initial = prevu
            ligne.montant_execute = realise
            ligne.save(update_fields=['montant_initial', 'montant_execute'])


def _budget_honoraires_global_summaries(academic_year):
    departments = Department.objects.filter(is_active=True).order_by('name')
    dept_summaries = []
    grand_total = Decimal('0')
    for dept in departments:
        rows, _months = _build_budget_department_rows(dept, academic_year) if academic_year else ([], [])
        dept_total = sum((r['ht'] for r in rows), Decimal('0'))
        grand_total += dept_total
        dept_summaries.append({'department': dept, 'total': dept_total, 'nb_classes': len(rows)})
    return dept_summaries, grand_total


@login_required
def budget_honoraires_export_excel(request):
    if not (request.user.can_manage_dept() or _can_view_all_departments_budget(request.user)):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    academic_year, dept_filter = _resolve_budget_honoraires_export_params(request)
    if not academic_year:
        messages.error(request, "Année académique invalide.")
        return redirect('accounting:budget_honoraires')

    navy, mid, green = "00173B", "1E3A5F", "DCFCE7"
    thin = Side(style='thin', color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    wb = openpyxl.Workbook()
    ws = wb.active

    if dept_filter:
        ws.title = dept_filter.code[:31]
        rows, all_months = _build_budget_department_rows(dept_filter, academic_year)
        dept_ht = sum((r['ht'] for r in rows), Decimal('0'))
        ncols = 4 + 2 * len(all_months)
        end_col = get_column_letter(ncols)

        ws.merge_cells(f'A1:{end_col}1')
        ws['A1'] = f"Budget honoraires mensuels — {dept_filter.name} — {academic_year.label}"
        ws['A1'].font = Font(bold=True, color="FFFFFF", size=13)
        ws['A1'].fill = PatternFill("solid", fgColor=navy)
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 26

        col = 1
        for h, w in [('Classe', 26), ('TAUX (FCFA/h)', 14), ('VHA', 12)]:
            c = ws.cell(row=3, column=col, value=h)
            c.font = Font(bold=True, color="FFFFFF", size=9)
            c.fill = PatternFill("solid", fgColor=mid)
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.border = border
            ws.merge_cells(start_row=3, start_column=col, end_row=4, end_column=col)
            ws.column_dimensions[get_column_letter(col)].width = w
            col += 1
        for m in all_months:
            m_bg, m_hdr = m['bg'].lstrip('#'), m['header_color'].lstrip('#')
            ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + 1)
            c = ws.cell(row=3, column=col, value=f"{m['label']} {m['year']}")
            c.font = Font(bold=True, color="1E293B", size=9)
            c.fill = PatternFill("solid", fgColor=m_hdr)
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.border = border
            ws.cell(row=3, column=col + 1).fill = PatternFill("solid", fgColor=m_hdr)
            ws.cell(row=3, column=col + 1).border = border
            cv = ws.cell(row=4, column=col, value='Vol. h')
            cv.font = Font(bold=True, size=8)
            cv.fill = PatternFill("solid", fgColor=m_bg)
            cv.border = border
            ch = ws.cell(row=4, column=col + 1, value='Honoraires')
            ch.font = Font(bold=True, size=8, color="166534")
            ch.fill = PatternFill("solid", fgColor=m_bg)
            ch.border = border
            ws.column_dimensions[get_column_letter(col)].width = 10
            ws.column_dimensions[get_column_letter(col + 1)].width = 13
            col += 2
        c = ws.cell(row=3, column=col, value='HT (FCFA)')
        c.font = Font(bold=True, color="FFFFFF", size=9)
        c.fill = PatternFill("solid", fgColor=mid)
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = border
        ws.merge_cells(start_row=3, start_column=col, end_row=4, end_column=col)
        ws.column_dimensions[get_column_letter(col)].width = 14
        ht_col = col

        rownum = 5
        for r in rows:
            ws.cell(row=rownum, column=1, value=r['class_group'].name).border = border
            rate_cell = ws.cell(row=rownum, column=2, value=float(r['rate'].rate_per_hour) if r['rate'] else None)
            rate_cell.border = border
            rate_cell.alignment = Alignment(horizontal='right')
            vha_cell = ws.cell(row=rownum, column=3, value=float(r['vha']))
            vha_cell.border = border
            vha_cell.alignment = Alignment(horizontal='right')
            col = 4
            for cell in r['months']:
                if cell:
                    c1 = ws.cell(row=rownum, column=col, value=float(cell['volume']))
                    c1.fill = PatternFill("solid", fgColor=cell['bg'].lstrip('#'))
                    c1.border = border
                    c1.alignment = Alignment(horizontal='right')
                    c2 = ws.cell(row=rownum, column=col + 1,
                                 value=float(cell['honoraires']) if cell['honoraires'] is not None else None)
                    c2.fill = PatternFill("solid", fgColor=cell['bg'].lstrip('#'))
                    c2.font = Font(color="166534")
                    c2.border = border
                    c2.alignment = Alignment(horizontal='right')
                    c2.number_format = '#,##0'
                col += 2
            c = ws.cell(row=rownum, column=ht_col, value=float(r['ht']))
            c.font = Font(bold=True, color="166534")
            c.border = border
            c.alignment = Alignment(horizontal='right')
            c.number_format = '#,##0'
            rownum += 1

        c = ws.cell(row=rownum, column=1, value=f"TOTAL {dept_filter.name.upper()}")
        ws.merge_cells(start_row=rownum, start_column=1, end_row=rownum, end_column=ht_col - 1)
        c.font = Font(bold=True, color="166534")
        c.fill = PatternFill("solid", fgColor=green)
        c.alignment = Alignment(horizontal='right')
        c2 = ws.cell(row=rownum, column=ht_col, value=float(dept_ht))
        c2.font = Font(bold=True, color="166534")
        c2.fill = PatternFill("solid", fgColor=green)
        c2.number_format = '#,##0'
        filename = f"budget_honoraires_{dept_filter.code}_{academic_year.label}.xlsx".replace(' ', '_')
    else:
        ws.title = "Budget honoraires — Global"
        dept_summaries, grand_total = _budget_honoraires_global_summaries(academic_year)

        ws.merge_cells('A1:C1')
        ws['A1'] = f"Budget honoraires mensuels — Vue globale — {academic_year.label}"
        ws['A1'].font = Font(bold=True, color="FFFFFF", size=13)
        ws['A1'].fill = PatternFill("solid", fgColor=navy)
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 26

        hdrs = [('Département', 40), ('Classes budgétées', 18), ('Total honoraires (FCFA)', 22)]
        for i, (h, w) in enumerate(hdrs, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = Font(bold=True, color="FFFFFF", size=9)
            c.fill = PatternFill("solid", fgColor=mid)
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.border = border
            ws.column_dimensions[get_column_letter(i)].width = w

        rownum = 4
        for d in dept_summaries:
            ws.cell(row=rownum, column=1, value=f"{d['department'].code} — {d['department'].name}").border = border
            nc = ws.cell(row=rownum, column=2, value=d['nb_classes'])
            nc.border = border
            nc.alignment = Alignment(horizontal='center')
            c = ws.cell(row=rownum, column=3, value=float(d['total']))
            c.font = Font(color="166534", bold=True)
            c.border = border
            c.alignment = Alignment(horizontal='right')
            c.number_format = '#,##0'
            rownum += 1

        c = ws.cell(row=rownum, column=1, value="TOTAL GÉNÉRAL")
        ws.merge_cells(start_row=rownum, start_column=1, end_row=rownum, end_column=2)
        c.font = Font(bold=True, color="166534")
        c.fill = PatternFill("solid", fgColor=green)
        c.alignment = Alignment(horizontal='right')
        c2 = ws.cell(row=rownum, column=3, value=float(grand_total))
        c2.font = Font(bold=True, color="166534")
        c2.fill = PatternFill("solid", fgColor=green)
        c2.number_format = '#,##0'
        filename = f"budget_honoraires_global_{academic_year.label}.xlsx".replace(' ', '_')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def budget_honoraires_export_pdf(request):
    if not (request.user.can_manage_dept() or _can_view_all_departments_budget(request.user)):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from reportlab.lib.pagesizes import A3, A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    academic_year, dept_filter = _resolve_budget_honoraires_export_params(request)
    if not academic_year:
        messages.error(request, "Année académique invalide.")
        return redirect('accounting:budget_honoraires')

    navy = colors.HexColor('#00173B')
    green = colors.HexColor('#166534')
    green_bg = colors.HexColor('#DCFCE7')

    buf = io.BytesIO()

    def _title(text):
        return Paragraph(text, ParagraphStyle('t', fontSize=13, textColor=navy, alignment=TA_CENTER, spaceAfter=8))

    story = []
    if dept_filter:
        doc = SimpleDocTemplate(buf, pagesize=landscape(A3), leftMargin=0.8 * cm, rightMargin=0.8 * cm,
                                 topMargin=0.8 * cm, bottomMargin=0.8 * cm)
        rows, all_months = _build_budget_department_rows(dept_filter, academic_year)
        dept_ht = sum((r['ht'] for r in rows), Decimal('0'))
        story.append(_title(f"Budget honoraires mensuels — {dept_filter.name} — {academic_year.label}"))

        header_row1 = ['Classe', 'TAUX', 'VHA']
        header_row2 = ['', '', '']
        span_cmds = [
            ('SPAN', (0, 0), (0, 1)), ('SPAN', (1, 0), (1, 1)), ('SPAN', (2, 0), (2, 1)),
        ]
        month_bg_cmds = []
        col = 3
        for m in all_months:
            header_row1 += [f"{m['label']} {m['year']}", '']
            header_row2 += ['Vol. h', 'Honoraires']
            span_cmds.append(('SPAN', (col, 0), (col + 1, 0)))
            month_bg_cmds.append(('BACKGROUND', (col, 0), (col + 1, 1), colors.HexColor(m['bg'])))
            col += 2
        header_row1.append('HT')
        header_row2.append('')
        span_cmds.append(('SPAN', (col, 0), (col, 1)))

        data = [header_row1, header_row2]
        for r in rows:
            row = [r['class_group'].name,
                   f"{r['rate'].rate_per_hour:,.0f}".replace(',', ' ') if r['rate'] else '—',
                   f"{r['vha']:,.0f}".replace(',', ' ')]
            for cell in r['months']:
                if cell:
                    row.append(f"{cell['volume']:,.0f}".replace(',', ' '))
                    row.append(f"{cell['honoraires']:,.0f}".replace(',', ' ') if cell['honoraires'] is not None else '—')
                else:
                    row += ['', '']
            row.append(f"{r['ht']:,.0f}".replace(',', ' '))
            data.append(row)
        data.append([f"TOTAL {dept_filter.name.upper()}"] + [''] * (len(header_row1) - 2) + [f"{dept_ht:,.0f}".replace(',', ' ')])

        n_months = len(all_months)
        col_widths = [4.5 * cm, 2 * cm, 2 * cm] + [1.6 * cm, 2 * cm] * n_months + [2.2 * cm]
        t = Table(data, colWidths=col_widths, repeatRows=2)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 1), navy), ('TEXTCOLOR', (0, 0), (-1, 1), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 7), ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, -1), (-1, -1), green_bg), ('TEXTCOLOR', (0, -1), (-1, -1), green),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('SPAN', (0, -1), (-2, -1)), ('ALIGN', (0, -1), (0, -1), 'RIGHT'),
        ] + span_cmds + month_bg_cmds
        t.setStyle(TableStyle(style_cmds))
        story.append(t)
        filename = f"budget_honoraires_{dept_filter.code}_{academic_year.label}.pdf".replace(' ', '_')
    else:
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                                 topMargin=1.2 * cm, bottomMargin=1.2 * cm)
        dept_summaries, grand_total = _budget_honoraires_global_summaries(academic_year)
        story.append(_title(f"Budget honoraires mensuels — Vue globale — {academic_year.label}"))
        data = [['Département', 'Classes budgétées', 'Total honoraires (FCFA)']]
        for d in dept_summaries:
            data.append([f"{d['department'].code} — {d['department'].name}", str(d['nb_classes']),
                         f"{d['total']:,.0f}".replace(',', ' ')])
        data.append(['TOTAL GÉNÉRAL', '', f"{grand_total:,.0f}".replace(',', ' ')])
        t = Table(data, colWidths=[9 * cm, 4 * cm, 5 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), navy), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5), ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'), ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), green_bg), ('TEXTCOLOR', (0, -1), (-1, -1), green),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('SPAN', (0, -1), (1, -1)),
        ]))
        story.append(t)
        filename = f"budget_honoraires_global_{academic_year.label}.pdf".replace(' ', '_')

    doc.build(story)
    buf.seek(0)
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def budget_honoraires_export_word(request):
    if not (request.user.can_manage_dept() or _can_view_all_departments_budget(request.user)):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    academic_year, dept_filter = _resolve_budget_honoraires_export_params(request)
    if not academic_year:
        messages.error(request, "Année académique invalide.")
        return redirect('accounting:budget_honoraires')

    def _shd(cell, hex_color):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color.lstrip('#'))
        tcPr.append(shd)

    def _wc(cell, text, bold=False, size=8, color='000000', align='center'):
        cell.text = ''
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if align == 'center' else WD_ALIGN_PARAGRAPH.RIGHT
        run = p.add_run(str(text))
        run.bold = bold
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor.from_string(color)

    doc = Document()

    if dept_filter:
        sec = doc.sections[0]
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = Cm(42), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(0.8)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(f"Budget honoraires mensuels — {dept_filter.name} — {academic_year.label}")
        run.bold = True
        run.font.size = Pt(13)
        run.font.color.rgb = RGBColor.from_string('00173B')

        rows, all_months = _build_budget_department_rows(dept_filter, academic_year)
        dept_ht = sum((r['ht'] for r in rows), Decimal('0'))
        n_months = len(all_months)
        ncols = 4 + 2 * n_months
        table = doc.add_table(rows=2 + len(rows) + 1, cols=ncols)
        table.style = 'Table Grid'

        r0, r1 = table.rows[0], table.rows[1]
        for i, h in enumerate(['Classe', 'TAUX', 'VHA']):
            r0.cells[i].merge(r1.cells[i])
            _wc(r0.cells[i], h, bold=True, color='FFFFFF')
            _shd(r0.cells[i], '1E3A5F')
        ci = 3
        for m in all_months:
            r0.cells[ci].merge(r0.cells[ci + 1])
            _wc(r0.cells[ci], f"{m['label']} {m['year']}", bold=True)
            _shd(r0.cells[ci], m['header_color'])
            _wc(r1.cells[ci], 'Vol. h', bold=True, size=7)
            _shd(r1.cells[ci], m['bg'])
            _wc(r1.cells[ci + 1], 'Honoraires', bold=True, size=7, color='166534')
            _shd(r1.cells[ci + 1], m['bg'])
            ci += 2
        r0.cells[ci].merge(r1.cells[ci])
        _wc(r0.cells[ci], 'HT', bold=True, color='FFFFFF')
        _shd(r0.cells[ci], '1E3A5F')

        for idx, r in enumerate(rows):
            tr = table.rows[2 + idx]
            _wc(tr.cells[0], r['class_group'].name, align='left', size=7.5)
            _wc(tr.cells[1], f"{r['rate'].rate_per_hour:,.0f}".replace(',', ' ') if r['rate'] else '—', size=7.5)
            _wc(tr.cells[2], f"{r['vha']:,.0f}".replace(',', ' '), size=7.5)
            ci = 3
            for cell in r['months']:
                if cell:
                    _wc(tr.cells[ci], f"{cell['volume']:,.0f}".replace(',', ' '), size=7.5)
                    _shd(tr.cells[ci], cell['bg'])
                    honor_txt = f"{cell['honoraires']:,.0f}".replace(',', ' ') if cell['honoraires'] is not None else '—'
                    _wc(tr.cells[ci + 1], honor_txt, size=7.5, color='166534')
                    _shd(tr.cells[ci + 1], cell['bg'])
                ci += 2
            _wc(tr.cells[ci], f"{r['ht']:,.0f}".replace(',', ' '), bold=True, size=7.5, color='166534')

        total_tr = table.rows[-1]
        total_tr.cells[0].merge(total_tr.cells[ncols - 2])
        _wc(total_tr.cells[0], f"TOTAL {dept_filter.name.upper()}", bold=True, align='right', color='166534')
        for c in [total_tr.cells[0]]:
            _shd(c, 'DCFCE7')
        _wc(total_tr.cells[ncols - 1], f"{dept_ht:,.0f}".replace(',', ' '), bold=True, color='166534')
        _shd(total_tr.cells[ncols - 1], 'DCFCE7')

        filename = f"budget_honoraires_{dept_filter.code}_{academic_year.label}.docx".replace(' ', '_')
    else:
        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(f"Budget honoraires mensuels — Vue globale — {academic_year.label}")
        run.bold = True
        run.font.size = Pt(13)
        run.font.color.rgb = RGBColor.from_string('00173B')

        dept_summaries, grand_total = _budget_honoraires_global_summaries(academic_year)
        table = doc.add_table(rows=1 + len(dept_summaries) + 1, cols=3)
        table.style = 'Table Grid'
        for i, h in enumerate(['Département', 'Classes budgétées', 'Total honoraires (FCFA)']):
            _wc(table.rows[0].cells[i], h, bold=True, color='FFFFFF')
            _shd(table.rows[0].cells[i], '1E3A5F')
        for idx, d in enumerate(dept_summaries):
            tr = table.rows[1 + idx]
            _wc(tr.cells[0], f"{d['department'].code} — {d['department'].name}", align='left', size=9)
            _wc(tr.cells[1], d['nb_classes'], size=9)
            _wc(tr.cells[2], f"{d['total']:,.0f}".replace(',', ' '), bold=True, color='166534', size=9)
        total_tr = table.rows[-1]
        total_tr.cells[0].merge(total_tr.cells[1])
        _wc(total_tr.cells[0], 'TOTAL GÉNÉRAL', bold=True, align='right', color='166534')
        _shd(total_tr.cells[0], 'DCFCE7')
        _wc(total_tr.cells[2], f"{grand_total:,.0f}".replace(',', ' '), bold=True, color='166534')
        _shd(total_tr.cells[2], 'DCFCE7')

        filename = f"budget_honoraires_global_{academic_year.label}.docx".replace(' ', '_')

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Partenaires de bourse (Trésorier Général)
# ---------------------------------------------------------------------------

@login_required
def partenaire_bourse_list(request):
    if not _require_partenaire_bourse_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    partenaires = PartenaireBourse.objects.all().order_by('code')
    return render(request, 'accounting/partenaire_bourse_list.html', {
        'partenaires': partenaires,
    })


@login_required
def partenaire_bourse_create(request):
    if not _require_partenaire_bourse_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    form = PartenaireBourseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        partenaire = form.save(commit=False)
        partenaire.created_by = request.user
        partenaire.save()
        messages.success(request, f"Partenaire de bourse « {partenaire.code} » créé avec succès.")
        return redirect('accounting:partenaire_bourse_list')

    return render(request, 'accounting/partenaire_bourse_form.html', {
        'form': form, 'action': 'Créer',
    })


@login_required
def partenaire_bourse_edit(request, pk):
    if not _require_partenaire_bourse_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    partenaire = get_object_or_404(PartenaireBourse, pk=pk)
    form = PartenaireBourseForm(request.POST or None, instance=partenaire)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Partenaire de bourse modifié avec succès.")
        return redirect('accounting:partenaire_bourse_list')

    return render(request, 'accounting/partenaire_bourse_form.html', {
        'form': form, 'partenaire': partenaire, 'action': 'Modifier',
    })


@login_required
def partenaire_bourse_delete(request, pk):
    if not _require_partenaire_bourse_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    partenaire = get_object_or_404(PartenaireBourse, pk=pk)
    if request.method == 'POST':
        partenaire.delete()
        messages.success(request, "Partenaire de bourse supprimé.")
        return redirect('accounting:partenaire_bourse_list')

    return render(request, 'accounting/partenaire_bourse_confirm_delete.html', {'partenaire': partenaire})


# ---------------------------------------------------------------------------
# Tableau de bord comptabilité (admin + CIAQ)
# ---------------------------------------------------------------------------

@login_required
def accounting_dashboard(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from collections import defaultdict
    from .models import TeacherHonoraire

    today = timezone.now().date()
    try:
        year  = int(request.GET.get('year',  today.year))
        month = int(request.GET.get('month', today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month
    month = max(1, min(12, month))
    teacher_id = request.GET.get('teacher')
    dept_id    = request.GET.get('department')

    teacher_filter = Teacher.objects.filter(pk=teacher_id).first() if teacher_id else None
    # Si 'department' absent (première visite) → pré-filtrer par active_department.
    # Si présent mais vide (?department=) → "Tous les départements" explicite, ne pas surcharger.
    if dept_id is None and 'department' not in request.GET:
        active_dept = getattr(request, 'active_department', None)
        dept_filter = active_dept
    else:
        dept_filter = Department.objects.filter(pk=dept_id).first() if dept_id else None

    # ── Source : TeacherHonoraire (source de vérité post-validation) ──────────
    qs = TeacherHonoraire.objects.filter(
        session_date__year=year,
        session_date__month=month,
    ).select_related(
        'teacher__user', 'department', 'academic_year',
        'attendance_sheet__timetable_entry__subject',
        'attendance_sheet__timetable_entry__class_group__level',
    ).order_by('department__name', 'teacher__user__last_name', 'session_date')

    # Pas de filtre par faculté/département actif : la vue comptabilité est globale
    # (cumul de tous les départements de l'établissement)
    if teacher_filter:
        qs = qs.filter(teacher=teacher_filter)
    if dept_filter:
        qs = qs.filter(department=dept_filter)

    # ── Regroupement par département ──────────────────────────────────────────
    by_dept = defaultdict(lambda: {
        'dept': None, 'teachers': defaultdict(lambda: {'teacher': None, 'rows': [], 'subtotal': Decimal('0'), 'subtotal_hours': Decimal('0')}),
        'dept_total': Decimal('0'),
    })
    grand_total   = Decimal('0')
    grand_impots  = Decimal('0')
    grand_net     = Decimal('0')
    grand_heures  = Decimal('0')
    total_seances = 0

    for h in qs:
        dk = h.department.pk
        tk = h.teacher.pk
        by_dept[dk]['dept'] = h.department
        by_dept[dk]['teachers'][tk]['teacher'] = h.teacher
        by_dept[dk]['teachers'][tk]['rows'].append(h)
        by_dept[dk]['teachers'][tk]['subtotal']        += h.amount
        by_dept[dk]['teachers'][tk]['subtotal_hours']  += Decimal(str(h.duration_hours or 0))
        by_dept[dk]['teachers'][tk]['subtotal_impots']  = by_dept[dk]['teachers'][tk].get('subtotal_impots', Decimal('0')) + h.impots
        by_dept[dk]['teachers'][tk]['subtotal_net']     = by_dept[dk]['teachers'][tk].get('subtotal_net', Decimal('0')) + h.net_a_payer
        by_dept[dk]['dept_total'] += h.amount
        grand_total   += h.amount
        grand_impots  += h.impots
        grand_net     += h.net_a_payer
        grand_heures  += Decimal(str(h.duration_hours or 0))
        total_seances += 1

        # Synthèse des heures par niveau (LMD), pour la colonne SYNTHESE.
        try:
            niveau = h.attendance_sheet.timetable_entry.class_group.level
            niveau_name = str(niveau) if niveau else 'Niveau non précisé'
        except Exception:
            niveau_name = 'Niveau non précisé'
        hpn = by_dept[dk]['teachers'][tk].setdefault('heures_par_niveau', defaultdict(lambda: Decimal('0')))
        hpn[niveau_name] += Decimal(str(h.duration_hours or 0))

    # Convertir les defaultdicts internes en dicts ordinaires
    by_dept_final = {}
    total_teachers = 0
    for dk, ddata in by_dept.items():
        teachers_final = {}
        dept_seances = 0
        for tk, td in ddata['teachers'].items():
            teachers_final[tk] = dict(td)
            teachers_final[tk]['subtotal_hours'] = float(td.get('subtotal_hours', Decimal('0')))
            teachers_final[tk]['phone'] = (td['teacher'].user.phone if td.get('teacher') else '') or '—'
            teachers_final[tk]['heures_par_niveau'] = {
                niveau: float(h) for niveau, h in sorted(td.get('heures_par_niveau', {}).items())
            }
            dept_seances += len(td.get('rows', []))
            total_teachers += 1
        by_dept_final[dk] = {
            'dept':         ddata['dept'],
            'teachers':     teachers_final,
            'dept_total':   ddata['dept_total'],
            'dept_seances': dept_seances,
            'dept_heures':  float(sum(td.get('subtotal_hours', Decimal('0')) for td in ddata['teachers'].values())),
            'dept_impots':  sum(td.get('subtotal_impots', Decimal('0')) for td in ddata['teachers'].values()),
            'dept_net':     sum(td.get('subtotal_net', Decimal('0')) for td in ddata['teachers'].values()),
        }

    months = [
        (1, 'Janvier'), (2, 'Février'), (3, 'Mars'), (4, 'Avril'),
        (5, 'Mai'), (6, 'Juin'), (7, 'Juillet'), (8, 'Août'),
        (9, 'Septembre'), (10, 'Octobre'), (11, 'Novembre'), (12, 'Décembre'),
    ]
    teachers    = Teacher.objects.select_related('user').order_by('user__last_name')
    departments = Department.objects.filter(is_active=True).order_by('name')

    return render(request, 'accounting/dashboard.html', {
        'by_dept':        by_dept_final,
        'grand_total':    grand_total,
        'grand_impots':   grand_impots,
        'grand_net':      grand_net,
        'total_seances':  total_seances,
        'total_teachers': total_teachers,
        'grand_heures':   float(grand_heures),
        'year':           year,
        'month':          month,
        'month_name':     dict(months).get(month, ''),
        'months':         months,
        'years':          range(today.year - 3, today.year + 2),
        'teachers':       teachers,
        'departments':    departments,
        'teacher_filter': teacher_filter,
        'dept_filter':    dept_filter,
    })


# ---------------------------------------------------------------------------
# Édition / Suppression d'un honoraire (admin département)
# ---------------------------------------------------------------------------

def _require_honoraire_edit(user):
    """Seuls admin, responsable, contrôleur et ciaq peuvent modifier/supprimer un honoraire."""
    return (user.is_admin() or user.is_responsable() or user.is_controleur()
            or user.is_ciaq() or user.is_inst_admin())


@login_required
def honoraire_edit(request, pk):
    """Modifier le taux, la durée ou la date d'un honoraire existant."""
    from .models import TeacherHonoraire
    honoraire = get_object_or_404(TeacherHonoraire, pk=pk)

    if not _require_honoraire_edit(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:dashboard')

    today = timezone.now().date()
    back_url = (f"?month={honoraire.session_date.month}"
                f"&year={honoraire.session_date.year}"
                f"&department={honoraire.department_id}")

    if request.method == 'POST':
        try:
            session_date   = request.POST.get('session_date')
            duration_hours = Decimal(request.POST.get('duration_hours', '0').replace(',', '.'))
            rate_per_hour  = Decimal(request.POST.get('rate_per_hour',  '0').replace(',', '.'))
            if duration_hours <= 0 or rate_per_hour <= 0:
                raise ValueError("Durée et taux doivent être > 0")
            amount = (duration_hours * rate_per_hour).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            honoraire.session_date   = session_date
            honoraire.duration_hours = duration_hours
            honoraire.rate_per_hour  = rate_per_hour
            honoraire.amount         = amount
            honoraire.save()
            messages.success(request, f"Honoraire mis à jour : {amount} FCFA.")
        except Exception as e:
            messages.error(request, f"Erreur : {e}")
        return redirect(f'/accounting/{back_url}')

    months = [
        (1, 'Janvier'), (2, 'Février'), (3, 'Mars'), (4, 'Avril'),
        (5, 'Mai'), (6, 'Juin'), (7, 'Juillet'), (8, 'Août'),
        (9, 'Septembre'), (10, 'Octobre'), (11, 'Novembre'), (12, 'Décembre'),
    ]
    return render(request, 'accounting/honoraire_edit.html', {
        'honoraire': honoraire,
        'back_url':  f'/accounting/{back_url}',
        'months':    months,
    })


@login_required
def honoraire_delete(request, pk):
    """Supprimer un honoraire."""
    from .models import TeacherHonoraire
    honoraire = get_object_or_404(TeacherHonoraire, pk=pk)

    if not _require_honoraire_edit(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:dashboard')

    back_url = (f"/accounting/?month={honoraire.session_date.month}"
                f"&year={honoraire.session_date.year}"
                f"&department={honoraire.department_id}")

    if request.method == 'POST':
        teacher_name = honoraire.teacher.full_name
        honoraire.delete()
        messages.success(request, f"Honoraire de {teacher_name} supprimé.")
        return redirect(back_url)

    return render(request, 'accounting/honoraire_delete_confirm.html', {
        'honoraire': honoraire,
        'back_url':  back_url,
    })


# ---------------------------------------------------------------------------
# Vue annuelle des honoraires
# ---------------------------------------------------------------------------

@login_required
def honoraires_annuels(request):
    """
    Tableau de bord annuel des honoraires.
    - Sans département : tableau croisé années × départements
    - Avec département : vue focalisée sur ce département (global + par mois)
    """
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import TeacherHonoraire
    from django.db.models import Sum, Count

    MONTHS_FR = {
        1: 'Janvier', 2: 'Février',  3: 'Mars',      4: 'Avril',
        5: 'Mai',     6: 'Juin',     7: 'Juillet',    8: 'Août',
        9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre',
    }

    academic_years = AcademicYear.objects.order_by('-start_date')
    departments    = Department.objects.filter(is_active=True).order_by('name')

    acad_year_id = request.GET.get('academic_year')
    dept_id      = request.GET.get('department')

    # Année académique : par défaut l'année en cours — "Toutes les années"
    # (academic_year=all) reste disponible pour le tableau croisé historique.
    if acad_year_id == 'all':
        acad_year_filter = None
    elif acad_year_id:
        acad_year_filter = AcademicYear.objects.filter(pk=acad_year_id).first()
    else:
        acad_year_filter = academic_years.filter(is_current=True).first()
    if dept_id is None and 'department' not in request.GET:
        active_dept = getattr(request, 'active_department', None)
        dept_filter = active_dept
    else:
        dept_filter = Department.objects.filter(pk=dept_id).first() if dept_id else None

    # QuerySet de base — TOUS les honoraires, tous départements confondus
    qs_all = TeacherHonoraire.objects.select_related(
        'academic_year', 'department', 'teacher__user'
    )
    # QuerySet filtré selon les sélections utilisateur
    qs = qs_all
    if acad_year_filter:
        qs = qs.filter(academic_year=acad_year_filter)
    if dept_filter:
        qs = qs.filter(department=dept_filter)

    # ─────────────────────────────────────────────────────────────────────────
    # Breakdown mensuel : toujours calculé (pour 1 ou tous les départements)
    # ─────────────────────────────────────────────────────────────────────────
    def _build_monthly_data(base_qs):
        """
        Retourne une liste de dicts :
          [{dept, dept_total, dept_seances, dept_heures,
            years: [{year_id, year_label, total, seances, heures,
                     months: [{month_label, total, seances, heures, teachers}]}]}]
        """
        monthly_qs = list(
            base_qs.values(
                'department__id', 'department__name', 'department__code',
                'academic_year__id', 'academic_year__label', 'academic_year__start_date',
                'session_date__year', 'session_date__month',
            )
            .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
            .order_by('department__name', '-academic_year__start_date',
                      'session_date__year', 'session_date__month')
        )

        teacher_monthly_qs = list(
            base_qs.values(
                'department__id', 'academic_year__id',
                'session_date__year', 'session_date__month',
                'teacher__id',
                'teacher__user__first_name', 'teacher__user__last_name',
            )
            .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
            .order_by('teacher__user__last_name')
        )

        # {dept_id: {year_id: {(sy,sm): [teachers]}}}
        t_map = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for r in teacher_monthly_qs:
            t_map[r['department__id']][r['academic_year__id']][
                (r['session_date__year'], r['session_date__month'])
            ].append(r)

        # Regrouper par dept → year → month
        dept_year_month = defaultdict(lambda: defaultdict(list))
        dept_meta = {}
        for row in monthly_qs:
            did = row['department__id']
            yid = row['academic_year__id']
            dept_meta[did] = {
                'id': did, 'name': row['department__name'], 'code': row['department__code']
            }
            mn = row['session_date__month']
            sy = row['session_date__year']
            teachers = t_map[did][yid][(sy, mn)]
            _mtotal = row['total'] or Decimal('0')
            _mimp   = (_mtotal * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            dept_year_month[did][yid].append({
                'month_num':   mn,
                'month_year':  sy,
                'month_label': f"{MONTHS_FR.get(mn, mn)} {sy}",
                'total':       _mtotal,
                'impots':      _mimp,
                'net':         _mtotal - _mimp,
                'seances':     row['seances'] or 0,
                'heures':      row['heures'] or Decimal('0'),
                'teachers':    sorted(teachers, key=lambda t: t['teacher__user__last_name']),
                'academic_year_id': yid,
                'academic_year_label': row['academic_year__label'],
                'academic_year_start_date': row['academic_year__start_date'],
            })

        # Totaux par dept × année
        year_totals_qs = list(
            base_qs.values(
                'department__id', 'department__name',
                'academic_year__id', 'academic_year__label',
                'academic_year__start_date',
            )
            .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
            .order_by('department__name', '-academic_year__start_date')
        )

        dept_year_totals = defaultdict(list)
        for yt in year_totals_qs:
            did = yt['department__id']
            yid = yt['academic_year__id']
            _ytotal = yt['total'] or Decimal('0')
            _yimp   = (_ytotal * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            dept_year_totals[did].append({

                'year_id':    yid,
                'year_label': yt['academic_year__label'],
                'total':      _ytotal,
                'impots':     _yimp,
                'net':        _ytotal - _yimp,
                'seances':    yt['seances'] or 0,
                'heures':     yt['heures'] or Decimal('0'),
                'months':     dept_year_month[did].get(yid, []),
            })

        result = []
        for did, meta in sorted(dept_meta.items(), key=lambda x: x[1]['name']):
            years = dept_year_totals[did]
            dept_total   = sum(y['total']   for y in years)
            dept_seances = sum(y['seances'] for y in years)
            dept_heures  = sum(y['heures']  for y in years)
            dept_imp     = sum(y['impots']  for y in years)
            dept_net     = sum(y['net']     for y in years)
            result.append({
                'dept':          meta,
                'dept_total':    dept_total,
                'dept_impots':   dept_imp,
                'dept_net':      dept_net,
                'dept_seances':  dept_seances,
                'dept_heures':   dept_heures,
                'years':         years,
            })
        return result

    # Calculer le breakdown mensuel selon le filtre actif
    dept_monthly_data = _build_monthly_data(qs)
    # Pour la vue globale (onglet tableau croisé), toujours sur qs_matrix (sans filtre dept)
    all_dept_monthly = None  # sera rempli plus bas après construction de qs_matrix

    # ─────────────────────────────────────────────────────────────────────────
    # VUE GLOBALE : tableau croisé années × départements
    # ─────────────────────────────────────────────────────────────────────────
    # Toujours calculé sur qs (filtré par année si sélectionnée, tous depts)
    qs_matrix = qs_all
    if acad_year_filter:
        qs_matrix = qs_matrix.filter(academic_year=acad_year_filter)

    by_year = list(
        qs_matrix.values('academic_year__id', 'academic_year__label')
          .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
          .order_by('-academic_year__start_date')
    )

    by_dept_year_qs = list(
        qs_matrix.values(
            'academic_year__id', 'academic_year__label',
            'department__id',    'department__name', 'department__code',
        )
        .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
        .order_by('-academic_year__start_date', 'department__name')
    )

    by_teacher_qs = list(
        qs_matrix.values(
            'academic_year__id', 'department__id',
            'teacher__id',
            'teacher__user__first_name', 'teacher__user__last_name',
        )
        .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
        .order_by('teacher__user__last_name')
    )

    matrix_raw = defaultdict(dict)
    for row in by_dept_year_qs:
        matrix_raw[row['academic_year__id']][row['department__id']] = row

    teacher_map = defaultdict(lambda: defaultdict(dict))
    for row in by_teacher_qs:
        teacher_map[row['academic_year__id']][row['department__id']][row['teacher__id']] = row

    year_order = list(
        qs_matrix.values('academic_year__id', 'academic_year__label', 'academic_year__start_date')
          .distinct().order_by('-academic_year__start_date')
    )

    matrix_rows = []
    for yr in year_order:
        yid = yr['academic_year__id']
        cells = []
        row_total = row_seances = row_heures = Decimal('0')
        for dept in departments:
            cell = matrix_raw[yid].get(dept.pk)
            if cell:
                row_total   += cell['total']   or Decimal('0')
                row_seances += cell['seances'] or 0
                row_heures  += cell['heures']  or Decimal('0')
            teachers_detail = sorted(
                teacher_map[yid][dept.pk].values(),
                key=lambda r: r['teacher__user__last_name']
            )
            cells.append({'dept': dept, 'data': cell, 'teachers': teachers_detail})
        matrix_rows.append({
            'year_id':     yid,
            'year_label':  yr['academic_year__label'],
            'cells':       cells,
            'row_total':   row_total,
            'row_seances': int(row_seances),
            'row_heures':  row_heures,
        })

    grand_total   = sum(r['row_total']   for r in matrix_rows)
    grand_seances = sum(r['row_seances'] for r in matrix_rows)
    grand_heures  = sum(r['row_heures']  for r in matrix_rows)
    grand_impots  = (grand_total * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    grand_net     = grand_total - grand_impots

    dept_totals = {}
    for dept in departments:
        dept_totals[dept.pk] = sum(
            (matrix_raw[yr['academic_year__id']].get(dept.pk, {}).get('total') or Decimal('0'))
            for yr in year_order
        )

    # Breakdown mensuel global (tous depts, pour vue "Tableau croisé" sans filtre dept)
    all_dept_monthly = _build_monthly_data(qs_matrix)

    # Totaux stats cards
    stats_qs = qs if dept_filter else qs_matrix
    stats = stats_qs.aggregate(
        total_amount=Sum('amount'),
        total_seances=Count('id'),
        total_heures=Sum('duration_hours'),
    )

    return render(request, 'accounting/honoraires_annuels.html', {
        'matrix_rows':       matrix_rows,
        'departments':       departments,
        'dept_totals':       dept_totals,
        'grand_total':       grand_total,
        'grand_impots':      grand_impots,
        'grand_net':         grand_net,
        'grand_seances':     grand_seances,
        'grand_heures':      grand_heures,
        'academic_years':    academic_years,
        'acad_year_filter':  acad_year_filter,
        'dept_filter':       dept_filter,
        'by_year':           by_year,
        'dept_monthly_data': dept_monthly_data,  # pour vue département sélectionné
        'all_dept_monthly':  all_dept_monthly,   # pour vue globale (tous depts)
        'stats':             stats,
    })


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def _build_export_data(request):
    """
    Construit les données d'export en utilisant TeacherHonoraire comme source de vérité,
    identique au dashboard. Garantit la cohérence des montants entre dashboard et exports.
    """
    from .models import TeacherHonoraire
    today = timezone.now().date()
    try:
        year  = int(request.GET.get('year',  today.year))
        month = int(request.GET.get('month', today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month
    month = max(1, min(12, month))
    teacher_id = request.GET.get('teacher')
    dept_id = request.GET.get('department')
    teacher_filter = Teacher.objects.filter(pk=teacher_id).first() if teacher_id else None
    dept_filter = Department.objects.filter(pk=dept_id).first() if dept_id else None
    months_fr = {
        1: 'Janvier', 2: 'Février', 3: 'Mars', 4: 'Avril',
        5: 'Mai', 6: 'Juin', 7: 'Juillet', 8: 'Août',
        9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre',
    }

    qs = TeacherHonoraire.objects.filter(
        session_date__year=year,
        session_date__month=month,
    ).select_related(
        'teacher__user',
        'department',
        'academic_year',
        'attendance_sheet__timetable_entry__subject',
        'attendance_sheet__timetable_entry__class_group__level',
    ).order_by('department__name', 'teacher__user__last_name', 'session_date')

    # Pas de filtre faculté : exports toujours globaux (tous départements)
    if teacher_filter:
        qs = qs.filter(teacher=teacher_filter)
    if dept_filter:
        qs = qs.filter(department=dept_filter)

    groups_raw = defaultdict(lambda: {
        'sessions': [], 'total': Decimal('0'),
        'total_impots': Decimal('0'), 'total_net': Decimal('0'),
        'total_hours': Decimal('0'), 'teacher': None,
    })
    dept_map = defaultdict(lambda: {
        'dept': None, 'teachers': [], '_teacher_set': set(),
        '_teachers_raw': defaultdict(lambda: {
            'teacher': None, 'seances': 0,
            'heures': Decimal('0'), 'total': Decimal('0'),
            'impots': Decimal('0'), 'net': Decimal('0'),
        }),
        'seances': 0, 'heures': Decimal('0'), 'total': Decimal('0'),
        'impots': Decimal('0'), 'net': Decimal('0'),
    })
    grand_total = Decimal('0')

    for h in qs:
        try:
            entry = h.attendance_sheet.timetable_entry
        except Exception:
            continue
        s = {
            'dept': h.department,
            'level': entry.class_group.level,
            'subject': entry.subject,
            'class_group': entry.class_group,
            'date': h.session_date,
            'hours': h.duration_hours,
            'rate': h.rate_per_hour,
            'amount': h.amount,
            'impots': h.impots,
            'net': h.net_a_payer,
        }
        tk = h.teacher.pk
        groups_raw[tk]['sessions'].append(s)
        groups_raw[tk]['total']        += h.amount
        groups_raw[tk]['total_impots'] += h.impots
        groups_raw[tk]['total_net']    += h.net_a_payer
        groups_raw[tk]['total_hours']  += Decimal(str(h.duration_hours))
        groups_raw[tk]['teacher'] = h.teacher
        grand_total += h.amount

        dk = h.department.pk
        dept_map[dk]['dept'] = h.department
        if tk not in dept_map[dk]['_teacher_set']:
            dept_map[dk]['teachers'].append(h.teacher.full_name)
            dept_map[dk]['_teacher_set'].add(tk)
        dept_map[dk]['seances'] += 1
        dept_map[dk]['heures']  += Decimal(str(h.duration_hours))
        dept_map[dk]['total']   += h.amount
        dept_map[dk]['impots']  += h.impots
        dept_map[dk]['net']     += h.net_a_payer
        # Agrégation par enseignant dans le département
        dept_map[dk]['_teachers_raw'][tk]['teacher'] = h.teacher
        dept_map[dk]['_teachers_raw'][tk]['seances'] += 1
        dept_map[dk]['_teachers_raw'][tk]['heures']  += Decimal(str(h.duration_hours))
        dept_map[dk]['_teachers_raw'][tk]['total']   += h.amount
        dept_map[dk]['_teachers_raw'][tk]['impots']  += h.impots
        dept_map[dk]['_teachers_raw'][tk]['net']     += h.net_a_payer

    groups = dict(sorted(groups_raw.items(), key=lambda x: x[1]['teacher'].user.last_name))

    # Répartition des heures par niveau (LMD) pour chaque enseignant (colonne
    # SYNTHESE), calculée sur l'ensemble de ses séances du mois — indépendant
    # du département affiché sur la ligne (voir groups_raw[tk]['sessions']).
    heures_par_niveau_par_teacher = defaultdict(lambda: defaultdict(lambda: Decimal('0')))
    for tk_tmp, g_tmp in groups_raw.items():
        for s_tmp in g_tmp['sessions']:
            niveau_name = str(s_tmp['level']) if s_tmp['level'] else 'Niveau non précisé'
            heures_par_niveau_par_teacher[tk_tmp][niveau_name] += Decimal(str(s_tmp['hours'] or 0))

    recap = []
    for r in dept_map.values():
        r.pop('_teacher_set', None)
        r['pct'] = round(float(r['total']) / float(grand_total) * 100) if grand_total else 0
        # Construire la liste ordonnée par nom de teacher
        teachers_data = sorted(
            r.pop('_teachers_raw').values(),
            key=lambda td: td['teacher'].user.last_name
        )
        for td in teachers_data:
            td['pct'] = round(float(td['total']) / float(grand_total) * 100) if grand_total else 0
            tk = td['teacher'].pk
            td['phone'] = td['teacher'].user.phone
            td['global_heures'] = groups_raw[tk]['total_hours']
            td['heures_par_niveau'] = dict(heures_par_niveau_par_teacher[tk])
        r['teachers_data'] = teachers_data
        recap.append(r)

    return groups, grand_total, year, month, months_fr.get(month, ''), teacher_filter, recap


def _synthese_lines(td):
    """
    Lignes de synthèse des heures d'un enseignant pour une ligne du
    récapitulatif d'honoraires (colonne SYNTHESE, remplace l'ancienne colonne
    Heures) : total global (toutes ses séances du mois, tous départements
    confondus), puis détail par niveau (LMD) des classes où il est intervenu
    — un enseignant partagé entre plusieurs niveaux a ainsi sa charge horaire
    ventilée directement sur chaque ligne, sans avoir à recouper plusieurs
    lignes/feuilles.
    """
    lines = [f"Total global : {float(td['global_heures']):.1f}h"]
    for niveau_name, h in sorted(td['heures_par_niveau'].items()):
        lines.append(f"{niveau_name} : {float(h):.1f}h")
    return lines


@login_required
def export_excel(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    groups, grand_total, year, month, month_name, teacher_filter, recap = _build_export_data(request)
    grand_impots_val = sum(r['impots'] for r in recap)
    grand_net_val    = sum(r['net']    for r in recap)

    navy = "00173B"
    green_bg = "DCFCE7"
    header_fill = PatternFill("solid", fgColor=navy)
    thin = Side(style='thin', color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def style_cell(cell, bold=False, color="000000", bg=None, align="left", size=10):
        cell.font = Font(bold=bold, color=color, size=size)
        cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=True)
        if bg:
            cell.fill = PatternFill("solid", fgColor=bg)
        cell.border = border

    wb = openpyxl.Workbook()

    # ── Feuille 1 : Récapitulatif par département (même format que le dashboard) ─
    ws1 = wb.active
    ws1.title = "Récapitulatif"

    ws1.merge_cells('A1:H1')
    ws1['A1'] = f"Récapitulatif par département — {month_name} {year}"
    ws1['A1'].font = Font(bold=True, color="FFFFFF", size=14)
    ws1['A1'].fill = header_fill
    ws1['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws1.row_dimensions[1].height = 30

    ws1.merge_cells('A2:H2')
    ws1['A2'] = f"Institut Supérieur d'Informatique - ISI  |  Généré le {date.today().strftime('%d/%m/%Y')}"
    ws1['A2'].font = Font(italic=True, color="64748B", size=9)
    ws1['A2'].alignment = Alignment(horizontal='center')

    recap_headers = ['Département', 'Enseignant(s)', 'SYNTHESE', 'Montant (FCFA)', 'Impôts 5% (FCFA)', 'Net à payer (FCFA)', 'Téléphone', 'Émargement']
    recap_widths  = [26, 28, 24, 18, 18, 18, 16, 22]
    for i, (h, w) in enumerate(zip(recap_headers, recap_widths), 1):
        c = ws1.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="1E3A5F")
        if i == 5:
            c.fill = PatternFill("solid", fgColor="7F1D1D")
        if i == 6:
            c.fill = PatternFill("solid", fgColor="1E4D8C")
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = border
        ws1.column_dimensions[get_column_letter(i)].width = w
    ws1.row_dimensions[3].height = 20

    current_excel_row = 4
    for r in recap:
        dept_start_row = current_excel_row
        for ti, td in enumerate(r['teachers_data']):
            bg2 = None if ti % 2 == 0 else "F8FAFC"
            row_vals = [
                r['dept'].name if ti == 0 else '',
                td['teacher'].full_name,
                '\n'.join(_synthese_lines(td)),
                float(td['total']),
                float(td['impots']),
                float(td['net']),
                td['phone'] or '—',
                '',
            ]
            for ci, val in enumerate(row_vals, 1):
                c = ws1.cell(row=current_excel_row, column=ci, value=val)
                cell_bg = "F8FAFC" if ti % 2 != 0 else None
                style_cell(c, bg=cell_bg)
                if ci == 4:
                    style_cell(c, bold=True, color="166534", bg=cell_bg)
                if ci == 5:
                    style_cell(c, bold=True, color="7F1D1D", bg=cell_bg)
                if ci == 6:
                    style_cell(c, bold=True, color="1d4ed8", bg=cell_bg)
                c.alignment = Alignment(horizontal='right' if ci in (4, 5, 6) else 'left', vertical='center')
            current_excel_row += 1
        # Fusionner la cellule département sur toutes ses lignes
        dept_end_row = current_excel_row - 1
        if dept_end_row > dept_start_row:
            ws1.merge_cells(f'A{dept_start_row}:A{dept_end_row}')
        dc = ws1.cell(row=dept_start_row, column=1)
        dc.value = r['dept'].name
        dc.font = Font(bold=True, size=9, color="00173B")
        dc.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        dc.border = border
        # Ligne sous-total si plusieurs enseignants
        if len(r['teachers_data']) > 1:
            ws1.merge_cells(f'A{current_excel_row}:B{current_excel_row}')
            sc = ws1.cell(row=current_excel_row, column=1, value=f"Sous-total — {r['dept'].name}")
            style_cell(sc, bold=True, bg="DCFCE7", color="166534")
            sc.alignment = Alignment(horizontal='right', vertical='center')
            for col, val, clr, bg in [
                (3, f"Total département : {float(r['heures']):.1f}h", "166534", "DCFCE7"),
                (4, float(r['total']),   "166534", "DCFCE7"),
                (5, float(r['impots']),  "7F1D1D", "FEE2E2"),
                (6, float(r['net']),     "1d4ed8", "DBEAFE"),
            ]:
                cell = ws1.cell(row=current_excel_row, column=col, value=val)
                style_cell(cell, bold=True, bg=bg, color=clr)
                cell.alignment = Alignment(horizontal='right', vertical='center')
            current_excel_row += 1

    # Ligne TOTAL GÉNÉRAL du récapitulatif
    tot_row = current_excel_row
    ws1.merge_cells(f'A{tot_row}:B{tot_row}')
    tc = ws1.cell(row=tot_row, column=1, value="TOTAL GÉNÉRAL")
    style_cell(tc, bold=True, bg=green_bg, color="166534")
    tc.alignment = Alignment(horizontal='right', vertical='center')
    recap_totals = [
        f"Total : {float(sum(r['heures'] for r in recap)):.1f}h",
        float(grand_total),
        float(grand_impots_val),
        float(grand_net_val),
    ]
    recap_tot_cols  = [3, 4, 5, 6]
    recap_tot_clrs  = ["166534", "166534", "7F1D1D", "1d4ed8"]
    for col, val, clr in zip(recap_tot_cols, recap_totals, recap_tot_clrs):
        c = ws1.cell(row=tot_row, column=col, value=val)
        style_cell(c, bold=True, bg=green_bg, color=clr)
        c.alignment = Alignment(horizontal='right', vertical='center')

    # ── Feuille 2 : Détail par séance ─────────────────────────────────────────
    ws2 = wb.create_sheet(title="Détail séances")

    ws2.merge_cells('A1:K1')
    ws2['A1'] = f"Honoraires des Enseignants — Détail des séances — {month_name} {year}"
    ws2['A1'].font = Font(bold=True, color="FFFFFF", size=13)
    ws2['A1'].fill = header_fill
    ws2['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws2.row_dimensions[1].height = 28

    headers = ['Enseignant', 'Département', 'Niveau', 'Module (EC)', 'Classe', 'Date', 'Heures', 'Taux/h (FCFA)', 'Montant (FCFA)', 'Impôts 5% (FCFA)', 'Net à payer (FCFA)']
    col_widths = [25, 20, 12, 25, 12, 12, 8, 14, 14, 14, 16]
    subheader_fill = PatternFill("solid", fgColor="1E3A5F")

    for i, (h, w) in enumerate(zip(headers, col_widths), 1):
        c = ws2.cell(row=2, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = subheader_fill
        if i == 10:
            c.fill = PatternFill("solid", fgColor="7F1D1D")
        if i == 11:
            c.fill = PatternFill("solid", fgColor="1E4D8C")
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = border
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.row_dimensions[2].height = 20

    row = 3
    for group in groups.values():
        teacher = group['teacher']
        teacher_start_row = row
        for idx, s in enumerate(group['sessions']):
            ws2.cell(row=row, column=1,  value=teacher.full_name if row == teacher_start_row else '')
            ws2.cell(row=row, column=2,  value=s['dept'].name)
            ws2.cell(row=row, column=3,  value=str(s['level']))
            ws2.cell(row=row, column=4,  value=s['subject'].title)
            ws2.cell(row=row, column=5,  value=s['class_group'].name)
            ws2.cell(row=row, column=6,  value=s['date'].strftime('%d/%m/%Y'))
            ws2.cell(row=row, column=7,  value=float(s['hours']))
            ws2.cell(row=row, column=8,  value=float(s['rate']))
            ws2.cell(row=row, column=9,  value=float(s['amount']))
            ws2.cell(row=row, column=10, value=float(s['impots']))
            ws2.cell(row=row, column=11, value=float(s['net']))
            bg = None if idx % 2 == 0 else "F8FAFC"
            for col in range(1, 12):
                cell = ws2.cell(row=row, column=col)
                style_cell(cell, bg=bg)
                if col in (7, 8, 9, 10, 11):
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            row += 1

        # Fusionner la colonne Enseignant sur toutes les lignes de cet enseignant
        teacher_end_row = row - 1
        if teacher_end_row > teacher_start_row:
            ws2.merge_cells(f'A{teacher_start_row}:A{teacher_end_row}')
        mc = ws2.cell(row=teacher_start_row, column=1)
        mc.value = teacher.full_name
        mc.font = Font(bold=True, size=9, color="00173B")
        mc.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        mc.border = border

        ws2.merge_cells(f'A{row}:H{row}')
        c = ws2.cell(row=row, column=1, value=f"Sous-total — {teacher.full_name}")
        style_cell(c, bold=True, bg="DBEAFE")
        c.alignment = Alignment(horizontal='right', vertical='center')
        for col, val, clr, bg in [(9, float(group['total']), "166534", "DBEAFE"),
                                   (10, float(group['total_impots']), "7F1D1D", "FEE2E2"),
                                   (11, float(group['total_net']), "1d4ed8", "DBEAFE")]:
            cell = ws2.cell(row=row, column=col, value=val)
            style_cell(cell, bold=True, bg=bg, color=clr)
            cell.alignment = Alignment(horizontal='right', vertical='center')
        row += 1

    ws2.merge_cells(f'A{row}:H{row}')
    c = ws2.cell(row=row, column=1, value="TOTAL GÉNÉRAL")
    style_cell(c, bold=True, bg=green_bg, color="166534")
    c.alignment = Alignment(horizontal='right', vertical='center')
    for col, val, clr in [(9, float(grand_total), "166534"),
                           (10, float(grand_impots_val), "7F1D1D"),
                           (11, float(grand_net_val), "1d4ed8")]:
        cell = ws2.cell(row=row, column=col, value=val)
        style_cell(cell, bold=True, bg=green_bg if col != 10 else "FEE2E2", color=clr)
        cell.alignment = Alignment(horizontal='right', vertical='center')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"honoraires_{month:02d}_{year}.xlsx"
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_pdf(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from academic_core.pdf_utils import logo_image as _logo_img_e_fn, get_institut_config_for_request
    _inst_cfg_e = get_institut_config_for_request(request)
    _logo_img_e = lambda **kw: _logo_img_e_fn(config=_inst_cfg_e, **kw)  # noqa: E731

    groups, grand_total, year, month, month_name, teacher_filter, recap = _build_export_data(request)
    grand_impots_val = sum(r['impots'] for r in recap)
    grand_net_val    = sum(r['net']    for r in recap)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    navy       = colors.HexColor('#00173B')
    navy_mid   = colors.HexColor('#1E3A5F')
    green      = colors.HexColor('#166534')
    light_green= colors.HexColor('#DCFCE7')
    sub_blue   = colors.HexColor('#DBEAFE')
    white      = colors.white
    accent     = colors.HexColor('#F59E0B')

    story = []
    from reportlab.platypus import PageBreak

    def _header_block(title_text):
        _logo_e = _logo_img_e(width=2.0*cm, height=1.3*cm)
        hd = Table([[
            Paragraph(f'<font color="white" size="14"><b>{title_text}</b></font>',
                      ParagraphStyle('hx1', fontName='Helvetica-Bold', alignment=TA_LEFT)),
            Paragraph(
                f'<font color="white" size="8"><b>Institut Supérieur d\'Informatique - ISI</b></font><br/>'
                f'<font color="#94A3B8" size="7">Gestion des Emplois du Temps</font>',
                ParagraphStyle('hx2', fontName='Helvetica', alignment=TA_RIGHT)),
            _logo_e or Paragraph('<font color="white" size="9"><b>ISI</b></font>',
                                  ParagraphStyle('hx3', fontName='Helvetica-Bold', alignment=TA_RIGHT)),
        ]], colWidths=[13*cm, 10*cm, 3.5*cm])
        hd.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), navy),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (0, -1), 18),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 18),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        info = Table([[
            Paragraph(f'<font size="8" color="#1E293B">Période : <b>{month_name} {year}</b></font>',
                      ParagraphStyle('ix1', fontName='Helvetica')),
            Paragraph(f'<font size="8" color="#1E293B">Généré le : <b>{date.today().strftime("%d/%m/%Y")}</b></font>',
                      ParagraphStyle('ix2', fontName='Helvetica', alignment=TA_CENTER)),
            Paragraph(f'<font size="8" color="#1E293B">Total brut : <b>{grand_total:,.0f} FCFA</b></font>',
                      ParagraphStyle('ix3', fontName='Helvetica', alignment=TA_RIGHT)),
        ]], colWidths=[8.83*cm, 8.83*cm, 8.84*cm])
        info.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING', (0, 0), (0, -1), 18),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 18),
            ('LINEBELOW', (0, 0), (-1, -1), 2, accent),
        ]))
        return [hd, Spacer(1, 0.2*cm), info, Spacer(1, 0.4*cm)]

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 1 : Récapitulatif par département (même format que le dashboard)
    # ══════════════════════════════════════════════════════════════════════════
    story += _header_block(f'RÉCAPITULATIF PAR DÉPARTEMENT — {month_name.upper()} {year}')

    synthese_style = ParagraphStyle('synth', fontName='Helvetica', fontSize=7.5, leading=9.5)
    synthese_style_bold = ParagraphStyle('synthb', fontName='Helvetica-Bold', fontSize=7.5, leading=9.5)

    recap_headers_pdf = ['Département', 'Enseignant', 'SYNTHESE',
                         'Montant (FCFA)', 'Impôts 5% (FCFA)', 'Net à payer (FCFA)', 'Téléphone', 'Émargement']
    recap_col_widths  = [4.3*cm, 4.8*cm, 4.3*cm, 3.3*cm, 3.3*cm, 3.3*cm, 2.6*cm, 2.8*cm]
    recap_data = [recap_headers_pdf]
    recap_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), navy_mid),
        ('TEXTCOLOR',  (0, 0), (-1, 0), white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('BACKGROUND', (4, 0), (4, 0), colors.HexColor('#7F1D1D')),
        ('BACKGROUND', (5, 0), (5, 0), colors.HexColor('#1E3A5F')),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('FONTNAME',   (0, 1), (-1, -1), 'Helvetica'),
        ('ALIGN',      (3, 1), (5, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    ri = 1
    for r in recap:
        dept_start_ri = ri
        for ti, td in enumerate(r['teachers_data']):
            bg = white if ti % 2 == 0 else colors.HexColor('#F8FAFC')
            recap_data.append([
                r['dept'].name if ti == 0 else '',
                td['teacher'].full_name,
                Paragraph('<br/>'.join(_synthese_lines(td)), synthese_style),
                f"{float(td['total']):,.0f}",
                f"{float(td['impots']):,.0f}",
                f"{float(td['net']):,.0f}",
                td['phone'] or '—',
                '',
            ])
            recap_cmds += [
                ('BACKGROUND', (0, ri), (-1, ri), bg),
                ('TEXTCOLOR',  (3, ri), (3, ri), green),
                ('FONTNAME',   (3, ri), (3, ri), 'Helvetica-Bold'),
                ('TEXTCOLOR',  (4, ri), (4, ri), colors.HexColor('#7F1D1D')),
                ('FONTNAME',   (4, ri), (4, ri), 'Helvetica-Bold'),
                ('TEXTCOLOR',  (5, ri), (5, ri), colors.HexColor('#1d4ed8')),
                ('FONTNAME',   (5, ri), (5, ri), 'Helvetica-Bold'),
            ]
            ri += 1
        # Fusionner cellule Département sur toutes les lignes
        if ri - 1 > dept_start_ri:
            recap_cmds += [
                ('SPAN',    (0, dept_start_ri), (0, ri - 1)),
                ('VALIGN',  (0, dept_start_ri), (0, ri - 1), 'MIDDLE'),
                ('FONTNAME',(0, dept_start_ri), (0, ri - 1), 'Helvetica-Bold'),
            ]
        # Ligne sous-total si plusieurs enseignants
        if len(r['teachers_data']) > 1:
            recap_data.append([
                f"Sous-total — {r['dept'].name}", '',
                Paragraph(f"Total département : {float(r['heures']):.1f}h", synthese_style_bold),
                f"{float(r['total']):,.0f}",
                f"{float(r['impots']):,.0f}",
                f"{float(r['net']):,.0f}",
                '', '',
            ])
            recap_cmds += [
                ('BACKGROUND', (0, ri), (-1, ri), light_green),
                ('FONTNAME',   (0, ri), (-1, ri), 'Helvetica-Bold'),
                ('TEXTCOLOR',  (3, ri), (3, ri), green),
                ('TEXTCOLOR',  (4, ri), (4, ri), colors.HexColor('#7F1D1D')),
                ('TEXTCOLOR',  (5, ri), (5, ri), colors.HexColor('#1d4ed8')),
                ('SPAN',       (0, ri), (1, ri)),
                ('ALIGN',      (0, ri), (-1, ri), 'RIGHT'),
            ]
            ri += 1

    tot_ri = ri
    recap_data.append([
        'TOTAL GÉNÉRAL', '',
        Paragraph(f"Total : {float(sum(r['heures'] for r in recap)):.1f}h", synthese_style_bold),
        f"{float(grand_total):,.0f}",
        f"{float(grand_impots_val):,.0f}",
        f"{float(grand_net_val):,.0f}",
        '', '',
    ])
    recap_cmds += [
        ('BACKGROUND', (0, tot_ri), (-1, tot_ri), light_green),
        ('TEXTCOLOR',  (0, tot_ri), (-1, tot_ri), green),
        ('FONTNAME',   (0, tot_ri), (-1, tot_ri), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, tot_ri), (-1, tot_ri), 9),
        ('SPAN',       (0, tot_ri), (1, tot_ri)),
        ('ALIGN',      (0, tot_ri), (-1, tot_ri), 'RIGHT'),
        ('BACKGROUND', (4, tot_ri), (4, tot_ri), colors.HexColor('#FEE2E2')),
        ('TEXTCOLOR',  (4, tot_ri), (4, tot_ri), colors.HexColor('#7F1D1D')),
        ('BACKGROUND', (5, tot_ri), (5, tot_ri), colors.HexColor('#DBEAFE')),
        ('TEXTCOLOR',  (5, tot_ri), (5, tot_ri), colors.HexColor('#1d4ed8')),
    ]
    t_recap = Table(recap_data, colWidths=recap_col_widths)
    t_recap.setStyle(TableStyle(recap_cmds))
    story.append(t_recap)
    story.append(Spacer(1, 0.4*cm))

    # Bandeau totaux
    footer_data = [[
        Paragraph('<font size="8" color="#166534">Ce document est généré automatiquement — ISI</font>',
                  ParagraphStyle('fl', fontName='Helvetica', alignment=TA_LEFT)),
        Paragraph(f'<font size="9" color="#166534"><b>Brut : {grand_total:,.0f} FCFA</b></font>',
                  ParagraphStyle('fm', fontName='Helvetica-Bold', alignment=TA_CENTER)),
        Paragraph(f'<font size="9" color="#7F1D1D"><b>Impôts (5%) : {grand_impots_val:,.0f} FCFA</b></font>',
                  ParagraphStyle('fi', fontName='Helvetica-Bold', alignment=TA_CENTER)),
        Paragraph(f'<font size="10" color="#1d4ed8"><b>Net à payer : {grand_net_val:,.0f} FCFA</b></font>',
                  ParagraphStyle('fr', fontName='Helvetica-Bold', alignment=TA_RIGHT)),
    ]]
    ft = Table(footer_data, colWidths=[8*cm, 6*cm, 6*cm, 6.5*cm])
    ft.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), light_green),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',   (0, 0), (0, -1), 14),
        ('RIGHTPADDING',  (-1, 0), (-1, -1), 14),
        ('LINEABOVE',     (0, 0), (-1, 0), 2, colors.HexColor('#86EFAC')),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(ft)
    story.append(Spacer(1, .2*cm))
    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 2 : Détail des honoraires par séance
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story += _header_block(f'DÉTAIL DES HONORAIRES PAR SÉANCE — {month_name.upper()} {year}')

    col_headers = ['Enseignant', 'Département', 'Niveau', 'Module (EC)', 'Classe',
                   'Date', 'Heures', 'Taux/h', 'Montant', 'Impôts 5%', 'Net à payer']
    col_widths  = [3.5*cm, 3.5*cm, 1.8*cm, 4*cm, 2.2*cm, 2*cm, 1.4*cm, 2.4*cm, 2.6*cm, 2.4*cm, 2.7*cm]

    data = [col_headers]
    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0), navy_mid),
        ('TEXTCOLOR',     (0, 0), (-1, 0), white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0), 7.5),
        ('ALIGN',         (0, 0), (-1, 0), 'CENTER'),
        ('BACKGROUND',    (9, 0), (9, 0), colors.HexColor('#7F1D1D')),
        ('BACKGROUND',    (10, 0), (10, 0), colors.HexColor('#1E3A5F')),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',          (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [white, colors.HexColor('#F8FAFC')]),
        ('FONTSIZE',      (0, 1), (-1, -1), 7),
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('ALIGN',         (6, 1), (-1, -1), 'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]

    data_row = 1
    for group in groups.values():
        teacher = group['teacher']
        teacher_start_row = data_row
        first = True
        for s in group['sessions']:
            data.append([
                teacher.full_name if first else '',
                s['dept'].name, str(s['level']), s['subject'].title,
                s['class_group'].name, s['date'].strftime('%d/%m/%Y'),
                f"{s['hours']:.1f}h", f"{s['rate']:,.0f}",
                f"{s['amount']:,.0f}", f"{s['impots']:,.0f}", f"{s['net']:,.0f}",
            ])
            first = False
            data_row += 1

        if data_row - teacher_start_row > 1:
            style_cmds += [
                ('SPAN',    (0, teacher_start_row), (0, data_row - 1)),
                ('VALIGN',  (0, teacher_start_row), (0, data_row - 1), 'MIDDLE'),
                ('FONTNAME',(0, teacher_start_row), (0, data_row - 1), 'Helvetica-Bold'),
            ]

        data.append(['', '', '', '', '', '', '', f"S/total {teacher.full_name}",
                     f"{group['total']:,.0f}", f"{group['total_impots']:,.0f}", f"{group['total_net']:,.0f}"])
        style_cmds += [
            ('BACKGROUND', (0, data_row), (-1, data_row), sub_blue),
            ('FONTNAME',   (0, data_row), (-1, data_row), 'Helvetica-Bold'),
            ('ALIGN',      (7, data_row), (10, data_row), 'RIGHT'),
            ('SPAN',       (0, data_row), (6, data_row)),
        ]
        data_row += 1

    data.append(['', '', '', '', '', '', '', 'TOTAL GÉNÉRAL',
                 f"{grand_total:,.0f}", f"{grand_impots_val:,.0f}", f"{grand_net_val:,.0f}"])
    style_cmds += [
        ('BACKGROUND', (0, data_row), (-1, data_row), light_green),
        ('TEXTCOLOR',  (0, data_row), (-1, data_row), green),
        ('FONTNAME',   (0, data_row), (-1, data_row), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, data_row), (-1, data_row), 8),
        ('ALIGN',      (7, data_row), (10, data_row), 'RIGHT'),
        ('SPAN',       (0, data_row), (6, data_row)),
        ('BACKGROUND', (9, data_row), (9, data_row), colors.HexColor('#FEE2E2')),
        ('TEXTCOLOR',  (9, data_row), (9, data_row), colors.HexColor('#7F1D1D')),
    ]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    story.append(t)

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    filename = f"honoraires_{month:02d}_{year}.pdf"
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_word(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from docx import Document
    from docx.shared import Pt, RGBColor, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.enum.table import WD_ALIGN_VERTICAL
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    def add_multiline(paragraph, lines, size=8, bold=False, color=None):
        for i, line in enumerate(lines):
            if i > 0:
                paragraph.add_run().add_break(WD_BREAK.LINE)
            r = paragraph.add_run(line)
            r.font.size = Pt(size)
            r.bold = bold
            if color:
                r.font.color.rgb = color

    groups, grand_total, year, month, month_name, teacher_filter, recap = _build_export_data(request)
    grand_impots_val = sum(r['impots'] for r in recap)
    grand_net_val    = sum(r['net']    for r in recap)

    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(13)
    section.page_height = Inches(9)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)

    def set_cell_bg(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color)
        shd.set(qn('w:val'), 'clear')
        tcPr.append(shd)

    def add_page_break():
        from docx.oxml.ns import qn as _qn
        from docx.oxml import OxmlElement as _OE
        p = doc.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pb = _OE('w:pageBreak')
        p._p.append(pb)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 : Récapitulatif par département (même format que le dashboard)
    # ══════════════════════════════════════════════════════════════════════════
    title = doc.add_heading('', level=0)
    run = title.add_run(f"Récapitulatif par département — {month_name} {year}")
    run.font.color.rgb = RGBColor(0, 23, 59)
    run.font.size = Pt(14)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph()
    rs = sub.add_run(f"Institut Supérieur d'Informatique - ISI  |  Généré le {date.today().strftime('%d/%m/%Y')}")
    rs.font.size = Pt(9)
    rs.font.color.rgb = RGBColor(100, 116, 139)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    recap_headers_w = ['Département', 'Enseignant', 'SYNTHESE',
                       'Montant (FCFA)', 'Impôts 5% (FCFA)', 'Net à payer (FCFA)', 'Téléphone', 'Émargement']
    recap_col_widths_w = [Cm(3.8), Cm(4.5), Cm(3.8), Cm(2.8), Cm(2.8), Cm(2.8), Cm(2.4), Cm(2.5)]
    recap_tbl = doc.add_table(rows=1, cols=8)
    recap_tbl.style = 'Table Grid'

    rh_row = recap_tbl.rows[0]
    for i, h in enumerate(recap_headers_w):
        cell = rh_row.cells[i]
        cell.width = recap_col_widths_w[i]
        set_cell_bg(cell, '7F1D1D' if i == 4 else '1E3A5F')
        p = cell.paragraphs[0]
        rn = p.add_run(h)
        rn.bold = True
        rn.font.color.rgb = RGBColor(255, 255, 255)
        rn.font.size = Pt(8)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for r in recap:
        for ti, td in enumerate(r['teachers_data']):
            trow = recap_tbl.add_row()
            bg_hex = 'FFFFFF' if ti % 2 == 0 else 'F8FAFC'
            vals_w = [
                r['dept'].name if ti == 0 else '',
                td['teacher'].full_name,
                None,
                f"{float(td['total']):,.0f}",
                f"{float(td['impots']):,.0f}",
                f"{float(td['net']):,.0f}",
                td['phone'] or '—',
                '',
            ]
            for i, val in enumerate(vals_w):
                cell = trow.cells[i]
                cell.width = recap_col_widths_w[i]
                set_cell_bg(cell, bg_hex)
                p = cell.paragraphs[0]
                if i == 2:
                    add_multiline(p, _synthese_lines(td), size=7.5)
                    continue
                rn = p.add_run(val)
                rn.font.size = Pt(8)
                if i == 0 and ti == 0:
                    rn.bold = True
                    rn.font.color.rgb = RGBColor(0, 23, 59)
                elif i == 3:
                    rn.font.color.rgb = RGBColor(22, 101, 52); rn.bold = True
                elif i == 4:
                    rn.font.color.rgb = RGBColor(127, 29, 29); rn.bold = True
                elif i == 5:
                    rn.font.color.rgb = RGBColor(29, 78, 216); rn.bold = True
                if i in (3, 4, 5):
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        # Ligne sous-total si plusieurs enseignants
        if len(r['teachers_data']) > 1:
            st_row = recap_tbl.add_row()
            st_vals = [
                f"Sous-total — {r['dept'].name}", '', None,
                f"{float(r['total']):,.0f}", f"{float(r['impots']):,.0f}",
                f"{float(r['net']):,.0f}", '', '',
            ]
            for i, val in enumerate(st_vals):
                cell = st_row.cells[i]
                cell.width = recap_col_widths_w[i]
                set_cell_bg(cell, 'DCFCE7')
                p = cell.paragraphs[0]
                if i == 2:
                    add_multiline(p, [f"Total département : {float(r['heures']):.1f}h"],
                                  size=7.5, bold=True, color=RGBColor(22, 101, 52))
                    continue
                if i in (1, 6, 7):
                    continue
                rn = p.add_run(val)
                rn.bold = True
                rn.font.size = Pt(8)
                if i == 3:
                    rn.font.color.rgb = RGBColor(22, 101, 52)
                elif i == 4:
                    rn.font.color.rgb = RGBColor(127, 29, 29)
                elif i == 5:
                    rn.font.color.rgb = RGBColor(29, 78, 216)
                else:
                    rn.font.color.rgb = RGBColor(22, 101, 52)
                if i in (3, 4, 5):
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # Ligne TOTAL GÉNÉRAL
    rt_row = recap_tbl.add_row()
    for i in range(8):
        set_cell_bg(rt_row.cells[i], 'DCFCE7')
    rt_row.cells[0].merge(rt_row.cells[1])
    p = rt_row.cells[0].paragraphs[0]
    rn = p.add_run("TOTAL GÉNÉRAL"); rn.bold = True; rn.font.size = Pt(9)
    rn.font.color.rgb = RGBColor(22, 101, 52)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    p_synth = rt_row.cells[2].paragraphs[0]
    add_multiline(p_synth, [f"Total : {float(sum(r['heures'] for r in recap)):.1f}h"],
                  size=9, bold=True, color=RGBColor(22, 101, 52))

    recap_tot_vals = [
        f"{float(grand_total):,.0f}",
        f"{float(grand_impots_val):,.0f}",
        f"{float(grand_net_val):,.0f}",
    ]
    recap_tot_clrs = [
        RGBColor(22, 101, 52), RGBColor(127, 29, 29), RGBColor(29, 78, 216),
    ]
    for ci, (val, clr) in enumerate(zip(recap_tot_vals, recap_tot_clrs), 3):
        cell = rt_row.cells[ci]
        if ci == 4:
            set_cell_bg(cell, 'FEE2E2')
        elif ci == 5:
            set_cell_bg(cell, 'DBEAFE')
        p = cell.paragraphs[0]
        rn = p.add_run(val); rn.bold = True; rn.font.size = Pt(9)
        rn.font.color.rgb = clr
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 : Détail des séances
    # ══════════════════════════════════════════════════════════════════════════
    doc.add_page_break()

    title2 = doc.add_heading('', level=1)
    run2 = title2.add_run(f"Détail des honoraires par séance — {month_name} {year}")
    run2.font.color.rgb = RGBColor(0, 23, 59)
    run2.font.size = Pt(13)
    title2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    col_headers = ['Enseignant', 'Département', 'Niveau', 'Module (EC)', 'Classe',
                   'Date', 'Heures', 'Taux/h', 'Montant', 'Impôts 5%', 'Net à payer']
    col_widths  = [Cm(3.2), Cm(3.2), Cm(1.8), Cm(3.5), Cm(2), Cm(2), Cm(1.4), Cm(2.2), Cm(2.3), Cm(2.3), Cm(2.5)]

    table = doc.add_table(rows=1, cols=11)
    table.style = 'Table Grid'
    hdr_row = table.rows[0]
    for i, h in enumerate(col_headers):
        cell = hdr_row.cells[i]
        cell.width = col_widths[i]
        set_cell_bg(cell, '00173B')
        p = cell.paragraphs[0]
        rn = p.add_run(h); rn.bold = True
        rn.font.color.rgb = RGBColor(255, 255, 255)
        rn.font.size = Pt(8)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for group in groups.values():
        teacher = group['teacher']
        session_rows = []
        for s in group['sessions']:
            trow = table.add_row()
            session_rows.append(trow)
            vals = [
                teacher.full_name if len(session_rows) == 1 else '',
                s['dept'].name,
                str(s['level']), s['subject'].title, s['class_group'].name,
                s['date'].strftime('%d/%m/%Y'),
                f"{s['hours']:.1f}h", f"{s['rate']:,.0f}",
                f"{s['amount']:,.0f}", f"{s['impots']:,.0f}", f"{s['net']:,.0f}",
            ]
            for i, val in enumerate(vals):
                cell = trow.cells[i]; cell.width = col_widths[i]
                p = cell.paragraphs[0]
                r = p.add_run(val); r.font.size = Pt(7)
                if i >= 6:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        # Fusion verticale de la colonne Enseignant sur toutes les séances
        if len(session_rows) > 1:
            merged = session_rows[0].cells[0].merge(session_rows[-1].cells[0])
            p = merged.paragraphs[0]
            for run in p.runs:
                run.text = ''
            rn = p.add_run(teacher.full_name)
            rn.bold = True; rn.font.size = Pt(7)
            rn.font.color.rgb = RGBColor(0, 23, 59)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            merged.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        st_row = table.add_row()
        for i in range(7):
            set_cell_bg(st_row.cells[i], 'DBEAFE')
        st_row.cells[0].merge(st_row.cells[6])
        p = st_row.cells[0].paragraphs[0]
        r = p.add_run(f"Sous-total — {teacher.full_name}")
        r.bold = True; r.font.size = Pt(8)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        for cidx, (val, clr, bg) in enumerate([
            (f"{group['total']:,.0f}",        RGBColor(22, 101, 52),  'DBEAFE'),
            (f"{group['total_impots']:,.0f}",  RGBColor(127, 29, 29), 'FEE2E2'),
            (f"{group['total_net']:,.0f}",     RGBColor(29, 78, 216), 'DBEAFE'),
        ], 8):
            set_cell_bg(st_row.cells[cidx], bg)
            p2 = st_row.cells[cidx].paragraphs[0]
            r2 = p2.add_run(val); r2.bold = True; r2.font.size = Pt(8)
            r2.font.color.rgb = clr
            p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    gt_row = table.add_row()
    for i in range(11):
        set_cell_bg(gt_row.cells[i], 'DCFCE7')
    gt_row.cells[0].merge(gt_row.cells[7])
    p = gt_row.cells[0].paragraphs[0]
    r = p.add_run("TOTAL GÉNÉRAL"); r.bold = True; r.font.size = Pt(10)
    r.font.color.rgb = RGBColor(22, 101, 52)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    for cidx, (val, clr, bg) in enumerate([
        (f"{grand_total:,.0f} FCFA",         RGBColor(22, 101, 52),  'DCFCE7'),
        (f"{grand_impots_val:,.0f} FCFA",    RGBColor(127, 29, 29), 'FEE2E2'),
        (f"{grand_net_val:,.0f} FCFA",       RGBColor(29, 78, 216), 'DBEAFE'),
    ], 8):
        set_cell_bg(gt_row.cells[cidx], bg)
        p2 = gt_row.cells[cidx].paragraphs[0]
        r2 = p2.add_run(val); r2.bold = True; r2.font.size = Pt(10)
        r2.font.color.rgb = clr
        p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    filename = f"honoraires_{month:02d}_{year}.docx"
    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Exports par enseignant (fiche individuelle)
# ---------------------------------------------------------------------------

def _build_teacher_export_data(request):
    """Construit les données d'export pour un seul enseignant."""
    from .models import TeacherHonoraire
    today = timezone.now().date()
    try:
        year  = int(request.GET.get('year',  today.year))
        month = int(request.GET.get('month', today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month
    month = max(1, min(12, month))
    months_fr = {
        1: 'Janvier', 2: 'Février', 3: 'Mars',      4: 'Avril',
        5: 'Mai',     6: 'Juin',    7: 'Juillet',    8: 'Août',
        9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre',
    }
    teacher_id = request.GET.get('teacher')
    teacher = Teacher.objects.filter(pk=teacher_id).select_related('user').first() if teacher_id else None
    if not teacher:
        return (None, year, month, months_fr.get(month, ''), [], Decimal('0'), Decimal('0'),
                Decimal('0'), Decimal('0'), {})

    qs = (TeacherHonoraire.objects
          .filter(teacher=teacher, session_date__year=year, session_date__month=month)
          .select_related(
              'department',
              'attendance_sheet__timetable_entry__subject',
              'attendance_sheet__timetable_entry__class_group__level',
          )
          .order_by('department__name', 'session_date'))

    sessions = []
    total = Decimal('0')
    total_impots = Decimal('0')
    total_net    = Decimal('0')
    total_hours  = Decimal('0')
    heures_par_niveau = defaultdict(lambda: Decimal('0'))
    for h in qs:
        try:
            entry = h.attendance_sheet.timetable_entry
        except Exception:
            continue
        sessions.append({
            'dept':        h.department,
            'level':       entry.class_group.level,
            'subject':     entry.subject,
            'class_group': entry.class_group,
            'date':        h.session_date,
            'hours':       h.duration_hours,
            'rate':        h.rate_per_hour,
            'amount':      h.amount,
            'impots':      h.impots,
            'net':         h.net_a_payer,
        })
        total        += h.amount
        total_impots += h.impots
        total_net    += h.net_a_payer
        total_hours  += Decimal(str(h.duration_hours))
        niveau_name = str(entry.class_group.level) if entry.class_group.level else 'Niveau non précisé'
        heures_par_niveau[niveau_name] += Decimal(str(h.duration_hours))

    return (teacher, year, month, months_fr.get(month, ''), sessions, total, total_impots,
            total_net, total_hours, dict(heures_par_niveau))


def _teacher_synthese_lines(total_hours, heures_par_niveau):
    """Synthèse des heures d'un enseignant pour sa fiche individuelle : total
    global du mois, puis détail par niveau (LMD) des classes concernées
    (voir _synthese_lines, même principe pour le récapitulatif global)."""
    lines = [f"Total global : {float(total_hours):.1f}h"]
    for niveau_name, h in sorted(heures_par_niveau.items()):
        lines.append(f"{niveau_name} : {float(h):.1f}h")
    return lines


@login_required
def export_teacher_excel(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    result = _build_teacher_export_data(request)
    teacher, year, month, month_name, sessions, total, total_impots, total_net, total_hours, heures_par_niveau = result
    if not teacher:
        messages.error(request, "Enseignant introuvable.")
        return redirect('accounting:dashboard')

    navy  = "00173B"
    thin  = Side(style='thin', color="CBD5E1")
    brd   = Border(left=thin, right=thin, top=thin, bottom=thin)

    def sc(cell, bold=False, color="000000", bg=None, align="left", size=10):
        cell.font      = Font(bold=bold, color=color, size=size)
        cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=True)
        if bg:
            cell.fill = PatternFill("solid", fgColor=bg)
        cell.border = brd

    wb  = openpyxl.Workbook()
    ws  = wb.active
    ws.title = "Honoraires"

    # ── Titre ──────────────────────────────────────────────────────────────────
    ws.merge_cells('A1:I1')
    ws['A1'] = f"Fiche d'honoraires — {teacher.full_name} — {month_name} {year}"
    ws['A1'].font      = Font(bold=True, color="FFFFFF", size=13)
    ws['A1'].fill      = PatternFill("solid", fgColor=navy)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    # ── Infos enseignant ───────────────────────────────────────────────────────
    grade_label = getattr(getattr(teacher, 'grade', None), 'abbreviation', '') or ''
    email_val   = teacher.user.email or ''
    phone_val   = teacher.user.phone or '—'
    synthese_txt = '   —   '.join(_teacher_synthese_lines(total_hours, heures_par_niveau))
    ws.merge_cells('A2:I2')
    ws['A2'] = f"{grade_label}  |  Tél. {phone_val}  |  {email_val}  |  {len(sessions)} séance(s)"
    ws['A2'].font      = Font(italic=True, color="64748B", size=9)
    ws['A2'].alignment = Alignment(horizontal='center')

    ws.merge_cells('A3:I3')
    ws['A3'] = f"SYNTHESE — {synthese_txt}"
    ws['A3'].font      = Font(bold=True, color="00173B", size=9)
    ws['A3'].alignment = Alignment(horizontal='center')
    ws['A3'].fill      = PatternFill("solid", fgColor="EFF6FF")

    # ── En-têtes colonnes ──────────────────────────────────────────────────────
    headers    = ['Département', 'Niveau', 'Module (EC)', 'Classe', 'Date',
                  'Heures', 'Taux/h (FCFA)', 'Montant (FCFA)', 'Impôts 5% (FCFA)', 'Net à payer (FCFA)']
    col_widths = [24, 12, 25, 12, 12, 8, 14, 16, 16, 18]
    fill_hdr   = PatternFill("solid", fgColor="1E3A5F")
    for i, (h, w) in enumerate(zip(headers, col_widths), 1):
        c = ws.cell(row=4, column=i, value=h)
        c.font      = Font(bold=True, color="FFFFFF", size=10)
        c.fill      = fill_hdr
        if i == 9:
            c.fill = PatternFill("solid", fgColor="7F1D1D")
        if i == 10:
            c.fill = PatternFill("solid", fgColor="1E4D8C")
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border    = brd
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[4].height = 20

    # ── Lignes ────────────────────────────────────────────────────────────────
    for idx, s in enumerate(sessions):
        row = idx + 5
        bg  = None if idx % 2 == 0 else "F8FAFC"
        vals = [
            s['dept'].name, str(s['level']), s['subject'].title,
            s['class_group'].name, s['date'].strftime('%d/%m/%Y'),
            float(s['hours']), float(s['rate']),
            float(s['amount']), float(s['impots']), float(s['net']),
        ]
        for ci, val in enumerate(vals, 1):
            c = ws.cell(row=row, column=ci, value=val)
            sc(c, bg=bg)
            if ci >= 6:
                c.alignment = Alignment(horizontal='right', vertical='center')
            if ci == 8:
                sc(c, bold=True, color="166534", bg=bg)
            if ci == 9:
                sc(c, bold=True, color="7F1D1D", bg=bg)
            if ci == 10:
                sc(c, bold=True, color="1d4ed8", bg=bg)

    # ── Ligne totaux ──────────────────────────────────────────────────────────
    tr = len(sessions) + 5
    ws.merge_cells(f'A{tr}:G{tr}')
    tc = ws.cell(row=tr, column=1, value=f"TOTAL — {teacher.full_name}")
    sc(tc, bold=True, bg="DCFCE7", color="166534")
    tc.alignment = Alignment(horizontal='right', vertical='center')
    for col, val, clr in [
        (8, float(total),        "166534"),
        (9, float(total_impots), "7F1D1D"),
        (10, float(total_net),   "1d4ed8"),
    ]:
        c = ws.cell(row=tr, column=col, value=val)
        sc(c, bold=True, bg="DCFCE7", color=clr)
        c.alignment = Alignment(horizontal='right', vertical='center')

    # ── Émargement ────────────────────────────────────────────────────────────
    em_row = tr + 2
    ws.merge_cells(f'A{em_row}:D{em_row}')
    em_c = ws.cell(row=em_row, column=1, value="Émargement de l'enseignant :")
    sc(em_c, bold=True)
    ws.merge_cells(f'E{em_row}:G{em_row}')
    ws.row_dimensions[em_row].height = 28
    for col in range(5, 8):
        ws.cell(row=em_row, column=col).border = brd

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    fname = f"honoraires_{teacher.user.last_name}_{month:02d}_{year}.xlsx"
    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


@login_required
def export_teacher_pdf(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from reportlab.lib         import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles  import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units   import cm
    from reportlab.platypus    import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.enums   import TA_CENTER, TA_RIGHT, TA_LEFT

    result = _build_teacher_export_data(request)
    teacher, year, month, month_name, sessions, total, total_impots, total_net, total_hours, heures_par_niveau = result
    if not teacher:
        messages.error(request, "Enseignant introuvable.")
        return redirect('accounting:dashboard')

    buffer   = io.BytesIO()
    doc      = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                                  leftMargin=1.5*cm, rightMargin=1.5*cm,
                                  topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles   = getSampleStyleSheet()
    navy_hex = '#00173B'

    def pS(name, **kw):
        return ParagraphStyle(name, **kw)

    story = []

    # ── Titre ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"<font color='white'><b>Fiche d'honoraires — {teacher.full_name} — {month_name} {year}</b></font>",
        pS('title_t', backColor=colors.HexColor(navy_hex),
           fontSize=13, textColor=colors.white, alignment=TA_CENTER,
           spaceAfter=4, leading=20, borderPad=6)
    ))
    grade_label = getattr(getattr(teacher, 'grade', None), 'abbreviation', '') or ''
    email_val   = teacher.user.email or ''
    phone_val   = teacher.user.phone or '—'
    synthese_txt = ' &nbsp;—&nbsp; '.join(_teacher_synthese_lines(total_hours, heures_par_niveau))
    story.append(Paragraph(
        f"{grade_label} &nbsp;|&nbsp; Tél. {phone_val} &nbsp;|&nbsp; {email_val} &nbsp;|&nbsp; "
        f"{len(sessions)} séance(s)",
        pS('sub_t', fontSize=8, textColor=colors.HexColor('#64748B'),
           alignment=TA_CENTER, spaceAfter=4)
    ))
    story.append(Paragraph(
        f"<b>SYNTHESE</b> &nbsp;—&nbsp; {synthese_txt}",
        pS('synth_t', fontSize=8.5, textColor=colors.HexColor('#00173B'),
           alignment=TA_CENTER, spaceAfter=10, backColor=colors.HexColor('#EFF6FF'), borderPad=4)
    ))

    # ── Tableau des séances ───────────────────────────────────────────────────
    col_widths = [4.5*cm, 2.5*cm, 4.5*cm, 2.5*cm, 2.5*cm, 1.5*cm, 2.5*cm, 2.8*cm, 2.8*cm, 2.8*cm]
    t_headers  = ['Département', 'Niveau', 'Module (EC)', 'Classe', 'Date',
                  'h', 'Taux/h', 'Montant', 'Impôts 5%', 'Net à payer']
    data = [t_headers]

    slate_bg   = colors.HexColor('#F1F5F9')
    red_color  = colors.HexColor('#DC2626')
    blue_color = colors.HexColor('#0284C7')

    style_cmds = [
        ('BACKGROUND',  (0, 0), (-1, 0), colors.HexColor('#1E3A5F')),
        ('BACKGROUND',  (8, 0), (8, 0),  colors.HexColor('#7F1D1D')),
        ('BACKGROUND',  (9, 0), (9, 0),  colors.HexColor('#1E4D8C')),
        ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
        ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, 0), 8),
        ('ALIGN',       (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE',    (0, 1), (-1, -1), 7.5),
        ('GRID',        (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, slate_bg]),
        ('ALIGN',       (5, 1), (-1, -1), 'RIGHT'),
    ]

    for s in sessions:
        data.append([
            s['dept'].name, str(s['level']), s['subject'].title,
            s['class_group'].name, s['date'].strftime('%d/%m/%Y'),
            f"{float(s['hours']):.1f}h",
            f"{float(s['rate']):,.0f}",
            f"{float(s['amount']):,.0f}",
            Paragraph(f"<font color='#DC2626'>{float(s['impots']):,.0f}</font>",
                      pS('ri', fontSize=7.5, alignment=TA_RIGHT)),
            Paragraph(f"<font color='#0284C7'>{float(s['net']):,.0f}</font>",
                      pS('bi', fontSize=7.5, alignment=TA_RIGHT)),
        ])

    # Ligne total
    tot_row = len(data)
    data.append([
        Paragraph(f"<b>TOTAL — {teacher.full_name}</b>",
                  pS('tl', fontSize=8, alignment=TA_RIGHT)),
        '', '', '', '', f"{float(total_hours):.1f}h", '',
        Paragraph(f"<b><font color='#166534'>{float(total):,.0f} FCFA</font></b>",
                  pS('ta', fontSize=8, alignment=TA_RIGHT)),
        Paragraph(f"<b><font color='#DC2626'>{float(total_impots):,.0f} FCFA</font></b>",
                  pS('tb', fontSize=8, alignment=TA_RIGHT)),
        Paragraph(f"<b><font color='#0284C7'>{float(total_net):,.0f} FCFA</font></b>",
                  pS('tc', fontSize=8, alignment=TA_RIGHT)),
    ])
    style_cmds += [
        ('SPAN',        (0, tot_row), (6, tot_row)),
        ('BACKGROUND',  (0, tot_row), (-1, tot_row), colors.HexColor('#DCFCE7')),
        ('FONTNAME',    (0, tot_row), (-1, tot_row), 'Helvetica-Bold'),
        ('LINEABOVE',   (0, tot_row), (-1, tot_row), 1, colors.HexColor('#86EFAC')),
    ]

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    story.append(Spacer(1, 0.8*cm))

    em_tbl = Table([[
        Paragraph("<b>Émargement de l'enseignant :</b>",
                  pS('em1', fontSize=9, textColor=colors.HexColor('#00173B'), alignment=TA_LEFT)),
        '',
    ]], colWidths=[6*cm, 8*cm])
    em_tbl.setStyle(TableStyle([
        ('LINEBELOW', (1, 0), (1, 0), 0.6, colors.HexColor('#64748B')),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(em_tbl)
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        f"<i>Généré le {date.today().strftime('%d/%m/%Y')}</i>",
        pS('ft', fontSize=7, textColor=colors.HexColor('#94A3B8'), alignment=TA_CENTER)
    ))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    fname = f"honoraires_{teacher.user.last_name}_{month:02d}_{year}.pdf"
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


@login_required
def export_teacher_word(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from docx                        import Document
    from docx.shared                 import Pt, Cm, RGBColor
    from docx.enum.text              import WD_ALIGN_PARAGRAPH
    from docx.enum.table             import WD_ALIGN_VERTICAL
    from docx.oxml.ns                import qn
    from docx.oxml                   import OxmlElement

    result = _build_teacher_export_data(request)
    teacher, year, month, month_name, sessions, total, total_impots, total_net, total_hours, heures_par_niveau = result
    if not teacher:
        messages.error(request, "Enseignant introuvable.")
        return redirect('accounting:dashboard')

    doc = Document()
    for section in doc.sections:
        section.page_width  = Cm(29.7)
        section.page_height = Cm(21.0)
        section.left_margin = section.right_margin = Cm(1.5)
        section.top_margin  = section.bottom_margin = Cm(1.5)

    def set_cell_bg(cell, hex_color):
        tc   = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd  = OxmlElement('w:shd')
        shd.set(qn('w:val'),   'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'),  hex_color)
        tcPr.append(shd)

    def add_run_colored(para, text, bold=False, size=9, rgb=None):
        rn = para.add_run(text)
        rn.bold = bold; rn.font.size = Pt(size)
        if rgb:
            rn.font.color.rgb = rgb
        return rn

    # ── Titre ─────────────────────────────────────────────────────────────────
    title_tbl = doc.add_table(rows=1, cols=1)
    title_tbl.style = 'Table Grid'
    tc_cell = title_tbl.cell(0, 0)
    set_cell_bg(tc_cell, '00173B')
    p = tc_cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_run_colored(p, f"Fiche d'honoraires — {teacher.full_name} — {month_name} {year}",
                    bold=True, size=12, rgb=RGBColor(255, 255, 255))
    doc.add_paragraph()

    grade_label = getattr(getattr(teacher, 'grade', None), 'abbreviation', '') or ''
    email_val   = teacher.user.email or ''
    phone_val   = teacher.user.phone or '—'
    synthese_txt = '   —   '.join(_teacher_synthese_lines(total_hours, heures_par_niveau))
    info_p = doc.add_paragraph()
    info_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_run_colored(info_p,
                    f"{grade_label}  |  Tél. {phone_val}  |  {email_val}  |  "
                    f"{len(sessions)} séance(s)",
                    size=8, rgb=RGBColor(100, 116, 139))
    synth_p = doc.add_paragraph()
    synth_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_run_colored(synth_p, "SYNTHESE — ", bold=True, size=8.5, rgb=RGBColor(0, 23, 59))
    add_run_colored(synth_p, synthese_txt, size=8.5, rgb=RGBColor(0, 23, 59))
    doc.add_paragraph()

    # ── Tableau des séances ───────────────────────────────────────────────────
    h_labels   = ['Département', 'Niveau', 'Module (EC)', 'Classe', 'Date',
                  'h', 'Taux/h', 'Montant', 'Impôts 5%', 'Net à payer']
    col_widths = [Cm(4.2), Cm(2.2), Cm(4.2), Cm(2.2), Cm(2.2),
                  Cm(1.2), Cm(2.2), Cm(2.5), Cm(2.5), Cm(2.5)]

    table = doc.add_table(rows=1, cols=len(h_labels))
    table.style = 'Table Grid'
    hrow = table.rows[0]
    for i, (lbl, w) in enumerate(zip(h_labels, col_widths)):
        cell = hrow.cells[i]
        cell.width = w
        set_cell_bg(cell, '7F1D1D' if i == 8 else ('1E4D8C' if i == 9 else '1E3A5F'))
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_run_colored(p, lbl, bold=True, size=7, rgb=RGBColor(255, 255, 255))

    for idx, s in enumerate(sessions):
        trow = table.add_row()
        bg   = 'FFFFFF' if idx % 2 == 0 else 'F1F5F9'
        vals = [
            s['dept'].name, str(s['level']), s['subject'].title,
            s['class_group'].name, s['date'].strftime('%d/%m/%Y'),
            f"{float(s['hours']):.1f}h",
            f"{float(s['rate']):,.0f}",
            f"{float(s['amount']):,.0f}",
            f"{float(s['impots']):,.0f}",
            f"{float(s['net']):,.0f}",
        ]
        clrs = [None, None, None, None, None, None, None,
                RGBColor(22, 101, 52), RGBColor(220, 38, 38), RGBColor(2, 132, 199)]
        for i, (val, clr) in enumerate(zip(vals, clrs)):
            cell = trow.cells[i]; cell.width = col_widths[i]
            set_cell_bg(cell, bg)
            p = cell.paragraphs[0]
            if i >= 5:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            add_run_colored(p, val, bold=(i >= 7), size=7, rgb=clr)

    # ── Ligne total ───────────────────────────────────────────────────────────
    tot_row = table.add_row()
    set_cell_bg(tot_row.cells[0], 'DCFCE7')
    tot_row.cells[0].merge(tot_row.cells[6])
    p = tot_row.cells[0].paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_run_colored(p, f"TOTAL — {teacher.full_name}", bold=True, size=8,
                    rgb=RGBColor(22, 101, 52))
    for col_idx, (val, clr, bg) in enumerate([
        (f"{float(total):,.0f} FCFA",        RGBColor(22, 101, 52),  'DCFCE7'),
        (f"{float(total_impots):,.0f} FCFA", RGBColor(220, 38, 38),  'FEE2E2'),
        (f"{float(total_net):,.0f} FCFA",    RGBColor(2, 132, 199),  'DBEAFE'),
    ], 7):
        set_cell_bg(tot_row.cells[col_idx], bg)
        p = tot_row.cells[col_idx].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        add_run_colored(p, val, bold=True, size=8, rgb=clr)

    # ── Émargement ────────────────────────────────────────────────────────────
    doc.add_paragraph()
    em_p = doc.add_paragraph()
    add_run_colored(em_p, "Émargement de l'enseignant : ", bold=True, size=9,
                    rgb=RGBColor(0, 23, 59))
    add_run_colored(em_p, "_" * 40, size=9, rgb=RGBColor(100, 116, 139))

    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    fname = f"honoraires_{teacher.user.last_name}_{month:02d}_{year}.docx"
    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


# ---------------------------------------------------------------------------
# Exports annuels (honoraires_annuels → Excel / PDF / Word)
# ---------------------------------------------------------------------------

MONTHS_FR_ANNUEL = {
    1: 'Janvier', 2: 'Février',  3: 'Mars',      4: 'Avril',
    5: 'Mai',     6: 'Juin',     7: 'Juillet',    8: 'Août',
    9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre',
}


def _build_annuel_export_data(request):
    """
    Retourne (all_dept_monthly, acad_year_filter, dept_filter, grand_total)
    en réutilisant la même logique que honoraires_annuels.
    all_dept_monthly = liste de dicts dept avec .years[].months[].
    """
    from .models import TeacherHonoraire
    from django.db.models import Sum, Count
    from decimal import ROUND_HALF_UP

    acad_year_id = request.GET.get('academic_year')
    dept_id      = request.GET.get('department')
    if acad_year_id == 'all':
        acad_year_filter = None
    elif acad_year_id:
        acad_year_filter = AcademicYear.objects.filter(pk=acad_year_id).first()
    else:
        acad_year_filter = AcademicYear.objects.filter(is_current=True).first()
    dept_filter      = Department.objects.filter(pk=dept_id).first()         if dept_id      else None

    qs = TeacherHonoraire.objects.select_related('academic_year', 'department', 'teacher__user')
    if acad_year_filter:
        qs = qs.filter(academic_year=acad_year_filter)
    if dept_filter:
        qs = qs.filter(department=dept_filter)

    # Agrégation mensuelle par dept
    monthly_qs = list(
        qs.values(
            'department__id', 'department__name', 'department__code',
            'academic_year__id', 'academic_year__label', 'academic_year__start_date',
            'session_date__year', 'session_date__month',
        )
        .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
        .order_by('department__name', '-academic_year__start_date',
                  'session_date__year', 'session_date__month')
    )

    teacher_qs = list(
        qs.values(
            'department__id', 'academic_year__id',
            'session_date__year', 'session_date__month',
            'teacher__id',
            'teacher__user__first_name', 'teacher__user__last_name',
        )
        .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
        .order_by('teacher__user__last_name')
    )

    t_map = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in teacher_qs:
        t_map[r['department__id']][r['academic_year__id']][
            (r['session_date__year'], r['session_date__month'])
        ].append(r)

    dept_year_month = defaultdict(lambda: defaultdict(list))
    dept_meta = {}
    for row in monthly_qs:
        did = row['department__id']
        yid = row['academic_year__id']
        dept_meta[did] = {'id': did, 'name': row['department__name'], 'code': row['department__code']}
        mn = row['session_date__month']
        sy = row['session_date__year']
        m_total = row['total'] or Decimal('0')
        m_impots = (m_total * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        dept_year_month[did][yid].append({
            'month_num':   mn,
            'month_year':  sy,
            'month_label': f"{MONTHS_FR_ANNUEL.get(mn, mn)} {sy}",
            'total':       m_total,
            'impots':      m_impots,
            'net':         m_total - m_impots,
            'seances':     row['seances'] or 0,
            'heures':      row['heures'] or Decimal('0'),
            'teachers':    sorted(t_map[did][yid][(sy, mn)], key=lambda t: t['teacher__user__last_name']),
        })

    year_totals_qs = list(
        qs.values('department__id', 'department__name',
                  'academic_year__id', 'academic_year__label', 'academic_year__start_date')
          .annotate(total=Sum('amount'), seances=Count('id'), heures=Sum('duration_hours'))
          .order_by('department__name', '-academic_year__start_date')
    )
    dept_year_totals = defaultdict(list)
    for yt in year_totals_qs:
        did = yt['department__id']
        yid = yt['academic_year__id']
        total = yt['total'] or Decimal('0')
        impots = (total * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        dept_year_totals[did].append({
            'year_id':    yid,
            'year_label': yt['academic_year__label'],
            'total':      total,
            'impots':     impots,
            'net':        total - impots,
            'seances':    yt['seances'] or 0,
            'heures':     yt['heures'] or Decimal('0'),
            'months':     dept_year_month[did].get(yid, []),
        })

    result = []
    for did, meta in sorted(dept_meta.items(), key=lambda x: x[1]['name']):
        years = dept_year_totals[did]
        dept_total = sum(y['total']  for y in years)
        dept_impots = (dept_total * Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        result.append({
            'dept':         meta,
            'dept_total':   dept_total,
            'dept_impots':  dept_impots,
            'dept_net':     dept_total - dept_impots,
            'dept_seances': sum(y['seances'] for y in years),
            'dept_heures':  sum(y['heures']  for y in years),
            'years':        years,
        })

    grand_total = sum(d['dept_total'] for d in result)
    return result, acad_year_filter, dept_filter, grand_total


@login_required
def export_annuel_excel(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    all_dept_monthly, acad_year_filter, dept_filter, grand_total = _build_annuel_export_data(request)

    suffix = acad_year_filter.label if acad_year_filter else "Toutes années"
    dept_label = dept_filter.name if dept_filter else "Tous départements"

    wb = openpyxl.Workbook()

    navy   = "00173B"
    mid    = "1E3A5F"
    green  = "DCFCE7"
    blue   = "DBEAFE"
    amber  = "FEF3C7"
    slate  = "F8FAFC"

    thin = Side(style='thin', color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def sc(cell, bold=False, color="1E293B", bg=None, align="left", size=9, wrap=False):
        cell.font = Font(bold=bold, color=color, size=size)
        cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=wrap)
        if bg:
            cell.fill = PatternFill("solid", fgColor=bg)
        cell.border = border

    red_bg  = "7F1D1D"
    blue2   = "1E3A5F"

    def make_header(ws, title_text, subtitle_text, ncols=7):
        end = get_column_letter(ncols)
        ws.merge_cells(f'A1:{end}1')
        ws['A1'] = title_text
        ws['A1'].font = Font(bold=True, color="FFFFFF", size=13)
        ws['A1'].fill = PatternFill("solid", fgColor=navy)
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 28

        ws.merge_cells(f'A2:{end}2')
        ws['A2'] = subtitle_text
        ws['A2'].font = Font(italic=True, color="64748B", size=8)
        ws['A2'].alignment = Alignment(horizontal='center')

    # ── Feuille 1 : Synthèse globale ─────────────────────────────────────────
    ws_global = wb.active
    ws_global.title = "Synthèse globale"
    make_header(ws_global,
                f"Honoraires Annuels — {suffix}",
                f"ISI — Généré le {date.today().strftime('%d/%m/%Y')} | {dept_label}", ncols=6)

    hdrs = ['Département', 'Année académique', 'Total (FCFA)', 'Impôts 5% (FCFA)', 'Net à payer (FCFA)', 'SYNTHESE']
    col_w = [30, 20, 18, 16, 18, 12]
    for i, (h, w) in enumerate(zip(hdrs, col_w), 1):
        c = ws_global.cell(row=4, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF", size=9)
        fill_c = mid
        if i == 4: fill_c = red_bg
        c.fill = PatternFill("solid", fgColor=fill_c)
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = border
        ws_global.column_dimensions[get_column_letter(i)].width = w
    ws_global.row_dimensions[4].height = 18

    row = 5
    grand_impots_val = Decimal('0')
    grand_net_val    = Decimal('0')
    for db in all_dept_monthly:
        first_dept = True
        for yr in db['years']:
            ws_global.cell(row=row, column=1, value=f"{db['dept']['code']} — {db['dept']['name']}" if first_dept else '')
            ws_global.cell(row=row, column=2, value=yr['year_label'])
            ws_global.cell(row=row, column=3, value=float(yr['total']))
            ws_global.cell(row=row, column=4, value=float(yr['impots']))
            ws_global.cell(row=row, column=5, value=float(yr['net']))
            ws_global.cell(row=row, column=6, value=f"{float(yr['heures']):.1f}h")
            for col in range(1, 7):
                cell = ws_global.cell(row=row, column=col)
                sc(cell, bg="F8FAFC" if not first_dept else None)
                if col in (3, 4, 5, 6):
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                if col in (3, 4, 5):
                    cell.number_format = '#,##0'
            first_dept = False
            row += 1

        # Sous-total dept
        ws_global.merge_cells(f'A{row}:B{row}')
        c = ws_global.cell(row=row, column=1, value=f"Sous-total {db['dept']['name']}")
        sc(c, bold=True, bg=blue, align='right')
        c3 = ws_global.cell(row=row, column=3, value=float(db['dept_total']))
        sc(c3, bold=True, bg=blue, align='right'); c3.number_format = '#,##0'
        c4 = ws_global.cell(row=row, column=4, value=float(db['dept_impots']))
        sc(c4, bold=True, bg="FEE2E2", align='right'); c4.number_format = '#,##0'
        c5 = ws_global.cell(row=row, column=5, value=float(db['dept_net']))
        sc(c5, bold=True, bg=blue, align='right'); c5.number_format = '#,##0'
        ws_global.cell(row=row, column=6, value=f"{float(db['dept_heures']):.1f}h").fill = PatternFill("solid", fgColor=blue)
        grand_impots_val += db['dept_impots']
        grand_net_val    += db['dept_net']
        row += 1

    # Grand total
    ws_global.merge_cells(f'A{row}:B{row}')
    c = ws_global.cell(row=row, column=1, value="TOTAL GÉNÉRAL")
    sc(c, bold=True, bg="166534", color="FFFFFF", size=10, align='right')
    c3 = ws_global.cell(row=row, column=3, value=float(grand_total))
    sc(c3, bold=True, bg="166534", color="FFFFFF", size=10, align='right'); c3.number_format = '#,##0'
    c4 = ws_global.cell(row=row, column=4, value=float(grand_impots_val))
    sc(c4, bold=True, bg="FEE2E2", color=red_bg, size=10, align='right'); c4.number_format = '#,##0'
    c5 = ws_global.cell(row=row, column=5, value=float(grand_net_val))
    sc(c5, bold=True, bg="166534", color="FFFFFF", size=10, align='right'); c5.number_format = '#,##0'

    # ── Feuilles par département ──────────────────────────────────────────────
    for db in all_dept_monthly:
        ws = wb.create_sheet(title=db['dept']['code'][:31])
        make_header(ws,
                    f"Honoraires — {db['dept']['name']} — {suffix}",
                    f"ISI — Généré le {date.today().strftime('%d/%m/%Y')}", ncols=7)

        hdrs2 = ['Mois', 'Année académique', 'Total (FCFA)', 'Impôts 5%', 'Net à payer', 'SYNTHESE', 'Enseignants']
        col_w2 = [18, 18, 16, 14, 16, 12, 50]
        for i, (h, w) in enumerate(zip(hdrs2, col_w2), 1):
            c = ws.cell(row=4, column=i, value=h)
            c.font = Font(bold=True, color="FFFFFF", size=9)
            fill_c = mid
            if i == 4: fill_c = red_bg
            c.fill = PatternFill("solid", fgColor=fill_c)
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.border = border
            ws.column_dimensions[get_column_letter(i)].width = w

        row2 = 5
        for yr in db['years']:
            # Titre année
            ws.merge_cells(f'A{row2}:G{row2}')
            c = ws.cell(row=row2, column=1, value=f"Année académique : {yr['year_label']}")
            sc(c, bold=True, bg=amber, color="92400E")
            row2 += 1

            for m in yr['months']:
                teacher_names = ', '.join(
                    f"{(t['teacher__user__first_name'] or '')[:1]}{'.' if t['teacher__user__first_name'] else ''}"
                    f"{t['teacher__user__last_name']} ({float(t['total']):,.0f} F)"
                    for t in m['teachers']
                )
                ws.cell(row=row2, column=1, value=m['month_label'])
                ws.cell(row=row2, column=2, value=yr['year_label'])
                ws.cell(row=row2, column=3, value=float(m['total']))
                ws.cell(row=row2, column=4, value=float(m['impots']))
                ws.cell(row=row2, column=5, value=float(m['net']))
                ws.cell(row=row2, column=6, value=f"{float(m['heures']):.1f}h")
                ws.cell(row=row2, column=7, value=teacher_names)
                for col in range(1, 8):
                    cell = ws.cell(row=row2, column=col)
                    sc(cell, bg="F8FAFC" if row2 % 2 == 0 else None, wrap=(col == 7))
                    if col in (3, 4, 5, 6):
                        cell.alignment = Alignment(horizontal='right', vertical='center')
                    if col in (3, 4, 5):
                        cell.number_format = '#,##0'
                row2 += 1

            # Sous-total année
            ws.merge_cells(f'A{row2}:B{row2}')
            c = ws.cell(row=row2, column=1, value=f"Total {yr['year_label']}")
            sc(c, bold=True, bg=blue, align='right')
            c3 = ws.cell(row=row2, column=3, value=float(yr['total']))
            sc(c3, bold=True, bg=blue, align='right'); c3.number_format = '#,##0'
            c4 = ws.cell(row=row2, column=4, value=float(yr['impots']))
            sc(c4, bold=True, bg="FEE2E2", align='right'); c4.number_format = '#,##0'
            c5 = ws.cell(row=row2, column=5, value=float(yr['net']))
            sc(c5, bold=True, bg=blue, align='right'); c5.number_format = '#,##0'
            ws.cell(row=row2, column=6, value=f"{float(yr['heures']):.1f}h").fill = PatternFill("solid", fgColor=blue)
            row2 += 1

        # Total département
        ws.merge_cells(f'A{row2}:B{row2}')
        c = ws.cell(row=row2, column=1, value=f"TOTAL {db['dept']['name'].upper()}")
        sc(c, bold=True, bg="166534", color="FFFFFF", size=10, align='right')
        c3 = ws.cell(row=row2, column=3, value=float(db['dept_total']))
        sc(c3, bold=True, bg="166534", color="FFFFFF", size=10, align='right'); c3.number_format = '#,##0'
        c4 = ws.cell(row=row2, column=4, value=float(db['dept_impots']))
        sc(c4, bold=True, bg="FEE2E2", color=red_bg, size=10, align='right'); c4.number_format = '#,##0'
        c5 = ws.cell(row=row2, column=5, value=float(db['dept_net']))
        sc(c5, bold=True, bg="166534", color="FFFFFF", size=10, align='right'); c5.number_format = '#,##0'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    slug = (dept_filter.code if dept_filter else "global").replace(' ', '_')
    ay_slug = (acad_year_filter.label if acad_year_filter else "all").replace('-', '_').replace(' ', '')
    filename = f"honoraires_annuels_{slug}_{ay_slug}.xlsx"
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_annuel_pdf(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from academic_core.pdf_utils import logo_image as _logo_img_a_fn, get_institut_config_for_request as _gcfr_a
    _inst_cfg_a = _gcfr_a(request)
    _logo_img_a = lambda **kw: _logo_img_a_fn(config=_inst_cfg_a, **kw)  # noqa: E731

    all_dept_monthly, acad_year_filter, dept_filter, grand_total = _build_annuel_export_data(request)

    suffix     = acad_year_filter.label if acad_year_filter else "Toutes années"
    dept_label = dept_filter.name if dept_filter else "Tous les départements"

    navy       = colors.HexColor('#00173B')
    navy_mid   = colors.HexColor('#1E3A5F')
    green      = colors.HexColor('#166534')
    light_green= colors.HexColor('#DCFCE7')
    blue_bg    = colors.HexColor('#DBEAFE')
    amber_bg   = colors.HexColor('#FEF3C7')
    slate_bg   = colors.HexColor('#F8FAFC')
    white      = colors.white
    accent     = colors.HexColor('#F59E0B')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    pS = ParagraphStyle
    story = []

    _logo_a = _logo_img_a(width=2.0*cm, height=1.3*cm)

    def banner(title_text, sub_text):
        hd = [[
            Paragraph(f'<font color="white" size="14"><b>{title_text}</b></font>',
                      pS('hd', fontName='Helvetica-Bold', alignment=TA_LEFT)),
            Paragraph(f'<font color="white" size="8"><b>Institut Supérieur d\'Informatique - ISI</b></font><br/>'
                      f'<font color="#94A3B8" size="7">{sub_text}</font>',
                      pS('hd2', fontName='Helvetica', alignment=TA_RIGHT)),
            _logo_a or Paragraph('<font color="white" size="9"><b>ISI</b></font>', pS('hd3', fontName='Helvetica-Bold', alignment=TA_RIGHT)),
        ]]
        t = Table(hd, colWidths=[13*cm, 10*cm, 3.5*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), navy),
            ('TOPPADDING',    (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING',   (0, 0), (0, -1), 16),
            ('RIGHTPADDING',  (-1, 0), (-1, -1), 16),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return t

    # ── Page 1 : Synthèse globale ─────────────────────────────────────────────
    story.append(banner(f"HONORAIRES ANNUELS — {suffix.upper()}", dept_label))
    story.append(Spacer(1, 0.4*cm))

    glob_data = [['Département', 'Année académique', 'Total (FCFA)', 'Impôts 5%', 'Net à payer', 'SYNTHESE']]
    glob_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), navy_mid),
        ('BACKGROUND', (3, 0), (3, 0), colors.HexColor('#7F1D1D')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('FONTNAME',   (0, 1), (-1, -1), 'Helvetica'),
        ('GRID',       (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    dr = 1
    _gpiv = Decimal('0')
    _gpnv = Decimal('0')
    for db in all_dept_monthly:
        first_dept = True
        for yr in db['years']:
            glob_data.append([
                f"{db['dept']['code']} — {db['dept']['name']}" if first_dept else '',
                yr['year_label'],
                f"{float(yr['total']):,.0f}",
                f"{float(yr['impots']):,.0f}",
                f"{float(yr['net']):,.0f}",
                f"{float(yr['heures']):.1f}h",
            ])
            if dr % 2 == 0:
                glob_cmds.append(('BACKGROUND', (0, dr), (-1, dr), slate_bg))
            glob_cmds.append(('ALIGN', (2, dr), (-1, dr), 'RIGHT'))
            glob_cmds.append(('TEXTCOLOR', (3, dr), (3, dr), colors.HexColor('#DC2626')))
            glob_cmds.append(('TEXTCOLOR', (4, dr), (4, dr), colors.HexColor('#0284C7')))
            first_dept = False
            dr += 1
        # Sous-total dept
        glob_data.append([f"Sous-total {db['dept']['name']}", '', f"{float(db['dept_total']):,.0f}",
                          f"{float(db['dept_impots']):,.0f}", f"{float(db['dept_net']):,.0f}",
                          f"{float(db['dept_heures']):.1f}h"])
        glob_cmds += [
            ('BACKGROUND', (0, dr), (-1, dr), blue_bg),
            ('FONTNAME',   (0, dr), (-1, dr), 'Helvetica-Bold'),
            ('ALIGN',      (2, dr), (-1, dr), 'RIGHT'),
            ('SPAN',       (0, dr), (1, dr)),
        ]
        _gpiv += db['dept_impots']
        _gpnv += db['dept_net']
        dr += 1
    # Grand total
    grand_heures = sum(db['dept_heures'] for db in all_dept_monthly)
    glob_data.append(['TOTAL GÉNÉRAL', '', f"{float(grand_total):,.0f} FCFA",
                      f"{float(_gpiv):,.0f}", f"{float(_gpnv):,.0f}", f"{float(grand_heures):.1f}h"])
    glob_cmds += [
        ('BACKGROUND', (0, dr), (-1, dr), light_green),
        ('BACKGROUND', (3, dr), (3, dr), colors.HexColor('#FEE2E2')),
        ('TEXTCOLOR',  (0, dr), (-1, dr), green),
        ('TEXTCOLOR',  (3, dr), (3, dr), colors.HexColor('#7F1D1D')),
        ('FONTNAME',   (0, dr), (-1, dr), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, dr), (-1, dr), 9),
        ('ALIGN',      (2, dr), (-1, dr), 'RIGHT'),
        ('SPAN',       (0, dr), (1, dr)),
        ('LINEABOVE',  (0, dr), (-1, dr), 1.5, accent),
    ]

    t = Table(glob_data, colWidths=[7*cm, 4.5*cm, 3.5*cm, 3*cm, 3.5*cm, 3*cm], repeatRows=1)
    t.setStyle(TableStyle(glob_cmds))
    story.append(t)

    # ── Pages par département ─────────────────────────────────────────────────
    for db in all_dept_monthly:
        story.append(PageBreak())
        story.append(banner(
            f"{db['dept']['code']} — {db['dept']['name']} — {suffix}",
            f"Total : {float(db['dept_total']):,.0f} FCFA · {db['dept_seances']} séances · {float(db['dept_heures']):.1f}h"
        ))
        story.append(Spacer(1, 0.3*cm))

        for yr in db['years']:
            # Titre année
            yr_t = Table([[Paragraph(
                f'<font size="9" color="#92400E"><b>Année académique : {yr["year_label"]}</b></font>',
                pS('yt', fontName='Helvetica-Bold'))
            ]], colWidths=[25*cm])
            yr_t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), amber_bg),
                ('TOPPADDING',    (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING',   (0, 0), (-1, -1), 12),
            ]))
            story.append(yr_t)

            m_data = [['Mois', 'Total (FCFA)', 'Impôts 5%', 'Net à payer', 'SYNTHESE', 'Enseignants']]
            m_cmds = [
                ('BACKGROUND', (0, 0), (-1, 0), navy_mid),
                ('BACKGROUND', (2, 0), (2, 0), colors.HexColor('#7F1D1D')),
                ('BACKGROUND', (3, 0), (3, 0), colors.HexColor('#1E3A5F')),
                ('TEXTCOLOR',  (0, 0), (-1, 0), white),
                ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE',   (0, 0), (-1, 0), 8),
                ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTSIZE',   (0, 1), (-1, -1), 7.5),
                ('FONTNAME',   (0, 1), (-1, -1), 'Helvetica'),
                ('GRID',       (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
            mr = 1
            for m in yr['months']:
                teacher_str = ', '.join(
                    f"{t['teacher__user__first_name'][0] if t['teacher__user__first_name'] else ''}.{t['teacher__user__last_name']} ({float(t['total']):,.0f}F)"
                    for t in m['teachers']
                )
                m_data.append([
                    m['month_label'],
                    f"{float(m['total']):,.0f}",
                    f"{float(m['impots']):,.0f}",
                    f"{float(m['net']):,.0f}",
                    f"{float(m['heures']):.1f}h",
                    Paragraph(teacher_str, pS('ts', fontName='Helvetica', fontSize=7)),
                ])
                if mr % 2 == 0:
                    m_cmds.append(('BACKGROUND', (0, mr), (-1, mr), slate_bg))
                m_cmds.append(('ALIGN', (1, mr), (4, mr), 'RIGHT'))
                m_cmds.append(('TEXTCOLOR', (2, mr), (2, mr), colors.HexColor('#DC2626')))
                m_cmds.append(('TEXTCOLOR', (3, mr), (3, mr), colors.HexColor('#0284C7')))
                mr += 1

            # Sous-total année
            m_data.append([f"Total {yr['year_label']}", f"{float(yr['total']):,.0f} FCFA",
                            f"{float(yr['impots']):,.0f}", f"{float(yr['net']):,.0f}",
                            f"{float(yr['heures']):.1f}h", ''])
            m_cmds += [
                ('BACKGROUND', (0, mr), (-1, mr), blue_bg),
                ('FONTNAME',   (0, mr), (-1, mr), 'Helvetica-Bold'),
                ('ALIGN',      (1, mr), (4, mr), 'RIGHT'),
                ('LINEABOVE',  (0, mr), (-1, mr), 1, colors.HexColor('#93C5FD')),
            ]

            mt = Table(m_data, colWidths=[3.5*cm, 3*cm, 2.8*cm, 3*cm, 2.4*cm, 10.3*cm], repeatRows=1)
            mt.setStyle(TableStyle(m_cmds))
            story.append(mt)
            story.append(Spacer(1, 0.3*cm))

        # Total département
        total_t = Table([[
            Paragraph(
                f'<font size="10" color="#166534"><b>TOTAL {db["dept"]["name"].upper()} : {float(db["dept_total"]):,.0f} FCFA</b></font>'
                f'<br/><font size="8" color="#DC2626">Impôts : {float(db["dept_impots"]):,.0f} FCFA</font>'
                f'&nbsp;&nbsp;<font size="9" color="#0284C7"><b>Net : {float(db["dept_net"]):,.0f} FCFA</b></font>',
                pS('tot', fontName='Helvetica-Bold', alignment=TA_RIGHT))
        ]], colWidths=[25*cm])
        total_t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), light_green),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
            ('LINEABOVE',     (0, 0), (-1, 0), 2, colors.HexColor('#86EFAC')),
        ]))
        story.append(total_t)

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    slug  = (dept_filter.code if dept_filter else "global").replace(' ', '_')
    ay_sl = (acad_year_filter.label if acad_year_filter else "all").replace('-', '_').replace(' ', '')
    filename = f"honoraires_annuels_{slug}_{ay_sl}.pdf"
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_annuel_word(request):
    if not _require_accounting_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    all_dept_monthly, acad_year_filter, dept_filter, grand_total = _build_annuel_export_data(request)

    suffix     = acad_year_filter.label if acad_year_filter else "Toutes années"

    def set_bg(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color)
        shd.set(qn('w:val'), 'clear')
        tcPr.append(shd)

    def add_cell(row, idx, text, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT, size=8, color=None, bg=None):
        cell = row.cells[idx]
        if bg:
            set_bg(cell, bg)
        p = cell.paragraphs[0]
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor(*[int(color[i:i+2], 16) for i in (0, 2, 4)])
        p.alignment = align
        return cell

    doc = Document()
    section = doc.sections[0]
    from docx.shared import Inches
    section.page_width   = Inches(13)
    section.page_height  = Inches(9)
    section.left_margin  = Cm(1.5)
    section.right_margin = Cm(1.5)
    section.top_margin   = Cm(1.5)
    section.bottom_margin= Cm(1.5)

    # ── Titre global ──────────────────────────────────────────────────────────
    ttl = doc.add_heading('', level=0)
    r = ttl.add_run(f"Honoraires Annuels — {suffix}")
    r.font.color.rgb = RGBColor(0, 23, 59)
    r.font.size = Pt(16)
    ttl.alignment = WD_ALIGN_PARAGRAPH.CENTER

    s = doc.add_paragraph()
    sr = s.add_run(f"Institut Supérieur d'Informatique - ISI  |  Généré le {date.today().strftime('%d/%m/%Y')}")
    sr.font.size = Pt(9)
    sr.font.color.rgb = RGBColor(100, 116, 139)
    s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # ── Tableau synthèse ──────────────────────────────────────────────────────
    h2 = doc.add_heading('Synthèse globale', level=2)
    h2.runs[0].font.color.rgb = RGBColor(0, 23, 59)

    t_glob = doc.add_table(rows=1, cols=6)
    t_glob.style = 'Table Grid'
    hdrs_g = ['Département', 'Année académique', 'Total (FCFA)', 'Impôts 5%', 'Net à payer', 'SYNTHESE']
    hdr_bgs = ['1E3A5F', '1E3A5F', '1E3A5F', '7F1D1D', '1E3A5F', '1E3A5F']
    for i, (h, bg) in enumerate(zip(hdrs_g, hdr_bgs)):
        add_cell(t_glob.rows[0], i, h, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                 size=8, color='FFFFFF', bg=bg)

    for db in all_dept_monthly:
        first_dept = True
        for yr in db['years']:
            row = t_glob.add_row()
            add_cell(row, 0, f"{db['dept']['code']} — {db['dept']['name']}" if first_dept else '', size=8)
            add_cell(row, 1, yr['year_label'], size=8)
            add_cell(row, 2, f"{float(yr['total']):,.0f}", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT)
            add_cell(row, 3, f"{float(yr['impots']):,.0f}", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT, color='7F1D1D')
            add_cell(row, 4, f"{float(yr['net']):,.0f}", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT, color='0284C7')
            add_cell(row, 5, f"{float(yr['heures']):.1f}h", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT)
            first_dept = False

        # Sous-total dept
        st = t_glob.add_row()
        for i in range(6): set_bg(st.cells[i], 'DBEAFE')
        st.cells[0].merge(st.cells[1])
        add_cell(st, 0, f"Sous-total {db['dept']['name']}", bold=True,
                 align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='DBEAFE')
        add_cell(st, 2, f"{float(db['dept_total']):,.0f}", bold=True,
                 align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='DBEAFE')
        add_cell(st, 3, f"{float(db['dept_impots']):,.0f}", bold=True,
                 align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='FEE2E2', color='7F1D1D')
        add_cell(st, 4, f"{float(db['dept_net']):,.0f}", bold=True,
                 align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='DBEAFE', color='0284C7')
        add_cell(st, 5, f"{float(db['dept_heures']):.1f}h", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT, bg='DBEAFE')

    _giv = sum(db['dept_impots'] for db in all_dept_monthly)
    _gnv = sum(db['dept_net']    for db in all_dept_monthly)
    _ghv = sum(db['dept_heures'] for db in all_dept_monthly)
    gt = t_glob.add_row()
    for i in range(6): set_bg(gt.cells[i], 'DCFCE7')
    gt.cells[0].merge(gt.cells[1])
    add_cell(gt, 0, "TOTAL GÉNÉRAL", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
             size=10, color='166534', bg='DCFCE7')
    add_cell(gt, 2, f"{float(grand_total):,.0f} FCFA", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
             size=10, color='166534', bg='DCFCE7')
    add_cell(gt, 3, f"{float(_giv):,.0f}", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
             size=9, color='7F1D1D', bg='FEE2E2')
    add_cell(gt, 4, f"{float(_gnv):,.0f} FCFA", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
             size=9, color='0284C7', bg='DCFCE7')
    add_cell(gt, 5, f"{float(_ghv):.1f}h", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
             size=9, color='166534', bg='DCFCE7')
    doc.add_paragraph()

    # ── Détail mensuel par département ────────────────────────────────────────
    for db in all_dept_monthly:
        doc.add_page_break()
        h2 = doc.add_heading(f"{db['dept']['code']} — {db['dept']['name']}", level=2)
        h2.runs[0].font.color.rgb = RGBColor(0, 23, 59)

        tot_p = doc.add_paragraph()
        tot_r = tot_p.add_run(f"Total : {float(db['dept_total']):,.0f} FCFA  |  Impôts 5% : {float(db['dept_impots']):,.0f} FCFA  |  Net : {float(db['dept_net']):,.0f} FCFA  |  {db['dept_seances']} séances")
        tot_r.font.size = Pt(9)
        tot_r.font.color.rgb = RGBColor(22, 101, 52)
        tot_r.bold = True

        for yr in db['years']:
            yr_p = doc.add_paragraph()
            yr_r = yr_p.add_run(f"Année académique : {yr['year_label']}")
            yr_r.bold = True
            yr_r.font.size = Pt(9)
            yr_r.font.color.rgb = RGBColor(146, 64, 14)

            t_m = doc.add_table(rows=1, cols=6)
            t_m.style = 'Table Grid'
            hdrs_m = ['Mois', 'Total (FCFA)', 'Impôts 5%', 'Net à payer', 'SYNTHESE', 'Enseignants']
            hdr_bgs_m = ['1E3A5F', '1E3A5F', '7F1D1D', '1E3A5F', '1E3A5F', '1E3A5F']
            for i, (h, bg) in enumerate(zip(hdrs_m, hdr_bgs_m)):
                add_cell(t_m.rows[0], i, h, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                         size=8, color='FFFFFF', bg=bg)

            for m in yr['months']:
                row = t_m.add_row()
                teacher_str = ', '.join(
                    f"{t['teacher__user__first_name'][0] if t['teacher__user__first_name'] else ''}.{t['teacher__user__last_name']} ({float(t['total']):,.0f}F)"
                    for t in m['teachers']
                )
                add_cell(row, 0, m['month_label'], size=8)
                add_cell(row, 1, f"{float(m['total']):,.0f}", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT)
                add_cell(row, 2, f"{float(m['impots']):,.0f}", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT, color='7F1D1D')
                add_cell(row, 3, f"{float(m['net']):,.0f}", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT, color='0284C7')
                add_cell(row, 4, f"{float(m['heures']):.1f}h", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT)
                add_cell(row, 5, teacher_str, size=7.5)

            # Sous-total année
            st = t_m.add_row()
            for i in range(6): set_bg(st.cells[i], 'DBEAFE')
            add_cell(st, 0, f"Total {yr['year_label']}", bold=True, size=8, bg='DBEAFE')
            add_cell(st, 1, f"{float(yr['total']):,.0f} FCFA", bold=True,
                     align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='DBEAFE')
            add_cell(st, 2, f"{float(yr['impots']):,.0f}", bold=True,
                     align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='FEE2E2', color='7F1D1D')
            add_cell(st, 3, f"{float(yr['net']):,.0f}", bold=True,
                     align=WD_ALIGN_PARAGRAPH.RIGHT, size=8, bg='DBEAFE', color='0284C7')
            add_cell(st, 4, f"{float(yr['heures']):.1f}h", size=8, align=WD_ALIGN_PARAGRAPH.RIGHT, bg='DBEAFE')
            doc.add_paragraph()

    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    slug  = (dept_filter.code if dept_filter else "global").replace(' ', '_')
    ay_sl = (acad_year_filter.label if acad_year_filter else "all").replace('-', '_').replace(' ', '')
    filename = f"honoraires_annuels_{slug}_{ay_sl}.docx"
    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ===========================================================================
# VALIDATION INSCRIPTION
# ===========================================================================

_COMPTABLE_ROLES = ('COMPTABLE', 'TRESORIER_GENERAL', 'CAISSIER')

def _require_inscription_access(user):
    # user.is_admin() couvre déjà ADMIN, INST_ADMIN, SI_ADMIN, CONTROLEUR,
    # COMPTABLE, TRESORIER_GENERAL, CAISSIER, etc. — utiliser cette méthode
    # (plutôt qu'un contrôle littéral sur role_name) pour que l'Administrateur
    # d'institut ait bien un accès réel, pas seulement visible dans le menu.
    return user.is_admin() or user.is_responsable()


@login_required
def validation_inscription_list(request):
    # Le Caissier ne fait pas partie du public de cette page de gestion
    # (création/liste complète des inscriptions) — sa page de travail est
    # « La Caisse », où il traite les dossiers déjà envoyés par le Trésorier.
    if request.user.is_caissier():
        return redirect('accounting:caisse_dashboard')
    if not _require_inscription_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment
    from academic_core.apps.academic_structure.models import AcademicYear
    from .models import CaissePayment
    from django.db.models import Q, Sum

    status_filter = request.GET.get('status', '')
    year_filter   = request.GET.get('academic_year', '')
    search        = request.GET.get('q', '').strip()

    # Contrôleur et comptable : vision globale, pas de filtre faculté
    _global_view = request.user.is_controleur() or request.user.is_comptable()
    faculty = None if _global_view else getattr(request, 'active_faculty', None)

    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=faculty) if faculty else academic_years

    # Année académique : par défaut l'année en cours — les inscriptions d'une
    # année précédente ne doivent pas apparaître mélangées avec l'année en
    # cours. "Toutes les années" (academic_year=all) reste sélectionnable
    # explicitement pour consulter l'historique.
    if year_filter == 'all':
        selected_year_id = None
    elif year_filter:
        selected_year_id = year_filter
    else:
        current_year = academic_years.filter(is_current=True).first()
        selected_year_id = current_year.pk if current_year else None

    qs = Enrollment.objects.select_related(
        'student__user', 'class_group__program__department',
        'class_group__level', 'academic_year', 'validated_by', 'previous_class',
    ).order_by('-enrollment_date', '-id')

    if faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if selected_year_id:
        qs = qs.filter(academic_year_id=selected_year_id)
    if search:
        qs = qs.filter(
            Q(student__matricule__icontains=search) |
            Q(student__user__first_name__icontains=search) |
            Q(student__user__last_name__icontains=search)
        )

    # Précalculer les paiements caisse par (student_id, academic_year_id) pour les inscriptions
    # sans payment_amount — utilisé en fallback dans le template
    caisse_totals = {}
    caisse_qs = (CaissePayment.objects
                 .filter(payment_type=CaissePayment.TYPE_INSCRIPTION)
                 .values('student_id', 'academic_year_id')
                 .annotate(total=Sum('amount')))
    for row in caisse_qs:
        caisse_totals[(row['student_id'], row['academic_year_id'])] = row['total']

    # Annoter chaque enrollment avec effective_payment_amount
    enrollments_list = list(qs)
    for enr in enrollments_list:
        if enr.payment_amount:
            enr.effective_payment = enr.payment_amount
        else:
            enr.effective_payment = caisse_totals.get(
                (enr.student_id, enr.academic_year_id), None
            )

    # Les compteurs KPI doivent respecter le même périmètre (institut + année
    # académique sélectionnée) que la liste ci-dessus, sinon ils affichent des
    # totaux toutes années confondues alors que le tableau est déjà filtré.
    base_count = Enrollment.objects.filter(class_group__program__department__faculty=faculty) if faculty else Enrollment.objects.all()
    if selected_year_id:
        base_count = base_count.filter(academic_year_id=selected_year_id)
    counts = {
        'all':            base_count.count(),
        'pending':        base_count.filter(status=Enrollment.STATUS_PENDING).count(),
        'pending_caisse': base_count.filter(status=Enrollment.STATUS_PENDING_CAISSE).count(),
        'validated':      base_count.filter(status=Enrollment.STATUS_VALIDATED).count(),
        'rejected':       base_count.filter(status=Enrollment.STATUS_REJECTED).count(),
    }

    return render(request, 'accounting/validation_inscription_list.html', {
        'enrollments':    enrollments_list,
        'status_filter':  status_filter,
        'year_filter':    year_filter,
        'search':         search,
        'counts':         counts,
        'academic_years': academic_years,
        'STATUS_PENDING':        Enrollment.STATUS_PENDING,
        'STATUS_PENDING_CAISSE': Enrollment.STATUS_PENDING_CAISSE,
        'STATUS_VALIDATED':      Enrollment.STATUS_VALIDATED,
        'STATUS_REJECTED':       Enrollment.STATUS_REJECTED,
    })


@login_required
def enrollment_update_payment(request, pk):
    """Met à jour le montant versé et la date de paiement d'une inscription depuis la liste."""
    from django.http import JsonResponse
    from academic_core.apps.students.models import Enrollment

    if not _require_inscription_access(request.user):
        return JsonResponse({'ok': False, 'error': 'Accès refusé.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Méthode non autorisée.'}, status=405)

    enrollment = get_object_or_404(Enrollment, pk=pk)
    amount_raw = request.POST.get('payment_amount', '').strip()
    date_raw   = request.POST.get('payment_date', '').strip()
    ref_raw    = request.POST.get('payment_reference', '').strip()

    from decimal import InvalidOperation
    try:
        amount = Decimal(amount_raw.replace(' ', '').replace(',', '.')) if amount_raw else None
    except (InvalidOperation, ValueError):
        return JsonResponse({'ok': False, 'error': 'Montant invalide.'}, status=400)

    enrollment.payment_amount    = amount
    enrollment.payment_date      = date_raw or None
    enrollment.payment_reference = ref_raw
    enrollment.save(update_fields=['payment_amount', 'payment_date', 'payment_reference'])

    return JsonResponse({
        'ok':     True,
        'amount': float(amount) if amount else None,
        'date':   enrollment.payment_date.strftime('%d/%m/%Y') if enrollment.payment_date else '',
    })


@login_required
def validation_inscription_delete(request, pk):
    if request.user.is_caissier():
        return redirect('accounting:caisse_dashboard')
    if not _require_inscription_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment

    enrollment = Enrollment.objects.filter(pk=pk, status=Enrollment.STATUS_PENDING).first()
    if not enrollment:
        messages.error(request, "Inscription introuvable ou déjà validée — suppression impossible.")
        return redirect('accounting:validation_inscription_list')

    if request.method == 'POST':
        nom = str(enrollment.student)
        enrollment.delete()
        messages.success(request, f"Inscription de {nom} supprimée.")
        return redirect('accounting:validation_inscription_list')

    return render(request, 'accounting/validation_inscription_confirm_delete.html', {
        'enrollment': enrollment,
    })


@login_required
def payment_proof_list(request):
    """File d'attente des preuves de paiement déposées par des candidats depuis
    le portail public d'admission — Caissier/Trésorier Général uniquement."""
    if not (request.user.is_caissier() or request.user.is_tresorier() or request.user.is_admin()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import PaymentProof
    proofs = PaymentProof.objects.filter(status=PaymentProof.STATUS_PENDING).select_related(
        'enrollment__student__user', 'enrollment__class_group',
    ).order_by('submitted_at')

    return render(request, 'accounting/payment_proof_list.html', {'proofs': proofs})


@login_required
def payment_proof_detail(request, pk):
    """Validation/rejet d'une preuve de paiement — déclenche
    finalize_enrollment_payment() sur validation (voir accounting/services.py),
    pré-rempli avec le montant/la date déclarés par le candidat."""
    if not (request.user.is_caissier() or request.user.is_tresorier() or request.user.is_admin()):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import PaymentProof
    proof = get_object_or_404(
        PaymentProof.objects.select_related('enrollment__student__user', 'enrollment__class_group'),
        pk=pk,
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'validate':
            if not request.POST.get('proof_reviewed'):
                messages.error(request, "Vous devez confirmer avoir vérifié le justificatif de paiement avant de valider.")
                return redirect('accounting:payment_proof_detail', pk=proof.pk)

            from .services import finalize_enrollment_payment
            finalize_enrollment_payment(
                proof.enrollment,
                payment_date=timezone.now().date(),
                validated_by=request.user,
                notes=f"Réglé par {proof.get_moyen_paiement_display()} — réf. {proof.reference_paiement or 'n/a'} (preuve candidat)",
                request=request,
            )
            proof.status = PaymentProof.STATUS_VALIDATED
            proof.reviewed_by = request.user
            proof.reviewed_at = timezone.now()
            proof.save()
            messages.success(request, f"Paiement validé — {proof.enrollment.student.full_name} inscrit(e).")
            return redirect('accounting:payment_proof_list')

        elif action == 'reject':
            proof.status = PaymentProof.STATUS_REJECTED
            proof.reviewed_by = request.user
            proof.reviewed_at = timezone.now()
            proof.motif_rejet = request.POST.get('motif_rejet', '').strip()
            proof.save()
            from academic_core.apps.notifications.utils import notify_payment_proof_rejected
            notify_payment_proof_rejected(proof, request=request)
            messages.success(request, "Preuve de paiement rejetée.")
            return redirect('accounting:payment_proof_list')

    file_name = (proof.piece_justificative.name or '').lower()
    is_image = file_name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
    is_pdf   = file_name.endswith('.pdf')
    montant_mismatch = (
        proof.enrollment.payment_amount is not None
        and proof.montant_declare is not None
        and proof.montant_declare != proof.enrollment.payment_amount
    )

    return render(request, 'accounting/payment_proof_detail.html', {
        'proof': proof,
        'is_image': is_image,
        'is_pdf': is_pdf,
        'montant_mismatch': montant_mismatch,
    })


@login_required
def validation_inscription_create(request):
    if request.user.is_caissier():
        return redirect('accounting:caisse_dashboard')
    if not _require_inscription_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Student, Enrollment
    from academic_core.apps.academic_structure.models import AcademicYear, Class

    if request.method == 'POST':
        student_id        = request.POST.get('student')
        class_group_id    = request.POST.get('class_group')
        academic_year_id  = request.POST.get('academic_year')
        enroll_type       = request.POST.get('enrollment_type', Enrollment.TYPE_NEW)
        previous_class_id = request.POST.get('previous_class') or None
        payment_amount    = request.POST.get('payment_amount') or None
        payment_date      = request.POST.get('payment_date') or None
        payment_ref       = request.POST.get('payment_reference', '').strip()
        notes             = request.POST.get('notes', '').strip()

        student     = Student.objects.filter(pk=student_id).first()
        class_group = Class.objects.filter(pk=class_group_id).first()
        acad_year   = AcademicYear.objects.filter(pk=academic_year_id).first()

        if not (student and class_group and acad_year):
            messages.error(request, "Étudiant, classe et année académique sont obligatoires.")
        elif Enrollment.objects.filter(student=student, academic_year=acad_year, status=Enrollment.STATUS_VALIDATED).exists():
            messages.error(request, "Cet étudiant possède déjà une inscription validée pour cette année académique.")
        else:
            prev_class = Class.objects.filter(pk=previous_class_id).first() if previous_class_id else None
            enrollment = Enrollment.objects.create(
                student=student, class_group=class_group, academic_year=acad_year,
                enrollment_type=enroll_type, previous_class=prev_class,
                payment_amount=payment_amount, payment_date=payment_date,
                payment_reference=payment_ref, notes=notes,
                status=Enrollment.STATUS_PENDING, is_active=False,
            )
            # Notifier les Trésoriers Généraux et Admins Institut
            try:
                from academic_core.apps.notifications.utils import notify_inscription_pending
                notify_inscription_pending(enrollment, request=request)
            except Exception:
                pass
            messages.success(request, f"Inscription de {student.full_name} créée — en attente de validation.")
            return redirect('accounting:validation_inscription_list')

    # Périmètre institut uniquement ici : le champ "classe précédente" doit
    # rester consultable même pour une classe d'une année antérieure (cas de
    # réinscription), donc pas de restriction à l'année en cours sur ce
    # queryset partagé entre "classe" et "classe précédente".
    faculty = None if (request.user.is_controleur() or request.user.is_comptable()) else getattr(request, 'active_faculty', None)
    classes = Class.objects.select_related('program__department', 'level', 'academic_year').order_by('name')
    academic_years = AcademicYear.objects.order_by('-start_date')
    if faculty:
        classes = classes.filter(program__department__faculty=faculty)
        academic_years = academic_years.filter(faculty=faculty)

    return render(request, 'accounting/validation_inscription_create.html', {
        'students':       Student.objects.select_related('user').order_by('user__last_name'),
        'classes':        classes,
        'academic_years': academic_years,
        'TYPE_NEW':           Enrollment.TYPE_NEW,
        'TYPE_REINSCRIPTION': Enrollment.TYPE_REINSCRIPTION,
    })


def _resolve_required_month(enrollment):
    """
    Retourne le numéro du dernier mois de l'année académique de la classe —
    le mois obligatoirement inclus (« Inclus ») à l'inscription. Même logique
    que celle utilisée pour construire `academic_months` côté affichage, afin
    que le mois traité comme "obligatoire" soit identique à l'affichage et à
    la génération réelle de l'échéancier.
    """
    from .models import AcademicYearDistribution
    from academic_core.db_router import get_current_db
    if not enrollment.class_group or not enrollment.academic_year:
        return None
    distrib = AcademicYearDistribution.objects.using(get_current_db()).filter(
        class_group=enrollment.class_group,
        academic_year=enrollment.academic_year,
    ).first()
    if distrib:
        return ((distrib.start_month - 1 + distrib.nb_months - 1) % 12) + 1
    return 6  # Fallback : octobre → juin, dernier mois = juin


def _apply_boursier_discount(enrollment, full_amount):
    """
    Réduit un montant mensuel plein selon le pourcentage de bourse de
    l'inscription (Enrollment.bourse_pourcentage), si l'étudiant est boursier
    et que ce pourcentage est renseigné — sinon retourne le montant plein
    inchangé. Ne doit être appliqué qu'aux montants de repli (config classe/
    niveau) : un `monthly_installment` déjà saisi explicitement par le
    Trésorier Général ne doit jamais être re-réduit ici.
    """
    if full_amount is None:
        return None
    student = getattr(enrollment, 'student', None)
    if not (student and student.is_boursier and enrollment.bourse_pourcentage is not None):
        return full_amount
    from decimal import Decimal, ROUND_HALF_UP
    return (Decimal(full_amount) * enrollment.bourse_pourcentage / Decimal('100')).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP
    )


@login_required
def validation_inscription_detail(request, pk):
    if not _require_inscription_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__program__department',
            'class_group__level', 'academic_year', 'validated_by', 'previous_class',
        ),
        pk=pk,
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'send_to_caisse':
            # ── Trésorier : envoie l'inscription à la caisse ──────────────
            from decimal import Decimal, InvalidOperation
            def to_decimal(raw):
                try:
                    return Decimal(raw) if raw else None
                except InvalidOperation:
                    return None

            total_fees_raw = request.POST.get('total_fees', '').strip()
            frais_gen_raw  = request.POST.get('frais_generaux', '').strip()
            monthly_raw    = request.POST.get('monthly_installment', '').strip()
            payment_date   = request.POST.get('payment_date', '').strip()
            notes          = request.POST.get('notes', '').strip()
            required_month = request.POST.get('required_month', '').strip()
            # Mois cochés (liste de numéros de mois: "9", "10", ...)
            checked_months = request.POST.getlist('advance_months')

            if not payment_date:
                messages.error(request, "La date de paiement est obligatoire.")
                return redirect('accounting:validation_inscription_detail', pk=pk)

            enrollment.total_fees          = to_decimal(total_fees_raw)
            enrollment.frais_generaux      = to_decimal(frais_gen_raw)
            # Boursier : pas de mensualité générique — son échéancier futur est
            # entièrement piloté à la main via « Répartir le solde restant ».
            if not enrollment.student.is_boursier:
                enrollment.monthly_installment = to_decimal(monthly_raw)
            enrollment.frais_tenue               = to_decimal(request.POST.get('frais_tenue', '').strip())
            enrollment.frais_assurance           = to_decimal(request.POST.get('frais_assurance', '').strip())
            enrollment.frais_amea                = to_decimal(request.POST.get('frais_amea', '').strip())
            enrollment.frais_bibliotheque        = to_decimal(request.POST.get('frais_bibliotheque', '').strip())
            enrollment.frais_soutenance          = to_decimal(request.POST.get('frais_soutenance', '').strip())
            enrollment.frais_soutenance_speciale = to_decimal(request.POST.get('frais_soutenance_speciale', '').strip())

            # Bourse : partenaire (sur l'étudiant) + pourcentage à payer (sur l'inscription)
            if enrollment.student.is_boursier:
                partenaire_id = request.POST.get('partenaire_bourse', '').strip()
                if partenaire_id:
                    try:
                        enrollment.student.partenaire_bourse_id = int(partenaire_id)
                        enrollment.student.save(update_fields=['partenaire_bourse'])
                    except ValueError:
                        pass
                enrollment.bourse_pourcentage = to_decimal(request.POST.get('bourse_pourcentage', '').strip())
                deadline_raw = request.POST.get('bourse_deadline', '').strip()
                enrollment.bourse_deadline = deadline_raw or None

            enrollment.payment_date        = payment_date
            enrollment.payment_reference   = ''
            if notes:
                enrollment.notes = notes

            mensuel = enrollment.monthly_installment or Decimal('0')

            if enrollment.student.is_boursier:
                # Boursier : le mois obligatoire reste inclus, sans coût
                # propre. Le montant à payer par l'étudiant (Montant global ×
                # pourcentage de bourse) peut être librement réparti par le
                # Trésorier Général sur les autres mois — 0 par défaut sur
                # chaque mois (toujours un token explicite "mois:montant",
                # jamais un token nu, pour ne jamais retomber sur la
                # mensualité par défaut dans advance_months_list()). Le
                # montant à encaisser à l'inscription est la somme des mois
                # ainsi renseignés ; toute part non affectée reste à
                # recouvrer auprès du partenaire (suivi séparé du Trésorier
                # Général).
                tokens = []
                extra_total = Decimal('0')
                for m in checked_months:
                    amt_raw = request.POST.get(f'month_amount_{m}', '').strip()
                    amt = to_decimal(amt_raw)
                    if m == required_month:
                        tokens.append(m)
                        continue
                    amt = amt if amt is not None else Decimal('0')
                    tokens.append(f'{m}:{amt}')
                    extra_total += amt
                enrollment.advance_months = ','.join(tokens)
                enrollment.payment_amount = extra_total
            else:
                # Montant de chaque mois coché : par défaut la mensualité courante,
                # modifiable individuellement (champ month_amount_<mois>). Le mois
                # obligatoire (déjà inclus dans le montant global) n'a pas de coût
                # additionnel propre.
                tokens = []
                extra_total = Decimal('0')
                for m in checked_months:
                    amt_raw = request.POST.get(f'month_amount_{m}', '').strip()
                    amt = to_decimal(amt_raw)
                    if m == required_month:
                        tokens.append(m)
                        continue
                    if amt is None or amt == mensuel:
                        tokens.append(m)
                        extra_total += mensuel
                    else:
                        tokens.append(f'{m}:{amt}')
                        extra_total += amt
                enrollment.advance_months = ','.join(tokens)

                # Montant à encaisser = Frais d'inscription + somme des mois payés
                # en avance (hors mois obligatoire, déjà inclus dans les frais
                # d'inscription). Le montant global de la formation (total_fees)
                # couvre aussi la scolarité réglée séparément via les mensualités
                # — il ne doit pas être exigé en une seule fois à l'inscription.
                frais_inscription_val = enrollment.frais_generaux or Decimal('0')
                enrollment.payment_amount = frais_inscription_val + extra_total

            enrollment.status       = Enrollment.STATUS_PENDING_CAISSE
            enrollment.validated_by = request.user
            enrollment.validated_at = timezone.now()
            enrollment.save()

            from academic_core.apps.notifications.utils import notify_inscription_pending_caisse
            notify_inscription_pending_caisse(enrollment, request=request)

            messages.success(request, f"Dossier de {enrollment.student.full_name} envoyé à la caisse.")
            return redirect('accounting:validation_inscription_list')

        elif action == 'validate':
            # ── Caissier : confirme le paiement et valide l'inscription ──
            # Le Caissier peut valider l'encaissement d'un étudiant boursier au
            # même titre qu'un étudiant non-boursier (montants déjà préparés
            # par le Trésorier Général lors de l'envoi à la caisse).
            # Logique de finalisation extraite dans accounting/services.py::
            # finalize_enrollment_payment (réutilisée par la validation des
            # preuves de paiement du portail public d'admission).

            payment_date_raw  = request.POST.get('payment_date', '').strip()
            total_fees_raw    = request.POST.get('total_fees', '').strip()
            frais_gen_raw     = request.POST.get('frais_generaux', '').strip()
            monthly_raw       = request.POST.get('monthly_installment', '').strip()
            notes             = request.POST.get('notes', '').strip()

            if not payment_date_raw:
                messages.error(request, "La date de paiement est obligatoire pour valider.")
                return redirect('accounting:validation_inscription_detail', pk=pk)

            from .models import PaymentProof
            if enrollment.payment_proofs.filter(status=PaymentProof.STATUS_PENDING).exists() and not request.POST.get('proof_reviewed'):
                messages.error(request, "Vous devez confirmer avoir vérifié la/les preuve(s) de paiement en ligne avant de valider.")
                return redirect('accounting:validation_inscription_detail', pk=pk)

            from decimal import Decimal, InvalidOperation
            def to_decimal(raw):
                try:
                    return Decimal(raw) if raw else None
                except InvalidOperation:
                    return None

            from .services import finalize_enrollment_payment
            finalize_enrollment_payment(
                enrollment,
                payment_date=payment_date_raw,
                validated_by=request.user,
                total_fees=to_decimal(total_fees_raw) if total_fees_raw else None,
                frais_generaux=to_decimal(frais_gen_raw) if frais_gen_raw else None,
                monthly_installment=to_decimal(monthly_raw) if monthly_raw else None,
                notes=notes,
                request=request,
            )

            # Marquer comme validée(s) la/les preuve(s) de paiement en ligne
            # associées, désormais couvertes par cet encaissement — évite
            # qu'elles restent indéfiniment "en attente" dans la file du
            # Caissier (accounting:payment_proof_list) alors que l'inscription
            # est déjà validée.
            enrollment.payment_proofs.filter(status=PaymentProof.STATUS_PENDING).update(
                status=PaymentProof.STATUS_VALIDATED, reviewed_by=request.user, reviewed_at=timezone.now(),
            )

            messages.success(request, f"Inscription validée. {enrollment.student.full_name} ajouté(e) à {enrollment.class_group.name}.")
            return redirect('accounting:inscription_recu', pk=pk)

        elif action == 'reject':
            notes = request.POST.get('notes', '').strip()
            enrollment.status       = Enrollment.STATUS_REJECTED
            enrollment.is_active    = False
            if notes:
                enrollment.notes = notes
            enrollment.validated_by = request.user
            enrollment.validated_at = timezone.now()
            enrollment.save()
            # Désactiver le compte et retirer la classe
            student = enrollment.student
            student.user.is_active = False
            student.user.save(update_fields=['is_active'])
            student.current_class = None
            student.save(update_fields=['current_class'])
            # Notifier l'étudiant
            try:
                from academic_core.apps.notifications.utils import notify_inscription_rejected
                notify_inscription_rejected(enrollment)
            except Exception:
                pass
            messages.warning(request, f"Inscription de {student.full_name} rejetée.")
            return redirect('accounting:validation_inscription_list')

        elif action == 'return_to_pending':
            # ── Renvoyer le dossier au Trésorier pour correction (depuis
            # « À la caisse ») — les montants/mois déjà saisis sont conservés,
            # seul le statut repasse à « En attente ».
            # Le Caissier n'a plus rien à faire sur ce dossier tant que le
            # Trésorier ne l'a pas corrigé et renvoyé : on le ramène donc sur
            # « La Caisse » (sa page de travail habituelle) plutôt que sur
            # « Validation des inscriptions », qui ne fait pas partie de ses
            # fonctionnalités et afficherait désormais le formulaire du Trésorier.
            notes = request.POST.get('notes', '').strip()
            enrollment.status = Enrollment.STATUS_PENDING
            if notes:
                enrollment.notes = notes
            enrollment.save(update_fields=['status', 'notes'])
            messages.info(
                request,
                f"Dossier de {enrollment.student.full_name} retourné en attente pour correction."
            )
            return redirect('accounting:caisse_dashboard')

        elif action == 'update':
            from decimal import Decimal, InvalidOperation
            def to_dec(raw, fallback):
                try:
                    return Decimal(raw) if raw and raw.strip() else fallback
                except InvalidOperation:
                    return fallback
            enrollment.total_fees          = to_dec(request.POST.get('total_fees', ''), enrollment.total_fees)
            enrollment.frais_generaux      = to_dec(request.POST.get('frais_generaux', ''), enrollment.frais_generaux)
            enrollment.payment_amount      = to_dec(request.POST.get('payment_amount', ''), enrollment.payment_amount)
            enrollment.monthly_installment = to_dec(request.POST.get('monthly_installment', ''), enrollment.monthly_installment)
            enrollment.payment_date        = request.POST.get('payment_date') or enrollment.payment_date
            enrollment.payment_reference   = request.POST.get('payment_reference', '').strip()
            enrollment.notes               = request.POST.get('notes', '').strip()
            enrollment.save()
            messages.success(request, "Informations mises à jour.")
            return redirect('accounting:validation_inscription_detail', pk=pk)

        elif action == 'pay_installment':
            from academic_core.apps.students.models import PaymentInstallment
            from datetime import date as dt
            inst_id     = request.POST.get('installment_id')
            amount_paid = request.POST.get('amount_paid', '').strip()
            paid_date   = request.POST.get('paid_date', '').strip()
            inst = get_object_or_404(PaymentInstallment, pk=inst_id, enrollment=enrollment)
            if amount_paid:
                inst.amount_paid = amount_paid
            inst.paid_date = paid_date or dt.today().isoformat()
            inst.is_paid   = True
            inst.save()

            # Réactivation immédiate si plus aucune mensualité échue impayée
            student = enrollment.student
            today   = dt.today()
            still_overdue = PaymentInstallment.objects.filter(
                enrollment__student=student,
                enrollment__status='VALIDATED',
                is_paid=False,
                due_date__lte=today,
            ).exists()

            if not still_overdue and student.payment_suspended:
                student.user.is_active      = True
                student.payment_suspended   = False
                student.suspension_date     = None
                student.user.save(update_fields=['is_active'])
                student.save(update_fields=['payment_suspended', 'suspension_date'])
                messages.success(
                    request,
                    f"Échéance {inst.installment_number} réglée. "
                    f"Compte de {student.full_name} réactivé."
                )
            else:
                messages.success(request, f"Échéance {inst.installment_number} marquée comme réglée.")
            return redirect('accounting:validation_inscription_detail', pk=pk)

        elif action == 'repartir_solde':
            # ── Trésorier Général : répartit librement le solde restant sur des
            # mois précis (ex : un boursier remboursé en plusieurs mensualités
            # inégales plutôt qu'au rythme mensuel standard automatique).
            # Ne touche jamais aux échéances déjà réglées — seules les échéances
            # non réglées sont remplacées par la nouvelle répartition soumise.
            if not request.user.is_tresorier():
                messages.error(request, "Seul le Trésorier Général peut répartir le solde restant.")
                return redirect('accounting:validation_inscription_detail', pk=pk)

            from decimal import Decimal, InvalidOperation
            from datetime import date as _repart_date
            from academic_core.apps.students.models import PaymentInstallment

            def _to_dec(raw):
                try:
                    return Decimal(raw) if raw and raw.strip() else Decimal('0')
                except InvalidOperation:
                    return Decimal('0')

            checked_months = request.POST.getlist('repartition_months')
            paid_months = set(
                enrollment.installments.filter(is_paid=True).values_list('due_date__month', flat=True)
            )

            acad_year   = enrollment.academic_year
            start_year  = (acad_year.start_date.year  if acad_year and acad_year.start_date else timezone.now().year)
            start_month = (acad_year.start_date.month if acad_year and acad_year.start_date else 9)

            enrollment.installments.filter(is_paid=False).delete()

            next_num = (enrollment.installments.aggregate(m=db_models.Max('installment_number'))['m'] or 0) + 1
            created_total = Decimal('0')
            created_count = 0
            auto_validated_count = 0
            for m_str in checked_months:
                try:
                    m = int(m_str)
                except ValueError:
                    continue
                if m in paid_months:
                    continue
                amount = _to_dec(request.POST.get(f'repartition_amount_{m}', ''))
                month_year = start_year if m >= start_month else start_year + 1
                try:
                    due = _repart_date(month_year, m, 1)
                except ValueError:
                    continue
                if amount <= 0:
                    # Mois coché à 0 FCFA (entièrement pris en charge par la
                    # bourse) : validé automatiquement, sans reçu à générer —
                    # sans ça, ce mois retombait sur la mensualité pleine par
                    # défaut dans Paiements Mensualités au lieu d'apparaître
                    # comme déjà réglé.
                    PaymentInstallment.objects.create(
                        enrollment=enrollment, installment_number=next_num,
                        due_date=due, amount_expected=Decimal('0'), amount_paid=Decimal('0'),
                        is_paid=True, paid_date=None,
                        notes="Pris en charge à 100% par la bourse — validé automatiquement",
                    )
                    auto_validated_count += 1
                else:
                    PaymentInstallment.objects.create(
                        enrollment=enrollment, installment_number=next_num,
                        due_date=due, amount_expected=amount,
                    )
                    created_total += amount
                    created_count += 1
                next_num += 1

            msg = f"Répartition mise à jour : {created_total:.0f} FCFA sur {created_count} mois."
            if auto_validated_count:
                msg += f" {auto_validated_count} mois à 0 FCFA validé(s) automatiquement (pris en charge par la bourse)."
            messages.success(request, msg)
            return redirect('accounting:validation_inscription_detail', pk=pk)

    from datetime import date as dt
    from .models import FraisGenerauxNiveau, FraisMensuelClasse, AcademicYearDistribution
    from decimal import Decimal
    installments = enrollment.installments.all()
    installments_total = installments.aggregate(total=db_models.Sum('amount_expected'))['total'] or Decimal('0')
    from academic_core.db_router import get_current_db
    _current_db = get_current_db()

    level = enrollment.class_group.level if enrollment.class_group else None
    is_l3_m2 = bool(level and level.name in ('Licence 3', 'Master 2'))

    from .models import PartenaireBourse
    partenaires_bourse = PartenaireBourse.objects.using(_current_db).filter(is_active=True).order_by('intitule')

    # Requêtes sur la bonne base de données (multi-tenant)
    try:
        niveau_cfg = FraisGenerauxNiveau.objects.using(_current_db).get(level=level) if level else None
    except FraisGenerauxNiveau.DoesNotExist:
        niveau_cfg = None

    # Frais mensuel & montant global : priorité FraisMensuelClasse (défini à la
    # création de la classe) > FraisGenerauxNiveau par niveau (repli générique).
    classe_cfg = None
    if enrollment.class_group:
        try:
            classe_cfg = FraisMensuelClasse.objects.using(_current_db).get(class_group=enrollment.class_group)
        except FraisMensuelClasse.DoesNotExist:
            pass

    # « Frais d'inscription » : priorité au frais d'inscription défini à la
    # création de la classe > frais généraux par niveau (repli générique).
    if classe_cfg and classe_cfg.frais_inscription is not None:
        frais_generaux_config = float(classe_cfg.frais_inscription)
    else:
        frais_generaux_config = float(niveau_cfg.frais_generaux) if niveau_cfg else 0.0

    montant_global_config = float(classe_cfg.montant_global) if (classe_cfg and classe_cfg.montant_global is not None) else None

    frais_totaux_config = montant_global_config
    if frais_totaux_config is None and niveau_cfg and niveau_cfg.frais_totaux is not None:
        frais_totaux_config = float(niveau_cfg.frais_totaux)

    frais_mensuel_config = float(classe_cfg.frais_mensuel) if (classe_cfg and classe_cfg.frais_mensuel is not None) else 0.0
    if not frais_mensuel_config and niveau_cfg and niveau_cfg.frais_mensuel is not None:
        frais_mensuel_config = float(niveau_cfg.frais_mensuel)

    # Frais annexes définis à la création de la classe (informatifs, non sommés
    # dans le montant à payer) — préremplis ici, modifiables par inscription.
    def _cfg_val(attr):
        val = getattr(classe_cfg, attr, None) if classe_cfg else None
        return float(val) if val is not None else None

    frais_tenue_config               = _cfg_val('frais_tenue')
    frais_assurance_config           = _cfg_val('frais_assurance')
    frais_amea_config                = _cfg_val('frais_amea')
    frais_bibliotheque_config        = _cfg_val('frais_bibliotheque')
    frais_soutenance_config          = _cfg_val('frais_soutenance')
    frais_soutenance_speciale_config = _cfg_val('frais_soutenance_speciale')

    # Valeurs effectives : enrollment d'abord, sinon config du niveau/classe
    fg_effectif = float(enrollment.frais_generaux) if enrollment.frais_generaux is not None else frais_generaux_config

    def _eff(field, config_val):
        val = getattr(enrollment, field, None)
        return float(val) if val is not None else (config_val or 0.0)

    annexes_effectif = (
        _eff('frais_tenue', frais_tenue_config)
        + _eff('frais_assurance', frais_assurance_config)
        + _eff('frais_amea', frais_amea_config)
        + _eff('frais_bibliotheque', frais_bibliotheque_config)
    )
    # Droit d'inscription = Frais d'inscription − (Tenue + Amicale + Assurance + Bibliothèque)
    droit_initial = max(fg_effectif - annexes_effectif, 0) if fg_effectif is not None else None

    # Liste des mois de l'année académique pour la classe
    MOIS_FR = ['', 'Janvier','Février','Mars','Avril','Mai','Juin',
               'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
    academic_months = []
    distrib = None
    if enrollment.class_group and enrollment.academic_year:
        distrib = AcademicYearDistribution.objects.using(_current_db).filter(
            class_group=enrollment.class_group,
            academic_year=enrollment.academic_year,
        ).first()
    if distrib:
        start = distrib.start_month
        for i in range(distrib.nb_months):
            m = ((start - 1 + i) % 12) + 1
            academic_months.append({'num': m, 'label': MOIS_FR[m]})
    else:
        # Fallback : octobre → juin (9 mois)
        for m in [10, 11, 12, 1, 2, 3, 4, 5, 6]:
            academic_months.append({'num': m, 'label': MOIS_FR[m]})

    # Dernier mois = toujours pré-sélectionné (inclus obligatoirement)
    last_month_num = academic_months[-1]['num'] if academic_months else None

    # Détail par mois (libellé + montant réellement retenu) — utilisé côté
    # Caissier pour afficher automatiquement le montant à payer par mois,
    # tel que saisi par le Trésorier Général (mêmes valeurs que celles
    # utilisées à la validation pour générer l'échéancier réel).
    # Pour un boursier, le mois obligatoire reste "Inclus" à coût nul (le
    # montant à sa charge est entièrement réparti sur les autres mois par le
    # Trésorier) — advance_months_list() retombe par défaut sur la mensualité
    # standard pour un token sans montant, ce qui ne s'applique pas ici.
    advance_months_detail = [
        {
            'num': m,
            'label': MOIS_FR[m] if 1 <= m <= 12 else f'Mois {m}',
            'amount': (
                Decimal('0') if (m == last_month_num and enrollment.student.is_boursier) else amt
            ),
            'is_required': (m == last_month_num),
        }
        for m, amt in enrollment.advance_months_list()
    ]

    # Mois déjà sélectionnés (pour le cas PENDING_CAISSE)
    # Pour STATUS_PENDING : pré-sélectionner le dernier mois par défaut
    advance_months_selected = [str(m) for m, _amt in enrollment.advance_months_list()]
    if not advance_months_selected and last_month_num is not None:
        advance_months_selected = [str(last_month_num)]

    from django.contrib.auth import get_user_model
    User = get_user_model()
    validated_by_user = None
    if enrollment.validated_by_id:
        validated_by_user = User.objects.using('default').filter(pk=enrollment.validated_by_id).first()

    # Montants personnalisés déjà enregistrés par mois (pour préremplir les
    # champs éditables du récapitulatif "Mois à payer en avance").
    import json as _json
    advance_months_amounts_map = {
        str(m): (float(amt) if amt is not None else None)
        for m, amt in enrollment.advance_months_list()
    }
    advance_months_amounts_json = _json.dumps(advance_months_amounts_map)

    # Mois déjà réglés (échéance payée) — à exclure de la répartition du solde
    # restant, pour ne jamais permettre au Trésorier de toucher à une échéance
    # déjà encaissée.
    paid_months = list(installments.filter(is_paid=True).values_list('due_date__month', flat=True))

    # Preuves de paiement en ligne transmises par le candidat pour cette
    # inscription — affichées automatiquement à la caisse (pas seulement un
    # lien) pour que le caissier les vérifie avant de valider l'encaissement.
    from .models import PaymentProof
    payment_proofs = []
    has_pending_proof = False
    for proof in enrollment.payment_proofs.order_by('-submitted_at'):
        file_name = (proof.piece_justificative.name or '').lower()
        payment_proofs.append({
            'proof':    proof,
            'is_image': file_name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')),
            'is_pdf':   file_name.endswith('.pdf'),
        })
        if proof.status == PaymentProof.STATUS_PENDING:
            has_pending_proof = True

    return render(request, 'accounting/validation_inscription_detail.html', {
        'payment_proofs':          payment_proofs,
        'has_pending_proof':       has_pending_proof,
        'enrollment':              enrollment,
        'installments':            installments,
        'installments_total':      installments_total,
        'paid_months':             paid_months,
        'today':                   dt.today(),
        'frais_totaux_config':     frais_totaux_config,
        'frais_generaux_config':   frais_generaux_config,
        'frais_mensuel_config':    frais_mensuel_config,
        'montant_global_config':   montant_global_config,
        'frais_tenue_config':               frais_tenue_config,
        'frais_assurance_config':           frais_assurance_config,
        'frais_amea_config':                frais_amea_config,
        'frais_bibliotheque_config':        frais_bibliotheque_config,
        'frais_soutenance_config':          frais_soutenance_config,
        'frais_soutenance_speciale_config': frais_soutenance_speciale_config,
        'droit_initial':           droit_initial,
        'level_id':                level.pk if level else '',
        'academic_months':         academic_months,
        'advance_months_selected': advance_months_selected,
        'advance_months_amounts':  advance_months_amounts_map,
        'advance_months_amounts_json': advance_months_amounts_json,
        'advance_months_detail':   advance_months_detail,
        'is_l3_m2':                is_l3_m2,
        'partenaires_bourse':      partenaires_bourse,
        'last_month_num':          last_month_num,
        'STATUS_PENDING':          Enrollment.STATUS_PENDING,
        'STATUS_PENDING_CAISSE':   Enrollment.STATUS_PENDING_CAISSE,
        'STATUS_VALIDATED':        Enrollment.STATUS_VALIDATED,
        'STATUS_REJECTED':         Enrollment.STATUS_REJECTED,
        'validated_by_user':       validated_by_user,
    })


@login_required
def certificat_inscription_pdf(request, pk):
    from academic_core.apps.students.models import Enrollment
    # Autoriser le staff OU l'étudiant propriétaire de l'inscription
    if not _require_inscription_access(request.user):
        if not request.user.is_etudiant():
            messages.error(request, "Accès refusé.")
            return redirect('dashboard:index')
        # Vérifier que l'étudiant connecté est bien le titulaire
        student = getattr(request.user, 'student_profile', None)
        if not student or not Enrollment.objects.filter(pk=pk, student=student).exists():
            messages.error(request, "Accès refusé.")
            return redirect('dashboard:index')
    from academic_core.apps.academic_structure.models import BulletinConfig
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image, KeepTogether
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from datetime import date as dt
    from academic_core.apps.students.qr_utils import student_qr_receipt_block
    from academic_core.pdf_utils import logo_image as _logo_img_fn1, senegal_flag as _flag, get_institut_config_for_request as _gcfr_cert
    _inst_cfg_cert = _gcfr_cert(request)
    _logo_img = lambda **kw: _logo_img_fn1(config=_inst_cfg_cert, **kw)  # noqa: E731

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__program__department',
            'class_group__level', 'academic_year',
        ),
        pk=pk, status=Enrollment.STATUS_VALIDATED,
    )
    config  = BulletinConfig.get()
    student = enrollment.student
    dept    = enrollment.class_group.program.department
    is_female = getattr(student, 'gender', '') == 'F'
    etudiant_label = "étudiante" if is_female else "étudiant"
    inscrit_label  = "inscrite"  if is_female else "inscrit"
    buffer  = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    ss    = getSampleStyleSheet()
    sc    = ParagraphStyle
    s_ctr = sc('c',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl = sc('t',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=18, fontName='Helvetica-Bold', textColor=navy)
    s_sub = sc('s',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=11, textColor=grey)
    s_lbl = sc('l',  parent=ss['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=navy)
    s_val = sc('v',  parent=ss['Normal'], fontSize=10)
    s_sgn = sc('sg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=10, fontName='Helvetica-Bold')

    _flag_el = _flag(width=2.4*cm, height=1.6*cm)
    _logo_el = _logo_img(width=2.4*cm, height=1.6*cm) or Paragraph('ISI', sc('lb', parent=s_ctr, fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    _rep_txt = Paragraph(
        '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="8">Un Peuple — Un But — Une Foi</font>'
        '<br/><br/><font size="13"><b>GROUPE ISI</b></font><br/>'
        "<font size='9'>Institut Supérieur d'Informatique</font>",
        sc('rh', parent=ss['Normal'], alignment=TA_CENTER, leading=14),
    )
    _hdr_tbl = Table([[_flag_el, _rep_txt, _logo_el]], colWidths=[3*cm, 11*cm, 3*cm])
    _hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    story = [
        _hdr_tbl,
        Spacer(1, .3*cm), HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=8),
        Spacer(1, .5*cm),
        Paragraph("CERTIFICAT D'INSCRIPTION", s_ttl),
        Spacer(1, .3*cm),
        Paragraph(f"Année académique {enrollment.academic_year.label}", s_sub),
        Spacer(1, .6*cm), HRFlowable(width='60%', thickness=1, color=gold, hAlign='CENTER'), Spacer(1, .8*cm),
        Paragraph(
            f"Nous soussignés, la Direction de l'Institut Supérieur d'Informatique, certifions que "
            f"l'{etudiant_label} dont les informations suivent est régulièrement {inscrit_label} "
            f"pour l'année académique <b>{enrollment.academic_year.label}</b>.",
            sc('intro', parent=ss['Normal'], fontSize=10, leading=16),
        ),
        Spacer(1, .6*cm),
    ]
    story.append(Table([
        [Paragraph("<b>Matricule</b>", s_lbl),           Paragraph(student.matricule, s_val)],
        [Paragraph("<b>Nom &amp; Prénom(s)</b>", s_lbl), Paragraph(student.full_name, s_val)],
        [Paragraph("<b>Date de naissance</b>", s_lbl),   Paragraph(student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '-', s_val)],
        [Paragraph("<b>Lieu de naissance</b>", s_lbl),   Paragraph(student.place_of_birth or '-', s_val)],
        [Paragraph("<b>Département</b>", s_lbl),         Paragraph(dept.name, s_val)],
        [Paragraph("<b>Filière</b>", s_lbl),             Paragraph(enrollment.class_group.program.name, s_val)],
        [Paragraph("<b>Niveau</b>", s_lbl),              Paragraph(str(enrollment.class_group.level) if enrollment.class_group.level else '-', s_val)],
        [Paragraph("<b>Classe</b>", s_lbl),              Paragraph(enrollment.class_group.name, s_val)],
        [Paragraph("<b>Date d'inscription</b>", s_lbl),  Paragraph(enrollment.enrollment_date.strftime('%d/%m/%Y'), s_val)],
    ], colWidths=[5.5*cm, 11*cm], style=TableStyle([
        ('BACKGROUND',     (0, 0), (0, -1), light),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('GRID',           (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',     (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',    (0, 0), (-1, -1), 8),
    ])))
    story += [
        Spacer(1, .8*cm),
        Paragraph("Le présent certificat est délivré pour servir et valoir ce que de droit.",
                  sc('srv', parent=ss['Normal'], fontSize=10, fontName='Helvetica-BoldOblique', alignment=TA_CENTER)),
        Spacer(1, 1*cm),
    ]
    tail = [
        Table([
            [Paragraph(f"Dakar, le {dt.today().strftime('%d/%m/%Y')}", sc('dl', parent=ss['Normal'], fontSize=9)),
             Paragraph(config.director_title or "Le Directeur Général", s_sgn)],
            ['', Paragraph(config.director_name or '', sc('dn', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, textColor=grey))],
        ], colWidths=[9*cm, 7.5*cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')]),
    ] + student_qr_receipt_block(student, enrollment)
    story.append(KeepTogether(tail))
    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="certificat_{student.matricule}.pdf"'
    return resp


@login_required
def attestation_passage_pdf(request, pk):
    from academic_core.apps.students.models import Enrollment

    # Accès admin/comptable OU étudiant propriétaire de l'inscription
    _is_owner = False
    if request.user.is_etudiant():
        student_profile = getattr(request.user, 'student_profile', None)
        _is_owner = student_profile is not None and Enrollment.objects.filter(
            pk=pk, student=student_profile
        ).exists()

    if not (_require_inscription_access(request.user) or _is_owner):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment  # noqa: F811 (réimport toléré)
    from academic_core.apps.academic_structure.models import BulletinConfig
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from datetime import date as dt
    from academic_core.pdf_utils import logo_image as _logo_img_fn2, senegal_flag as _flag, get_institut_config_for_request as _gcfr_att
    _inst_cfg_att = _gcfr_att(request)
    _logo_img = lambda **kw: _logo_img_fn2(config=_inst_cfg_att, **kw)  # noqa: E731

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__program__department',
            'class_group__level', 'academic_year', 'previous_class__level',
        ),
        pk=pk, status=Enrollment.STATUS_VALIDATED, enrollment_type=Enrollment.TYPE_REINSCRIPTION,
    )
    config  = BulletinConfig.get()
    student = enrollment.student
    prev    = enrollment.previous_class
    dept    = enrollment.class_group.program.department
    buffer  = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    ss    = getSampleStyleSheet()
    sc    = ParagraphStyle
    s_ctr = sc('c',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl = sc('t',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=18, fontName='Helvetica-Bold', textColor=navy)
    s_sub = sc('s',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=11, textColor=grey)
    s_lbl = sc('l',  parent=ss['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=navy)
    s_val = sc('v',  parent=ss['Normal'], fontSize=10)
    s_sgn = sc('sg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=10, fontName='Helvetica-Bold')

    _flag_el2 = _flag(width=2.4*cm, height=1.6*cm)
    _logo_el2 = _logo_img(width=2.4*cm, height=1.6*cm) or Paragraph('ISI', sc('lb2', parent=s_ctr, fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    _rep_txt2 = Paragraph(
        '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="8">Un Peuple — Un But — Une Foi</font>'
        '<br/><br/><font size="13"><b>GROUPE ISI</b></font><br/>'
        "<font size='9'>Institut Supérieur d'Informatique</font>",
        sc('rh2', parent=ss['Normal'], alignment=TA_CENTER, leading=14),
    )
    _hdr_tbl2 = Table([[_flag_el2, _rep_txt2, _logo_el2]], colWidths=[3*cm, 11*cm, 3*cm])
    _hdr_tbl2.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    story = [
        _hdr_tbl2,
        Spacer(1, .3*cm), HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=8),
        Spacer(1, .5*cm),
        Paragraph("ATTESTATION DE PASSAGE", s_ttl),
        Spacer(1, .3*cm),
        Paragraph(f"Année académique {enrollment.academic_year.label}", s_sub),
        Spacer(1, .6*cm), HRFlowable(width='60%', thickness=1, color=gold, hAlign='CENTER'), Spacer(1, .8*cm),
        Paragraph(
            f"Nous soussignés, la Direction de l'Institut Supérieur d'Informatique, attestons que "
            f"l'étudiant(e) mentionné(e) ci-dessous a été admis(e) à passer en "
            f"<b>{enrollment.class_group.name}</b> pour l'année académique <b>{enrollment.academic_year.label}</b>, "
            f"après avoir accompli sa formation en <b>{prev.name if prev else 'classe précédente'}</b>.",
            sc('intro', parent=ss['Normal'], fontSize=10, leading=16),
        ),
        Spacer(1, .6*cm),
    ]
    story.append(Table([
        [Paragraph("<b>Matricule</b>", s_lbl),           Paragraph(student.matricule, s_val)],
        [Paragraph("<b>Nom &amp; Prénom(s)</b>", s_lbl), Paragraph(student.full_name, s_val)],
        [Paragraph("<b>Date de naissance</b>", s_lbl),   Paragraph(student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '-', s_val)],
        [Paragraph("<b>Département</b>", s_lbl),         Paragraph(dept.name, s_val)],
        [Paragraph("<b>Filière</b>", s_lbl),             Paragraph(enrollment.class_group.program.name, s_val)],
        [Paragraph("<b>Classe précédente</b>", s_lbl),   Paragraph(prev.name if prev else '-', s_val)],
        [Paragraph("<b>Classe d'accueil</b>", s_lbl),    Paragraph(enrollment.class_group.name, s_val)],
        [Paragraph("<b>Année académique</b>", s_lbl),    Paragraph(enrollment.academic_year.label, s_val)],
    ], colWidths=[5.5*cm, 11*cm], style=TableStyle([
        ('BACKGROUND',     (0, 0), (0, -1), light),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('GRID',           (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',     (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',    (0, 0), (-1, -1), 8),
    ])))
    story += [
        Spacer(1, .8*cm),
        Paragraph("La présente attestation est délivrée pour servir et valoir ce que de droit.",
                  sc('srv', parent=ss['Normal'], fontSize=10, fontName='Helvetica-BoldOblique', alignment=TA_CENTER)),
        Spacer(1, 1*cm),
        Table([
            [Paragraph(f"Dakar, le {dt.today().strftime('%d/%m/%Y')}", sc('dl', parent=ss['Normal'], fontSize=9)),
             Paragraph(config.director_title or "Le Directeur Général", s_sgn)],
            ['', Paragraph(config.director_name or '', sc('dn', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, textColor=grey))],
        ], colWidths=[9*cm, 7.5*cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')]),
    ]
    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="attestation_passage_{student.matricule}.pdf"'
    return resp


@login_required
def diploma_supplement_pdf(request, cycle):
    """
    Supplément au diplôme (Licence L1-L2-L3 ou Master M1-M2) — réplique la
    structure du modèle Word de référence (voir DiplomaSupplementConfig),
    avec la table « Contenus des enseignements » construite automatiquement
    à partir des modules (EC) réels de la filière
    (build_diploma_supplement_ue_table). N'est délivré que si l'étudiant a
    validé, dans cet institut et cette filière précise, une inscription à
    CHAQUE niveau du cycle demandé (check_diploma_supplement_eligibility) —
    sinon un message explique précisément le(s) niveau(x) manquant(s), sans
    générer de document.
    """
    from academic_core.apps.students.models import Student
    from academic_core.apps.students.services import (
        DIPLOMA_SUPPLEMENT_CYCLES, resolve_diploma_supplement_program,
        check_diploma_supplement_eligibility,
    )
    from academic_core.apps.academic_structure.models import DiplomaSupplementConfig, BulletinConfig
    from .services import build_diploma_supplement_ue_table
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from datetime import date as dt
    from academic_core.pdf_utils import logo_image as _logo_img_fn, senegal_flag as _flag_fn, get_institut_config_for_request, watermark_canvas

    if cycle not in DIPLOMA_SUPPLEMENT_CYCLES:
        messages.error(request, "Cycle invalide.")
        return redirect('dashboard:index')
    cycle_label = 'Licence' if cycle == 'licence' else 'Master'

    student = None
    if request.user.is_etudiant():
        student = getattr(request.user, 'student_profile', None)
    student_id = request.GET.get('student_id')
    if student_id and _require_inscription_access(request.user):
        student = get_object_or_404(Student, pk=student_id)

    if not student:
        messages.error(request, "Profil étudiant introuvable.")
        return redirect('dashboard:index')

    program = resolve_diploma_supplement_program(student, cycle)
    if not program:
        messages.warning(
            request,
            f"Vous ne pouvez pas obtenir de supplément de diplôme {cycle_label} : "
            f"aucune inscription validée de niveau {cycle_label} n'a été trouvée pour vous dans cet institut."
        )
        return redirect('dashboard:index')

    eligible, missing_levels, enrollments_by_level = check_diploma_supplement_eligibility(student, program, cycle)
    if not eligible:
        messages.warning(
            request,
            f"Vous ne pouvez pas obtenir le supplément de diplôme {cycle_label} pour la filière "
            f"« {program.name} » : vous n'avez pas validé le(s) niveau(x) suivant(s) dans cet institut — "
            f"{', '.join(missing_levels)}."
        )
        return redirect('dashboard:index')

    num_semesters = 6 if cycle == 'licence' else 4
    levels = DIPLOMA_SUPPLEMENT_CYCLES[cycle]
    last_enrollment = enrollments_by_level[levels[-1]]
    last_class = last_enrollment.class_group

    config, _ = DiplomaSupplementConfig.objects.get_or_create(program=program)
    bulletin_config = BulletinConfig.get()
    inst_cfg = get_institut_config_for_request(request)
    domaine = config.domaine or last_class.domaine or '—'
    ue_table_data = build_diploma_supplement_ue_table(program, num_semesters)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.7*cm, leftMargin=1.7*cm, topMargin=1.7*cm, bottomMargin=1.7*cm)

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    ss    = getSampleStyleSheet()
    sc    = ParagraphStyle
    s_ttl   = sc('dst', parent=ss['Normal'], alignment=TA_CENTER, fontSize=17, fontName='Helvetica-Bold', textColor=navy)
    s_sec   = sc('dss', parent=ss['Normal'], fontSize=11, fontName='Helvetica-Bold', textColor=navy, spaceBefore=10, spaceAfter=4)
    s_body  = sc('dsb', parent=ss['Normal'], fontSize=9.5, leading=14, alignment=TA_LEFT)
    s_bul   = sc('dsu', parent=ss['Normal'], fontSize=9.5, leading=13, alignment=TA_LEFT, leftIndent=14)
    s_sgn   = sc('dsg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')
    s_th    = sc('dth', parent=ss['Normal'], fontSize=7.5, fontName='Helvetica-Bold', textColor=colors.white, alignment=TA_CENTER, leading=9)
    s_td    = sc('dtd', parent=ss['Normal'], fontSize=7.3, alignment=TA_LEFT, leading=9)
    s_tdc   = sc('dtdc', parent=ss['Normal'], fontSize=7.3, alignment=TA_CENTER, leading=9)

    inst_nom   = inst_cfg.nom if inst_cfg else ''
    inst_sigle = (inst_cfg.sigle if inst_cfg else '') or inst_nom
    ville      = (inst_cfg.ville if inst_cfg and inst_cfg.ville else 'Dakar')

    flag_el = _flag_fn(width=2.2*cm, height=1.5*cm)
    logo_el = _logo_img_fn(width=2.2*cm, height=1.5*cm, config=inst_cfg) or Paragraph(
        inst_sigle, sc('lb3', parent=ss['Normal'], alignment=TA_CENTER, fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    rep_txt = Paragraph(
        '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="8">Un Peuple — Un But — Une Foi</font>'
        f'<br/><br/><font size="13"><b>{inst_sigle}</b></font><br/>'
        f"<font size='9'>{inst_nom}</font>",
        sc('rh3', parent=ss['Normal'], alignment=TA_CENTER, leading=14),
    )
    hdr_tbl = Table([[flag_el, rep_txt, logo_el]], colWidths=[3*cm, 12.6*cm, 3*cm])
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    def _field(label, value):
        return Paragraph(f"<b>{label}</b> : {value if value else '—'}", s_body)

    story = [
        hdr_tbl,
        Spacer(1, .3*cm), HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=10),
        Spacer(1, .3*cm),
        Paragraph("Supplément au diplôme", s_ttl),
        Spacer(1, .5*cm),

        Paragraph("Identification du détenteur de la qualification :", s_sec),
        _field('Nom', student.user.last_name.upper()),
        _field('Prénom', student.user.first_name),
        _field('Matricule', student.matricule),
        _field('Date et lieu de naissance',
               f"{student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '—'} à {student.place_of_birth or '—'}"),

        Paragraph("Identification de la qualification :", s_sec),
        _field('Intitulé et titre', program.name),
        _field('Domaine', domaine),
        _field("Nom de l'institut", inst_nom),
        _field("Langue d'études", config.langue_etudes),

        Paragraph("Niveau de qualification :", s_sec),
        _field('Définition de la qualification', config.definition_qualification),
        _field('Durée', config.duree_texte),
        Paragraph("<b>Condition d'admission</b> :", s_body),
    ]
    conditions = config.conditions_admission_list
    if conditions:
        for cond in conditions:
            story.append(Paragraph(f"•&nbsp;&nbsp;{cond}", s_bul))
    else:
        story.append(Paragraph("—", s_bul))

    story += [
        Paragraph("Fonction de la qualification acquise :", s_sec),
        _field("Poursuite d'études", config.poursuite_etudes),
        _field("Statut professionnel qu'on lui confère", config.statut_professionnel),

        Paragraph("Contenus des enseignements :", s_sec),
        _field('Forme des études', config.forme_etudes),
        Paragraph(
            "<b>Programme (avec les détails)</b> : Unités d'enseignement, Éléments Constitutifs, "
            "Quota horaire et crédits :",
            s_body,
        ),
        Spacer(1, .3*cm),
    ]

    # ── Table des enseignements ────────────────────────────────────────────
    sem_headers = [Paragraph(f"S{n}", s_th) for n in range(1, num_semesters + 1)]
    header_row = [Paragraph("Unité d'Enseignement — UE", s_th), Paragraph("Modules", s_th)] + \
                 sem_headers + [Paragraph("QT", s_th), Paragraph("Crédits", s_th)]
    table_rows = [header_row]
    for row in ue_table_data['rows']:
        marks = [Paragraph('x' if row['sem_marks'].get(n) else '', s_tdc) for n in range(1, num_semesters + 1)]
        table_rows.append(
            [Paragraph(row['ue_label'], s_td), Paragraph(row['module'], s_td)] + marks +
            [Paragraph(str(row['qt']), s_tdc), Paragraph(str(row['credits']), s_tdc)]
        )
    table_rows.append(
        [Paragraph('<b>TOTAL</b>', s_tdc), Paragraph('', s_tdc)] +
        [Paragraph('', s_tdc) for _ in range(num_semesters)] +
        [Paragraph(f"<b>{ue_table_data['total_qt']}</b>", s_tdc), Paragraph(f"<b>{ue_table_data['total_credits']}</b>", s_tdc)]
    )

    ue_col   = 3.6*cm
    mod_col  = 18*cm - ue_col - (0.72*cm * num_semesters) - 1.3*cm - 1.3*cm
    sem_col  = 0.72*cm
    col_widths = [ue_col, mod_col] + [sem_col] * num_semesters + [1.3*cm, 1.3*cm]

    if ue_table_data['rows']:
        ue_tbl = Table(table_rows, colWidths=col_widths, repeatRows=1)
        ue_tbl.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0), navy),
            ('BACKGROUND',     (0, -1), (-1, -1), light),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',     (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',    (0, 0), (-1, -1), 3), ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ]))
        story.append(ue_tbl)
    else:
        story.append(Paragraph("Aucun module (EC) n'est encore défini pour cette filière.", s_body))

    story += [
        Spacer(1, .8*cm),
        Table([
            [Paragraph(f"{ville}, le {dt.today().strftime('%d/%m/%Y')}", sc('dsdl', parent=ss['Normal'], fontSize=9)),
             Paragraph(bulletin_config.director_title or 'La Directrice des Études', s_sgn)],
            ['', Paragraph(bulletin_config.director_name or '', sc('dsdn', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, textColor=grey))],
        ], colWidths=[10.5*cm, 7.5*cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')]),
    ]

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="supplement_diplome_{cycle}_{student.matricule}.pdf"'
    return resp


@login_required
def attestation_non_soutenance_pdf(request):
    """
    Attestation de non soutenance — réservée aux étudiants actuellement en
    Licence 3 ou Master 2 (voir students/services.py::NON_SOUTENANCE_LEVELS),
    délivrée uniquement s'ils ont validé TOUTES les UE de TOUTES les classes
    précédentes ET de leur classe actuelle
    (students/services.py::check_non_soutenance_eligibility) — condition
    explicitement demandée, plus stricte que la simple inscription validée
    utilisée pour le supplément de diplôme (diploma_supplement_pdf).

    Accès : l'étudiant lui-même (son propre dossier), ou un membre du
    personnel habilité (_require_inscription_access) via ?student_id=.
    """
    from academic_core.apps.students.models import Student
    from academic_core.apps.students.services import (
        check_non_soutenance_eligibility, non_soutenance_cycle_label,
        resolve_non_soutenance_context,
    )
    from academic_core.apps.academic_structure.models import BulletinConfig
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from datetime import date as dt
    from academic_core.pdf_utils import logo_image as _logo_img_fn4, senegal_flag as _flag_fn4, get_institut_config_for_request, watermark_canvas

    student = None
    if request.user.is_etudiant():
        student = getattr(request.user, 'student_profile', None)
    student_id = request.GET.get('student_id')
    if student_id and _require_inscription_access(request.user):
        student = get_object_or_404(Student, pk=student_id)

    if not student:
        messages.error(request, "Profil étudiant introuvable.")
        return redirect('dashboard:index')

    enrollment, required_levels = resolve_non_soutenance_context(student)
    if not enrollment:
        messages.warning(
            request,
            "L'attestation de non soutenance n'est délivrée qu'aux étudiants actuellement "
            "inscrits en Licence 3 ou Master 2 — ce n'est pas votre cas."
        )
        return redirect('dashboard:index')

    program = enrollment.class_group.program
    result = check_non_soutenance_eligibility(student, enrollment, required_levels)
    if not result['eligible']:
        parts = []
        if result['missing_enrollment_levels']:
            parts.append(
                "inscription(s) validée(s) manquante(s) pour : " + ', '.join(result['missing_enrollment_levels'])
            )
        if result['missing_semesters']:
            parts.append(f"{len(result['missing_semesters'])} semestre(s) sans bulletin")
        if result['missing_ue']:
            parts.append(f"{len(result['missing_ue'])} UE non encore validée(s)")
        messages.warning(
            request,
            "Vous ne pouvez pas encore obtenir l'attestation de non soutenance : "
            + ' · '.join(parts) if parts else
            "Vous ne remplissez pas encore les conditions pour l'attestation de non soutenance."
        )
        return redirect('dashboard:index')

    config = BulletinConfig.get()
    inst_cfg = get_institut_config_for_request(request)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    ss    = getSampleStyleSheet()
    sc    = ParagraphStyle
    s_ctr = sc('nsc',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl = sc('nst',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=17, fontName='Helvetica-Bold', textColor=navy)
    s_sub = sc('nss',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=10, textColor=grey)
    s_lbl = sc('nsl',  parent=ss['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=navy)
    s_val = sc('nsv',  parent=ss['Normal'], fontSize=10)
    s_sgn = sc('nssg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=10, fontName='Helvetica-Bold')

    inst_nom   = inst_cfg.nom if inst_cfg else ''
    inst_sigle = (inst_cfg.sigle if inst_cfg else '') or inst_nom
    ville      = (inst_cfg.ville if inst_cfg and inst_cfg.ville else 'Dakar')

    flag_el = _flag_fn4(width=2.4*cm, height=1.6*cm)
    logo_el = _logo_img_fn4(width=2.4*cm, height=1.6*cm, config=inst_cfg) or Paragraph(
        inst_sigle, sc('nslb', parent=s_ctr, fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    rep_txt = Paragraph(
        '<b>REPUBLIQUE DU SÉNÉGAL</b><br/><font size="8">Un Peuple — Un But — Une Foi</font>'
        f'<br/><br/><font size="13"><b>{inst_sigle}</b></font><br/>'
        f"<font size='9'>{inst_nom}</font>",
        sc('nsrh', parent=ss['Normal'], alignment=TA_CENTER, leading=14),
    )
    hdr_tbl = Table([[flag_el, rep_txt, logo_el]], colWidths=[3*cm, 11*cm, 3*cm])
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    cycle_label = non_soutenance_cycle_label(enrollment.class_group.level.name)
    inst_nom_display = inst_nom or "l'institut"
    story = [
        hdr_tbl,
        Spacer(1, .3*cm), HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=8),
        Spacer(1, .5*cm),
        Paragraph("ATTESTATION DE NON SOUTENANCE", s_ttl),
        Spacer(1, .3*cm),
        Paragraph(f"Année académique {enrollment.academic_year.label}", s_sub),
        Spacer(1, .6*cm), HRFlowable(width='60%', thickness=1, color=gold, hAlign='CENTER'), Spacer(1, .8*cm),
        Paragraph(
            f"Nous soussignés, la Direction de {inst_nom_display}, attestons que l'étudiant(e) "
            f"mentionné(e) ci-dessous a suivi et <b>validé la totalité des Unités d'Enseignement (UE)</b> "
            f"du cycle {cycle_label} au titre de la classe <b>{enrollment.class_group.name}</b>"
            + (f", à l'exception de l'UE « <b>{result['exempted_ue'].title}</b> » (stage / mémoire)"
               if result.get('exempted_ue') else '')
            + f", mais n'a <b>pas encore soutenu</b> son mémoire / projet de fin d'études à la date de "
              f"délivrance de la présente attestation.",
            sc('nsintro', parent=ss['Normal'], fontSize=10, leading=16),
        ),
        Spacer(1, .6*cm),
    ]
    story.append(Table([
        [Paragraph("<b>Matricule</b>", s_lbl),           Paragraph(student.matricule, s_val)],
        [Paragraph("<b>Nom &amp; Prénom(s)</b>", s_lbl), Paragraph(student.full_name, s_val)],
        [Paragraph("<b>Date de naissance</b>", s_lbl),   Paragraph(student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '-', s_val)],
        [Paragraph("<b>Filière</b>", s_lbl),             Paragraph(program.name, s_val)],
        [Paragraph("<b>Classe actuelle</b>", s_lbl),     Paragraph(enrollment.class_group.name, s_val)],
        [Paragraph("<b>Année académique</b>", s_lbl),    Paragraph(enrollment.academic_year.label, s_val)],
    ], colWidths=[5.5*cm, 11*cm], style=TableStyle([
        ('BACKGROUND',     (0, 0), (0, -1), light),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('GRID',           (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',     (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',    (0, 0), (-1, -1), 8),
    ])))
    story += [
        Spacer(1, .8*cm),
        Paragraph(
            "La présente attestation est délivrée à l'intéressé(e) pour servir et valoir ce que de droit, "
            "dans l'attente de sa soutenance et de la délivrance du diplôme définitif.",
            sc('nssrv', parent=ss['Normal'], fontSize=10, fontName='Helvetica-BoldOblique', alignment=TA_CENTER),
        ),
        Spacer(1, 1*cm),
        Table([
            [Paragraph(f"{ville}, le {dt.today().strftime('%d/%m/%Y')}", sc('nsdl', parent=ss['Normal'], fontSize=9)),
             Paragraph(config.director_title or "Le Directeur Général", s_sgn)],
            ['', Paragraph(config.director_name or '', sc('nsdn', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, textColor=grey))],
        ], colWidths=[9*cm, 7.5*cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')]),
    ]
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="attestation_non_soutenance_{student.matricule}.pdf"'
    return resp


# ===========================================================================
# RÉPARTITION ANNÉE ACADÉMIQUE
# ===========================================================================

def _require_repartition_access(user):
    # is_admin() couvre déjà ADMIN, INST_ADMIN, CONTROLEUR, COMPTABLE,
    # TRESORIER_GENERAL, CAISSIER, etc. — assure un accès réel à
    # l'Administrateur d'institut, pas seulement un lien visible dans le menu.
    return user.is_admin() or user.is_responsable()


@login_required
def repartition_annee_list(request):
    if not _require_repartition_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import AcademicYearDistribution
    from academic_core.apps.academic_structure.models import AcademicYear

    faculty_r = None if (request.user.is_controleur() or request.user.is_comptable()) else getattr(request, 'active_faculty', None)
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=faculty_r) if faculty_r else academic_years

    # Année académique : par défaut l'année en cours — "Toutes les années"
    # (academic_year=all) reste disponible pour consulter l'historique.
    year_filter = request.GET.get('academic_year', '')
    if year_filter == 'all':
        selected_year_id = None
    elif year_filter:
        selected_year_id = year_filter
    else:
        current_year = academic_years.filter(is_current=True).first()
        selected_year_id = current_year.pk if current_year else None

    qs = AcademicYearDistribution.objects.select_related(
        'academic_year', 'class_group__program__department',
        'class_group__level', 'created_by',
    ).order_by('-academic_year__start_date', 'class_group__name')

    if faculty_r:
        qs = qs.filter(class_group__program__department__faculty=faculty_r)
    if selected_year_id:
        qs = qs.filter(academic_year_id=selected_year_id)

    return render(request, 'accounting/repartition_annee_list.html', {
        'distributions':  qs,
        'year_filter':    year_filter,
        'academic_years': academic_years,
    })


@login_required
def repartition_annee_create(request):
    if not _require_repartition_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import AcademicYearDistribution
    from academic_core.apps.academic_structure.models import AcademicYear, Class

    from .models import AcademicYearDistribution
    MONTHS = AcademicYearDistribution.MONTHS

    if request.method == 'POST':
        class_group_id   = request.POST.get('class_group')
        academic_year_id = request.POST.get('academic_year')
        start_month      = request.POST.get('start_month')
        nb_months        = request.POST.get('nb_months')
        notes            = request.POST.get('notes', '').strip()

        class_group = Class.objects.filter(pk=class_group_id).first()
        acad_year   = AcademicYear.objects.filter(pk=academic_year_id).first()

        if not (class_group and acad_year and start_month and nb_months):
            messages.error(request, "Classe, année académique, mois de début et nombre de mois sont obligatoires.")
        elif AcademicYearDistribution.objects.filter(academic_year=acad_year, class_group=class_group).exists():
            messages.error(request, "Une répartition existe déjà pour cette classe et cette année.")
        else:
            AcademicYearDistribution.objects.create(
                academic_year=acad_year, class_group=class_group,
                start_month=int(start_month),
                nb_months=int(nb_months), notes=notes, created_by=request.user,
            )
            messages.success(request, f"Répartition créée : {class_group.name} → {nb_months} mois.")
            return redirect('accounting:repartition_annee_list')

    faculty = None if (request.user.is_controleur() or request.user.is_comptable()) else getattr(request, 'active_faculty', None)
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=faculty) if faculty else academic_years
    classes = Class.objects.select_related('program__department', 'level', 'academic_year').order_by('name')
    if faculty:
        classes = classes.filter(program__department__faculty=faculty)
        current_year = academic_years.filter(is_current=True).first()
        if current_year:
            classes = classes.filter(academic_year=current_year)

    return render(request, 'accounting/repartition_annee_form.html', {
        'title':          "Nouvelle répartition",
        'academic_years': academic_years,
        'classes':        classes,
        'months':         MONTHS,
    })


@login_required
def repartition_annee_edit(request, pk):
    if not _require_repartition_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import AcademicYearDistribution
    from academic_core.apps.academic_structure.models import AcademicYear, Class

    obj = get_object_or_404(AcademicYearDistribution, pk=pk)
    MONTHS = AcademicYearDistribution.MONTHS

    if request.method == 'POST':
        start_month = request.POST.get('start_month')
        nb_months   = request.POST.get('nb_months')
        notes       = request.POST.get('notes', '').strip()
        if not (start_month and nb_months):
            messages.error(request, "Le mois de début et le nombre de mois sont obligatoires.")
        else:
            obj.start_month = int(start_month)
            obj.nb_months   = int(nb_months)
            obj.notes       = notes
            obj.save()
            messages.success(request, "Répartition mise à jour.")
            return redirect('accounting:repartition_annee_list')

    faculty = None if (request.user.is_controleur() or request.user.is_comptable()) else getattr(request, 'active_faculty', None)
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=faculty) if faculty else academic_years
    classes = Class.objects.select_related('program__department', 'level', 'academic_year').order_by('name')
    if faculty:
        classes = classes.filter(program__department__faculty=faculty)

    return render(request, 'accounting/repartition_annee_form.html', {
        'title':   "Modifier la répartition",
        'obj':     obj,
        'months':  MONTHS,
        'academic_years': academic_years,
        'classes': classes,
    })


@login_required
def repartition_annee_delete(request, pk):
    if not _require_repartition_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import AcademicYearDistribution
    obj = get_object_or_404(AcademicYearDistribution, pk=pk)
    if request.method == 'POST':
        label = str(obj)
        obj.delete()
        messages.success(request, f"Répartition supprimée : {label}.")
    return redirect('accounting:repartition_annee_list')


# ---------------------------------------------------------------------------
# Attestation de réussite (PDF, comptabilité seulement)
# ---------------------------------------------------------------------------

def _require_reussite_access(user):
    return user.is_admin() or user.is_responsable() or user.is_comptable()


@login_required
def attestation_reussite_pdf(request, pk):
    if not _require_reussite_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from academic_core.apps.students.models import Student, Enrollment
    from academic_core.apps.academic_structure.models import BulletinConfig
    from datetime import date as dt

    student = get_object_or_404(Student, pk=pk)

    # Vérifier validité du compte
    if not student.user.is_active or student.payment_suspended:
        messages.error(request, "Le compte de cet étudiant n'est pas valide. L'attestation de réussite ne peut pas être éditée.")
        return redirect('accounting:validation_inscription_list')

    enrollment = Enrollment.objects.filter(student=student, status=Enrollment.STATUS_VALIDATED).order_by('-id').first()
    config = BulletinConfig.get()
    today = dt.today()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)

    styles = getSampleStyleSheet()
    navy = colors.HexColor('#1e3a5f')
    gold = colors.HexColor('#d4af37')
    light_blue = colors.HexColor('#e8f0fe')

    title_style = ParagraphStyle('Title', fontSize=16, fontName='Helvetica-Bold',
                                 textColor=navy, alignment=TA_CENTER, spaceAfter=6)
    subtitle_style = ParagraphStyle('Sub', fontSize=11, fontName='Helvetica',
                                    textColor=colors.HexColor('#475569'), alignment=TA_CENTER, spaceAfter=4)
    body_style = ParagraphStyle('Body', fontSize=11, fontName='Helvetica',
                                leading=18, spaceAfter=8)
    center_style = ParagraphStyle('Center', fontSize=11, fontName='Helvetica',
                                  alignment=TA_CENTER, leading=18, spaceAfter=8)

    from academic_core.pdf_utils import logo_image as _logo_img_r_fn, senegal_flag as _flag_r, get_institut_config_for_request as _gcfr_r
    from reportlab.platypus import Image as _RLImage
    _inst_cfg_r = _gcfr_r(request)
    _logo_img_r = lambda **kw: _logo_img_r_fn(config=_inst_cfg_r, **kw)  # noqa: E731

    story = []

    # En-tête avec logo
    school_name = _inst_cfg_r.nom if _inst_cfg_r and _inst_cfg_r.nom else ''
    school_address = _inst_cfg_r.adresse if _inst_cfg_r and _inst_cfg_r.adresse else ''
    _logo_r = _logo_img_r(width=2.4*cm, height=1.6*cm)
    _center_r = []
    if school_name:
        _center_r.append(Paragraph(f'<b>{school_name.upper()}</b>', title_style))
    if school_address:
        _center_r.append(Paragraph(school_address, subtitle_style))
    from reportlab.platypus import KeepTogether
    _hdr_r = Table([[
        Paragraph('', title_style),
        Paragraph(
            f'<b>{school_name.upper() if school_name else "GROUPE ISI"}</b>'
            + (f'<br/><font size="9">{school_address}</font>' if school_address else ''),
            ParagraphStyle('rhr', fontSize=12, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, leading=16),
        ),
        _logo_r or Paragraph('ISI', subtitle_style),
    ]], colWidths=[3*cm, 11*cm, 3*cm])
    _hdr_r.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(_hdr_r)
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width='100%', thickness=2, color=navy))
    story.append(Spacer(1, 0.5*cm))

    # Titre du document
    story.append(Paragraph("ATTESTATION DE RÉUSSITE", ParagraphStyle('DocTitle', fontSize=18,
                             fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER,
                             spaceAfter=4, spaceBefore=8)))
    story.append(HRFlowable(width='60%', thickness=1, color=gold, hAlign='CENTER'))
    story.append(Spacer(1, 0.8*cm))

    # Corps
    class_name = enrollment.class_group.name if enrollment and enrollment.class_group else (student.current_class.name if student.current_class else '–')
    year_name = enrollment.academic_year.name if enrollment and enrollment.academic_year else '–'

    story.append(Paragraph(
        f"Nous soussignés, <b>{config.director_name or 'la Direction'}</b>,"
        f" {config.director_title or 'Direction'} de <b>{school_name or 'l\'établissement'}</b>,"
        " attestons par la présente que :", body_style))
    story.append(Spacer(1, 0.3*cm))

    # Encadré étudiant
    info_data = [
        [Paragraph('<b>Nom complet</b>', body_style), Paragraph(student.full_name, body_style)],
        [Paragraph('<b>Matricule</b>', body_style), Paragraph(student.matricule or '–', body_style)],
        [Paragraph('<b>Date de naissance</b>', body_style), Paragraph(student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '–', body_style)],
        [Paragraph('<b>Classe</b>', body_style), Paragraph(class_name, body_style)],
        [Paragraph('<b>Année académique</b>', body_style), Paragraph(year_name, body_style)],
    ]
    info_table = Table(info_data, colWidths=[5*cm, 10*cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), light_blue),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#e8f0fe'), colors.white]),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.6*cm))

    story.append(Paragraph(
        f"a satisfait aux exigences académiques de l'année <b>{year_name}</b> "
        f"en classe de <b>{class_name}</b>. Son dossier financier est en règle "
        "et son compte est en statut <b>Valide</b>.",
        body_style))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "La présente attestation est délivrée pour servir et valoir ce que de droit.",
        body_style))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        f"Fait à {school_address or '___________'}, le {today.strftime('%d/%m/%Y')}",
        center_style))
    story.append(Spacer(1, 0.5*cm))

    # Signature
    sig_data = [[
        Paragraph('', body_style),
        Paragraph(f"<b>{config.director_title or 'Le Directeur'}</b><br/><br/><br/><br/>{config.director_name or ''}", center_style),
    ]]
    sig_table = Table(sig_data, colWidths=[8*cm, 8*cm])
    sig_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(sig_table)

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf = buffer.getvalue()
    buffer.close()

    filename = f"attestation_reussite_{student.matricule or student.pk}.pdf"
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Attestation de fin de cycle (Licence 3 / Master 2)
# ---------------------------------------------------------------------------

def _detect_fin_cycle(level_name):
    """Retourne ('LICENCE', [1,2,3]) ou ('MASTER', [1,2]) selon le nom du niveau, sinon (None, None)."""
    import re
    n = level_name.lower()
    if re.search(r'licen[cs]?e?\s*3|l\s*3\b', n):
        return 'LICENCE', [1, 2, 3]
    if re.search(r'master\s*2|m\s*2\b', n):
        return 'MASTER', [1, 2]
    return None, None


def _level_matches_year(level_name, cycle, year_num):
    import re
    n = level_name.lower()
    if cycle == 'LICENCE':
        return bool(re.search(rf'licen[cs]?e?\s*{year_num}|l\s*{year_num}\b', n))
    return bool(re.search(rf'master\s*{year_num}|m\s*{year_num}\b', n))


@login_required
def attestation_fin_cycle_pdf(request, pk):
    if not _require_reussite_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from academic_core.apps.students.models import Student, Enrollment
    from academic_core.apps.grades.models import Bulletin
    from academic_core.apps.academic_structure.models import BulletinConfig, Level
    from academic_core.pdf_utils import (logo_image as _logo_fn,
                                         get_institut_config_for_request as _gcfr)
    from datetime import date as dt

    student = get_object_or_404(Student, pk=pk)

    # Déterminer le cycle depuis l'inscription en cours / la dernière validée
    last_enrollment = (Enrollment.objects
                       .filter(student=student, status=Enrollment.STATUS_VALIDATED)
                       .select_related('class_group__level', 'academic_year')
                       .order_by('-id').first())

    if not last_enrollment:
        messages.error(request, "Aucune inscription validée trouvée pour cet étudiant.")
        return redirect('accounting:validation_inscription_list')

    cycle, year_nums = _detect_fin_cycle(last_enrollment.class_group.level.name)
    if cycle is None:
        messages.error(request, "L'attestation de fin de cycle n'est disponible que pour les niveaux Licence 3 et Master 2.")
        return redirect('accounting:validation_inscription_list')

    cycle_label = 'Licence' if cycle == 'LICENCE' else 'Master'

    # --- Récupérer toutes les inscriptions validées du cycle ------------------
    all_levels = Level.objects.all()
    cycle_data = []  # liste de dicts par année du cycle
    errors = []

    for year_num in year_nums:
        matching_levels = [l for l in all_levels if _level_matches_year(l.name, cycle, year_num)]
        if not matching_levels:
            errors.append(f"{cycle_label} {year_num} : niveau introuvable dans la base.")
            continue

        enrollment = (Enrollment.objects
                      .filter(student=student,
                              status=Enrollment.STATUS_VALIDATED,
                              class_group__level__in=matching_levels)
                      .select_related('class_group', 'class_group__level', 'academic_year')
                      .order_by('-id').first())

        if not enrollment:
            errors.append(f"{cycle_label} {year_num} : aucune inscription validée.")
            continue

        # Crédits : somme des bulletins publiés/verrouillés pour cette inscription
        bulletins = Bulletin.objects.filter(
            student=student,
            class_group=enrollment.class_group,
            semester__academic_year=enrollment.academic_year,
            status__in=[Bulletin.STATUS_PUBLISHED, Bulletin.STATUS_LOCKED],
        )
        total_credits = sum(b.total_credits_obtained for b in bulletins)
        credits_ok = total_credits >= 60

        # Paiements mensualités
        unpaid_count = enrollment.installments.filter(is_paid=False).count()
        payments_ok = unpaid_count == 0

        cycle_data.append({
            'level_name': enrollment.class_group.level.name,
            'year_label': enrollment.academic_year.label,
            'credits': total_credits,
            'credits_ok': credits_ok,
            'payments_ok': payments_ok,
            'unpaid_count': unpaid_count,
        })

        if not credits_ok:
            errors.append(f"{cycle_label} {year_num} ({enrollment.academic_year.label}) : "
                          f"crédits insuffisants ({total_credits}/60).")
        if not payments_ok:
            errors.append(f"{cycle_label} {year_num} ({enrollment.academic_year.label}) : "
                          f"{unpaid_count} mensualité(s) impayée(s).")

    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect('accounting:validation_inscription_detail', pk=last_enrollment.pk)

    # --- Génération PDF -------------------------------------------------------
    config = BulletinConfig.get()
    inst_cfg = _gcfr(request)
    today = dt.today()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                            topMargin=2.5 * cm, bottomMargin=2.5 * cm)

    styles = getSampleStyleSheet()
    navy = colors.HexColor('#1e3a5f')
    gold = colors.HexColor('#d4af37')

    title_style = ParagraphStyle('title', parent=styles['Normal'],
                                 fontSize=15, textColor=navy,
                                 fontName='Helvetica-Bold', alignment=TA_CENTER,
                                 spaceAfter=4)
    subtitle_style = ParagraphStyle('subtitle', parent=styles['Normal'],
                                    fontSize=11, textColor=gold,
                                    fontName='Helvetica-Bold', alignment=TA_CENTER,
                                    spaceAfter=6)
    body_style = ParagraphStyle('body', parent=styles['Normal'],
                                fontSize=10, leading=16, spaceAfter=8)
    center_style = ParagraphStyle('center', parent=styles['Normal'],
                                  fontSize=10, leading=14, alignment=TA_CENTER)
    label_style = ParagraphStyle('label', parent=styles['Normal'],
                                 fontSize=10, fontName='Helvetica-Bold')

    logo = _logo_fn(config=inst_cfg, width=2.4 * cm, height=1.6 * cm)

    school_name = config.school_name or 'ÉTABLISSEMENT D\'ENSEIGNEMENT SUPÉRIEUR'
    school_address = config.school_address or ''

    header_table = Table([[
        Paragraph('', body_style),
        Paragraph(f'<b>{school_name}</b><br/><font size="8">{school_address}</font>',
                  center_style),
        logo or Paragraph('', body_style),
    ]], colWidths=[3 * cm, 11 * cm, 3 * cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
    ]))

    # Nom & genre de l'étudiant
    gender_prefix = 'Mme' if student.gender == 'F' else 'M.'
    full_name = student.user.get_full_name() or student.matricule
    program_name = last_enrollment.class_group.program.name if hasattr(last_enrollment.class_group, 'program') else ''
    mention_name = last_enrollment.class_group.mention or ''

    year_range = f"{cycle_data[0]['year_label']} – {cycle_data[-1]['year_label']}"

    story = []

    # En-tête
    story.append(header_table)
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width='100%', thickness=2, color=navy))
    story.append(Spacer(1, 0.4 * cm))

    # Titre
    story.append(Paragraph('ATTESTATION DE FIN DE CYCLE', title_style))
    story.append(Paragraph(cycle_label.upper(), subtitle_style))
    story.append(HRFlowable(width='60%', thickness=1.5, color=gold))
    story.append(Spacer(1, 0.6 * cm))

    # Paragraphe introductif
    director_title = config.director_title or 'Le Directeur Général'
    director_name = config.director_name or ''
    story.append(Paragraph(
        f'<b>{director_title}</b> de <b>{school_name}</b>,',
        body_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph('Atteste que :', label_style))
    story.append(Spacer(1, 0.4 * cm))

    # Tableau infos étudiant
    info_rows = [
        ['Nom et Prénom', f'{gender_prefix} {full_name}'],
        ['Matricule', student.matricule or '—'],
        ['Date de naissance', student.date_of_birth.strftime('%d/%m/%Y') if student.date_of_birth else '—'],
        ['Lieu de naissance', student.place_of_birth or '—'],
        ['Filière / Mention', mention_name or program_name or '—'],
        ['Cycle', f'{cycle_label} ({year_range})'],
    ]
    info_table = Table(info_rows, colWidths=[5 * cm, 12 * cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), navy),
        ('ROWBACKGROUNDS', (1, 0), (1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.6 * cm))

    # Corps du texte
    story.append(Paragraph(
        f'A suivi et <b>validé l\'intégralité du cursus de {cycle_label}</b> '
        f'en <b>{mention_name or program_name}</b> '
        f'au sein de <b>{school_name}</b>, '
        f'de l\'année académique {cycle_data[0]["year_label"]} '
        f'à l\'année académique {cycle_data[-1]["year_label"]}.',
        body_style))
    story.append(Spacer(1, 0.3 * cm))

    # Tableau récapitulatif des crédits par année
    story.append(Paragraph('<b>Récapitulatif des crédits obtenus par niveau :</b>', label_style))
    story.append(Spacer(1, 0.3 * cm))

    credits_header = [
        Paragraph('<b>Niveau</b>', center_style),
        Paragraph('<b>Année académique</b>', center_style),
        Paragraph('<b>Crédits obtenus</b>', center_style),
        Paragraph('<b>Statut</b>', center_style),
    ]
    credits_rows = [credits_header]
    for row in cycle_data:
        credits_rows.append([
            Paragraph(row['level_name'], center_style),
            Paragraph(row['year_label'], center_style),
            Paragraph(f"{row['credits']} / 60", center_style),
            Paragraph('<font color="#16a34a">✓ Validé</font>', center_style),
        ])
    total_credits_all = sum(r['credits'] for r in cycle_data)
    credits_rows.append([
        Paragraph('<b>TOTAL</b>', center_style),
        Paragraph('', center_style),
        Paragraph(f'<b>{total_credits_all} / {60 * len(cycle_data)}</b>', center_style),
        Paragraph('', center_style),
    ])

    credits_table = Table(credits_rows, colWidths=[4 * cm, 4.5 * cm, 4 * cm, 4.5 * cm])
    credits_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8fafc')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f1f5f9')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(credits_table)
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph(
        'L\'intéressé(e) a satisfait à l\'ensemble des conditions académiques '
        '(validation des unités d\'enseignement) et financières (règlement de la '
        'totalité des frais de formation) requises pour l\'obtention de cette attestation.',
        body_style))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph(
        'La présente attestation est délivrée pour servir et valoir ce que de droit.',
        body_style))
    story.append(Spacer(1, 0.6 * cm))

    # Date
    months_fr = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
    date_str = f'Fait à Dakar, le {today.day} {months_fr[today.month - 1]} {today.year}'
    story.append(Paragraph(date_str, center_style))
    story.append(Spacer(1, 0.6 * cm))

    # Signature
    sig_table = Table([[
        Paragraph('', body_style),
        Paragraph(f'<b>{director_title}</b><br/><br/><br/><br/>{director_name}',
                  center_style),
    ]], colWidths=[8 * cm, 8 * cm])
    sig_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(sig_table)

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf = buffer.getvalue()
    buffer.close()

    filename = f"attestation_fin_cycle_{cycle_label.lower()}_{student.matricule or student.pk}.pdf"
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# État journalier & clôture comptable
# ---------------------------------------------------------------------------

def _require_etat_access(user):
    return user.is_admin() or user.is_responsable() or user.is_comptable() or user.is_controleur()


# ── État journalier : modifier / supprimer ────────────────────────────────────

@login_required
def etat_caisse_edit(request, pk):
    """Modifier un CaissePayment depuis l'état journalier (AJAX POST)."""
    from django.http import JsonResponse
    from .models import CaissePayment
    if not _require_etat_access(request.user):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    cp = get_object_or_404(CaissePayment, pk=pk)
    try:
        cp.amount       = Decimal(request.POST.get('amount', cp.amount))
        cp.payment_date = request.POST.get('payment_date', str(cp.payment_date))
        cp.notes        = request.POST.get('notes', cp.notes or '').strip()
        cp.save()
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'ok': True,
        'amount':       str(cp.amount),
        'payment_date': cp.payment_date.strftime('%d/%m/%Y'),
        'notes':        cp.notes,
        'reference':    cp.reference or '—',
    })


@login_required
def etat_caisse_delete(request, pk):
    """Supprimer un CaissePayment depuis l'état journalier (AJAX POST)."""
    from django.http import JsonResponse
    from .models import CaissePayment
    if not _require_etat_access(request.user):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    cp = get_object_or_404(CaissePayment, pk=pk)
    cp.delete()
    return JsonResponse({'ok': True})


@login_required
def etat_installment_edit(request, pk):
    """Modifier un PaymentInstallment depuis l'état journalier (AJAX POST)."""
    from django.http import JsonResponse
    from academic_core.apps.students.models import PaymentInstallment
    import datetime as _dt
    if not _require_etat_access(request.user):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    inst = get_object_or_404(PaymentInstallment, pk=pk)
    try:
        inst.amount_paid = Decimal(request.POST.get('amount', inst.amount_paid or 0))
        date_raw = request.POST.get('payment_date', '')
        if date_raw:
            inst.paid_date = _dt.date.fromisoformat(date_raw)
        inst.notes = request.POST.get('notes', inst.notes or '').strip()
        inst.save()
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({
        'ok': True,
        'amount':       str(inst.amount_paid),
        'payment_date': inst.paid_date.strftime('%d/%m/%Y') if inst.paid_date else '—',
        'notes':        inst.notes,
    })


@login_required
def etat_installment_delete(request, pk):
    """Annuler (dépayer) un PaymentInstallment depuis l'état journalier (AJAX POST)."""
    from django.http import JsonResponse
    from academic_core.apps.students.models import PaymentInstallment
    if not _require_etat_access(request.user):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    inst = get_object_or_404(PaymentInstallment, pk=pk)
    inst.is_paid     = False
    inst.amount_paid = None
    inst.paid_date   = None
    inst.save()
    return JsonResponse({'ok': True})


@login_required
def etat_journalier(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment, PaymentInstallment, Student
    from .models import AccountingClosure, CaissePayment, CaisseMovement
    from academic_core.apps.academic_structure.models import AcademicYear
    from academic_core.apps.academic_structure.utils import resolve_academic_years
    from django.db.models import Q
    from datetime import date as dt, datetime

    today = dt.today()

    # Filtre de date : paramètre GET ou aujourd'hui
    date_str = request.GET.get('date', '')
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        selected_date = today

    # Filtre d'année académique : paramètre GET ou année en cours. Les
    # enregistrements sans année renseignée (anciennes données) restent
    # toujours visibles, quelle que soit l'année sélectionnée.
    academic_years, selected_year = resolve_academic_years(request)
    year_q = Q(academic_year=selected_year) | Q(academic_year__isnull=True) if selected_year else Q()
    enr_year_q = Q(academic_year=selected_year) | Q(academic_year__isnull=True) if selected_year else Q()
    inst_year_q = Q(enrollment__academic_year=selected_year) | Q(enrollment__academic_year__isnull=True) if selected_year else Q()

    faculty_e = None if (request.user.is_controleur() or request.user.is_comptable()) else getattr(request, 'active_faculty', None)

    def _enr_qs():
        qs = Enrollment.objects.filter(enr_year_q)
        if faculty_e:
            qs = qs.filter(class_group__program__department__faculty=faculty_e)
        return qs

    def _inst_qs():
        qs = PaymentInstallment.objects.filter(inst_year_q)
        if faculty_e:
            qs = qs.filter(enrollment__class_group__program__department__faculty=faculty_e)
        return qs

    def _caisse_qs():
        # Pas de filtre faculté sur caisse : le paiement caisse n'est pas
        # forcément lié à une inscription active dans la même faculté
        return CaissePayment.objects.filter(year_q)

    # Paiements initiaux d'inscription (ancien flux Enrollment — montant non nul seulement)
    # Exclure ceux qui ont déjà un CaissePayment lié pour éviter le double affichage
    from django.db.models import Exists, OuterRef as _OuterRef
    payments_today = _enr_qs().filter(
        payment_date=selected_date,
        status=Enrollment.STATUS_VALIDATED,
        payment_amount__isnull=False,
        payment_amount__gt=0,
    ).filter(
        ~Exists(CaissePayment.objects.filter(enrollment_id=_OuterRef('pk')))
    ).select_related('student__user', 'class_group', 'academic_year')

    # Mensualités payées (ancien flux PaymentInstallment)
    # Exclure ceux dont l'étudiant a déjà un CaissePayment SCOLARITE à la même date
    # (les CaissePayment peuvent avoir enrollment_id=None, on joint par student_id).
    installments_today = _inst_qs().filter(
        paid_date=selected_date, is_paid=True,
    ).filter(
        ~Exists(
            CaissePayment.objects.filter(
                student_id=_OuterRef('enrollment__student_id'),
                payment_date=selected_date,
                payment_type__in=[CaissePayment.TYPE_SCOLARITE, CaissePayment.TYPE_SOUTENANCE],
            )
        )
    ).select_related('enrollment__student__user', 'enrollment__class_group')

    # Paiements caisse de la date sélectionnée
    caisse_day = _caisse_qs().filter(
        payment_date=selected_date,
    ).select_related('student__user', 'student__current_class', 'academic_year').order_by('-id')

    caisse_inscription_today = caisse_day.filter(payment_type=CaissePayment.TYPE_INSCRIPTION)
    caisse_scolarite_today   = caisse_day.filter(payment_type__in=[CaissePayment.TYPE_SCOLARITE, CaissePayment.TYPE_SOUTENANCE])

    # Totaux
    total_inscription = (
        sum(e.payment_amount or 0 for e in payments_today)
        + sum(c.amount or 0 for c in caisse_inscription_today)
    )
    total_mensualites = (
        sum(i.amount_paid or 0 for i in installments_today)
        + sum(c.amount or 0 for c in caisse_scolarite_today)
    )
    total_du_jour = total_inscription + total_mensualites

    # Vue globale
    nb_validated = _enr_qs().filter(status=Enrollment.STATUS_VALIDATED).count()
    nb_pending   = _enr_qs().filter(status=Enrollment.STATUS_PENDING).count()
    nb_rejected  = _enr_qs().filter(status=Enrollment.STATUS_REJECTED).count()
    nb_suspended = Student.objects.filter(
        Q(enrollments__academic_year=selected_year) | Q(enrollments__academic_year__isnull=True) if selected_year else Q(),
        payment_suspended=True,
        **(({'enrollments__class_group__program__department__faculty': faculty_e}) if faculty_e else {})
    ).distinct().count()

    from django.db.models import Sum as _AggSum
    _validated_qs = _enr_qs().filter(status=Enrollment.STATUS_VALIDATED)
    _agg = _validated_qs.aggregate(s=_AggSum('payment_amount'), t=_AggSum('total_fees'))
    total_collected_global = _agg['s'] or 0
    total_remaining_global = (_agg['t'] or 0) - total_collected_global
    total_installments_global = (
        _inst_qs().filter(is_paid=True).aggregate(s=_AggSum('amount_paid'))['s'] or 0
    )

    already_closed = AccountingClosure.objects.filter(closure_date=selected_date).exists()

    # Mouvements de caisse (Brouillard) de la date sélectionnée — hors
    # paiements étudiants, déjà couverts ci-dessus.
    movements_day = CaisseMovement.objects.filter(year_q).filter(
        movement_date=selected_date,
    ).select_related('created_by', 'executed_by').order_by('-created_at')
    total_entrees_jour = sum(m.amount for m in movements_day if m.movement_type == CaisseMovement.TYPE_ENTREE and m.is_executed)
    total_sorties_jour = sum(m.amount for m in movements_day if m.movement_type == CaisseMovement.TYPE_SORTIE and m.is_executed)
    solde_caisse_jour  = total_du_jour + total_entrees_jour - total_sorties_jour

    ctx = {
        'today': today,
        'selected_date': selected_date,
        'is_today': selected_date == today,
        'academic_years': academic_years,
        'selected_year': selected_year,
        'payments_today': payments_today,
        'installments_today': installments_today,
        'caisse_inscription_today': caisse_inscription_today,
        'caisse_scolarite_today': caisse_scolarite_today,
        'total_inscription': total_inscription,
        'total_mensualites': total_mensualites,
        'total_du_jour': total_du_jour,
        'movements_day': movements_day,
        'total_entrees_jour': total_entrees_jour,
        'total_sorties_jour': total_sorties_jour,
        'solde_caisse_jour': solde_caisse_jour,
        'TYPE_ENTREE': CaisseMovement.TYPE_ENTREE,
        'nb_validated': nb_validated,
        'nb_pending': nb_pending,
        'nb_rejected': nb_rejected,
        'nb_suspended': nb_suspended,
        'total_collected_global': total_collected_global,
        'total_installments_global': total_installments_global,
        'total_remaining_global': total_remaining_global,
        'already_closed': already_closed,
    }
    return render(request, 'accounting/etat_journalier.html', ctx)


@login_required
def etat_journalier_pdf(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from academic_core.apps.students.models import Enrollment, PaymentInstallment, Student
    from .models import CaissePayment, CaisseMovement
    from academic_core.pdf_utils import get_institut_config_for_request
    from datetime import date as dt, datetime

    today = dt.today()

    # Filtre date (GET ?date=YYYY-MM-DD)
    date_str = request.GET.get('date', '')
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        selected_date = today

    # Config établissement pour le nom
    inst_config = get_institut_config_for_request(request)
    school_name = (inst_config.nom if inst_config and inst_config.nom else 'GROUPE ISI')

    from django.db.models import Exists, OuterRef as _OuterRef2, Sum
    payments_today = Enrollment.objects.filter(
        payment_date=selected_date, status=Enrollment.STATUS_VALIDATED,
        payment_amount__isnull=False, payment_amount__gt=0,
    ).filter(
        ~Exists(CaissePayment.objects.filter(enrollment_id=_OuterRef2('pk')))
    ).select_related('student__user', 'class_group', 'academic_year')

    installments_today = PaymentInstallment.objects.filter(
        paid_date=selected_date, is_paid=True,
    ).select_related('enrollment__student__user', 'enrollment__class_group')

    caisse_day = CaissePayment.objects.filter(
        payment_date=selected_date,
    ).select_related('student__user', 'student__current_class', 'academic_year').order_by('-id')
    caisse_insc   = caisse_day.filter(payment_type=CaissePayment.TYPE_INSCRIPTION)
    caisse_scol   = caisse_day.filter(payment_type__in=[CaissePayment.TYPE_SCOLARITE, CaissePayment.TYPE_SOUTENANCE])

    total_inscription = (
        sum(e.payment_amount or 0 for e in payments_today)
        + sum(c.amount or 0 for c in caisse_insc)
    )
    total_mensualites = (
        sum(i.amount_paid or 0 for i in installments_today)
        + sum(c.amount or 0 for c in caisse_scol)
    )
    total_du_jour = total_inscription + total_mensualites

    movements_today = CaisseMovement.objects.filter(movement_date=selected_date).select_related('created_by')
    total_entrees_jour = sum(m.amount for m in movements_today if m.movement_type == CaisseMovement.TYPE_ENTREE and m.is_executed)
    total_sorties_jour = sum(m.amount for m in movements_today if m.movement_type == CaisseMovement.TYPE_SORTIE and m.is_executed)
    solde_caisse_jour  = total_du_jour + total_entrees_jour - total_sorties_jour

    nb_validated = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED).count()
    nb_pending = Enrollment.objects.filter(status=Enrollment.STATUS_PENDING).count()
    nb_suspended = Student.objects.filter(payment_suspended=True).count()
    _enr_agg = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED).aggregate(
        t=Sum('total_fees'), p=Sum('payment_amount')
    )
    total_remaining_global = (_enr_agg['t'] or 0) - (_enr_agg['p'] or 0)

    buffer = io.BytesIO()
    navy = colors.HexColor('#1e3a5f')
    gold = colors.HexColor('#d4af37')
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle('H', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, spaceAfter=4)
    sub_style = ParagraphStyle('Sub', fontSize=9, fontName='Helvetica', textColor=colors.HexColor('#475569'), alignment=TA_CENTER, spaceAfter=3)
    sec_style = ParagraphStyle('Sec', fontSize=10, fontName='Helvetica-Bold', textColor=navy, spaceBefore=10, spaceAfter=4)
    norm_style = ParagraphStyle('N', fontSize=9, fontName='Helvetica', leading=14)
    right_style = ParagraphStyle('R', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT)

    from academic_core.pdf_utils import logo_image as _logo_img_j_fn

    story = []
    _logo_j = _logo_img_j_fn(config=inst_config, width=2.2*cm, height=1.4*cm)
    _hdr_j = Table([[
        Paragraph('', h_style),
        Paragraph(
            f'<b>{school_name.upper()}</b><br/>'
            f'<font size="10">ÉTAT JOURNALIER COMPTABLE — {selected_date.strftime("%d/%m/%Y")}</font>',
            ParagraphStyle('hj', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, leading=18),
        ),
        _logo_j or Paragraph('ISI', h_style),
    ]], colWidths=[3*cm, 11*cm, 3*cm])
    _hdr_j.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(_hdr_j)
    story.append(HRFlowable(width='100%', thickness=2, color=navy))
    story.append(Spacer(1, 0.4*cm))

    # Résumé global
    story.append(Paragraph("RÉSUMÉ GLOBAL", sec_style))
    summary_data = [
        ['Indicateur', 'Valeur'],
        ['Inscriptions validées', str(nb_validated)],
        ['En attente', str(nb_pending)],
        ['Comptes suspendus (impayés)', str(nb_suspended)],
        ['Total restant dû (global)', f"{total_remaining_global:,.0f} FCFA"],
    ]
    summary_table = Table(summary_data, colWidths=[9*cm, 6*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.4*cm))

    _insc_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])
    _scol_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f0fdf9'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])

    # Encaissements du jour
    story.append(Paragraph(f"ENCAISSEMENTS DU JOUR ({selected_date.strftime('%d/%m/%Y')})", sec_style))

    has_insc = list(payments_today) + list(caisse_insc)
    has_scol = list(installments_today) + list(caisse_scol)

    # Frais d'inscription
    if has_insc:
        story.append(Paragraph("Frais d'inscription :", ParagraphStyle('SH', fontSize=9, fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=3)))
        rows = [['Étudiant', 'Matricule', 'Classe', 'Montant (FCFA)', 'Référence']]
        for e in payments_today:
            rows.append([
                e.student.full_name,
                e.student.matricule or '–',
                str(e.class_group) if e.class_group else '–',
                f"{e.payment_amount:,.0f}" if e.payment_amount else '–',
                e.payment_reference or '–',
            ])
        for c in caisse_insc:
            rows.append([
                c.student.full_name,
                c.student.matricule or '–',
                str(c.student.current_class) if c.student.current_class else '–',
                f"{c.amount:,.0f}" if c.amount else '–',
                c.reference or '–',
            ])
        t = Table(rows, colWidths=[4.5*cm, 2.5*cm, 3*cm, 3*cm, 3.5*cm])
        t.setStyle(_insc_style)
        story.append(t)
        story.append(Paragraph(f"Sous-total inscription : {total_inscription:,.0f} FCFA",
                                ParagraphStyle('ST', fontSize=9, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=navy, spaceAfter=6)))

    # Mensualités / Scolarité
    if has_scol:
        story.append(Paragraph("Mensualités / Scolarité :", ParagraphStyle('SH', fontSize=9, fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=3)))
        rows = [['Étudiant', 'Matricule', 'Classe', 'Type', 'Montant (FCFA)']]
        for i in installments_today:
            rows.append([
                i.enrollment.student.full_name,
                i.enrollment.student.matricule or '–',
                str(i.enrollment.class_group) if i.enrollment.class_group else '–',
                f"Mensualité N°{i.installment_number}",
                f"{i.amount_paid:,.0f}" if i.amount_paid else '–',
            ])
        for c in caisse_scol:
            rows.append([
                c.student.full_name,
                c.student.matricule or '–',
                str(c.student.current_class) if c.student.current_class else '–',
                c.get_payment_type_display(),
                f"{c.amount:,.0f}" if c.amount else '–',
            ])
        t = Table(rows, colWidths=[4.5*cm, 2.5*cm, 3*cm, 3*cm, 3.5*cm])
        t.setStyle(_scol_style)
        story.append(t)
        story.append(Paragraph(f"Sous-total mensualités : {total_mensualites:,.0f} FCFA",
                                ParagraphStyle('ST', fontSize=9, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor('#0f766e'), spaceAfter=6)))

    if not has_insc and not has_scol:
        story.append(Paragraph("Aucun encaissement enregistré ce jour.", norm_style))

    # Mouvements de caisse (Brouillard)
    story.append(Paragraph("MOUVEMENTS DE CAISSE (BROUILLARD) :", ParagraphStyle('SH2', fontSize=9, fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=3)))
    if movements_today:
        _mvt_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6d28d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#faf5ff'), colors.white]),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])
        rows = [['Type', 'Motif', 'Saisi par', 'Statut', 'Montant (FCFA)']]
        for m in movements_today:
            rows.append([
                m.get_movement_type_display(),
                m.motif,
                m.created_by.get_full_name() if m.created_by else '–',
                'Exécuté' if m.is_executed else 'En attente',
                f"{m.amount:,.0f}",
            ])
        t = Table(rows, colWidths=[2.2*cm, 5.3*cm, 3*cm, 2.5*cm, 4*cm])
        t.setStyle(_mvt_style)
        story.append(t)
        story.append(Paragraph(f"Entrées : {total_entrees_jour:,.0f} FCFA — Sorties : {total_sorties_jour:,.0f} FCFA",
                                ParagraphStyle('ST2', fontSize=9, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor('#6d28d9'), spaceAfter=6)))
    else:
        story.append(Paragraph("Aucun mouvement de caisse enregistré ce jour.", norm_style))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=gold))
    story.append(Paragraph(f"SOLDE DE CAISSE DU JOUR : {solde_caisse_jour:,.0f} FCFA",
                            ParagraphStyle('Total', fontSize=12, fontName='Helvetica-Bold', textColor=navy, alignment=TA_RIGHT, spaceBefore=6)))
    story.append(Paragraph(f"(Total encaissé étudiants : {total_du_jour:,.0f} FCFA)",
                            ParagraphStyle('SubTotal', fontSize=8, fontName='Helvetica', textColor=colors.HexColor('#64748b'), alignment=TA_RIGHT)))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        f"Établi par : {request.user.get_full_name() or request.user.username}",
        ParagraphStyle('Sign', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT)))
    story.append(Paragraph(
        f"Le {today.strftime('%d/%m/%Y')}",
        ParagraphStyle('SignDate', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT)))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="etat_journalier_{selected_date.strftime("%Y%m%d")}.pdf"'
    return response


def _etat_journalier_export_data(request):
    """Données communes aux exports Excel/Word de l'état journalier (même
    périmètre que etat_journalier_pdf, non filtré par faculté/département)."""
    from academic_core.apps.students.models import Enrollment, PaymentInstallment, Student
    from .models import CaissePayment, CaisseMovement
    from datetime import date as dt, datetime
    from django.db.models import Exists, OuterRef, Sum

    today = dt.today()
    date_str = request.GET.get('date', '')
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        selected_date = today

    payments_today = Enrollment.objects.filter(
        payment_date=selected_date, status=Enrollment.STATUS_VALIDATED,
        payment_amount__isnull=False, payment_amount__gt=0,
    ).filter(
        ~Exists(CaissePayment.objects.filter(enrollment_id=OuterRef('pk')))
    ).select_related('student__user', 'class_group', 'academic_year')

    installments_today = PaymentInstallment.objects.filter(
        paid_date=selected_date, is_paid=True,
    ).select_related('enrollment__student__user', 'enrollment__class_group')

    caisse_day = CaissePayment.objects.filter(
        payment_date=selected_date,
    ).select_related('student__user', 'student__current_class', 'academic_year').order_by('-id')
    caisse_insc = caisse_day.filter(payment_type=CaissePayment.TYPE_INSCRIPTION)
    caisse_scol = caisse_day.filter(payment_type__in=[CaissePayment.TYPE_SCOLARITE, CaissePayment.TYPE_SOUTENANCE])

    total_inscription = sum(e.payment_amount or 0 for e in payments_today) + sum(c.amount or 0 for c in caisse_insc)
    total_mensualites  = sum(i.amount_paid or 0 for i in installments_today) + sum(c.amount or 0 for c in caisse_scol)
    total_du_jour      = total_inscription + total_mensualites

    nb_validated = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED).count()
    nb_pending   = Enrollment.objects.filter(status=Enrollment.STATUS_PENDING).count()
    nb_suspended = Student.objects.filter(payment_suspended=True).count()
    _enr_agg = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED).aggregate(
        t=Sum('total_fees'), p=Sum('payment_amount'))
    total_remaining_global = (_enr_agg['t'] or 0) - (_enr_agg['p'] or 0)

    movements_day = list(CaisseMovement.objects.filter(movement_date=selected_date).select_related('created_by', 'executed_by'))
    total_entrees_jour = sum(m.amount for m in movements_day if m.movement_type == CaisseMovement.TYPE_ENTREE and m.is_executed)
    total_sorties_jour = sum(m.amount for m in movements_day if m.movement_type == CaisseMovement.TYPE_SORTIE and m.is_executed)
    solde_caisse_jour  = total_du_jour + total_entrees_jour - total_sorties_jour

    return {
        'selected_date':          selected_date,
        'payments_today':         list(payments_today),
        'installments_today':     list(installments_today),
        'caisse_insc':            list(caisse_insc),
        'caisse_scol':            list(caisse_scol),
        'total_inscription':      total_inscription,
        'total_mensualites':      total_mensualites,
        'total_du_jour':          total_du_jour,
        'movements_day':          movements_day,
        'total_entrees_jour':     total_entrees_jour,
        'total_sorties_jour':     total_sorties_jour,
        'solde_caisse_jour':      solde_caisse_jour,
        'TYPE_ENTREE':            CaisseMovement.TYPE_ENTREE,
        'nb_validated':           nb_validated,
        'nb_pending':             nb_pending,
        'nb_suspended':           nb_suspended,
        'total_remaining_global': total_remaining_global,
    }


@login_required
def etat_journalier_excel(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    d = _etat_journalier_export_data(request)

    navy, teal = "1E3A5F", "0F766E"
    thin = Side(style='thin', color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def style_header(cell, bg=navy):
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor=bg)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border

    def style_cell(cell, bold=False, align='left', color="000000"):
        cell.font = Font(bold=bold, size=10, color=color)
        cell.alignment = Alignment(horizontal=align, vertical='center')
        cell.border = border

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "État journalier"

    ws.merge_cells('A1:E1')
    ws['A1'] = f"État journalier comptable — {d['selected_date'].strftime('%d/%m/%Y')}"
    ws['A1'].font = Font(bold=True, color="FFFFFF", size=14)
    ws['A1'].fill = PatternFill("solid", fgColor=navy)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    row = 3
    ws.cell(row=row, column=1, value="RÉSUMÉ GLOBAL").font = Font(bold=True, size=11, color=navy)
    row += 1
    for label, val in [
        ('Inscriptions validées', d['nb_validated']),
        ('En attente', d['nb_pending']),
        ('Comptes suspendus (impayés)', d['nb_suspended']),
        ('Total restant dû (global)', f"{d['total_remaining_global']:,.0f} FCFA"),
    ]:
        style_cell(ws.cell(row=row, column=1, value=label))
        style_cell(ws.cell(row=row, column=2, value=val))
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="FRAIS D'INSCRIPTION").font = Font(bold=True, size=11, color=navy)
    row += 1
    for ci, h in enumerate(['Étudiant', 'Matricule', 'Classe', 'Montant (FCFA)', 'Référence'], 1):
        style_header(ws.cell(row=row, column=ci, value=h))
    row += 1
    for e in d['payments_today']:
        vals = [e.student.full_name, e.student.matricule or '–',
                str(e.class_group) if e.class_group else '–',
                float(e.payment_amount) if e.payment_amount else 0, e.payment_reference or '–']
        for ci, v in enumerate(vals, 1):
            style_cell(ws.cell(row=row, column=ci, value=v), align='right' if ci == 4 else 'left')
        row += 1
    for c in d['caisse_insc']:
        vals = [c.student.full_name, c.student.matricule or '–',
                str(c.student.current_class) if c.student.current_class else '–',
                float(c.amount) if c.amount else 0, c.reference or '–']
        for ci, v in enumerate(vals, 1):
            style_cell(ws.cell(row=row, column=ci, value=v), align='right' if ci == 4 else 'left')
        row += 1
    style_cell(ws.cell(row=row, column=4, value=f"Sous-total : {d['total_inscription']:,.0f} FCFA"), bold=True, align='right', color=navy)
    row += 2

    ws.cell(row=row, column=1, value="MENSUALITÉS / SCOLARITÉ").font = Font(bold=True, size=11, color=teal)
    row += 1
    for ci, h in enumerate(['Étudiant', 'Matricule', 'Classe', 'Type', 'Montant (FCFA)'], 1):
        style_header(ws.cell(row=row, column=ci, value=h), bg=teal)
    row += 1
    for i in d['installments_today']:
        vals = [i.enrollment.student.full_name, i.enrollment.student.matricule or '–',
                str(i.enrollment.class_group) if i.enrollment.class_group else '–',
                f"Mensualité N°{i.installment_number}", float(i.amount_paid) if i.amount_paid else 0]
        for ci, v in enumerate(vals, 1):
            style_cell(ws.cell(row=row, column=ci, value=v), align='right' if ci == 5 else 'left')
        row += 1
    for c in d['caisse_scol']:
        vals = [c.student.full_name, c.student.matricule or '–',
                str(c.student.current_class) if c.student.current_class else '–',
                c.get_payment_type_display(), float(c.amount) if c.amount else 0]
        for ci, v in enumerate(vals, 1):
            style_cell(ws.cell(row=row, column=ci, value=v), align='right' if ci == 5 else 'left')
        row += 1
    style_cell(ws.cell(row=row, column=5, value=f"Sous-total : {d['total_mensualites']:,.0f} FCFA"), bold=True, align='right', color=teal)
    row += 2

    purple = "6D28D9"
    ws.cell(row=row, column=1, value="MOUVEMENTS DE CAISSE (BROUILLARD)").font = Font(bold=True, size=11, color=purple)
    row += 1
    for ci, h in enumerate(['Type', 'Motif', 'Saisi par', 'Statut', 'Montant (FCFA)'], 1):
        style_header(ws.cell(row=row, column=ci, value=h), bg=purple)
    row += 1
    for m in d['movements_day']:
        vals = [
            m.get_movement_type_display(),
            m.motif,
            m.created_by.get_full_name() if m.created_by else '–',
            'Exécuté' if m.is_executed else 'En attente',
            float(m.amount),
        ]
        for ci, v in enumerate(vals, 1):
            style_cell(ws.cell(row=row, column=ci, value=v), align='right' if ci == 5 else 'left')
        row += 1
    style_cell(ws.cell(row=row, column=5, value=f"Entrées : {d['total_entrees_jour']:,.0f} — Sorties : {d['total_sorties_jour']:,.0f} FCFA"), bold=True, align='right', color=purple)
    row += 2

    style_cell(ws.cell(row=row, column=1, value=f"SOLDE DE CAISSE DU JOUR : {d['solde_caisse_jour']:,.0f} FCFA"), bold=True, color=navy)
    row += 1
    style_cell(ws.cell(row=row, column=1, value=f"(Total encaissé étudiants : {d['total_du_jour']:,.0f} FCFA)"))

    for i, w in enumerate([28, 16, 20, 22, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="etat_journalier_{d["selected_date"].strftime("%Y%m%d")}.xlsx"'
    wb.save(response)
    return response


@login_required
def etat_journalier_word(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    d = _etat_journalier_export_data(request)

    def set_cell_bg(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color)
        shd.set(qn('w:val'), 'clear')
        tcPr.append(shd)

    def header_row(table, headers, bg):
        row_cells = table.rows[0].cells
        for i, h in enumerate(headers):
            cell = row_cells[i]
            set_cell_bg(cell, bg)
            rn = cell.paragraphs[0].add_run(h)
            rn.font.color.rgb = RGBColor(255, 255, 255)
            rn.font.bold = True

    doc = Document()
    section = doc.sections[0]
    section.left_margin = Cm(1.5); section.right_margin = Cm(1.5)
    section.top_margin = Cm(1.5); section.bottom_margin = Cm(1.5)

    title = doc.add_heading('', level=0)
    run = title.add_run(f"État journalier comptable — {d['selected_date'].strftime('%d/%m/%Y')}")
    run.font.color.rgb = RGBColor(0, 23, 59)
    run.font.size = Pt(14)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    doc.add_heading('Résumé global', level=2)
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = 'Table Grid'
    header_row(tbl, ['Indicateur', 'Valeur'], '1E3A5F')
    for label, val in [
        ('Inscriptions validées', str(d['nb_validated'])),
        ('En attente', str(d['nb_pending'])),
        ('Comptes suspendus (impayés)', str(d['nb_suspended'])),
        ('Total restant dû (global)', f"{d['total_remaining_global']:,.0f} FCFA"),
    ]:
        row_cells = tbl.add_row().cells
        row_cells[0].text = label
        row_cells[1].text = val
    doc.add_paragraph()

    doc.add_heading("Frais d'inscription", level=2)
    if d['payments_today'] or d['caisse_insc']:
        tbl2 = doc.add_table(rows=1, cols=5)
        tbl2.style = 'Table Grid'
        header_row(tbl2, ['Étudiant', 'Matricule', 'Classe', 'Montant (FCFA)', 'Référence'], '1E3A5F')
        for e in d['payments_today']:
            row_cells = tbl2.add_row().cells
            row_cells[0].text = e.student.full_name
            row_cells[1].text = e.student.matricule or '–'
            row_cells[2].text = str(e.class_group) if e.class_group else '–'
            row_cells[3].text = f"{e.payment_amount:,.0f}" if e.payment_amount else '–'
            row_cells[4].text = e.payment_reference or '–'
        for c in d['caisse_insc']:
            row_cells = tbl2.add_row().cells
            row_cells[0].text = c.student.full_name
            row_cells[1].text = c.student.matricule or '–'
            row_cells[2].text = str(c.student.current_class) if c.student.current_class else '–'
            row_cells[3].text = f"{c.amount:,.0f}" if c.amount else '–'
            row_cells[4].text = c.reference or '–'
    else:
        doc.add_paragraph("Aucun encaissement d'inscription enregistré ce jour.")
    p = doc.add_paragraph()
    r = p.add_run(f"Sous-total inscription : {d['total_inscription']:,.0f} FCFA")
    r.font.bold = True
    r.font.color.rgb = RGBColor(0, 23, 59)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()

    doc.add_heading('Mensualités / Scolarité', level=2)
    if d['installments_today'] or d['caisse_scol']:
        tbl3 = doc.add_table(rows=1, cols=5)
        tbl3.style = 'Table Grid'
        header_row(tbl3, ['Étudiant', 'Matricule', 'Classe', 'Type', 'Montant (FCFA)'], '0F766E')
        for i in d['installments_today']:
            row_cells = tbl3.add_row().cells
            row_cells[0].text = i.enrollment.student.full_name
            row_cells[1].text = i.enrollment.student.matricule or '–'
            row_cells[2].text = str(i.enrollment.class_group) if i.enrollment.class_group else '–'
            row_cells[3].text = f"Mensualité N°{i.installment_number}"
            row_cells[4].text = f"{i.amount_paid:,.0f}" if i.amount_paid else '–'
        for c in d['caisse_scol']:
            row_cells = tbl3.add_row().cells
            row_cells[0].text = c.student.full_name
            row_cells[1].text = c.student.matricule or '–'
            row_cells[2].text = str(c.student.current_class) if c.student.current_class else '–'
            row_cells[3].text = c.get_payment_type_display()
            row_cells[4].text = f"{c.amount:,.0f}" if c.amount else '–'
    else:
        doc.add_paragraph("Aucun encaissement de scolarité enregistré ce jour.")
    p2 = doc.add_paragraph()
    r2 = p2.add_run(f"Sous-total mensualités : {d['total_mensualites']:,.0f} FCFA")
    r2.font.bold = True
    r2.font.color.rgb = RGBColor(15, 118, 110)
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()

    doc.add_heading('Mouvements de caisse (Brouillard)', level=2)
    if d['movements_day']:
        tbl4 = doc.add_table(rows=1, cols=5)
        tbl4.style = 'Table Grid'
        header_row(tbl4, ['Type', 'Motif', 'Saisi par', 'Statut', 'Montant (FCFA)'], '6D28D9')
        for m in d['movements_day']:
            row_cells = tbl4.add_row().cells
            row_cells[0].text = m.get_movement_type_display()
            row_cells[1].text = m.motif
            row_cells[2].text = m.created_by.get_full_name() if m.created_by else '–'
            row_cells[3].text = 'Exécuté' if m.is_executed else 'En attente'
            row_cells[4].text = f"{m.amount:,.0f}"
    else:
        doc.add_paragraph("Aucun mouvement de caisse enregistré ce jour.")
    p4 = doc.add_paragraph()
    r4 = p4.add_run(f"Entrées : {d['total_entrees_jour']:,.0f} FCFA — Sorties : {d['total_sorties_jour']:,.0f} FCFA")
    r4.font.bold = True
    r4.font.color.rgb = RGBColor(109, 40, 217)
    p4.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()

    p3 = doc.add_paragraph()
    r3 = p3.add_run(f"SOLDE DE CAISSE DU JOUR : {d['solde_caisse_jour']:,.0f} FCFA")
    r3.font.bold = True
    r3.font.size = Pt(13)
    r3.font.color.rgb = RGBColor(0, 23, 59)
    p3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p3b = doc.add_paragraph()
    r3b = p3b.add_run(f"(Total encaissé étudiants : {d['total_du_jour']:,.0f} FCFA)")
    r3b.font.size = Pt(9)
    p3b.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="etat_journalier_{d["selected_date"].strftime("%Y%m%d")}.docx"'
    return response


@login_required
def cloturer_journee(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    if request.method != 'POST':
        return redirect('accounting:etat_journalier')

    from academic_core.apps.students.models import Enrollment, PaymentInstallment, Student
    from .models import AccountingClosure, CaisseMovement
    from academic_core.apps.academic_structure.utils import resolve_academic_years
    from datetime import date as dt
    from decimal import Decimal

    today = dt.today()

    if AccountingClosure.objects.filter(closure_date=today).exists():
        messages.warning(request, "La journée a déjà été clôturée.")
        return redirect('accounting:etat_journalier')

    payments_today = Enrollment.objects.filter(payment_date=today, status=Enrollment.STATUS_VALIDATED)
    installments_today = PaymentInstallment.objects.filter(paid_date=today, is_paid=True)

    total_inscription = sum(e.payment_amount or 0 for e in payments_today)
    total_mensualites = sum(i.amount_paid or 0 for i in installments_today)

    # Mouvements de caisse (Brouillard) du jour — uniquement ceux exécutés
    # (une sortie non décaissée ne compte pas encore dans la clôture).
    movements_today = CaisseMovement.objects.filter(movement_date=today, is_executed=True)
    total_entrees = sum(m.amount for m in movements_today if m.movement_type == CaisseMovement.TYPE_ENTREE)
    total_sorties = sum(m.amount for m in movements_today if m.movement_type == CaisseMovement.TYPE_SORTIE)

    nb_validated = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED).count()
    nb_pending = Enrollment.objects.filter(status=Enrollment.STATUS_PENDING).count()
    nb_rejected = Enrollment.objects.filter(status=Enrollment.STATUS_REJECTED).count()
    nb_suspended = Student.objects.filter(payment_suspended=True).count()
    total_remaining = sum(
        (e.remaining_amount or 0) for e in Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED)
    )

    _, current_year = resolve_academic_years(request)
    notes = request.POST.get('notes', '').strip()

    closure = AccountingClosure.objects.create(
        closure_date=today,
        academic_year=current_year,
        nb_validated=nb_validated,
        nb_pending=nb_pending,
        nb_rejected=nb_rejected,
        nb_suspended=nb_suspended,
        total_collected=Decimal(str(total_inscription)),
        total_installments=Decimal(str(total_mensualites)),
        total_remaining=Decimal(str(total_remaining)),
        total_entrees=Decimal(str(total_entrees)),
        total_sorties=Decimal(str(total_sorties)),
        notes=notes,
        closed_by=request.user,
    )

    # ── Envoi du rapport par e-mail ──────────────────────────────────────────
    from .models import ClosureEmailConfig
    from django.core.mail import send_mail
    from django.conf import settings as django_settings

    email_cfg = ClosureEmailConfig.get()
    recipients = email_cfg.get_recipients_list()
    if recipients:
        total_jour = Decimal(str(total_inscription)) + Decimal(str(total_mensualites))
        solde_caisse = total_jour + Decimal(str(total_entrees)) - Decimal(str(total_sorties))
        subject = f"[Clôture] Journée comptable du {today.strftime('%d/%m/%Y')}"
        body = (
            f"Rapport de clôture — {today.strftime('%d/%m/%Y')}\n"
            f"Clôturé par : {request.user.get_full_name()}\n\n"
            f"─── Encaissements du jour (étudiants) ───\n"
            f"  Inscriptions : {total_inscription:,.0f} FCFA\n"
            f"  Mensualités  : {total_mensualites:,.0f} FCFA\n"
            f"  TOTAL        : {total_jour:,.0f} FCFA\n\n"
            f"─── Mouvements de caisse (Brouillard) ───\n"
            f"  Entrées      : {total_entrees:,.0f} FCFA\n"
            f"  Sorties      : {total_sorties:,.0f} FCFA\n\n"
            f"─── Solde de caisse du jour ───\n"
            f"  {solde_caisse:,.0f} FCFA\n\n"
            f"─── Situation globale ───\n"
            f"  Inscriptions validées  : {nb_validated}\n"
            f"  En attente             : {nb_pending}\n"
            f"  Rejetées               : {nb_rejected}\n"
            f"  Comptes suspendus      : {nb_suspended}\n"
            f"  Restant dû (global)    : {total_remaining:,.0f} FCFA\n"
        )
        if notes:
            body += f"\n─── Observations ───\n{notes}\n"
        # L'utilisateur connecté est l'expéditeur ; fallback sur DEFAULT_FROM_EMAIL
        sender = (request.user.email
                  if request.user.email
                  else getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@gestion.local'))
        try:
            send_mail(
                subject,
                body,
                sender,
                recipients,
                fail_silently=True,
            )
        except Exception:
            pass  # Ne pas bloquer la clôture si l'e-mail échoue

    messages.success(request, f"Journée du {today.strftime('%d/%m/%Y')} clôturée avec succès.")
    return redirect('accounting:clotures_list')


@login_required
def clotures_list(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from .models import AccountingClosure, ClosureEmailConfig, CaissePayment
    from django.db.models import Sum, Q
    from academic_core.db_router import get_current_db
    from academic_core.apps.academic_structure.utils import resolve_academic_years

    # Les clôtures sont globales à l'institut : ignorer le filtre département,
    # et forcer la DB de l'institut (auth_db de session) pour éviter que le
    # changement de département ne route vers une autre base.
    institute_db = request.session.get('_auth_db', 'default') if hasattr(request, 'session') else 'default'

    academic_years, selected_year = resolve_academic_years(request, using=institute_db)

    clotures = AccountingClosure.objects.using(institute_db).select_related('closed_by', 'academic_year').all()
    if selected_year:
        clotures = clotures.filter(Q(academic_year=selected_year) | Q(academic_year__isnull=True))
    email_cfg, _ = ClosureEmailConfig.objects.using(institute_db).get_or_create(pk=1)

    # Calculer les encaissements réels depuis CaissePayment par date de clôture
    caisse_qs = (CaissePayment.objects.using(institute_db)
                 .values('payment_date', 'payment_type')
                 .annotate(total=Sum('amount')))
    caisse_by_date = {}
    for row in caisse_qs:
        d = row['payment_date']
        if d not in caisse_by_date:
            caisse_by_date[d] = {'inscription': 0, 'scolarite': 0, 'soutenance': 0, 'total': 0}
        t = row['total'] or 0
        if row['payment_type'] == CaissePayment.TYPE_INSCRIPTION:
            caisse_by_date[d]['inscription'] += t
        elif row['payment_type'] == CaissePayment.TYPE_SCOLARITE:
            caisse_by_date[d]['scolarite'] += t
        elif row['payment_type'] == CaissePayment.TYPE_SOUTENANCE:
            caisse_by_date[d]['soutenance'] += t
        caisse_by_date[d]['total'] += t

    # Enrichir chaque clôture avec les montants réels
    clotures_enrichies = []
    for c in clotures:
        caisse = caisse_by_date.get(c.closure_date, {})
        c.caisse_inscription = caisse.get('inscription', 0)
        c.caisse_scolarite   = caisse.get('scolarite', 0)
        c.caisse_soutenance  = caisse.get('soutenance', 0)
        c.caisse_total       = caisse.get('total', 0)
        clotures_enrichies.append(c)

    return render(request, 'accounting/clotures_list.html', {
        'clotures':       clotures_enrichies,
        'email_cfg':      email_cfg,
        'academic_years': academic_years,
        'selected_year':  selected_year,
    })


@login_required
def closure_edit(request, pk):
    """Modifier une clôture comptable (réservé à l'administrateur d'institut)."""
    if not request.user.is_inst_admin():
        messages.error(request, "Accès réservé à l'administrateur d'institut.")
        return redirect('accounting:clotures_list')

    from .models import AccountingClosure
    from academic_core.apps.academic_structure.models import AcademicYear
    from academic_core.apps.academic_structure.utils import resolve_academic_years
    closure = get_object_or_404(AccountingClosure, pk=pk)

    if request.method == 'POST':
        from datetime import datetime as _cdt
        from decimal import Decimal as _D, InvalidOperation as _IO

        def _parse_date(raw, fallback):
            if raw:
                try:
                    return _cdt.strptime(raw, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    pass
            return fallback

        def _parse_decimal(raw, fallback):
            if raw is not None and str(raw).strip() != '':
                try:
                    return _D(str(raw).replace(' ', '').replace(',', '.'))
                except (_IO, ValueError):
                    pass
            return fallback

        def _parse_int(raw, fallback):
            if raw is not None and str(raw).strip() != '':
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    pass
            return fallback

        closure.closure_date       = _parse_date(request.POST.get('closure_date'), closure.closure_date)
        closure.total_collected    = _parse_decimal(request.POST.get('total_collected'), closure.total_collected)
        closure.total_installments = _parse_decimal(request.POST.get('total_installments'), closure.total_installments)
        closure.total_remaining    = _parse_decimal(request.POST.get('total_remaining'), closure.total_remaining)
        closure.nb_validated       = _parse_int(request.POST.get('nb_validated'), closure.nb_validated)
        closure.nb_pending         = _parse_int(request.POST.get('nb_pending'), closure.nb_pending)
        closure.nb_rejected        = _parse_int(request.POST.get('nb_rejected'), closure.nb_rejected)
        closure.nb_suspended       = _parse_int(request.POST.get('nb_suspended'), closure.nb_suspended)
        year_pk = request.POST.get('academic_year', '')
        closure.academic_year      = AcademicYear.objects.filter(pk=year_pk).first() if year_pk else closure.academic_year
        closure.notes              = request.POST.get('notes', closure.notes)
        closure.save()
        messages.success(request, f"Clôture du {closure.closure_date.strftime('%d/%m/%Y')} modifiée avec succès.")
        return redirect('accounting:clotures_list')

    academic_years, _ = resolve_academic_years(request)
    return render(request, 'accounting/closure_edit.html', {
        'closure': closure,
        'academic_years': academic_years,
    })


@login_required
def closure_delete(request, pk):
    """Supprimer une clôture comptable (réservé à l'administrateur d'institut)."""
    if not request.user.is_inst_admin():
        messages.error(request, "Accès réservé à l'administrateur d'institut.")
        return redirect('accounting:clotures_list')

    from .models import AccountingClosure
    closure = get_object_or_404(AccountingClosure, pk=pk)

    if request.method == 'POST':
        date_str = closure.closure_date.strftime('%d/%m/%Y')
        closure.delete()
        messages.success(request, f"Clôture du {date_str} supprimée avec succès.")
        return redirect('accounting:clotures_list')

    return render(request, 'accounting/closure_confirm_delete.html', {'closure': closure})


@login_required
def closure_email_config_view(request):
    if not _require_etat_access(request.user):
        messages.error(request, "Accès réservé à la comptabilité.")
        return redirect('dashboard:index')

    from .models import ClosureEmailConfig
    cfg = ClosureEmailConfig.get()

    if request.method == 'POST':
        cfg.recipients = request.POST.get('recipients', '')
        cfg.save()
        messages.success(request, "Adresses e-mail de clôture mises à jour.")
        return redirect('accounting:clotures_list')

    return render(request, 'accounting/closure_email_config.html', {'cfg': cfg})


# ===========================================================================
# ENTRÉE & SORTIE CAISSE — Mouvements de caisse (Brouillard)
# ===========================================================================

def _require_caisse_movement_view(user):
    """Consultation + décaissement : Trésorier Général, Caissier, et les rôles
    de supervision globale (Admin, Administrateur d'institut, Contrôleur)."""
    return user.is_tresorier() or user.is_caissier() or user.is_admin() or user.is_inst_admin()


def _require_caisse_movement_create(user):
    """Seul le Trésorier Général peut saisir une entrée/sortie de caisse
    (+ rôles de supervision globale, à titre de sécurité/dépannage)."""
    return user.is_tresorier() or user.is_admin() or user.is_inst_admin()


@login_required
def caisse_movement_list(request):
    """
    Suivi des entrées et sorties de caisse (hors paiements étudiants). Seul le
    Trésorier Général peut saisir un mouvement ; une sortie qu'il crée reste
    « en attente » jusqu'à ce que le Caissier (ou lui-même) clique sur
    « Décaisser » — le Caissier ne peut ni créer, ni modifier le montant/motif.
    """
    if not _require_caisse_movement_view(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from .models import CaisseMovement, CompteComptable
    from academic_core.apps.accounts.models import Direction
    from academic_core.apps.academic_structure.utils import resolve_academic_years
    from datetime import datetime as _dt

    academic_years, selected_year = resolve_academic_years(request)

    date_from_raw = request.GET.get('from', '')
    date_to_raw   = request.GET.get('to', '')
    type_filt     = request.GET.get('type', '')
    status_filt   = request.GET.get('status', '')
    direction_filt = request.GET.get('direction', '').strip()

    today = date.today()
    try:
        date_from = _dt.strptime(date_from_raw, '%Y-%m-%d').date() if date_from_raw else today.replace(day=1)
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = _dt.strptime(date_to_raw, '%Y-%m-%d').date() if date_to_raw else today
    except ValueError:
        date_to = today

    comptes_tresorerie = list(CompteComptable.objects.filter(nature=CompteComptable.NATURE_TRESORERIE, is_active=True))

    compte_id_raw = request.GET.get('compte', '').strip()
    compte_caisse_selectionne = None
    if compte_id_raw:
        compte_caisse_selectionne = next((c for c in comptes_tresorerie if str(c.pk) == compte_id_raw), None)
    if not compte_caisse_selectionne and comptes_tresorerie:
        compte_caisse_selectionne = comptes_tresorerie[0]

    from django.db.models import Q
    qs = CaisseMovement.objects.select_related(
        'created_by', 'executed_by', 'compte_caisse', 'compte_associe', 'direction',
    ).filter(movement_date__gte=date_from, movement_date__lte=date_to)
    if selected_year:
        qs = qs.filter(Q(academic_year=selected_year) | Q(academic_year__isnull=True))
    if compte_caisse_selectionne:
        qs = qs.filter(compte_caisse=compte_caisse_selectionne)
    if type_filt in (CaisseMovement.TYPE_ENTREE, CaisseMovement.TYPE_SORTIE):
        qs = qs.filter(movement_type=type_filt)
    if status_filt == 'attente':
        qs = qs.filter(is_executed=False)
    elif status_filt == 'execute':
        qs = qs.filter(is_executed=True)
    if direction_filt.isdigit():
        qs = qs.filter(direction_id=int(direction_filt))

    movements = list(qs)
    total_entrees = sum(m.amount for m in movements if m.movement_type == CaisseMovement.TYPE_ENTREE and m.is_executed)
    total_sorties = sum(m.amount for m in movements if m.movement_type == CaisseMovement.TYPE_SORTIE and m.is_executed)
    nb_attente    = sum(1 for m in movements if not m.is_executed)

    comptes_associes   = list(
        CompteComptable.objects.filter(is_active=True)
        .exclude(nature=CompteComptable.NATURE_TRESORERIE)
        .order_by('matricule')
    )
    compte_caisse_defaut = compte_caisse_selectionne

    return render(request, 'accounting/caisse_movement_list.html', {
        'movements':       movements,
        'academic_years':  academic_years,
        'selected_year':   selected_year,
        'date_from':       date_from,
        'date_to':         date_to,
        'type_filter':     type_filt,
        'status_filter':   status_filt,
        'direction_filter': direction_filt,
        'directions':      Direction.objects.filter(is_active=True).order_by('name'),
        'total_entrees':   total_entrees,
        'total_sorties':   total_sorties,
        'solde':           total_entrees - total_sorties,
        'nb_attente':      nb_attente,
        'can_create':      _require_caisse_movement_create(request.user),
        'today':           today,
        'TYPE_ENTREE':     CaisseMovement.TYPE_ENTREE,
        'TYPE_SORTIE':     CaisseMovement.TYPE_SORTIE,
        'comptes_tresorerie':   comptes_tresorerie,
        'comptes_associes':     comptes_associes,
        'compte_caisse_defaut': compte_caisse_defaut,
        'SENS_ENTREE': CompteComptable.SENS_ENTREE,
        'SENS_SORTIE': CompteComptable.SENS_SORTIE,
        'SENS_MIXTE':  CompteComptable.SENS_MIXTE,
        'CATEGORIE_CHOICES': CaisseMovement.CATEGORIE_CHOICES,
        'CATEGORIE_COMPTE_MATRICULE_JSON': json.dumps(CaisseMovement.CATEGORIE_COMPTE_MATRICULE),
    })


@login_required
def caisse_movement_create(request):
    if not _require_caisse_movement_create(request.user):
        messages.error(request, "Seul le Trésorier Général peut saisir une entrée ou une sortie de caisse.")
        return redirect('accounting:caisse_movement_list')

    if request.method != 'POST':
        return redirect('accounting:caisse_movement_list')

    from .models import CaisseMovement, CompteComptable
    from academic_core.apps.academic_structure.utils import resolve_academic_years
    from decimal import Decimal, InvalidOperation

    _, current_year = resolve_academic_years(request)

    def to_decimal(raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        try:
            v = Decimal(raw)
            return v if v > 0 else None
        except InvalidOperation:
            return None

    entree_amount = to_decimal(request.POST.get('entree_amount', ''))
    sortie_amount = to_decimal(request.POST.get('sortie_amount', ''))
    movement_date_raw = request.POST.get('movement_date', '').strip()
    motif         = request.POST.get('motif', '').strip()
    beneficiaire  = request.POST.get('beneficiaire', '').strip()
    direction_id  = request.POST.get('direction', '').strip()
    categorie     = request.POST.get('categorie', '').strip()
    piece         = request.POST.get('piece_justificative', '').strip()
    notes         = request.POST.get('notes', '').strip()
    compte_caisse_id   = request.POST.get('compte_caisse', '').strip()
    compte_associe_id  = request.POST.get('compte_associe', '').strip()
    justificatif  = request.FILES.get('justificatif')

    if entree_amount and sortie_amount:
        messages.error(request, "Renseignez soit une Entrée, soit une Sortie — pas les deux à la fois.")
        return redirect('accounting:caisse_movement_list')
    if not entree_amount and not sortie_amount:
        messages.error(request, "Indiquez un montant en Entrée ou en Sortie.")
        return redirect('accounting:caisse_movement_list')
    if not motif:
        messages.error(request, "Le libellé est obligatoire.")
        return redirect('accounting:caisse_movement_list')

    movement_type = CaisseMovement.TYPE_ENTREE if entree_amount else CaisseMovement.TYPE_SORTIE
    amount = entree_amount or sortie_amount
    is_entree = movement_type == CaisseMovement.TYPE_ENTREE

    # Compte de caisse/banque : celui choisi, sinon le compte de trésorerie par défaut.
    compte_caisse = CompteComptable.objects.filter(pk=compte_caisse_id, nature=CompteComptable.NATURE_TRESORERIE).first() \
        if compte_caisse_id else None
    if not compte_caisse:
        compte_caisse = CompteComptable.objects.filter(nature=CompteComptable.NATURE_TRESORERIE, is_active=True).first()

    # Compte associé : obligatoire, et sa nature (sens) doit correspondre à
    # l'opération (Entrée → sens ENTREE/MIXTE, Sortie → sens SORTIE/MIXTE).
    sens_attendu = CompteComptable.SENS_ENTREE if is_entree else CompteComptable.SENS_SORTIE
    compte_associe = CompteComptable.objects.filter(pk=compte_associe_id).first() if compte_associe_id else None
    if not compte_associe:
        messages.error(request, "Le « Compte associé » est obligatoire — sélectionnez le compte comptable de contrepartie.")
        return redirect('accounting:caisse_movement_list')
    if compte_associe.sens not in (sens_attendu, CompteComptable.SENS_MIXTE):
        nature_op = 'une Entrée' if is_entree else 'une Sortie'
        messages.error(request, f"Le compte « {compte_associe} » ne peut pas être utilisé comme contrepartie pour {nature_op}.")
        return redirect('accounting:caisse_movement_list')

    movement_date = movement_date_raw or date.today().isoformat()

    from academic_core.apps.accounts.models import Direction
    direction = Direction.objects.filter(pk=direction_id).first() if direction_id else None

    movement = CaisseMovement.objects.create(
        movement_type=movement_type,
        amount=amount,
        movement_date=movement_date,
        academic_year=current_year,
        motif=motif,
        beneficiaire=beneficiaire,
        direction=direction,
        categorie=categorie,
        piece_justificative=piece,
        notes=notes,
        compte_caisse=compte_caisse,
        compte_associe=compte_associe,
        justificatif=justificatif,
        created_by=request.user,
        # Une ENTRÉE est enregistrée directement ; une SORTIE reste en attente
        # de décaissement par le Caissier (ou le Trésorier Général).
        is_executed=is_entree,
        executed_by=request.user if is_entree else None,
        executed_at=timezone.now() if is_entree else None,
    )
    if is_entree:
        messages.success(request, f"Entrée de caisse enregistrée : {amount:,.0f} FCFA.")
    else:
        messages.success(request, f"Sortie de caisse autorisée : {amount:,.0f} FCFA — en attente de décaissement par la caisse.")
    return redirect('accounting:caisse_movement_list')


@login_required
def caisse_movement_edit(request, pk):
    """Modifier un mouvement de caisse non encore exécuté — réservé au
    Trésorier Général (une fois exécuté/décaissé, il n'est plus modifiable)."""
    if not _require_caisse_movement_create(request.user):
        messages.error(request, "Seul le Trésorier Général peut modifier un mouvement de caisse.")
        return redirect('accounting:caisse_movement_list')

    from .models import CaisseMovement, CompteComptable
    from decimal import Decimal, InvalidOperation

    movement = get_object_or_404(CaisseMovement, pk=pk)
    # Une Entrée est toujours marquée exécutée dès sa création (pas de décaissement
    # à attendre) — seule une Sortie déjà décaissée par la caisse est verrouillée.
    if movement.movement_type == CaisseMovement.TYPE_SORTIE and movement.is_executed:
        messages.error(request, "Une sortie déjà décaissée ne peut plus être modifiée.")
        return redirect('accounting:caisse_movement_list')

    if request.method != 'POST':
        return redirect('accounting:caisse_movement_list')

    def to_decimal(raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        try:
            v = Decimal(raw)
            return v if v > 0 else None
        except InvalidOperation:
            return None

    entree_amount = to_decimal(request.POST.get('entree_amount', ''))
    sortie_amount = to_decimal(request.POST.get('sortie_amount', ''))
    motif         = request.POST.get('motif', '').strip()
    beneficiaire  = request.POST.get('beneficiaire', '').strip()
    direction_id  = request.POST.get('direction', '').strip()
    categorie     = request.POST.get('categorie', '').strip()
    piece         = request.POST.get('piece_justificative', '').strip()
    notes         = request.POST.get('notes', '').strip()
    movement_date_raw = request.POST.get('movement_date', '').strip()
    compte_caisse_id  = request.POST.get('compte_caisse', '').strip()
    compte_associe_id = request.POST.get('compte_associe', '').strip()
    justificatif  = request.FILES.get('justificatif')

    if entree_amount and sortie_amount:
        messages.error(request, "Renseignez soit une Entrée, soit une Sortie — pas les deux à la fois.")
        return redirect('accounting:caisse_movement_list')
    if not entree_amount and not sortie_amount:
        messages.error(request, "Indiquez un montant en Entrée ou en Sortie.")
        return redirect('accounting:caisse_movement_list')
    if not motif:
        messages.error(request, "Le libellé est obligatoire.")
        return redirect('accounting:caisse_movement_list')

    is_entree = bool(entree_amount)

    compte_caisse = CompteComptable.objects.filter(pk=compte_caisse_id, nature=CompteComptable.NATURE_TRESORERIE).first() \
        if compte_caisse_id else None
    if not compte_caisse:
        compte_caisse = movement.compte_caisse or CompteComptable.objects.filter(nature=CompteComptable.NATURE_TRESORERIE, is_active=True).first()

    sens_attendu = CompteComptable.SENS_ENTREE if is_entree else CompteComptable.SENS_SORTIE
    compte_associe = CompteComptable.objects.filter(pk=compte_associe_id).first() if compte_associe_id else None
    if not compte_associe:
        messages.error(request, "Le « Compte associé » est obligatoire — sélectionnez le compte comptable de contrepartie.")
        return redirect('accounting:caisse_movement_list')
    if compte_associe.sens not in (sens_attendu, CompteComptable.SENS_MIXTE):
        nature_op = 'une Entrée' if is_entree else 'une Sortie'
        messages.error(request, f"Le compte « {compte_associe} » ne peut pas être utilisé comme contrepartie pour {nature_op}.")
        return redirect('accounting:caisse_movement_list')

    movement.movement_type = CaisseMovement.TYPE_ENTREE if entree_amount else CaisseMovement.TYPE_SORTIE
    movement.amount        = entree_amount or sortie_amount
    movement.movement_date = movement_date_raw or movement.movement_date
    movement.motif         = motif
    movement.beneficiaire  = beneficiaire
    from academic_core.apps.accounts.models import Direction
    movement.direction     = Direction.objects.filter(pk=direction_id).first() if direction_id else None
    movement.categorie     = categorie
    movement.piece_justificative = piece
    movement.notes         = notes
    movement.compte_caisse  = compte_caisse
    movement.compte_associe = compte_associe
    if justificatif:
        movement.justificatif = justificatif
    # Une entrée reste toujours directement exécutée ; une sortie modifiée
    # reste en attente (elle doit repasser par le décaissement de la caisse).
    if movement.movement_type == CaisseMovement.TYPE_ENTREE:
        movement.is_executed = True
        movement.executed_by = movement.executed_by or request.user
        movement.executed_at = movement.executed_at or timezone.now()
    movement.save()
    messages.success(request, "Mouvement de caisse modifié.")
    return redirect('accounting:caisse_movement_list')


@login_required
def fiche_depense_detail(request, pk):
    """Affichage (et point d'entrée impression/PDF) d'une fiche de dépense
    (ou fiche de mouvement de caisse pour une entrée)."""
    if not _require_caisse_movement_view(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:caisse_movement_list')

    from .models import CaisseMovement
    movement = get_object_or_404(CaisseMovement.objects.select_related('created_by', 'executed_by'), pk=pk)
    return render(request, 'accounting/fiche_depense_detail.html', {'m': movement})


@login_required
def fiche_depense_pdf(request, pk):
    """Génère la fiche de dépense (ou fiche de mouvement) en PDF."""
    if not _require_caisse_movement_view(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:caisse_movement_list')

    from .models import CaisseMovement
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from academic_core.pdf_utils import get_institut_config_for_request, logo_image

    movement = get_object_or_404(CaisseMovement.objects.select_related('created_by', 'executed_by'), pk=pk)
    is_sortie = movement.movement_type == CaisseMovement.TYPE_SORTIE

    inst_config = get_institut_config_for_request(request)
    school_name = (inst_config.nom if inst_config and inst_config.nom else 'GROUPE ISI')

    navy   = colors.HexColor('#1e3a5f')
    purple = colors.HexColor('#6d28d9')
    h_style = ParagraphStyle('H', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, spaceAfter=4)
    right_style = ParagraphStyle('R', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.5*cm, rightMargin=2.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    story = []

    title_txt = "FICHE DE DÉPENSE" if is_sortie else "FICHE D'ENTRÉE DE CAISSE"
    logo = logo_image(config=inst_config, width=2.2*cm, height=1.4*cm)
    hdr = Table([[
        logo or Paragraph('ISI', h_style),
        Paragraph(f'<b>{school_name.upper()}</b><br/><font size="10">{title_txt} N°{movement.pk}</font>',
                  ParagraphStyle('hj', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, leading=18)),
        Paragraph('', h_style),
    ]], colWidths=[3*cm, 11*cm, 3*cm])
    hdr.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story.append(hdr)
    story.append(HRFlowable(width='100%', thickness=2, color=navy))
    story.append(Spacer(1, 0.6*cm))

    rows = [
        ['Date', movement.movement_date.strftime('%d/%m/%Y')],
        ['Type', movement.get_movement_type_display()],
    ]
    if movement.beneficiaire:
        rows.append(['Bénéficiaire / Fournisseur', movement.beneficiaire])
    if movement.categorie:
        rows.append(['Catégorie', movement.get_categorie_display()])
    rows.append(['Motif', movement.motif])
    if movement.piece_justificative:
        rows.append(['Pièce justificative', movement.piece_justificative])
    rows.append(['Montant', f"{movement.amount:,.0f} FCFA"])
    if movement.notes:
        rows.append(['Observations', movement.notes])
    rows.append(['Saisi par (Trésorier Général)', movement.created_by.get_full_name() if movement.created_by else '—'])
    rows.append(['Saisi le', movement.created_at.strftime('%d/%m/%Y %H:%M')])
    rows.append(['Statut', 'Décaissé / Exécuté' if movement.is_executed else 'En attente de décaissement'])
    if movement.is_executed:
        rows.append(['Décaissé par (Caissier)', movement.executed_by.get_full_name() if movement.executed_by else '—'])
        rows.append(['Décaissé le', movement.executed_at.strftime('%d/%m/%Y %H:%M') if movement.executed_at else '—'])

    t = Table(rows, colWidths=[6.5*cm, 9.5*cm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), navy),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 1.5*cm))

    sig = Table([[
        Paragraph('<b>Le Trésorier Général</b><br/><br/><br/>_________________________', ParagraphStyle('sig1', fontSize=9, fontName='Helvetica', alignment=TA_CENTER)),
        Paragraph('<b>Le Caissier</b><br/><br/><br/>_________________________', ParagraphStyle('sig2', fontSize=9, fontName='Helvetica', alignment=TA_CENTER)),
    ]], colWidths=[8*cm, 8*cm])
    story.append(sig)
    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph(f"Document généré le {date.today().strftime('%d/%m/%Y')} par {request.user.get_full_name() or request.user.username}", right_style))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="fiche_depense_{movement.pk}.pdf"'
    return response


@login_required
def caisse_movement_decaisser(request, pk):
    """Le Caissier (ou le Trésorier Général) confirme le décaissement physique
    d'une sortie déjà autorisée — le montant/motif ne sont pas modifiables ici."""
    if not _require_caisse_movement_view(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:caisse_movement_list')

    from .models import CaisseMovement

    movement = get_object_or_404(CaisseMovement, pk=pk, movement_type=CaisseMovement.TYPE_SORTIE)

    if request.method != 'POST':
        return redirect('accounting:caisse_movement_list')

    if movement.is_executed:
        messages.info(request, "Cette sortie a déjà été décaissée.")
        return redirect('accounting:caisse_movement_list')

    movement.is_executed = True
    movement.executed_by = request.user
    movement.executed_at = timezone.now()
    movement.save(update_fields=['is_executed', 'executed_by', 'executed_at'])
    messages.success(request, f"Sortie de caisse décaissée : {movement.amount:,.0f} FCFA.")
    return redirect('accounting:caisse_movement_list')


@login_required
def caisse_movement_delete(request, pk):
    """Supprimer un mouvement de caisse (erreur de saisie) — réservé au
    Trésorier Général. Une Entrée peut toujours être supprimée ; une Sortie
    ne peut plus l'être une fois décaissée par la caisse."""
    if not _require_caisse_movement_create(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:caisse_movement_list')

    from .models import CaisseMovement

    movement = get_object_or_404(CaisseMovement, pk=pk)

    if request.method != 'POST':
        return redirect('accounting:caisse_movement_list')

    if movement.movement_type == CaisseMovement.TYPE_SORTIE and movement.is_executed:
        messages.error(request, "Une sortie déjà décaissée ne peut pas être supprimée.")
        return redirect('accounting:caisse_movement_list')

    movement.delete()
    messages.success(request, "Mouvement de caisse supprimé.")
    return redirect('accounting:caisse_movement_list')


# ===========================================================================
# COMPTES COMPTABLES (plan comptable) — Trésorier Général uniquement
# ===========================================================================

def _require_compte_comptable_access(user):
    """Seul le Trésorier Général peut définir les comptes comptables
    (+ rôles de supervision globale, à titre de sécurité/dépannage)."""
    return user.is_tresorier() or user.is_admin() or user.is_inst_admin()


@login_required
def compte_comptable_list(request):
    if not _require_compte_comptable_access(request.user):
        messages.error(request, "Accès refusé : réservé au Trésorier Général.")
        return redirect('dashboard:index')

    from .models import CompteComptable, CaisseMovement
    search = request.GET.get('q', '').strip()

    # Plan comptable SYSCOHADA uniforme pour tous les instituts (existants et
    # à venir) : comme Role/Level, la table comptes_comptables est clonée
    # vide à la création de chaque base institut — on l'initialise
    # automatiquement au premier accès à cette page (même pattern que
    # LevelListView pour les Niveaux), plutôt que de dépendre d'une commande
    # manuelle (populate_syscohada) à lancer institut par institut. Les
    # comptes sont créés inactifs par défaut : le Trésorier Général active
    # explicitement ceux qu'il utilise réellement.
    if not CompteComptable.objects.exists():
        from .management.commands.populate_syscohada import COMPTES, CATEGORIE_PAR_MATRICULE
        for matricule, libelle, classe, nature, sens in COMPTES:
            CompteComptable.objects.get_or_create(
                matricule=matricule,
                defaults={
                    'libelle': libelle, 'classe': classe, 'nature': nature,
                    'sens': sens, 'categorie': CATEGORIE_PAR_MATRICULE.get(matricule, ''),
                    'is_active': False,
                },
            )

    comptes = CompteComptable.objects.all()
    if search:
        from django.db.models import Q
        comptes = comptes.filter(Q(matricule__icontains=search) | Q(libelle__icontains=search))

    par_classe = {}
    for c in comptes:
        par_classe.setdefault(c.classe, []).append(c)
    # Toujours afficher les 8 classes SYSCOHADA, même vides
    def _build_group(val, label):
        clist = par_classe.get(val, [])
        actifs   = sum(1 for c in clist if c.is_active)
        inactifs = len(clist) - actifs
        return {'classe': val, 'classe_label': label, 'comptes': clist, 'actifs': actifs, 'inactifs': inactifs}
    classe_groups = [_build_group(val, label) for val, label in CompteComptable.CLASSE_CHOICES]

    return render(request, 'accounting/compte_comptable_list.html', {
        'comptes': comptes,
        'classe_groups': classe_groups,
        'search': search,
        'CLASSE_CHOICES': CompteComptable.CLASSE_CHOICES,
        'NATURE_CHOICES': CompteComptable.NATURE_CHOICES,
        'SENS_CHOICES': CompteComptable.SENS_CHOICES,
        'CATEGORIE_CHOICES': CaisseMovement.CATEGORIE_CHOICES,
    })


@login_required
def compte_comptable_create(request):
    if not _require_compte_comptable_access(request.user):
        messages.error(request, "Accès refusé : réservé au Trésorier Général.")
        return redirect('accounting:compte_comptable_list')

    if request.method != 'POST':
        return redirect('accounting:compte_comptable_list')

    from .models import CompteComptable

    matricule = request.POST.get('matricule', '').strip()
    libelle   = request.POST.get('libelle', '').strip()
    classe    = request.POST.get('classe', '').strip() or CompteComptable.CLASSE_6
    nature    = request.POST.get('nature', '').strip() or CompteComptable.NATURE_CHARGE
    sens      = request.POST.get('sens', '').strip() or CompteComptable.SENS_MIXTE
    categorie = request.POST.get('categorie', '').strip()

    if not matricule or not libelle:
        messages.error(request, "Le matricule et le libellé sont obligatoires.")
        return redirect('accounting:compte_comptable_list')
    if CompteComptable.objects.filter(matricule=matricule).exists():
        messages.error(request, f"Un compte avec le matricule « {matricule} » existe déjà.")
        return redirect('accounting:compte_comptable_list')

    CompteComptable.objects.create(
        matricule=matricule, libelle=libelle, classe=classe, nature=nature,
        sens=sens, categorie=categorie, created_by=request.user,
    )
    messages.success(request, f"Compte comptable « {matricule} — {libelle} » créé.")
    return redirect('accounting:compte_comptable_list')


@login_required
def compte_comptable_edit(request, pk):
    if not _require_compte_comptable_access(request.user):
        messages.error(request, "Accès refusé : réservé au Trésorier Général.")
        return redirect('accounting:compte_comptable_list')

    from .models import CompteComptable
    compte = get_object_or_404(CompteComptable, pk=pk)

    if request.method != 'POST':
        return redirect('accounting:compte_comptable_list')

    matricule = request.POST.get('matricule', '').strip()
    libelle   = request.POST.get('libelle', '').strip()
    classe    = request.POST.get('classe', '').strip() or compte.classe
    nature    = request.POST.get('nature', '').strip() or compte.nature
    sens      = request.POST.get('sens', '').strip() or compte.sens
    categorie = request.POST.get('categorie', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not matricule or not libelle:
        messages.error(request, "Le matricule et le libellé sont obligatoires.")
        return redirect('accounting:compte_comptable_list')
    if CompteComptable.objects.filter(matricule=matricule).exclude(pk=compte.pk).exists():
        messages.error(request, f"Un autre compte utilise déjà le matricule « {matricule} ».")
        return redirect('accounting:compte_comptable_list')

    compte.matricule = matricule
    compte.libelle   = libelle
    compte.classe    = classe
    compte.nature    = nature
    compte.sens      = sens
    compte.categorie = categorie
    compte.is_active = is_active
    compte.save()
    messages.success(request, f"Compte comptable « {matricule} — {libelle} » modifié.")
    return redirect('accounting:compte_comptable_list')


@login_required
def compte_comptable_delete(request, pk):
    if not _require_compte_comptable_access(request.user):
        messages.error(request, "Accès refusé : réservé au Trésorier Général.")
        return redirect('accounting:compte_comptable_list')

    from .models import CompteComptable
    compte = get_object_or_404(CompteComptable, pk=pk)

    if request.method != 'POST':
        return redirect('accounting:compte_comptable_list')

    label = str(compte)
    compte.delete()
    messages.success(request, f"Compte comptable « {label} » supprimé.")
    return redirect('accounting:compte_comptable_list')


@login_required
def compte_comptable_toggle(request, pk):
    if not _require_compte_comptable_access(request.user):
        from django.http import JsonResponse
        return JsonResponse({'error': 'Accès refusé'}, status=403)
    if request.method != 'POST':
        from django.http import JsonResponse
        return JsonResponse({'error': 'POST requis'}, status=405)
    from .models import CompteComptable
    from django.http import JsonResponse
    compte = get_object_or_404(CompteComptable, pk=pk)
    compte.is_active = not compte.is_active
    compte.save(update_fields=['is_active'])
    return JsonResponse({'is_active': compte.is_active, 'pk': compte.pk})


# ===========================================================================
# DEMANDES DE DÉPENSE (fiche de dépense par Direction) — workflow :
# Direction (soumission) -> Trésorier Général (validation/rejet) ->
# Caissier (décaissement) -> mouvement de caisse (Sortie) automatique
# ===========================================================================

def _require_demande_depense_submit(user):
    """Toute Direction peut soumettre une demande pour elle-même ; les rôles
    de supervision globale peuvent soumettre pour n'importe quelle direction."""
    return bool(user.direction_id) or user.is_admin() or user.is_inst_admin()


def _require_demande_depense_validate(user):
    """Seul le Trésorier Général valide ou rejette une demande de dépense."""
    return user.is_tresorier() or user.is_admin() or user.is_inst_admin()


def _require_demande_depense_decaisser(user):
    """Le Caissier (ou le Trésorier Général) décaisse une demande déjà validée."""
    return user.is_caissier() or user.is_tresorier() or user.is_admin() or user.is_inst_admin()


def _resoudre_compte_associe_depense(categorie):
    """Résout automatiquement le compte comptable SYSCOHADA associé (charge)
    à partir de la catégorie de dépense choisie — plusieurs catégories peuvent
    partager le même compte (cf. CaisseMovement.CATEGORIE_COMPTE_MATRICULE)."""
    from .models import CompteComptable, CaisseMovement
    compte = None
    matricule = CaisseMovement.CATEGORIE_COMPTE_MATRICULE.get(categorie) if categorie else None
    if matricule:
        compte = CompteComptable.objects.filter(matricule=matricule, is_active=True).first()
    if not compte:
        compte = CompteComptable.objects.filter(
            nature=CompteComptable.NATURE_CHARGE,
            sens__in=[CompteComptable.SENS_SORTIE, CompteComptable.SENS_MIXTE],
            is_active=True,
        ).order_by('matricule').first()
    return compte


@login_required
def demande_depense_list(request):
    from .models import DemandeDepense, CaisseMovement, LigneBudgetaire
    from academic_core.apps.accounts.models import Direction

    user = request.user
    is_super = user.is_admin() or user.is_inst_admin()
    can_validate  = _require_demande_depense_validate(user)
    can_decaisser = _require_demande_depense_decaisser(user)
    can_submit    = _require_demande_depense_submit(user)

    qs = DemandeDepense.objects.select_related('direction', 'requested_by', 'validated_by', 'decaisse_by')

    if is_super or can_validate:
        pass  # le Trésorier Général (et les rôles de supervision) voient tout
    elif can_decaisser:
        qs = qs.filter(statut__in=[DemandeDepense.STATUT_VALIDEE, DemandeDepense.STATUT_DECAISSEE])
    elif user.direction_id:
        qs = qs.filter(direction_id=user.direction_id)
    else:
        qs = qs.none()

    statut_filt = request.GET.get('statut', '').strip()
    if statut_filt in dict(DemandeDepense.STATUT_CHOICES):
        qs = qs.filter(statut=statut_filt)

    direction_filt = request.GET.get('direction', '').strip()
    if direction_filt.isdigit():
        qs = qs.filter(direction_id=int(direction_filt))

    demandes = list(qs)
    for d in demandes:
        d.can_edit_flag = _can_edit_demande(user, d)
    nb_a_valider   = sum(1 for d in demandes if d.statut == DemandeDepense.STATUT_EN_ATTENTE)
    nb_a_decaisser = sum(1 for d in demandes if d.statut == DemandeDepense.STATUT_VALIDEE)

    directions_dispo = []
    if user.direction_id and not is_super:
        directions_dispo = [user.direction]
    elif can_submit:
        directions_dispo = list(Direction.objects.filter(is_active=True).order_by('name'))

    return render(request, 'accounting/demande_depense_list.html', {
        'demandes': demandes,
        'can_submit': can_submit,
        'can_validate': can_validate,
        'can_decaisser': can_decaisser,
        'is_super': is_super,
        'directions_dispo': directions_dispo,
        'user_direction': user.direction if user.direction_id else None,
        'statut_filter': statut_filt,
        'direction_filter': direction_filt,
        'nb_a_valider': nb_a_valider,
        'nb_a_decaisser': nb_a_decaisser,
        'STATUT_CHOICES': DemandeDepense.STATUT_CHOICES,
        'CATEGORIE_CHOICES': CaisseMovement.CATEGORIE_CHOICES,
        'all_directions': Direction.objects.filter(is_active=True).order_by('name') if (is_super or can_validate or can_decaisser) else [],
        'today': date.today(),
        'lignes_budgetaires': LigneBudgetaire.objects.select_related(
            'direction', 'compte_comptable', 'academic_year'
        ).filter(academic_year__is_current=True).order_by('direction__name'),
    })


@login_required
def demande_depense_create(request):
    from .models import DemandeDepense
    from academic_core.apps.accounts.models import Direction

    user = request.user
    if not _require_demande_depense_submit(user):
        messages.error(request, "Seul un utilisateur rattaché à une Direction peut soumettre une demande de dépense.")
        return redirect('accounting:demande_depense_list')

    if request.method != 'POST':
        return redirect('accounting:demande_depense_list')

    is_super = user.is_admin() or user.is_inst_admin()
    if user.direction_id and not is_super:
        direction = user.direction
    else:
        direction_id = request.POST.get('direction', '').strip()
        direction = Direction.objects.filter(pk=direction_id, is_active=True).first() if direction_id else None
        if not direction:
            messages.error(request, "Sélectionnez la Direction pour laquelle la demande est soumise.")
            return redirect('accounting:demande_depense_list')

    objet     = request.POST.get('objet', '').strip()
    categorie = request.POST.get('categorie', '').strip()
    motif     = request.POST.get('motif', '').strip()
    montant_raw = request.POST.get('montant', '').strip()
    ordonnateur  = request.POST.get('ordonnateur', '').strip()
    fournisseur  = request.POST.get('fournisseur', '').strip()
    beneficiaire = request.POST.get('beneficiaire', '').strip()
    piece        = request.POST.get('piece_justificative', '').strip()
    justificatif = request.FILES.get('justificatif')

    from decimal import Decimal, InvalidOperation
    try:
        montant = Decimal(montant_raw)
        if montant <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        montant = None

    if not objet:
        messages.error(request, "L'objet de la demande est obligatoire.")
        return redirect('accounting:demande_depense_list')
    if not motif:
        messages.error(request, "Le motif / description de la dépense est obligatoire.")
        return redirect('accounting:demande_depense_list')
    if montant is None:
        messages.error(request, "Le montant est invalide.")
        return redirect('accounting:demande_depense_list')

    # Pilotage et Suivi Budgétaire : rattachement optionnel à une ligne
    # budgétaire de la même Direction, pour un suivi automatique de l'exécuté.
    from .models import LigneBudgetaire
    ligne_id = request.POST.get('ligne_budgetaire', '').strip()
    ligne_budgetaire = (
        LigneBudgetaire.objects.filter(pk=ligne_id, direction=direction).first()
        if ligne_id else None
    )

    demande = DemandeDepense.objects.create(
        direction=direction,
        objet=objet,
        categorie=categorie,
        motif=motif,
        montant=montant,
        ordonnateur=ordonnateur or user.get_full_name(),
        fournisseur=fournisseur,
        beneficiaire=beneficiaire,
        piece_justificative=piece,
        justificatif=justificatif,
        requested_by=user,
        ligne_budgetaire=ligne_budgetaire,
    )
    messages.success(request, f"Demande de dépense {demande.reference} soumise au Trésorier Général.")
    return redirect('accounting:demande_depense_detail', pk=demande.pk)


def _can_view_demande(user, demande):
    if user.is_admin() or user.is_inst_admin():
        return True
    if _require_demande_depense_validate(user) or _require_demande_depense_decaisser(user):
        return True
    return user.direction_id and user.direction_id == demande.direction_id


def _can_edit_demande(user, demande):
    """Modifier/Supprimer une demande : réservé à la Direction qui l'a soumise
    (+ Admin/InstAdmin par sécurité), et uniquement tant qu'elle est encore
    en attente de validation — une fois validée/rejetée/décaissée, plus rien
    ne doit changer (traçabilité)."""
    from .models import DemandeDepense
    if demande.statut != DemandeDepense.STATUT_EN_ATTENTE:
        return False
    if user.is_admin() or user.is_inst_admin():
        return True
    return bool(user.direction_id) and user.direction_id == demande.direction_id


@login_required
def demande_depense_edit(request, pk):
    from .models import DemandeDepense
    demande = get_object_or_404(DemandeDepense, pk=pk)
    if not _can_edit_demande(request.user, demande):
        messages.error(request, "Cette demande ne peut plus être modifiée (déjà traitée, ou réservée à la Direction concernée).")
        return redirect('accounting:demande_depense_detail', pk=pk)

    if request.method != 'POST':
        return redirect('accounting:demande_depense_detail', pk=pk)

    objet     = request.POST.get('objet', '').strip()
    categorie = request.POST.get('categorie', '').strip()
    motif     = request.POST.get('motif', '').strip()
    montant_raw = request.POST.get('montant', '').strip()
    ordonnateur  = request.POST.get('ordonnateur', '').strip()
    fournisseur  = request.POST.get('fournisseur', '').strip()
    beneficiaire = request.POST.get('beneficiaire', '').strip()
    piece        = request.POST.get('piece_justificative', '').strip()
    justificatif = request.FILES.get('justificatif')

    from decimal import Decimal, InvalidOperation
    try:
        montant = Decimal(montant_raw)
        if montant <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        montant = None

    if not objet:
        messages.error(request, "L'objet de la demande est obligatoire.")
        return redirect('accounting:demande_depense_detail', pk=pk)
    if not motif:
        messages.error(request, "Le motif / description de la dépense est obligatoire.")
        return redirect('accounting:demande_depense_detail', pk=pk)
    if montant is None:
        messages.error(request, "Le montant est invalide.")
        return redirect('accounting:demande_depense_detail', pk=pk)

    from .models import LigneBudgetaire
    ligne_id = request.POST.get('ligne_budgetaire', '').strip()
    demande.ligne_budgetaire = (
        LigneBudgetaire.objects.filter(pk=ligne_id, direction=demande.direction).first()
        if ligne_id else None
    )

    demande.objet = objet
    demande.categorie = categorie
    demande.motif = motif
    demande.montant = montant
    demande.ordonnateur = ordonnateur
    demande.fournisseur = fournisseur
    demande.beneficiaire = beneficiaire
    demande.piece_justificative = piece
    if justificatif:
        demande.justificatif = justificatif
    demande.save()
    messages.success(request, f"Demande {demande.reference} modifiée.")
    return redirect('accounting:demande_depense_detail', pk=pk)


@login_required
def demande_depense_delete(request, pk):
    from .models import DemandeDepense
    demande = get_object_or_404(DemandeDepense, pk=pk)
    if not _can_edit_demande(request.user, demande):
        messages.error(request, "Cette demande ne peut plus être supprimée (déjà traitée, ou réservée à la Direction concernée).")
        return redirect('accounting:demande_depense_detail', pk=pk)

    if request.method != 'POST':
        return redirect('accounting:demande_depense_detail', pk=pk)

    reference = demande.reference
    demande.delete()
    messages.success(request, f"Demande {reference} supprimée.")
    return redirect('accounting:demande_depense_list')


@login_required
def demande_depense_detail(request, pk):
    from .models import DemandeDepense, CaisseMovement
    demande = get_object_or_404(
        DemandeDepense.objects.select_related('direction', 'requested_by', 'validated_by', 'decaisse_by', 'caisse_movement'),
        pk=pk,
    )
    if not _can_view_demande(request.user, demande):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:demande_depense_list')

    return render(request, 'accounting/demande_depense_detail.html', {
        'd': demande,
        'can_validate': _require_demande_depense_validate(request.user),
        'can_decaisser': _require_demande_depense_decaisser(request.user),
        'can_edit': _can_edit_demande(request.user, demande),
        'CATEGORIE_CHOICES': CaisseMovement.CATEGORIE_CHOICES,
    })


@login_required
def demande_depense_pdf(request, pk):
    from .models import DemandeDepense
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from academic_core.pdf_utils import get_institut_config_for_request, logo_image

    demande = get_object_or_404(DemandeDepense.objects.select_related('direction', 'requested_by'), pk=pk)
    if not _can_view_demande(request.user, demande):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:demande_depense_list')

    inst_config = get_institut_config_for_request(request)
    school_name = (inst_config.nom if inst_config and inst_config.nom else 'GROUPE ISI')

    navy = colors.HexColor('#0d2244')
    h_style = ParagraphStyle('H', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, leading=17)
    lbl_style = ParagraphStyle('L', fontSize=9, fontName='Helvetica-Bold', textColor=colors.HexColor('#475569'))
    sig_style = ParagraphStyle('S', fontSize=9, fontName='Helvetica-Bold', alignment=TA_CENTER)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.5*cm, rightMargin=2.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    story = []

    logo = logo_image(config=inst_config, width=2.2*cm, height=1.4*cm)
    hdr = Table([[
        logo or Paragraph('ISI', h_style),
        Paragraph(f'<b>{school_name.upper()}</b><br/><font size="10">{demande.direction.name.upper()}</font>',
                  h_style),
        Paragraph(f'<font size="8">N° de référence</font><br/><b>{demande.reference}</b>',
                  ParagraphStyle('ref', fontSize=9, fontName='Helvetica-Bold', alignment=TA_RIGHT)),
    ]], colWidths=[3*cm, 10*cm, 4*cm])
    hdr.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story.append(hdr)
    story.append(HRFlowable(width='100%', thickness=2, color=navy))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('FICHE DE DEMANDE DE DÉPENSE', h_style))
    story.append(Spacer(1, 0.7*cm))

    rows = [
        ["Objet de la demande", demande.objet],
        ["Catégorie de dépense", demande.get_categorie_display() if demande.categorie else '—'],
        ["Motif / Description de la dépense", demande.motif],
        ["Montant", f"{demande.montant:,.0f} FCFA"],
    ]
    if demande.piece_justificative:
        rows.append(["Pièce justificative", demande.piece_justificative])
    rows.append(["Soumise par", demande.requested_by.get_full_name() if demande.requested_by else '—'])
    rows.append(["Soumise le", demande.requested_at.strftime('%d/%m/%Y %H:%M')])
    rows.append(["Statut", demande.get_statut_display()])

    t = Table(rows, colWidths=[6*cm, 11*cm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), navy),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 2*cm))

    sig = Table([
        [Paragraph('Ordonnateur', sig_style), Paragraph('Fournisseur', sig_style), Paragraph('Bénéficiaire', sig_style)],
        [Paragraph(demande.ordonnateur or '—', ParagraphStyle('o', fontSize=9, alignment=TA_CENTER)),
         Paragraph(demande.fournisseur or '—', ParagraphStyle('f', fontSize=9, alignment=TA_CENTER)),
         Paragraph(demande.beneficiaire or '—', ParagraphStyle('b', fontSize=9, alignment=TA_CENTER))],
        [Paragraph('<br/><br/>_________________________', ParagraphStyle('s1', fontSize=9, alignment=TA_CENTER)),
         Paragraph('<br/><br/>_________________________', ParagraphStyle('s2', fontSize=9, alignment=TA_CENTER)),
         Paragraph('<br/><br/>_________________________', ParagraphStyle('s3', fontSize=9, alignment=TA_CENTER))],
    ], colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    sig.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 4)]))
    story.append(sig)
    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph(
        f"Document généré le {date.today().strftime('%d/%m/%Y')} par {request.user.get_full_name() or request.user.username}",
        ParagraphStyle('R', fontSize=8, fontName='Helvetica', alignment=TA_RIGHT),
    ))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="demande_depense_{demande.reference}.pdf"'
    return response


@login_required
def demande_depense_valider(request, pk):
    from .models import DemandeDepense
    if not _require_demande_depense_validate(request.user):
        messages.error(request, "Seul le Trésorier Général peut valider une demande de dépense.")
        return redirect('accounting:demande_depense_list')

    demande = get_object_or_404(DemandeDepense, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:demande_depense_list')
    if demande.statut != DemandeDepense.STATUT_EN_ATTENTE:
        messages.error(request, "Cette demande n'est plus en attente de validation.")
        return redirect('accounting:demande_depense_detail', pk=pk)

    demande.statut = DemandeDepense.STATUT_VALIDEE
    demande.validated_by = request.user
    demande.validated_at = timezone.now()
    demande.save(update_fields=['statut', 'validated_by', 'validated_at'])
    messages.success(request, f"Demande {demande.reference} validée — transmise à la caisse pour décaissement.")
    return redirect('accounting:demande_depense_detail', pk=pk)


@login_required
def demande_depense_rejeter(request, pk):
    from .models import DemandeDepense
    if not _require_demande_depense_validate(request.user):
        messages.error(request, "Seul le Trésorier Général peut rejeter une demande de dépense.")
        return redirect('accounting:demande_depense_list')

    demande = get_object_or_404(DemandeDepense, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:demande_depense_list')
    if demande.statut != DemandeDepense.STATUT_EN_ATTENTE:
        messages.error(request, "Cette demande n'est plus en attente de validation.")
        return redirect('accounting:demande_depense_detail', pk=pk)

    reason = request.POST.get('rejection_reason', '').strip()
    demande.statut = DemandeDepense.STATUT_REJETEE
    demande.validated_by = request.user
    demande.validated_at = timezone.now()
    demande.rejection_reason = reason
    demande.save(update_fields=['statut', 'validated_by', 'validated_at', 'rejection_reason'])
    messages.success(request, f"Demande {demande.reference} rejetée.")
    return redirect('accounting:demande_depense_detail', pk=pk)


@login_required
def demande_depense_decaisser(request, pk):
    from .models import DemandeDepense, CaisseMovement, CompteComptable
    if not _require_demande_depense_decaisser(request.user):
        messages.error(request, "Seul le Caissier (ou le Trésorier Général) peut décaisser une demande validée.")
        return redirect('accounting:demande_depense_list')

    demande = get_object_or_404(DemandeDepense, pk=pk)
    if request.method != 'POST':
        return redirect('accounting:demande_depense_list')
    if demande.statut != DemandeDepense.STATUT_VALIDEE:
        messages.error(request, "Cette demande doit d'abord être validée par le Trésorier Général avant décaissement.")
        return redirect('accounting:demande_depense_detail', pk=pk)

    compte_caisse = CompteComptable.objects.filter(nature=CompteComptable.NATURE_TRESORERIE, is_active=True).order_by('matricule').first()
    compte_associe = _resoudre_compte_associe_depense(demande.categorie)

    movement = CaisseMovement.objects.create(
        movement_type=CaisseMovement.TYPE_SORTIE,
        amount=demande.montant,
        movement_date=date.today(),
        motif=f"{demande.objet} ({demande.direction.name})",
        beneficiaire=demande.beneficiaire or demande.fournisseur,
        categorie=demande.categorie,
        piece_justificative=demande.piece_justificative,
        notes=f"Généré depuis la demande de dépense {demande.reference}",
        compte_caisse=compte_caisse,
        compte_associe=compte_associe,
        justificatif=demande.justificatif,
        created_by=demande.validated_by,
        is_executed=True,
        executed_by=request.user,
        executed_at=timezone.now(),
    )
    demande.statut = DemandeDepense.STATUT_DECAISSEE
    demande.decaisse_by = request.user
    demande.decaisse_at = timezone.now()
    demande.caisse_movement = movement
    demande.save(update_fields=['statut', 'decaisse_by', 'decaisse_at', 'caisse_movement'])

    # Pilotage et Suivi Budgétaire : si cette demande est rattachée à une ligne
    # budgétaire, son montant exécuté doit refléter ce nouveau décaissement.
    if demande.ligne_budgetaire_id:
        from .budget_services import recompute_montant_execute
        recompute_montant_execute(demande.ligne_budgetaire)

    messages.success(request, f"Demande {demande.reference} décaissée : {demande.montant:,.0f} FCFA — enregistrée comme sortie de caisse.")
    return redirect('accounting:demande_depense_detail', pk=pk)


# ===========================================================================
# RAPPORTS FINANCIERS (Direction Administrative Financière)
# ===========================================================================

REPORT_TYPES = [
    ('prevision_recette',          'Prévision et recette de l’établissement'),
    ('abandons',                   'Liste des abandons'),
    ('prevision_classe',           'Prévisions recettes par classe'),
    ('manque_a_gagner',            'Manques à gagner'),
    ('comparatif_exercices',       'Diagramme comparatif des exercices'),
    ('recettes_classe_mois',       'Tableau des recettes par classe et par mois'),
    ('recette_jour',               'Recette du jour'),
    ('recette_periodique_detaillee', 'Recette périodique détaillée'),
    ('recette_periodique_synthese', 'Recette périodique synthèse'),
    ('analyse_inscription',        'Analyse croisée inscription'),
    ('analyse_mensualite',         'Analyse croisée mensualité'),
    ('impayes_mensuels',           'Liste des impayées mensuelles'),
    ('invalidation_impayes',       'Invalidation des comptes impayés'),
    ('total_impayes',              'Total impayés apprenants'),
    ('vacations_mensuelles',       'Vacations mensuelles'),
    ('pointage_personnel',         'Rapport pointage du personnel'),
    ('statistique_rentree',        'Statistique rentrée'),
    ('recettes_diverses',          'Recettes diverses'),
    ('rapports_mensualites',       'Rapports des mensualités'),
]

# Regroupement des rapports pour la liste déroulante (accounting:rapports_financiers) —
# évite la longue liste verticale à faire défiler, tous les rapports restent
# accessibles en un clic dans un <select> compact, catégorisés par thème.
REPORT_GROUPS = [
    ('Prévisions & recettes', [
        ('prevision_recette',      dict(REPORT_TYPES)['prevision_recette']),
        ('prevision_classe',       dict(REPORT_TYPES)['prevision_classe']),
        ('manque_a_gagner',        dict(REPORT_TYPES)['manque_a_gagner']),
        ('comparatif_exercices',   dict(REPORT_TYPES)['comparatif_exercices']),
        ('recettes_classe_mois',   dict(REPORT_TYPES)['recettes_classe_mois']),
        ('recettes_diverses',      dict(REPORT_TYPES)['recettes_diverses']),
    ]),
    ('Recettes périodiques', [
        ('recette_jour',                 dict(REPORT_TYPES)['recette_jour']),
        ('recette_periodique_detaillee',  dict(REPORT_TYPES)['recette_periodique_detaillee']),
        ('recette_periodique_synthese',   dict(REPORT_TYPES)['recette_periodique_synthese']),
    ]),
    ('Analyses croisées', [
        ('analyse_inscription',   dict(REPORT_TYPES)['analyse_inscription']),
        ('analyse_mensualite',    dict(REPORT_TYPES)['analyse_mensualite']),
        ('rapports_mensualites',  dict(REPORT_TYPES)['rapports_mensualites']),
    ]),
    ('Impayés & abandons', [
        ('impayes_mensuels',       dict(REPORT_TYPES)['impayes_mensuels']),
        ('invalidation_impayes',   dict(REPORT_TYPES)['invalidation_impayes']),
        ('total_impayes',          dict(REPORT_TYPES)['total_impayes']),
        ('abandons',               dict(REPORT_TYPES)['abandons']),
    ]),
    ('Personnel', [
        ('vacations_mensuelles',  dict(REPORT_TYPES)['vacations_mensuelles']),
        ('pointage_personnel',    dict(REPORT_TYPES)['pointage_personnel']),
    ]),
    ('Autres', [
        ('statistique_rentree',   dict(REPORT_TYPES)['statistique_rentree']),
    ]),
]


def _require_rapports_financiers_access(user):
    return user.is_comptable() or user.is_controleur() or user.is_admin() or user.is_inst_admin()


def _rf_scope(request):
    """Périmètre faculté/département — même convention que mensualite_list /
    taux_recouvrement (les rôles de supervision globale voient tout)."""
    is_global = request.user.is_controleur() or request.user.is_comptable() or request.user.role_name == 'ADMIN'
    faculty  = None if is_global else getattr(request, 'active_faculty', None)
    department = None if is_global else getattr(request, 'active_department', None)
    return faculty, department


def _rf_years(request):
    from academic_core.apps.academic_structure.models import AcademicYear
    faculty, _ = _rf_scope(request)
    years = AcademicYear.objects.order_by('-start_date')
    if faculty and not request.user.is_super_admin():
        fy = years.filter(faculty=faculty)
        years = fy if fy.exists() else years
    return years


def _rf_classes(request, year=None):
    from academic_core.apps.academic_structure.models import Class
    faculty, department = _rf_scope(request)
    qs = Class.objects.select_related('level', 'program__department').order_by('name')
    if department:
        qs = qs.filter(program__department=department)
    elif faculty:
        qs = qs.filter(program__department__faculty=faculty)
    if year:
        qs = qs.filter(academic_year=year)
    return qs


def _rf_prevision_monthly_table(request, title, classes_qs_for_year, year_obj, field):
    """
    Construit une section 'Indicateur | Jan..Déc | Total' à partir de
    PaymentInstallment.<field> (amount_expected pour la prévision,
    amount_paid pour les recettes constatées), une ligne pour `year_obj` et
    une ligne pour l'année académique précédente (même périmètre
    faculté/département, résolue via _rf_classes/_rf_years — jamais le
    filtre 'classe' ponctuel, qui référence une Class d'une autre année).
    """
    from django.db.models import Sum
    from academic_core.apps.students.models import PaymentInstallment
    from academic_core.apps.academic_structure.models import AcademicYear

    MOIS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc']

    def month_sums(y, classes):
        if not y:
            return {}
        agg = (PaymentInstallment.objects
               .filter(is_paid=True, enrollment__academic_year=y, enrollment__class_group__in=classes) if field == 'amount_paid'
               else PaymentInstallment.objects.filter(enrollment__academic_year=y, enrollment__class_group__in=classes))
        agg = (agg.values('due_date__month')
                  .annotate(total=Sum(field))
                  .order_by('due_date__month'))
        return {a['due_date__month']: a['total'] or 0 for a in agg}

    previous_year = None
    if year_obj:
        prev_qs = AcademicYear.objects.filter(start_date__lt=year_obj.start_date)
        if year_obj.faculty_id:
            prev_qs = prev_qs.filter(faculty=year_obj.faculty_id)
        previous_year = prev_qs.order_by('-start_date').first()
    previous_classes = _rf_classes(request, previous_year) if previous_year else classes_qs_for_year.none()

    current_sums = month_sums(year_obj, classes_qs_for_year)
    previous_sums = month_sums(previous_year, previous_classes)

    columns = ['Indicateur'] + MOIS + ['Total']
    rows = [
        [year_obj.label if year_obj else '—'] + [f"{current_sums.get(m, 0):,.0f} F" for m in range(1, 13)]
        + [f"{sum(current_sums.values()):,.0f} F"],
    ]
    if previous_year:
        rows.append(
            [previous_year.label] + [f"{previous_sums.get(m, 0):,.0f} F" for m in range(1, 13)]
            + [f"{sum(previous_sums.values()):,.0f} F"]
        )
    return {'title': title, 'columns': columns, 'rows': rows}, current_sums, previous_sums, previous_year


def _rf_rapport_prevision_recette(request, year, classes_qs):
    """
    'Prévision et recette de l'établissement' — redéfini pour couvrir toutes
    les catégories de frais par niveau/classe (comme le tableau de référence
    fourni par la Direction Financière), une synthèse établissement, et un
    suivi mensuel prévision/recettes constatées/taux de réalisation basé sur
    l'échéancier réel des mensualités (PaymentInstallment) — seule catégorie
    ayant une échéance par mois fiable en base ; Examen/Loyer/Stage/Total
    restau/Total transport ne sont pas encore configurables dans
    l'application et apparaissent donc à 0.
    """
    from django.db.models import Sum, Count, Value, DecimalField
    from django.db.models.functions import Coalesce
    from academic_core.apps.students.models import Enrollment, PaymentInstallment
    from academic_core.apps.academic_structure.models import AcademicYear

    enrollments_qs = Enrollment.objects.filter(
        status=Enrollment.STATUS_VALIDATED, academic_year=year, class_group__in=classes_qs,
    )

    # ── Mensualités par classe (échéancier réel — requête séparée pour
    # éviter la multiplication de lignes classique d'un JOIN sur une
    # relation inverse combiné à d'autres Sum() sur Enrollment) ──────────
    mensualites_par_classe = {
        a['enrollment__class_group_id']: a['total'] or 0
        for a in (PaymentInstallment.objects
                  .filter(enrollment__academic_year=year, enrollment__class_group__in=classes_qs)
                  .values('enrollment__class_group_id')
                  .annotate(total=Sum('amount_expected')))
    }

    zero = Value(0, output_field=DecimalField())
    per_class = (enrollments_qs
        .values('class_group__id', 'class_group__name')
        .annotate(
            effectif=Count('id'),
            soutenance=Coalesce(Sum('frais_soutenance'), zero) + Coalesce(Sum('frais_soutenance_speciale'), zero),
            frais_dossier=Coalesce(Sum('frais_generaux'), zero),
            uniforme=Coalesce(Sum('frais_tenue'), zero),
            assurance=Coalesce(Sum('frais_assurance'), zero),
            amical=Coalesce(Sum('frais_amea'), zero),
            cout_global=Coalesce(Sum('total_fees'), zero),
        )
        .order_by('class_group__name'))

    columns = ['Niveau', 'Effectif', 'Mensualités', 'Examen', 'Soutenance', 'Frais dossier',
               'Uniforme', 'Assurance', 'Amical', 'Loyer', 'Stage', 'Total restau',
               'Total transport', 'Coût global']
    rows = []
    totals = {k: 0 for k in ['effectif', 'mensualites', 'soutenance', 'frais_dossier',
                              'uniforme', 'assurance', 'amical', 'cout_global']}
    for a in per_class:
        mensualites = mensualites_par_classe.get(a['class_group__id'], 0)
        totals['effectif']      += a['effectif']
        totals['mensualites']   += mensualites
        totals['soutenance']    += a['soutenance']
        totals['frais_dossier'] += a['frais_dossier']
        totals['uniforme']      += a['uniforme']
        totals['assurance']     += a['assurance']
        totals['amical']        += a['amical']
        totals['cout_global']   += a['cout_global']
        rows.append([
            a['class_group__name'] or '—', a['effectif'], f"{mensualites:,.0f} F", '0',
            f"{a['soutenance']:,.0f} F", f"{a['frais_dossier']:,.0f} F", f"{a['uniforme']:,.0f} F",
            f"{a['assurance']:,.0f} F", f"{a['amical']:,.0f} F", '0', '0', '0', '0',
            f"{a['cout_global']:,.0f} F",
        ])
    rows.append([
        'TOTAL', totals['effectif'], f"{totals['mensualites']:,.0f} F", '0',
        f"{totals['soutenance']:,.0f} F", f"{totals['frais_dossier']:,.0f} F",
        f"{totals['uniforme']:,.0f} F", f"{totals['assurance']:,.0f} F", f"{totals['amical']:,.0f} F",
        '0', '0', '0', '0', f"{totals['cout_global']:,.0f} F",
    ])

    agg_global = enrollments_qs.aggregate(t=Sum('total_fees'), p=Sum('payment_amount'))
    prevu = agg_global['t'] or 0
    percu = agg_global['p'] or 0
    taux = (percu / prevu * 100) if prevu else 0

    # ── Synthèse ──────────────────────────────────────────────────────────
    synthese_section = {
        'title': 'Synthèse',
        'color': '#0d2244',
        'columns': ['Effectif', 'Mensualités', 'Examen', 'Soutenance', 'Frais dossier', 'Uniforme',
                    'Assurance', 'Amical', 'Loyer', 'Stage', 'Total restau', 'Total transport',
                    'Coût global', "Chiffre d'affaires"],
        'rows': [[
            totals['effectif'], f"{totals['mensualites']:,.0f} F", '0', f"{totals['soutenance']:,.0f} F",
            f"{totals['frais_dossier']:,.0f} F", f"{totals['uniforme']:,.0f} F",
            f"{totals['assurance']:,.0f} F", f"{totals['amical']:,.0f} F", '0', '0', '0', '0',
            f"{totals['cout_global']:,.0f} F", f"{percu:,.0f} F",
        ]],
    }

    # ── Suivi mensuel des mensualités (prévision / constatées / taux) ─────
    prevision_section, prevision_current, prevision_previous, _prev_year = _rf_prevision_monthly_table(
        request, 'Prévision annuelle — Mensualités par mois', classes_qs, year, 'amount_expected',
    )
    prevision_section['color'] = '#0891b2'
    recettes_section, recettes_current, recettes_previous, prev_year = _rf_prevision_monthly_table(
        request, 'Recettes constatées — Mensualités par mois', classes_qs, year, 'amount_paid',
    )
    recettes_section['color'] = '#059669'

    def taux_row(label, prevision_by_month, recette_by_month):
        cells = []
        for m in range(1, 13):
            attendu = prevision_by_month.get(m, 0)
            encaisse = recette_by_month.get(m, 0)
            cells.append(f"{(encaisse / attendu * 100):,.1f} %" if attendu else "—")
        total_attendu = sum(prevision_by_month.values())
        total_encaisse = sum(recette_by_month.values())
        cells.append(f"{(total_encaisse / total_attendu * 100):,.1f} %" if total_attendu else "—")
        return [label] + cells

    MOIS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc']
    taux_rows = [taux_row(year.label, prevision_current, recettes_current)]
    if prev_year:
        taux_rows.append(taux_row(prev_year.label, prevision_previous, recettes_previous))
    taux_section = {
        'title': 'Taux de réalisation — Mensualités par mois',
        'color': '#7c3aed',
        'columns': ['Indicateur'] + MOIS + ['Total'],
        'rows': taux_rows,
    }

    return {
        'summary': [
            ('Effectif total', str(totals['effectif'])),
            ('Prévision totale', f"{prevu:,.0f} F"),
            ('Recette perçue', f"{percu:,.0f} F"),
            ("Chiffre d'affaires", f"{percu:,.0f} F"),
            ('Taux de réalisation global', f"{taux:,.1f} %"),
        ],
        'columns': columns,
        'rows': rows,
        'main_table_title': 'Détail par niveau',
        'main_table_color': '#1e3a5f',
        'sections': [synthese_section, prevision_section, recettes_section, taux_section],
    }


def _rf_rapport_abandons(request, year, classes_qs):
    from academic_core.apps.students.models import Enrollment
    qs = (Enrollment.objects
          .filter(status=Enrollment.STATUS_ABANDONED, academic_year=year, class_group__in=classes_qs)
          .select_related('student__user', 'class_group')
          .order_by('class_group__name', 'student__user__last_name'))
    rows = [[
        e.student.user.get_full_name() if e.student and e.student.user else '—',
        e.class_group.name if e.class_group else '—',
        e.status_changed_at.strftime('%d/%m/%Y') if e.status_changed_at else '—',
        e.status_reason or '—',
    ] for e in qs]
    return {
        'summary': [('Total abandons', str(len(rows)))],
        'columns': ['Étudiant', 'Classe', 'Date', 'Motif'],
        'rows': rows,
    }


def _rf_rapport_prevision_classe(request, year, classes_qs):
    from django.db.models import Sum, Count
    from academic_core.apps.students.models import Enrollment
    agg = (Enrollment.objects
           .filter(status=Enrollment.STATUS_VALIDATED, academic_year=year, class_group__in=classes_qs)
           .values('class_group__id', 'class_group__name')
           .annotate(effectif=Count('id'), prevision=Sum('total_fees'))
           .order_by('class_group__name'))
    rows = [[a['class_group__name'] or '—', a['effectif'], f"{(a['prevision'] or 0):,.0f} F"] for a in agg]
    total = sum(a['prevision'] or 0 for a in agg)
    return {
        'summary': [('Prévision totale', f"{total:,.0f} F")],
        'columns': ['Classe', 'Effectif', 'Prévision'],
        'rows': rows,
    }


def _rf_rapport_manque_a_gagner(request, year, classes_qs):
    from django.db.models import Sum
    from academic_core.apps.students.models import Enrollment
    agg = (Enrollment.objects
           .filter(status=Enrollment.STATUS_VALIDATED, academic_year=year, class_group__in=classes_qs)
           .values('class_group__id', 'class_group__name')
           .annotate(prevu=Sum('total_fees'), percu=Sum('payment_amount'))
           .order_by('class_group__name'))
    rows = []
    total_manque = 0
    for a in agg:
        prevu = a['prevu'] or 0
        percu = a['percu'] or 0
        manque = prevu - percu
        total_manque += manque
        rows.append([a['class_group__name'] or '—', f"{prevu:,.0f} F", f"{percu:,.0f} F", f"{manque:,.0f} F"])
    return {
        'summary': [('Manque à gagner total', f"{total_manque:,.0f} F")],
        'columns': ['Classe', 'Prévu', 'Perçu', 'Manque à gagner'],
        'rows': rows,
    }


def _rf_rapport_comparatif_exercices(request, year, classes_qs):
    from django.db.models import Sum
    from academic_core.apps.students.models import Enrollment
    years = _rf_years(request)[:8]
    labels, values, rows = [], [], []
    for y in years:
        agg = Enrollment.objects.filter(status=Enrollment.STATUS_VALIDATED, academic_year=y).aggregate(p=Sum('payment_amount'))
        percu = agg['p'] or 0
        labels.append(y.label)
        values.append(float(percu))
        rows.append([y.label, f"{percu:,.0f} F"])
    rows.reverse()
    return {
        'columns': ['Exercice (Année académique)', 'Recette perçue'],
        'rows': rows,
        'chart_labels': list(reversed(labels)),
        'chart_data': list(reversed(values)),
    }


def _rf_rapport_recettes_classe_mois(request, year, classes_qs):
    from django.db.models import Sum
    from academic_core.apps.students.models import PaymentInstallment
    MOIS = ['', 'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc']
    agg = (PaymentInstallment.objects
           .filter(is_paid=True, enrollment__academic_year=year, enrollment__class_group__in=classes_qs)
           .values('enrollment__class_group__name', 'due_date__month')
           .annotate(total=Sum('amount_paid'))
           .order_by('enrollment__class_group__name', 'due_date__month'))
    par_classe = {}
    mois_presents = set()
    for a in agg:
        cls = a['enrollment__class_group__name'] or '—'
        m = a['due_date__month']
        mois_presents.add(m)
        par_classe.setdefault(cls, {})[m] = a['total'] or 0
    mois_tries = sorted(mois_presents)
    columns = ['Classe'] + [MOIS[m] for m in mois_tries] + ['Total']
    rows = []
    for cls, data in sorted(par_classe.items()):
        row = [cls] + [f"{data.get(m, 0):,.0f} F" for m in mois_tries]
        row.append(f"{sum(data.values()):,.0f} F")
        rows.append(row)
    return {'columns': columns, 'rows': rows}


def _rf_rapport_recette_jour(request, year, classes_qs):
    from django.db.models import Sum
    from academic_core.apps.accounting.models import CaissePayment, CaisseMovement
    today = date.today()
    caisse_payments = CaissePayment.objects.filter(payment_date=today, student__enrollments__class_group__in=classes_qs).distinct()
    total_scolarite = caisse_payments.aggregate(t=Sum('amount'))['t'] or 0
    total_entree_divers = (CaisseMovement.objects
                            .filter(movement_type=CaisseMovement.TYPE_ENTREE, movement_date=today, is_executed=True)
                            .aggregate(t=Sum('amount'))['t'] or 0)
    return {
        'summary': [
            ('Recette scolarité du jour', f"{total_scolarite:,.0f} F"),
            ('Recettes diverses du jour', f"{total_entree_divers:,.0f} F"),
            ('Total du jour', f"{(total_scolarite + total_entree_divers):,.0f} F"),
        ],
        'columns': ['Origine', 'Montant'],
        'rows': [
            ['Paiements scolarité (La Caisse)', f"{total_scolarite:,.0f} F"],
            ['Entrées diverses (Entrée & Sortie Caisse)', f"{total_entree_divers:,.0f} F"],
        ],
    }


def _rf_rapport_recette_periodique(request, year, classes_qs, detaillee):
    from django.db.models import Sum
    from datetime import datetime
    from academic_core.apps.accounting.models import CaissePayment
    date_from_raw = request.GET.get('from', '')
    date_to_raw = request.GET.get('to', '')
    today = date.today()
    try:
        date_from = datetime.strptime(date_from_raw, '%Y-%m-%d').date() if date_from_raw else today.replace(day=1)
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = datetime.strptime(date_to_raw, '%Y-%m-%d').date() if date_to_raw else today
    except ValueError:
        date_to = today

    qs = (CaissePayment.objects
          .filter(payment_date__gte=date_from, payment_date__lte=date_to,
                  student__enrollments__class_group__in=classes_qs)
          .select_related('student__user').distinct().order_by('payment_date'))
    total = qs.aggregate(t=Sum('amount'))['t'] or 0

    if detaillee:
        rows = [[p.payment_date.strftime('%d/%m/%Y'), p.student.user.get_full_name() if p.student and p.student.user else '—',
                  p.get_payment_type_display(), p.reference, f"{p.amount:,.0f} F"] for p in qs]
        columns = ['Date', 'Étudiant', 'Type', 'Référence', 'Montant']
    else:
        by_day = {}
        for p in qs:
            by_day.setdefault(p.payment_date, 0)
            by_day[p.payment_date] += p.amount
        rows = [[d.strftime('%d/%m/%Y'), f"{amt:,.0f} F"] for d, amt in sorted(by_day.items())]
        columns = ['Date', 'Total du jour']

    return {
        'summary': [(f"Total du {date_from.strftime('%d/%m/%Y')} au {date_to.strftime('%d/%m/%Y')}", f"{total:,.0f} F")],
        'columns': columns,
        'rows': rows,
    }


def _rf_rapport_analyse_inscription(request, year, classes_qs):
    from django.db.models import Count
    from academic_core.apps.students.models import Enrollment
    statuses = [Enrollment.STATUS_PENDING, Enrollment.STATUS_PENDING_CAISSE, Enrollment.STATUS_VALIDATED,
                Enrollment.STATUS_REJECTED, Enrollment.STATUS_ABANDONED, Enrollment.STATUS_SUSPENDED]
    labels = dict(Enrollment.STATUS_CHOICES) if hasattr(Enrollment, 'STATUS_CHOICES') else {}
    agg = (Enrollment.objects
           .filter(academic_year=year, class_group__in=classes_qs)
           .values('class_group__name', 'status')
           .annotate(n=Count('id')))
    par_classe = {}
    for a in agg:
        cls = a['class_group__name'] or '—'
        par_classe.setdefault(cls, {})[a['status']] = a['n']
    columns = ['Classe'] + [labels.get(s, s) for s in statuses] + ['Total']
    rows = []
    for cls, data in sorted(par_classe.items()):
        row = [cls] + [str(data.get(s, 0)) for s in statuses]
        row.append(str(sum(data.values())))
        rows.append(row)
    return {'columns': columns, 'rows': rows}


def _rf_rapport_analyse_mensualite(request, year, classes_qs):
    from django.db.models import Sum, Count, Q
    from academic_core.apps.students.models import PaymentInstallment
    agg = (PaymentInstallment.objects
           .filter(enrollment__academic_year=year, enrollment__class_group__in=classes_qs)
           .values('enrollment__class_group__name')
           .annotate(
               nb_paye=Count('id', filter=Q(is_paid=True)),
               nb_impaye=Count('id', filter=Q(is_paid=False)),
               montant_impaye=Sum('amount_expected', filter=Q(is_paid=False)),
           ).order_by('enrollment__class_group__name'))
    rows = [[a['enrollment__class_group__name'] or '—', a['nb_paye'], a['nb_impaye'], f"{(a['montant_impaye'] or 0):,.0f} F"] for a in agg]
    return {'columns': ['Classe', 'Mensualités payées', 'Mensualités impayées', 'Montant impayé'], 'rows': rows}


def _rf_rapport_impayes_mensuels(request, year, classes_qs):
    from django.db.models import Sum
    from academic_core.apps.students.models import PaymentInstallment
    qs = (PaymentInstallment.objects
          .filter(is_paid=False, enrollment__academic_year=year, enrollment__class_group__in=classes_qs)
          .select_related('enrollment__student__user', 'enrollment__class_group')
          .order_by('enrollment__class_group__name', 'due_date'))
    rows = [[
        pi.enrollment.student.user.get_full_name() if pi.enrollment.student and pi.enrollment.student.user else '—',
        pi.enrollment.class_group.name if pi.enrollment.class_group else '—',
        pi.due_date.strftime('%B %Y') if pi.due_date else '—',
        f"{pi.amount_expected:,.0f} F",
    ] for pi in qs]
    total = qs.aggregate(t=Sum('amount_expected'))['t'] or 0
    return {
        'summary': [('Nombre de mensualités impayées', str(len(rows))), ('Montant total impayé', f"{total:,.0f} F")],
        'columns': ['Étudiant', 'Classe', 'Mois', 'Montant attendu'],
        'rows': rows,
    }


def _rf_rapport_invalidation_impayes(request, year, classes_qs):
    """Étudiants dont le mois de référence courant n'est pas payé — carte
    invalide au contrôle d'accueil (même règle que students:controle_scan)."""
    from academic_core.apps.students.models import Enrollment
    today = date.today()
    qs = (Enrollment.objects
          .filter(status=Enrollment.STATUS_VALIDATED, academic_year=year, class_group__in=classes_qs)
          .select_related('student__user', 'class_group')
          .prefetch_related('installments'))
    rows = []
    for e in qs:
        pi = e.installments.filter(due_date__year=today.year, due_date__month=today.month).first()
        if pi and not pi.is_paid:
            rows.append([
                e.student.user.get_full_name() if e.student and e.student.user else '—',
                e.class_group.name if e.class_group else '—',
                today.strftime('%B %Y'),
                'INVALIDÉ',
            ])
    return {
        'summary': [('Comptes invalidés (mois en cours)', str(len(rows)))],
        'columns': ['Étudiant', 'Classe', 'Mois de référence', 'Statut carte'],
        'rows': rows,
    }


def _rf_rapport_total_impayes(request, year, classes_qs):
    from django.db.models import Sum, Count
    from academic_core.apps.students.models import PaymentInstallment
    agg = (PaymentInstallment.objects
           .filter(is_paid=False, enrollment__academic_year=year, enrollment__class_group__in=classes_qs)
           .values('enrollment__id', 'enrollment__student__user__first_name', 'enrollment__student__user__last_name',
                    'enrollment__class_group__name')
           .annotate(total=Sum('amount_expected'), nb=Count('id'))
           .order_by('-total'))
    rows = [[
        f"{a['enrollment__student__user__first_name'] or ''} {a['enrollment__student__user__last_name'] or ''}".strip() or '—',
        a['enrollment__class_group__name'] or '—',
        a['nb'],
        f"{(a['total'] or 0):,.0f} F",
    ] for a in agg]
    total_general = sum(a['total'] or 0 for a in agg)
    return {
        'summary': [('Total impayés (tous apprenants)', f"{total_general:,.0f} F")],
        'columns': ['Étudiant', 'Classe', 'Mois impayés', 'Montant impayé'],
        'rows': rows,
    }


def _rf_rapport_vacations_mensuelles(request, year, classes_qs):
    from django.db.models import Sum, Count
    from academic_core.apps.accounting.models import TeacherHonoraire
    from academic_core.apps.teachers.models import Teacher
    month = request.GET.get('month', '').strip()
    qs = TeacherHonoraire.objects.filter(academic_year=year, teacher__statut=Teacher.STATUT_VACATAIRE)
    if month.isdigit():
        qs = qs.filter(session_date__month=int(month))
    agg = (qs.values('teacher__id', 'teacher__user__first_name', 'teacher__user__last_name', 'department__name')
           .annotate(seances=Count('id'), heures=Sum('duration_hours'), montant=Sum('amount'))
           .order_by('teacher__user__last_name'))
    rows = []
    total = 0
    for a in agg:
        nom = f"{a['teacher__user__first_name'] or ''} {a['teacher__user__last_name'] or ''}".strip() or '—'
        montant = a['montant'] or 0
        net = montant * Decimal('0.95')
        total += montant
        rows.append([nom, a['department__name'] or '—', a['seances'], f"{(a['heures'] or 0):.1f} h", f"{montant:,.0f} F", f"{net:,.0f} F"])
    return {
        'summary': [('Total des vacations', f"{total:,.0f} F")],
        'columns': ['Enseignant', 'Département', 'Séances', 'Heures', 'Montant', 'Net à payer'],
        'rows': rows,
    }


def _rf_rapport_pointage_personnel(request, year, classes_qs):
    from django.db.models import Count
    from academic_core.apps.hr.models import StaffPresence
    today = date.today()
    month = request.GET.get('month', '').strip()
    month = int(month) if month.isdigit() else today.month
    yr = request.GET.get('py', '').strip()
    yr = int(yr) if yr.isdigit() else today.year
    agg = (StaffPresence.objects
           .filter(date__year=yr, date__month=month)
           .values('user__id', 'user__first_name', 'user__last_name', 'statut')
           .annotate(n=Count('id')))
    par_agent = {}
    for a in agg:
        nom = f"{a['user__first_name'] or ''} {a['user__last_name'] or ''}".strip() or '—'
        par_agent.setdefault(nom, {})[a['statut']] = a['n']
    STATUTS = ['PRESENT', 'ABSENT', 'RETARD', 'CONGE', 'DEMI_JOURNEE', 'TELETRAVAIL', 'FERIE']
    LABELS = {'PRESENT': 'Présences', 'ABSENT': 'Absences', 'RETARD': 'Retards', 'CONGE': 'Congés',
              'DEMI_JOURNEE': 'Demi-journées', 'TELETRAVAIL': 'Télétravail', 'FERIE': 'Fériés'}
    columns = ['Agent'] + [LABELS[s] for s in STATUTS]
    rows = [[nom] + [str(data.get(s, 0)) for s in STATUTS] for nom, data in sorted(par_agent.items())]
    return {'columns': columns, 'rows': rows}


def _rf_rapport_statistique_rentree(request, year, classes_qs):
    from django.db.models import Count, Q
    from academic_core.apps.students.models import Enrollment
    labels = dict(Enrollment.STATUS_CHOICES) if hasattr(Enrollment, 'STATUS_CHOICES') else {}
    agg = (Enrollment.objects
           .filter(academic_year=year, class_group__in=classes_qs)
           .values('class_group__name', 'class_group__capacity')
           .annotate(
               valides=Count('id', filter=Q(status=Enrollment.STATUS_VALIDATED)),
               attente=Count('id', filter=Q(status__in=[Enrollment.STATUS_PENDING, Enrollment.STATUS_PENDING_CAISSE])),
               rejetes=Count('id', filter=Q(status=Enrollment.STATUS_REJECTED)),
               abandons=Count('id', filter=Q(status=Enrollment.STATUS_ABANDONED)),
           ).order_by('class_group__name'))
    rows = [[a['class_group__name'] or '—', a['class_group__capacity'] or '—', a['valides'], a['attente'], a['rejetes'], a['abandons']] for a in agg]
    total_valides = sum(a['valides'] for a in agg)
    return {
        'summary': [('Total inscrits validés', str(total_valides))],
        'columns': ['Classe', 'Capacité', 'Validés', 'En attente', 'Rejetés', 'Abandons'],
        'rows': rows,
    }


def _rf_rapport_recettes_diverses(request, year, classes_qs):
    from django.db.models import Sum
    from datetime import datetime
    from academic_core.apps.accounting.models import CaisseMovement
    date_from_raw = request.GET.get('from', '')
    date_to_raw = request.GET.get('to', '')
    today = date.today()
    try:
        date_from = datetime.strptime(date_from_raw, '%Y-%m-%d').date() if date_from_raw else today.replace(day=1)
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = datetime.strptime(date_to_raw, '%Y-%m-%d').date() if date_to_raw else today
    except ValueError:
        date_to = today

    qs = (CaisseMovement.objects
          .filter(movement_type=CaisseMovement.TYPE_ENTREE, is_executed=True,
                  movement_date__gte=date_from, movement_date__lte=date_to)
          .select_related('created_by').order_by('movement_date'))
    rows = [[m.movement_date.strftime('%d/%m/%Y'), m.motif, m.beneficiaire or '—',
              f"{m.amount:,.0f} F", m.created_by.get_full_name() if m.created_by else '—'] for m in qs]
    total = qs.aggregate(t=Sum('amount'))['t'] or 0
    return {
        'summary': [('Total recettes diverses', f"{total:,.0f} F")],
        'columns': ['Date', 'Libellé', 'Bénéficiaire / Donneur', 'Montant', 'Saisi par'],
        'rows': rows,
    }


def _rf_rapport_rapports_mensualites(request, year, classes_qs):
    from django.db.models import Sum, Count
    from academic_core.apps.students.models import PaymentInstallment
    agg = (PaymentInstallment.objects
           .filter(enrollment__academic_year=year, enrollment__class_group__in=classes_qs)
           .values('enrollment__class_group__name')
           .annotate(
               effectif=Count('enrollment', distinct=True),
               total_attendu=Sum('amount_expected'),
               total_paye=Sum('amount_paid'),
           ).order_by('enrollment__class_group__name'))
    rows = []
    for a in agg:
        attendu = a['total_attendu'] or 0
        paye = a['total_paye'] or 0
        taux = (paye / attendu * 100) if attendu else 0
        rows.append([a['enrollment__class_group__name'] or '—', a['effectif'], f"{attendu:,.0f} F", f"{paye:,.0f} F",
                      f"{(attendu - paye):,.0f} F", f"{taux:,.1f} %"])
    return {'columns': ['Classe', 'Effectif', 'Total attendu', 'Total payé', 'Total impayé', 'Taux'], 'rows': rows}


_RF_DISPATCH = {
    'prevision_recette':            _rf_rapport_prevision_recette,
    'abandons':                     _rf_rapport_abandons,
    'prevision_classe':             _rf_rapport_prevision_classe,
    'manque_a_gagner':               _rf_rapport_manque_a_gagner,
    'comparatif_exercices':          _rf_rapport_comparatif_exercices,
    'recettes_classe_mois':          _rf_rapport_recettes_classe_mois,
    'recette_jour':                  _rf_rapport_recette_jour,
    'recette_periodique_detaillee':  lambda req, y, c: _rf_rapport_recette_periodique(req, y, c, True),
    'recette_periodique_synthese':   lambda req, y, c: _rf_rapport_recette_periodique(req, y, c, False),
    'analyse_inscription':          _rf_rapport_analyse_inscription,
    'analyse_mensualite':            _rf_rapport_analyse_mensualite,
    'impayes_mensuels':              _rf_rapport_impayes_mensuels,
    'invalidation_impayes':          _rf_rapport_invalidation_impayes,
    'total_impayes':                 _rf_rapport_total_impayes,
    'vacations_mensuelles':          _rf_rapport_vacations_mensuelles,
    'pointage_personnel':            _rf_rapport_pointage_personnel,
    'statistique_rentree':           _rf_rapport_statistique_rentree,
    'recettes_diverses':             _rf_rapport_recettes_diverses,
    'rapports_mensualites':          _rf_rapport_rapports_mensualites,
}


def _rf_compute(request):
    from academic_core.apps.academic_structure.models import AcademicYear

    years = _rf_years(request)
    year_id = request.GET.get('year', '').strip()
    year = years.filter(pk=year_id).first() if year_id else None
    if not year:
        year = years.filter(is_current=True).first() or years.first()

    classes_qs = _rf_classes(request, year)
    class_id = request.GET.get('classe', '').strip()
    if class_id:
        classes_qs = classes_qs.filter(pk=class_id)

    code = request.GET.get('report', REPORT_TYPES[0][0])
    if code not in _RF_DISPATCH:
        code = REPORT_TYPES[0][0]

    if not year:
        data = {'columns': [], 'rows': [], 'summary': []}
    else:
        data = _RF_DISPATCH[code](request, year, classes_qs)

    return code, year, years, classes_qs, data


@login_required
def rapports_financiers(request):
    if not _require_rapports_financiers_access(request.user):
        messages.error(request, "Accès refusé : réservé à la Direction Administrative Financière.")
        return redirect('dashboard:index')

    code, year, years, classes_qs, data = _rf_compute(request)
    all_classes = _rf_classes(request, year)

    return render(request, 'accounting/rapports_financiers.html', {
        'REPORT_TYPES': REPORT_TYPES,
        'REPORT_GROUPS': REPORT_GROUPS,
        'selected_report': code,
        'selected_report_label': dict(REPORT_TYPES).get(code, ''),
        'years': years,
        'selected_year': year,
        'classes': all_classes,
        'selected_class_id': request.GET.get('classe', ''),
        'data': data,
        'today': date.today(),
    })


def _rf_resolve_section_filter(request):
    """
    Export par rubrique : ?section=main n'exporte que le tableau principal,
    ?section=<index> (0, 1, 2...) n'exporte que la section correspondante de
    `data['sections']` — sans ce paramètre (ou une valeur invalide), tout le
    rapport (comportement global inchangé).
    """
    return request.GET.get('section', '').strip()


def _rf_filtered_data(data, section_filter):
    """Retourne (main_table_included, sections_included) selon le filtre."""
    if section_filter == 'main':
        return True, []
    if section_filter.isdigit():
        idx = int(section_filter)
        sections = data.get('sections', [])
        if 0 <= idx < len(sections):
            return False, [sections[idx]]
    return True, data.get('sections', [])


@login_required
def rapports_financiers_export_excel(request):
    if not _require_rapports_financiers_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:rapports_financiers')

    import openpyxl
    from openpyxl.styles import Font, PatternFill

    code, year, years, classes_qs, data = _rf_compute(request)
    label = dict(REPORT_TYPES).get(code, 'Rapport')
    section_filter = _rf_resolve_section_filter(request)
    include_main, sections = _rf_filtered_data(data, section_filter)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = label[:31] if label else 'Rapport'

    ws.append([label])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([f"Année académique : {year.label if year else '—'}"])
    ws.append([])

    def _write_headers(headers, header_colors=None):
        header_row = ws.max_row + 1
        ws.append(headers)
        for i, cell in enumerate(ws[header_row]):
            color = (header_colors[i].lstrip('#') if header_colors and header_colors[i] else '0D2244')
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')

    if include_main:
        header_cells = data.get('header_cells')
        if header_cells:
            _write_headers([c['label'] for c in header_cells], [c.get('color') for c in header_cells])
        else:
            _write_headers(data.get('columns', []))
        for row in data.get('rows', []):
            ws.append(row)

    for section in sections:
        ws.append([])
        ws.append([section.get('title', '')])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
        if section.get('summary'):
            for slabel, svalue in section['summary']:
                ws.append([slabel, svalue])
        _write_headers(section.get('columns', []))
        for row in section.get('rows', []):
            ws.append(row)

    for col in ws.columns:
        length = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(length + 2, 10), 40)

    suffix = f"_{section_filter}" if section_filter else ""
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{label.replace(" ", "_")}{suffix}.xlsx"'
    wb.save(response)
    return response


@login_required
def rapports_financiers_export_pdf(request):
    if not _require_rapports_financiers_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:rapports_financiers')

    from academic_core.pdf_utils import get_institut_config_for_request
    from academic_core.apps.reports.pdf_generator import generate_financial_report_pdf

    code, year, years, classes_qs, data = _rf_compute(request)
    label = dict(REPORT_TYPES).get(code, 'Rapport')
    section_filter = _rf_resolve_section_filter(request)
    include_main, sections = _rf_filtered_data(data, section_filter)
    config = get_institut_config_for_request(request)

    buf = generate_financial_report_pdf(
        data, label=label, year=year, config=config,
        include_main=include_main, sections=sections,
    )
    suffix = f"_{section_filter}" if section_filter else ""
    filename = f"{label.replace(' ', '_')}{suffix}.pdf"
    return FileResponse(buf, as_attachment=True, filename=filename, content_type='application/pdf')


@login_required
def rapports_financiers_export_word(request):
    if not _require_rapports_financiers_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:rapports_financiers')

    from academic_core.pdf_utils import get_institut_config_for_request
    from .word_financial_report import generate_financial_report_word

    code, year, years, classes_qs, data = _rf_compute(request)
    label = dict(REPORT_TYPES).get(code, 'Rapport')
    section_filter = _rf_resolve_section_filter(request)
    include_main, sections = _rf_filtered_data(data, section_filter)
    config = get_institut_config_for_request(request)

    buf = generate_financial_report_word(
        data, label=label, year=year, config=config,
        include_main=include_main, sections=sections,
    )
    suffix = f"_{section_filter}" if section_filter else ""
    filename = f"{label.replace(' ', '_')}{suffix}.docx"
    return HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@login_required
def mon_certificat_inscription_pdf(request):
    """Redirige l'étudiant connecté vers son certificat d'inscription (même PDF que l'admin)."""
    from academic_core.apps.students.models import Enrollment

    if not request.user.is_etudiant():
        messages.error(request, "Accès réservé aux étudiants.")
        return redirect('dashboard:index')

    student = getattr(request.user, 'student_profile', None)
    if not student:
        messages.error(request, "Profil étudiant introuvable.")
        return redirect('dashboard:index')

    enrollment = Enrollment.objects.filter(
        student=student, status=Enrollment.STATUS_VALIDATED
    ).order_by('-academic_year__start_date').first()

    if not enrollment:
        messages.error(request, "Aucune inscription validée trouvée.")
        return redirect('dashboard:index')

    return redirect('accounting:certificat_inscription_pdf', pk=enrollment.pk)


@login_required
def mon_attestation_passage_pdf(request):
    """Génère l'attestation de passage de l'étudiant connecté (classe précédente → classe actuelle)."""
    from academic_core.apps.students.models import Enrollment

    if not request.user.is_etudiant():
        messages.error(request, "Accès réservé aux étudiants.")
        return redirect('dashboard:index')

    student = getattr(request.user, 'student_profile', None)
    if not student:
        messages.error(request, "Profil étudiant introuvable.")
        return redirect('dashboard:index')

    # Chercher l'inscription de réinscription la plus récente et validée
    enrollment = (
        Enrollment.objects
        .filter(
            student=student,
            status=Enrollment.STATUS_VALIDATED,
            enrollment_type=Enrollment.TYPE_REINSCRIPTION,
        )
        .select_related('class_group__level', 'academic_year', 'previous_class')
        .order_by('-academic_year__start_date')
        .first()
    )

    if not enrollment:
        messages.warning(
            request,
            "Aucune attestation de passage disponible. "
            "Ce document est délivré lors d'une réinscription en classe supérieure."
        )
        return redirect('dashboard:index')

    if not enrollment.previous_class:
        messages.warning(request, "La classe précédente n'est pas renseignée sur votre dossier.")
        return redirect('dashboard:index')

    # Déléguer au PDF admin (l'accès étudiant est désormais autorisé par attestation_passage_pdf)
    return redirect('accounting:attestation_passage_pdf', pk=enrollment.pk)


# ===========================================================================
# LA CAISSE — Paiements (inscription, scolarité, soutenance)
# ===========================================================================

def _require_caisse_access(user):
    return user.is_admin() or user.is_controleur() or user.is_comptable() \
        or getattr(user, 'role_name', '') in ('ASSISTANTE', 'RESPONSABLE', 'CIAQ')


@login_required
def caisse_student_search(request):
    """Endpoint JSON pour l'autocomplétion étudiant dans La Caisse."""
    import json
    from academic_core.apps.students.models import Student

    if not _require_caisse_access(request.user):
        return HttpResponse(json.dumps([]), content_type='application/json')

    q  = request.GET.get('q', '').strip()
    pk = request.GET.get('pk', '').strip()

    # Pré-remplissage par PK (bouton "Encaisser" du dashboard)
    if pk and pk.isdigit():
        students = Student.objects.filter(pk=pk).select_related('user', 'current_class')
    elif len(q) >= 2:
        students = Student.objects.filter(
            db_models.Q(matricule__icontains=q) |
            db_models.Q(user__first_name__icontains=q) |
            db_models.Q(user__last_name__icontains=q)
        ).select_related('user', 'current_class').order_by('user__last_name', 'user__first_name')[:15]
    else:
        return HttpResponse(json.dumps([]), content_type='application/json')

    data = [
        {
            'id':        s.pk,
            'label':     f"{s.matricule} — {s.full_name}",
            'matricule': s.matricule,
            'name':      s.full_name,
            'classe':    s.current_class.name if s.current_class else '',
        }
        for s in students
    ]
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def caisse_student_fees(request, pk):
    """Retourne la mensualité pour l'étudiant : classe en priorité, niveau en fallback."""
    import json
    from academic_core.apps.students.models import Student, Enrollment
    from .models import FraisGenerauxNiveau, FraisMensuelClasse

    if not _require_caisse_access(request.user):
        return HttpResponse(json.dumps({}), content_type='application/json')

    student = get_object_or_404(Student.objects.select_related(
        'current_class__level', 'current_class__program'
    ), pk=pk)

    current_class = student.current_class

    # Si pas de classe active (étudiant en attente de validation), chercher dans l'enrollment PENDING
    if not current_class:
        pending_enr = Enrollment.objects.filter(
            student=student, status=Enrollment.STATUS_PENDING
        ).select_related('class_group__level', 'class_group__program').order_by('-id').first()
        if pending_enr:
            current_class = pending_enr.class_group

    level         = current_class.level if current_class else None
    frais_mensuel = None
    source        = ''    # 'classe' | 'niveau' | 'enrollment'
    niveau_label  = str(level) if level else ''
    classe_label  = current_class.name if current_class else ''

    # 1) Priorité : mensualité configurée directement sur la classe
    if current_class:
        try:
            cfg_classe = FraisMensuelClasse.objects.get(class_group=current_class)
            if cfg_classe.frais_mensuel is not None:
                frais_mensuel = float(cfg_classe.frais_mensuel)
                source = 'classe'
        except FraisMensuelClasse.DoesNotExist:
            pass

    # 2) Fallback : mensualité configurée sur le niveau
    if frais_mensuel is None and level:
        cfg_niveau = FraisGenerauxNiveau.get_for_level(level)
        if cfg_niveau and cfg_niveau.frais_mensuel:
            frais_mensuel = float(cfg_niveau.frais_mensuel)
            source = 'niveau'

    # 3) Fallback final : mensualité sur l'inscription en cours
    if frais_mensuel is None:
        enrollment = Enrollment.objects.filter(
            student=student,
            academic_year__is_current=True,
            status=Enrollment.STATUS_VALIDATED,
        ).first()
        if enrollment and enrollment.monthly_installment:
            frais_mensuel = float(enrollment.monthly_installment)
            source = 'enrollment'

    # Frais d'inscription (frais_totaux du niveau)
    frais_inscription = None
    if level:
        cfg = FraisGenerauxNiveau.get_for_level(level)
        if cfg and cfg.frais_totaux:
            frais_inscription = float(cfg.frais_totaux)

    # Frais de soutenance (frais_generaux du niveau)
    frais_soutenance = None
    if level:
        cfg = FraisGenerauxNiveau.get_for_level(level)
        if cfg and cfg.frais_generaux:
            frais_soutenance = float(cfg.frais_generaux)

    data = {
        'frais_mensuel':    frais_mensuel,
        'frais_inscription': frais_inscription,
        'frais_soutenance':  frais_soutenance,
        'source':            source,
        'niveau':            niveau_label,
        'classe':            classe_label,
    }
    return HttpResponse(json.dumps(data), content_type='application/json')


def _get_payment_class_name(p):
    """Retourne le nom de la classe d'un paiement (enrollment → current_class → 'Sans classe')."""
    if p.enrollment and p.enrollment.class_group:
        return p.enrollment.class_group.name
    if p.student and p.student.current_class:
        return p.student.current_class.name
    return 'Sans classe'


def _group_by_class(qs):
    """
    Retourne une liste de dicts {class_name, students, total} où students est
    une liste de dicts {student_name, matricule, payments, subtotal}.
    Groupé par classe, puis par étudiant.
    """
    from itertools import groupby as _groupby

    # Préchargement pour éviter N+1
    payments = list(qs.select_related(
        'student__user', 'student__current_class',
        'enrollment__class_group',
    ).order_by(
        'enrollment__class_group__name',
        'student__current_class__name',
        'student__user__last_name',
        'student__user__first_name',
        '-payment_date',
    ))

    # Tri stable par nom de classe pour groupby
    payments.sort(key=_get_payment_class_name)

    class_groups = []
    for class_name, class_items in _groupby(payments, key=_get_payment_class_name):
        class_list = list(class_items)
        student_groups = []
        for student_id, stu_items in _groupby(class_list, key=lambda p: p.student_id):
            stu_list = list(stu_items)
            student_groups.append({
                'student':    stu_list[0].student,
                'payments':   stu_list,
                'subtotal':   sum(p.amount for p in stu_list),
            })
        class_groups.append({
            'class_name':    class_name,
            'students':      student_groups,
            'total':         sum(p.amount for p in class_list),
            'count':         len(class_list),
        })
    return class_groups


@login_required
def caisse_dashboard(request):
    if not _require_caisse_access(request.user):
        messages.error(request, "Accès réservé à la caisse.")
        return redirect('dashboard:index')

    from .models import CaissePayment
    from academic_core.apps.academic_structure.models import AcademicYear, Class, Level

    payment_type = request.GET.get('type', '')
    q            = request.GET.get('q', '').strip()
    year_filter  = request.GET.get('academic_year', '')
    dept_filter  = request.GET.get('department', '')
    class_filter = request.GET.get('classe', '')
    level_filter = request.GET.get('level', '')
    month_filter = request.GET.get('month', '')

    departments = Department.objects.filter(is_active=True).order_by('name')

    if 'department' not in request.GET:
        active_dept = getattr(request, 'active_department', None)
        if active_dept:
            dept_filter = str(active_dept.pk)

    dept_obj  = Department.objects.filter(pk=dept_filter).first() if dept_filter else None
    level_obj = Level.objects.filter(pk=level_filter).first() if level_filter else None
    class_obj = Class.objects.filter(pk=class_filter).first() if class_filter else None

    # Année académique : par défaut l'année en cours — "Toutes les années"
    # (academic_year=all) reste disponible pour consulter l'historique.
    if year_filter == 'all':
        selected_year_id = None
    elif year_filter:
        selected_year_id = year_filter
    else:
        current_year = AcademicYear.objects.filter(is_current=True).first()
        selected_year_id = current_year.pk if current_year else None

    # Listes déroulantes classes et niveaux
    classes_qs = Class.objects.select_related('level', 'program__department').order_by('name')
    levels_qs  = Level.objects.order_by('name')
    if dept_obj:
        classes_qs = classes_qs.filter(program__department=dept_obj)
        levels_qs  = levels_qs.filter(classes__program__department=dept_obj).distinct()
    if selected_year_id:
        classes_qs = classes_qs.filter(academic_year_id=selected_year_id)
    if level_obj:
        classes_qs = classes_qs.filter(level=level_obj)

    MOIS_FR = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
               'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    months_choices = [(str(i), MOIS_FR[i]) for i in range(1, 13)]

    # La caisse est globale — tous rôles autorisés voient tout, filtre optionnel
    qs = CaissePayment.objects.select_related(
        'student__user', 'student__current_class__level',
        'academic_year', 'created_by'
    ).order_by('-payment_date', '-created_at')

    if dept_obj:
        qs = qs.filter(
            db_models.Q(student__enrollments__class_group__program__department=dept_obj) |
            db_models.Q(student__current_class__program__department=dept_obj)
        ).distinct()
    if level_obj:
        qs = qs.filter(
            db_models.Q(student__enrollments__class_group__level=level_obj) |
            db_models.Q(student__current_class__level=level_obj)
        ).distinct()
    if class_obj:
        qs = qs.filter(
            db_models.Q(student__enrollments__class_group=class_obj) |
            db_models.Q(student__current_class=class_obj)
        ).distinct()
    if payment_type:
        qs = qs.filter(payment_type=payment_type)
    if selected_year_id:
        qs = qs.filter(academic_year_id=selected_year_id)
    if month_filter and month_filter.isdigit():
        qs = qs.filter(payment_month=int(month_filter))
    if q:
        qs = qs.filter(
            db_models.Q(reference__icontains=q) |
            db_models.Q(student__matricule__icontains=q) |
            db_models.Q(student__user__first_name__icontains=q) |
            db_models.Q(student__user__last_name__icontains=q)
        )

    academic_years = AcademicYear.objects.order_by('-start_date')
    base_caisse = CaissePayment.objects.filter(academic_year_id=selected_year_id) if selected_year_id else CaissePayment.objects
    counts = {
        'all':          base_caisse.count(),
        'inscription':  base_caisse.filter(payment_type=CaissePayment.TYPE_INSCRIPTION).count(),
        'scolarite':    base_caisse.filter(payment_type=CaissePayment.TYPE_SCOLARITE).count(),
        'soutenance':   base_caisse.filter(payment_type=CaissePayment.TYPE_SOUTENANCE).count(),
    }

    # Inscriptions envoyées à la caisse par le trésorier général — en attente de paiement
    from academic_core.apps.students.models import Enrollment
    pending_enrollments = Enrollment.objects.select_related(
        'student__user', 'class_group', 'academic_year', 'validated_by'
    ).filter(
        status=Enrollment.STATUS_PENDING_CAISSE,
    ).order_by('validated_at', 'enrollment_date')

    return render(request, 'accounting/caisse_dashboard.html', {
        'payments':            qs,
        'payments_by_class':   _group_by_class(qs),
        'payment_type':        payment_type,
        'search':              q,
        'year_filter':         year_filter,
        'dept_filter':         dept_filter,
        'dept_obj':            dept_obj,
        'departments':         departments,
        'academic_years':      academic_years,
        'counts':              counts,
        'pending_enrollments': pending_enrollments,
        'classes':             classes_qs,
        'levels':              levels_qs,
        'class_filter':        class_filter,
        'level_filter':        level_filter,
        'month_filter':        month_filter,
        'months_choices':      months_choices,
        'TYPE_INSCRIPTION': CaissePayment.TYPE_INSCRIPTION,
        'TYPE_SCOLARITE':   CaissePayment.TYPE_SCOLARITE,
        'TYPE_SOUTENANCE':  CaissePayment.TYPE_SOUTENANCE,
    })


@login_required
def caisse_payment_create(request):
    if not _require_caisse_access(request.user):
        messages.error(request, "Accès réservé à la caisse.")
        return redirect('dashboard:index')

    from .models import CaissePayment, AccountingClosure
    from academic_core.apps.students.models import Student
    from academic_core.apps.academic_structure.models import AcademicYear
    from datetime import date as dt, timedelta

    # ── Vérifier que la veille est clôturée (sauf si c'est le tout premier jour) ──
    today      = dt.today()
    yesterday  = today - timedelta(days=1)
    first_ever = not AccountingClosure.objects.exists()  # aucune clôture = premier jour
    yesterday_closed = AccountingClosure.objects.filter(closure_date=yesterday).exists()

    if not first_ever and not yesterday_closed:
        messages.error(
            request,
            f"⚠️ La journée du {yesterday.strftime('%d/%m/%Y')} n'a pas été clôturée. "
            "Vous devez clôturer la journée précédente avant de pouvoir enregistrer de nouveaux encaissements."
        )
        return redirect('accounting:etat_journalier')

    students       = Student.objects.select_related('user').order_by('user__last_name', 'user__first_name')
    academic_years = AcademicYear.objects.order_by('-start_date')
    errors = {}

    # Pré-remplissage depuis la caisse (bouton "Encaisser" depuis la liste d'attente)
    prefill = {
        'student':       request.GET.get('student', ''),
        'payment_type':  request.GET.get('type', ''),
        'academic_year': request.GET.get('year', ''),
    }

    if request.method == 'POST':
        student_id    = request.POST.get('student')
        payment_type  = request.POST.get('payment_type')
        amount_raw    = request.POST.get('amount', '').strip()
        payment_date  = request.POST.get('payment_date')
        acad_year_id  = request.POST.get('academic_year')
        payment_month_raw = request.POST.get('payment_month', '').strip()
        notes         = request.POST.get('notes', '').strip()

        if not student_id:
            errors['student'] = "Étudiant requis."
        if payment_type not in (CaissePayment.TYPE_INSCRIPTION, CaissePayment.TYPE_SCOLARITE, CaissePayment.TYPE_SOUTENANCE):
            errors['payment_type'] = "Type de frais invalide."
        if not amount_raw:
            errors['amount'] = "Montant requis."
        else:
            try:
                amount = Decimal(amount_raw.replace(' ', '').replace(',', '.'))
                if amount <= 0:
                    errors['amount'] = "Le montant doit être positif."
            except Exception:
                errors['amount'] = "Montant invalide."
        if not payment_date:
            errors['payment_date'] = "Date de paiement requise."

        if not errors:
            student       = get_object_or_404(Student, pk=student_id)
            acad_year     = AcademicYear.objects.filter(pk=acad_year_id).first() if acad_year_id else None
            payment_month = int(payment_month_raw) if payment_month_raw.isdigit() and 1 <= int(payment_month_raw) <= 12 else None
            payment       = CaissePayment.objects.create(
                student=student,
                payment_type=payment_type,
                amount=amount,
                payment_date=payment_date,
                payment_month=payment_month,
                academic_year=acad_year,
                notes=notes,
                created_by=request.user,
            )

            # Lier automatiquement l'enrollment PENDING si paiement d'inscription
            if payment_type == CaissePayment.TYPE_INSCRIPTION:
                from academic_core.apps.students.models import Enrollment
                enrollment_qs = Enrollment.objects.filter(
                    student=student,
                    status=Enrollment.STATUS_PENDING,
                )
                if acad_year:
                    enrollment_qs = enrollment_qs.filter(academic_year=acad_year)
                enrollment = enrollment_qs.order_by('-id').first()
                if enrollment:
                    enrollment.payment_amount    = amount
                    enrollment.payment_date      = payment_date
                    enrollment.payment_reference = payment.reference
                    enrollment.save(update_fields=['payment_amount', 'payment_date', 'payment_reference'])

            messages.success(request, f"Paiement enregistré. Référence : {payment.reference}")
            return redirect('accounting:caisse_recu_pdf', pk=payment.pk)

    from django.urls import reverse
    return render(request, 'accounting/caisse_payment_form.html', {
        'students':          students,
        'academic_years':    academic_years,
        'errors':            errors,
        'post':              request.POST,
        'prefill':           prefill,
        'TYPE_CHOICES':      CaissePayment.TYPE_CHOICES,
        'student_search_url': reverse('accounting:caisse_student_search'),
        'student_fees_base_url': reverse('accounting:caisse_student_fees', kwargs={'pk': 99999}).replace('99999/frais/', ''),
    })


@login_required
def inscription_recu(request, pk):
    """Page HTML du reçu de paiement d'inscription (accessible caissier + trésorier)."""
    from academic_core.apps.students.models import Enrollment
    from .models import CaissePayment
    from academic_core.pdf_utils import get_institut_config_for_request

    # Pas de select_related('...__faculty') : Faculty est un modèle maître,
    # Enrollment est routé par tenant — le hop __faculty forcerait un INNER
    # JOIN chaîné sur la table locale `faculties`, toujours vide côté tenant,
    # faisant échouer get_object_or_404 pour TOUTE inscription valide.
    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__level',
            'class_group__program__department',
            'academic_year', 'validated_by',
        ),
        pk=pk,
    )

    if not (request.user.is_admin() or request.user.is_comptable()
            or request.user.is_controleur() or request.user.is_responsable()
            or request.user.is_inst_admin()):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    payments = list(CaissePayment.objects.filter(enrollment=enrollment).order_by('-created_at'))
    config   = get_institut_config_for_request(request)

    # Montant réellement encaissé : privilégier le total déjà enregistré sur
    # l'inscription (tient compte des montants par mois éventuellement
    # personnalisés) ; à défaut, retomber sur la structure tarifaire générique.
    if enrollment.payment_amount:
        total_paid = enrollment.payment_amount
    else:
        _months  = enrollment.advance_months_list()
        _fees    = enrollment.total_fees or 0
        _mensuel = enrollment.monthly_installment or 0
        if _months and _mensuel:
            total_paid = _fees + max(len(_months) - 1, 0) * _mensuel
        else:
            total_paid = _fees or sum(p.amount for p in payments)

    return render(request, 'accounting/inscription_recu.html', {
        'enrollment': enrollment,
        'payments':   payments,
        'total_paid': total_paid,
        'config':     config,
    })


@login_required
def inscription_recu_pdf(request, pk):
    """Génère le reçu PDF consolidé d'une inscription (tous paiements)."""
    from academic_core.apps.students.models import Enrollment
    from academic_core.pdf_utils import get_institut_config_for_request as _gcfr
    from .services import generate_inscription_recu_pdf

    def _has_recu_access(user):
        return (user.is_admin() or user.is_comptable()
                or user.is_controleur() or user.is_responsable()
                or user.is_inst_admin())

    if not _has_recu_access(request.user):
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__level', 'academic_year', 'validated_by',
        ),
        pk=pk,
    )
    config = _gcfr(request)
    buffer = generate_inscription_recu_pdf(enrollment, config=config)
    safe_ref = (enrollment.payment_reference or f'inscription-{pk}').replace('/', '-')
    return FileResponse(buffer, as_attachment=False,
                        filename=f'recu_{safe_ref}.pdf',
                        content_type='application/pdf')


@login_required
def caisse_recu_pdf(request, pk):
    if not _require_caisse_access(request.user):
        messages.error(request, "Accès réservé à la caisse.")
        return redirect('dashboard:index')

    from .models import CaissePayment
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from academic_core.pdf_utils import logo_image as _logo_img_caisse_fn, get_institut_config_for_request as _gcfr_caisse
    _logo_img = lambda **kw: _logo_img_caisse_fn(config=_gcfr_caisse(request), **kw)  # noqa: E731

    payment = get_object_or_404(
        CaissePayment.objects.select_related('student__user', 'academic_year', 'created_by'),
        pk=pk,
    )
    student = payment.student

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A5,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    green = colors.HexColor('#166534')

    ss = getSampleStyleSheet()
    sc = ParagraphStyle

    s_ctr  = sc('c',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl  = sc('t',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=14, fontName='Helvetica-Bold', textColor=navy)
    s_sub  = sc('s',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=9, textColor=grey)
    s_lbl  = sc('l',  parent=ss['Normal'], fontSize=9, fontName='Helvetica-Bold', textColor=navy)
    s_val  = sc('v',  parent=ss['Normal'], fontSize=9)
    s_ref  = sc('rf', parent=ss['Normal'], alignment=TA_CENTER, fontSize=13, fontName='Helvetica-Bold', textColor=green)
    s_amt  = sc('am', parent=ss['Normal'], alignment=TA_CENTER, fontSize=16, fontName='Helvetica-Bold', textColor=navy)
    s_sgn  = sc('sg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')
    s_foot = sc('ft', parent=ss['Normal'], alignment=TA_CENTER, fontSize=7, textColor=grey)

    _logo_el = _logo_img(width=2*cm, height=1.4*cm) or Paragraph('ISI', sc('lb', parent=s_ctr, fontSize=9, fontName='Helvetica-Bold', textColor=navy))
    _hdr_tbl = Table(
        [[_logo_el,
          Paragraph(
            "<b>GROUPE ISI</b><br/><font size='8'>Institut Supérieur d'Informatique</font>",
            sc('rh', parent=ss['Normal'], alignment=TA_CENTER, leading=13),
          )]],
        colWidths=[2.5*cm, 9.5*cm],
    )
    _hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    type_label = payment.get_type_label()

    story = [
        _hdr_tbl,
        Spacer(1, .2*cm),
        HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=6),
        Paragraph("REÇU DE PAIEMENT", s_ttl),
        Spacer(1, .2*cm),
        Paragraph(type_label.upper(), s_sub),
        Spacer(1, .3*cm),
        HRFlowable(width='50%', thickness=1, color=gold, hAlign='CENTER'),
        Spacer(1, .4*cm),
        Paragraph(payment.reference, s_ref),
        Spacer(1, .3*cm),
        Table([
            [Paragraph("<b>Matricule</b>", s_lbl),        Paragraph(student.matricule, s_val)],
            [Paragraph("<b>Étudiant(e)</b>", s_lbl),      Paragraph(student.full_name, s_val)],
            [Paragraph("<b>Type de frais</b>", s_lbl),    Paragraph(type_label, s_val)],
            *([[Paragraph("<b>Type de soutenance</b>", s_lbl),
               Paragraph(payment.get_soutenance_type_label(), s_val)]]
              if payment.soutenance_type else []),
            *([[Paragraph("<b>Mois payés</b>", s_lbl),
               Paragraph(', '.join(payment.get_months_labels()), s_val)]]
              if payment.get_months_labels() else
              ([[Paragraph("<b>Mois concerné</b>", s_lbl), Paragraph(payment.get_month_label(), s_val)]]
               if payment.payment_month else [])),
            [Paragraph("<b>Année académique</b>", s_lbl), Paragraph(payment.academic_year.label if payment.academic_year else '-', s_val)],
            [Paragraph("<b>Date de paiement</b>", s_lbl), Paragraph(payment.payment_date.strftime('%d/%m/%Y'), s_val)],
            [Paragraph("<b>Enregistré par</b>", s_lbl),   Paragraph(payment.created_by.get_full_name() if payment.created_by else '-', s_val)],
        ], colWidths=[4.5*cm, 7.5*cm], style=TableStyle([
            ('BACKGROUND',     (0, 0), (0, -1), light),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',     (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
            ('LEFTPADDING',    (0, 0), (-1, -1), 7),
        ])),
        Spacer(1, .5*cm),
        Paragraph(f"{int(payment.amount):,} FCFA".replace(',', ' '), s_amt),
        Spacer(1, .5*cm),
        HRFlowable(width='100%', thickness=1, color=colors.HexColor('#CBD5E1')),
        Spacer(1, .4*cm),
    ]

    from academic_core.apps.students.qr_utils import student_qr_receipt_block
    tail = [
        Table([
            [Paragraph(f"Dakar, le {payment.payment_date.strftime('%d/%m/%Y')}",
                       sc('dl', parent=ss['Normal'], fontSize=9)),
             Paragraph("Le Caissier / La Caissière", s_sgn)],
        ], colWidths=[6.5*cm, 5.5*cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')]),
    ]
    if payment.notes:
        tail.append(Spacer(1, .3*cm))
        tail.append(Paragraph(f"<i>Note : {payment.notes}</i>",
                               sc('n', parent=ss['Normal'], fontSize=8, textColor=grey)))
    tail += [
        Spacer(1, 1*cm),
        HRFlowable(width='100%', thickness=0.5, color=grey),
        Spacer(1, .2*cm),
        Paragraph(f"Réf. {payment.reference}  —  Institut Supérieur d'Informatique - ISI  —  Dakar, Sénégal", s_foot),
    ]
    tail += student_qr_receipt_block(student, payment.enrollment)
    story.append(KeepTogether(tail))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="recu_{payment.reference}.pdf"'
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# GESTION FRAIS SOUTENANCE (Licence 3 / Master 2)
# ══════════════════════════════════════════════════════════════════════════════

def _require_soutenance_access(user):
    # is_admin() couvre déjà TRESORIER_GENERAL et CAISSIER (voir accounts/models.py),
    # les deux rôles explicitement visés par cette fonctionnalité, ainsi que les
    # autres rôles admin-tier pour la supervision.
    return user.is_admin()


@login_required
def soutenance_dashboard(request):
    """Page de recherche : sélectionner un étudiant de L3/M2 pour gérer ses
    frais de soutenance (affichage auto des montants + validation du paiement)."""
    if not _require_soutenance_access(request.user):
        messages.error(request, "Accès réservé au Trésorier Général et au Caissier.")
        return redirect('dashboard:index')

    return render(request, 'accounting/soutenance_dashboard.html', {
        'can_valider': request.user.is_caissier() or request.user.is_admin(),
        'student_search_url': reverse('accounting:soutenance_student_search'),
        'fees_base_url': reverse('accounting:soutenance_enrollment_fees', kwargs={'enrollment_pk': 99999}).replace('99999/frais/', ''),
        'payer_base_url': reverse('accounting:soutenance_payer', kwargs={'enrollment_pk': 99999}).replace('99999/valider/', ''),
    })


@login_required
def soutenance_student_search(request):
    """Endpoint JSON pour l'autocomplétion étudiant — restreint aux inscriptions
    validées de Licence 3 / Master 2 (seuls niveaux concernés par la soutenance)."""
    import json
    from academic_core.apps.students.models import Enrollment

    if not _require_soutenance_access(request.user):
        return HttpResponse(json.dumps([]), content_type='application/json')

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return HttpResponse(json.dumps([]), content_type='application/json')

    enrollments = Enrollment.objects.filter(
        status=Enrollment.STATUS_VALIDATED,
        class_group__level__name__in=('Licence 3', 'Master 2'),
    ).filter(
        db_models.Q(student__matricule__icontains=q) |
        db_models.Q(student__user__first_name__icontains=q) |
        db_models.Q(student__user__last_name__icontains=q)
    ).select_related('student__user', 'class_group').order_by(
        'student__user__last_name', 'student__user__first_name'
    )[:15]

    data = [
        {
            'id':        e.pk,
            'label':     f"{e.student.matricule} — {e.student.full_name} ({e.class_group.name})",
            'matricule': e.student.matricule,
            'name':      e.student.full_name,
            'classe':    e.class_group.name,
        }
        for e in enrollments
    ]
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def soutenance_enrollment_fees(request, enrollment_pk):
    """Retourne en JSON les montants de soutenance (normal/spéciale) et le
    statut de paiement pour cette inscription."""
    import json
    from academic_core.apps.students.models import Enrollment

    if not _require_soutenance_access(request.user):
        return HttpResponse(json.dumps({}), content_type='application/json')

    enrollment = get_object_or_404(
        Enrollment.objects.select_related('student__user', 'class_group__level'),
        pk=enrollment_pk,
    )

    payment = enrollment.soutenance_payment
    data = {
        'matricule':      enrollment.student.matricule,
        'name':           enrollment.student.full_name,
        'classe':         enrollment.class_group.name,
        'frais_normal':   float(enrollment.get_frais_soutenance(speciale=False)) if enrollment.get_frais_soutenance(speciale=False) is not None else None,
        'frais_speciale': float(enrollment.get_frais_soutenance(speciale=True)) if enrollment.get_frais_soutenance(speciale=True) is not None else None,
        'paye':           payment is not None,
    }
    if payment:
        data.update({
            'payment_type':      str(payment.get_soutenance_type_label()),
            'payment_amount':    float(payment.amount),
            'payment_date':      payment.payment_date.strftime('%d/%m/%Y'),
            'payment_reference': payment.reference,
            'receipt_url':       reverse('accounting:caisse_recu_pdf', args=[payment.pk]),
        })
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
@require_http_methods(['POST'])
def soutenance_payer(request, enrollment_pk):
    """Valide le paiement des frais de soutenance (normal ou spéciale) pour
    cette inscription — réservé au Caissier (et à l'admin, pour supervision)."""
    import json
    from datetime import date as dt, timedelta
    from academic_core.apps.students.models import Enrollment
    from .models import CaissePayment, AccountingClosure

    if not (request.user.is_caissier() or request.user.is_admin()):
        return HttpResponse(
            json.dumps({'error': "Seul le Caissier peut valider ce paiement."}),
            content_type='application/json', status=403,
        )

    enrollment = get_object_or_404(Enrollment.objects.select_related('student', 'class_group__level'), pk=enrollment_pk)

    if enrollment.soutenance_payment:
        return HttpResponse(
            json.dumps({'error': "Les frais de soutenance ont déjà été payés pour cet étudiant."}),
            content_type='application/json', status=400,
        )

    soutenance_type = request.POST.get('soutenance_type', '').strip().upper()
    if soutenance_type not in (CaissePayment.SOUTENANCE_NORMALE, CaissePayment.SOUTENANCE_SPECIALE):
        return HttpResponse(
            json.dumps({'error': "Type de soutenance invalide."}),
            content_type='application/json', status=400,
        )

    amount = enrollment.get_frais_soutenance(speciale=(soutenance_type == CaissePayment.SOUTENANCE_SPECIALE))
    if amount is None:
        return HttpResponse(
            json.dumps({'error': "Aucun montant de soutenance configuré pour cette classe."}),
            content_type='application/json', status=400,
        )

    today = dt.today()
    yesterday = today - timedelta(days=1)
    first_ever = not AccountingClosure.objects.exists()
    if not first_ever and not AccountingClosure.objects.filter(closure_date=yesterday).exists():
        return HttpResponse(
            json.dumps({'error': f"La journée du {yesterday.strftime('%d/%m/%Y')} n'a pas été clôturée."}),
            content_type='application/json', status=400,
        )

    payment = CaissePayment.objects.create(
        student=enrollment.student,
        payment_type=CaissePayment.TYPE_SOUTENANCE,
        soutenance_type=soutenance_type,
        amount=amount,
        payment_date=today,
        academic_year=enrollment.academic_year,
        enrollment=enrollment,
        created_by=request.user,
    )

    return HttpResponse(json.dumps({
        'status': 'ok',
        'receipt_url': reverse('accounting:caisse_recu_pdf', args=[payment.pk]),
        'reference': payment.reference,
    }), content_type='application/json')


# ══════════════════════════════════════════════════════════════════════════════
# PAIEMENT MENSUALITÉS
# ══════════════════════════════════════════════════════════════════════════════

def _require_mensualite_access(user):
    # is_admin() couvre déjà ADMIN, INST_ADMIN, CONTROLEUR, COMPTABLE,
    # TRESORIER_GENERAL, CAISSIER, etc. — assure un accès réel à
    # l'Administrateur d'institut, pas seulement un lien visible dans le menu.
    return user.is_admin() or user.is_responsable()


@login_required
def mensualite_recu_pdf(request, enrollment_pk, year, month):
    """Génère le reçu PDF d'un paiement de mensualité."""
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment, PaymentInstallment
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from academic_core.pdf_utils import logo_image as _logo_img_fn, get_institut_config_for_request as _gcfr
    _logo_img = lambda **kw: _logo_img_fn(config=_gcfr(request), **kw)  # noqa: E731

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'class_group__level', 'academic_year'
        ),
        pk=enrollment_pk,
    )
    inst = get_object_or_404(
        PaymentInstallment,
        enrollment=enrollment,
        due_date__year=year,
        due_date__month=month,
        is_paid=True,
    )

    student = enrollment.student
    MOIS_LONG = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    mois_label  = MOIS_LONG[month] if 1 <= month <= 12 else str(month)
    ref         = f"MENS-{year}-{month:02d}-{enrollment_pk}"
    paid_date   = inst.paid_date or inst.due_date
    amount      = inst.amount_paid or inst.amount_expected or Decimal('0')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A5,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    light = colors.HexColor('#EFF6FF')
    grey  = colors.HexColor('#64748B')
    green = colors.HexColor('#166534')

    ss = getSampleStyleSheet()
    sc = ParagraphStyle

    s_ctr  = sc('mc',  parent=ss['Normal'], alignment=TA_CENTER)
    s_ttl  = sc('mt',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=14, fontName='Helvetica-Bold', textColor=navy)
    s_sub  = sc('ms',  parent=ss['Normal'], alignment=TA_CENTER, fontSize=9, textColor=grey)
    s_lbl  = sc('ml',  parent=ss['Normal'], fontSize=9, fontName='Helvetica-Bold', textColor=navy)
    s_val  = sc('mv',  parent=ss['Normal'], fontSize=9)
    s_ref  = sc('mrf', parent=ss['Normal'], alignment=TA_CENTER, fontSize=13, fontName='Helvetica-Bold', textColor=green)
    s_amt  = sc('mam', parent=ss['Normal'], alignment=TA_CENTER, fontSize=16, fontName='Helvetica-Bold', textColor=navy)
    s_sgn  = sc('msg', parent=ss['Normal'], alignment=TA_RIGHT, fontSize=9, fontName='Helvetica-Bold')
    s_foot = sc('mft', parent=ss['Normal'], alignment=TA_CENTER, fontSize=7, textColor=grey)

    _logo_el = _logo_img(width=2*cm, height=1.4*cm) or Paragraph(
        'ISI', sc('mlb', parent=s_ctr, fontSize=9, fontName='Helvetica-Bold', textColor=navy)
    )

    # Récupérer le nom de l'institut depuis la config
    config = _gcfr(request)
    inst_name    = getattr(config, 'name', "Institut Supérieur d'Informatique") if config else "Institut Supérieur d'Informatique"
    inst_acronym = getattr(config, 'acronym', 'ISI') if config else 'ISI'

    hdr_tbl = Table(
        [[_logo_el,
          Paragraph(
            f"<b>{inst_acronym}</b><br/><font size='8'>{inst_name}</font>",
            sc('mrh', parent=ss['Normal'], alignment=TA_CENTER, leading=13),
          )]],
        colWidths=[2.5*cm, 9.5*cm],
    )
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    classe_label = enrollment.class_group.name if enrollment.class_group else '—'
    acad_label   = enrollment.academic_year.label if enrollment.academic_year else '—'
    issuer_name  = request.user.get_full_name() or request.user.username

    story = [
        hdr_tbl,
        Spacer(1, .2*cm),
        HRFlowable(width='100%', thickness=2, color=navy),
        HRFlowable(width='100%', thickness=1, color=gold, spaceAfter=6),
        Paragraph("REÇU DE PAIEMENT", s_ttl),
        Spacer(1, .15*cm),
        Paragraph("MENSUALITÉ DE SCOLARITÉ", s_sub),
        Spacer(1, .3*cm),
        HRFlowable(width='50%', thickness=1, color=gold, hAlign='CENTER'),
        Spacer(1, .35*cm),
        Paragraph(ref, s_ref),
        Spacer(1, .3*cm),
        Table([
            [Paragraph("<b>Matricule</b>",        s_lbl), Paragraph(student.matricule, s_val)],
            [Paragraph("<b>Étudiant(e)</b>",       s_lbl), Paragraph(student.full_name, s_val)],
            [Paragraph("<b>Classe</b>",            s_lbl), Paragraph(classe_label, s_val)],
            [Paragraph("<b>Mois concerné</b>",     s_lbl), Paragraph(f"{mois_label} {year}", s_val)],
            [Paragraph("<b>Année académique</b>",  s_lbl), Paragraph(acad_label, s_val)],
            [Paragraph("<b>Date de paiement</b>",  s_lbl), Paragraph(paid_date.strftime('%d/%m/%Y'), s_val)],
            [Paragraph("<b>Enregistré par</b>",    s_lbl), Paragraph(issuer_name, s_val)],
        ], colWidths=[4.5*cm, 7.5*cm], style=TableStyle([
            ('BACKGROUND',     (0, 0), (0, -1), light),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',     (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
            ('LEFTPADDING',    (0, 0), (-1, -1), 7),
        ])),
        Spacer(1, .5*cm),
        Paragraph(f"{int(amount):,} FCFA".replace(',', ' '), s_amt),
        Spacer(1, .5*cm),
        HRFlowable(width='100%', thickness=1, color=colors.HexColor('#CBD5E1')),
        Spacer(1, .4*cm),
    ]

    from academic_core.apps.students.qr_utils import student_qr_receipt_block
    tail = [
        Table([
            [Paragraph(f"Dakar, le {paid_date.strftime('%d/%m/%Y')}",
                       sc('mdl', parent=ss['Normal'], fontSize=9)),
             Paragraph("Le Caissier / La Caissière", s_sgn)],
        ], colWidths=[6.5*cm, 5.5*cm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP')]),
    ]
    if inst.notes:
        tail.append(Spacer(1, .3*cm))
        tail.append(Paragraph(
            f"<i>Note : {inst.notes}</i>",
            sc('mn', parent=ss['Normal'], fontSize=8, textColor=grey),
        ))
    tail += [
        Spacer(1, 1*cm),
        HRFlowable(width='100%', thickness=0.5, color=grey),
        Spacer(1, .2*cm),
        Paragraph(
            f"Réf. {ref}  —  {inst_name} - {inst_acronym}  —  Dakar, Sénégal",
            s_foot,
        ),
    ]
    tail += student_qr_receipt_block(student, enrollment)
    story.append(KeepTogether(tail))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    filename = f"recu_mensualite_{mois_label}_{year}_{student.matricule}.pdf"
    resp = HttpResponse(buffer.read(), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{filename}"'
    return resp


@login_required
def mensualite_list(request):
    """Liste des étudiants avec leur grille de paiement mensuel."""
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment, PaymentInstallment
    from academic_core.apps.academic_structure.models import AcademicYear, Class, Level
    from academic_core.apps.accounting.models import FraisMensuelClasse, FraisGenerauxNiveau, AcademicYearDistribution
    from django.db.models import Prefetch

    # --- Filtres ---
    _global_view = request.user.is_controleur() or request.user.is_comptable()
    faculty  = None if _global_view else getattr(request, 'active_faculty', None)
    dept_req = None if _global_view else getattr(request, 'active_department', None)

    years = AcademicYear.objects.order_by('-start_date')
    if faculty and not request.user.is_super_admin():
        fy = years.filter(faculty=faculty)
        years = fy if fy.exists() else years

    year_id   = request.GET.get('year')
    class_id  = request.GET.get('classe')
    level_id  = request.GET.get('level')
    search    = request.GET.get('q', '').strip()

    selected_year  = None
    selected_class = None
    selected_level = None

    if year_id:
        try:
            selected_year = years.get(pk=year_id)
        except AcademicYear.DoesNotExist:
            pass
    if not selected_year and years.exists():
        selected_year = years.filter(is_current=True).first() or years.first()

    # Niveaux disponibles
    levels_qs = Level.objects.order_by('name')
    if dept_req:
        levels_qs = levels_qs.filter(classes__program__department=dept_req).distinct()
    elif faculty:
        levels_qs = levels_qs.filter(classes__program__department__faculty=faculty).distinct()

    if level_id:
        selected_level = levels_qs.filter(pk=level_id).first()

    # Classes filtrées par faculté/département et niveau
    classes_qs = Class.objects.select_related('level', 'program__department').order_by('name')
    if dept_req:
        classes_qs = classes_qs.filter(program__department=dept_req)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)

    if selected_year:
        classes_qs = classes_qs.filter(academic_year=selected_year)
    if selected_level:
        classes_qs = classes_qs.filter(level=selected_level)

    if class_id:
        try:
            selected_class = classes_qs.get(pk=class_id)
        except Class.DoesNotExist:
            pass

    # --- Mois académiques (calculés par classe, chacune ayant sa propre
    # répartition d'année académique — cf. AcademicYearDistribution) ──────────
    MOIS_FR = ['', 'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
               'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc']
    MOIS_LONG = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    def _months_for(class_group):
        """Liste [(y, m), ...] des mois à payer pour CETTE classe, selon sa
        répartition d'année académique (ou sept → juin par défaut)."""
        if not selected_year:
            return []
        try:
            distrib = AcademicYearDistribution.objects.get(
                academic_year=selected_year, class_group=class_group)
            start_m, nb = distrib.start_month, distrib.nb_months
        except AcademicYearDistribution.DoesNotExist:
            start_m, nb = 9, 10  # Défaut : sept → juin (10 mois)

        # Déduire l'année calendaire de départ depuis l'année académique
        # Ex : 2025-2026 → start_year=2025
        start_year = selected_year.start_date.year if selected_year.start_date else int(str(selected_year)[:4])
        result = []
        for i in range(nb):
            m = ((start_m - 1 + i) % 12) + 1
            y = start_year + ((start_m - 1 + i) // 12)
            result.append((y, m))
        return result

    # --- Inscriptions ---
    enrollments_qs = Enrollment.objects.select_related(
        'student__user', 'class_group__level', 'class_group__program',
        'academic_year',
    ).prefetch_related(
        Prefetch('installments', queryset=PaymentInstallment.objects.order_by('due_date'))
    )

    if selected_year:
        enrollments_qs = enrollments_qs.filter(academic_year=selected_year)
    if selected_class:
        enrollments_qs = enrollments_qs.filter(class_group=selected_class)
    elif dept_req:
        enrollments_qs = enrollments_qs.filter(class_group__program__department=dept_req)
    elif faculty:
        enrollments_qs = enrollments_qs.filter(class_group__program__department__faculty=faculty)

    if search:
        from django.db.models import Q
        enrollments_qs = enrollments_qs.filter(
            Q(student__user__first_name__icontains=search) |
            Q(student__user__last_name__icontains=search) |
            Q(student__matricule__icontains=search)
        )

    enrollments_qs = enrollments_qs.order_by('class_group__name', 'student__user__last_name')

    # --- Construire grille paiements ---
    def _get_frais_mensuel(enr):
        """Retourne le montant mensuel dû pour cette inscription."""
        # Boursier : aucune mensualité par défaut — seuls les mois explicitement
        # renseignés via « Répartir le solde restant » (ou payés à l'inscription)
        # comptent. Un mois sans échéance existante s'affiche donc « non
        # configuré » plutôt que de retomber sur une mensualité générique.
        if enr.student.is_boursier:
            return None
        # 1. Mensualité directement sur l'enrollment (défini lors de la validation)
        if enr.monthly_installment:
            return enr.monthly_installment
        # 2. Config par classe
        full = None
        try:
            full = enr.class_group.frais_mensuel_config.frais_mensuel
        except Exception:
            pass
        # 3. Config par niveau
        if full is None:
            try:
                level = enr.class_group.level
                full = FraisGenerauxNiveau.objects.get(level=level).frais_mensuel
            except Exception:
                pass
        return full

    def _get_frais_soutenance(enr, field):
        """
        Retourne le frais de soutenance (normale/spéciale) pour cette inscription :
        valeur propre à l'inscription si définie, sinon celle de la classe
        (FraisMensuelClasse, définie à la création de la classe).
        """
        val = getattr(enr, field, None)
        if val is not None:
            return val
        try:
            return getattr(enr.class_group.frais_mensuel_config, field)
        except Exception:
            return None

    # --- Regrouper les inscriptions par classe : chaque classe n'affiche que
    # ses propres mois à payer (sa répartition d'année académique) ───────────
    class_groups = []
    groups_by_id = {}
    for enr in enrollments_qs:
        cg = enr.class_group
        group = groups_by_id.get(cg.pk)
        if group is None:
            is_l3_m2 = bool(cg.level and cg.level.name in ('Licence 3', 'Master 2'))
            group = {'class_group': cg, 'months_raw': _months_for(cg), 'rows': [], 'is_l3_m2': is_l3_m2}
            groups_by_id[cg.pk] = group
            class_groups.append(group)

        # Index installments par (year, month)
        inst_by_month = {}
        for inst in enr.installments.all():
            key = (inst.due_date.year, inst.due_date.month)
            inst_by_month[key] = inst

        frais = _get_frais_mensuel(enr)

        month_cells = []
        for (y, m) in group['months_raw']:
            inst = inst_by_month.get((y, m))
            # Chaque mois de la répartition de la classe est "à payer" : si
            # aucune échéance n'existe encore pour ce mois, la mensualité par
            # défaut de l'étudiant/classe sert de montant attendu — l'échéance
            # réelle est créée à la volée dès l'enregistrement du paiement
            # (voir mensualite_payer._get_or_create_inst).
            expected = inst.amount_expected if inst else frais
            month_cells.append({
                'year': y,
                'month': m,
                'label': MOIS_FR[m],
                'inst': inst,
                'paid': inst.is_paid if inst else False,
                'amount': inst.amount_paid if inst and inst.is_paid else None,
                'expected': expected,
            })

        group['rows'].append({
            'enrollment': enr,
            'frais_mensuel': frais,
            'month_cells': month_cells,
            'nb_paid': sum(1 for c in month_cells if c['paid']),
            'nb_total': len([c for c in month_cells if c['expected']]),
            'frais_soutenance': _get_frais_soutenance(enr, 'frais_soutenance'),
            'frais_soutenance_speciale': _get_frais_soutenance(enr, 'frais_soutenance_speciale'),
        })

    # Finaliser chaque groupe : mois formatés, frais de classe, totaux
    today_date  = date.today()
    current_key = (today_date.year, today_date.month)
    total_paid, total_unpaid_current, total_students = 0, 0, 0

    for group in class_groups:
        group['months'] = [(y, m, MOIS_FR[m], MOIS_LONG[m]) for y, m in group['months_raw']]

        # Montant mensuel / montant global de la classe (définis à la création
        # de la classe) — affichés en bas de chaque tableau, modifiables ici et
        # automatiquement pris en compte pour tous les étudiants sans
        # dérogation individuelle (via _get_frais_mensuel ci-dessus).
        try:
            _cfg = FraisMensuelClasse.objects.get(class_group=group['class_group'])
            group['class_frais_mensuel']  = _cfg.frais_mensuel
            group['class_montant_global'] = _cfg.montant_global
        except FraisMensuelClasse.DoesNotExist:
            group['class_frais_mensuel']  = None
            group['class_montant_global'] = None

        total_students += len(group['rows'])
        total_paid     += sum(r['nb_paid'] for r in group['rows'])
        total_unpaid_current += sum(
            1 for r in group['rows']
            for c in r['month_cells']
            if (c['year'], c['month']) == current_key and c['expected'] and not c['paid']
        )

    ctx = {
        'years': years,
        'selected_year': selected_year,
        'levels': levels_qs,
        'selected_level': selected_level,
        'classes': classes_qs,
        'selected_class': selected_class,
        'class_groups': class_groups,
        'search': search,
        'today': today_date,
        'total_students': total_students,
        'total_paid': total_paid,
        'total_unpaid_current': total_unpaid_current,
    }
    return render(request, 'accounting/mensualite_list.html', ctx)


@login_required
def mensualite_update_class_fee(request):
    """
    Met à jour la mensualité (et le montant global) d'une classe depuis la page
    Paiement des Mensualités. Modifie la même configuration (FraisMensuelClasse)
    que celle définie à la création de la classe — la nouvelle valeur est donc
    automatiquement prise en compte pour tous les étudiants de la classe qui
    n'ont pas de dérogation individuelle (enrollment.monthly_installment).
    """
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('accounting:mensualite_list')

    from academic_core.apps.academic_structure.models import Class
    from .models import FraisMensuelClasse
    from decimal import InvalidOperation

    def to_decimal(raw):
        try:
            return Decimal(raw) if raw and raw.strip() else None
        except InvalidOperation:
            return None

    class_id = request.POST.get('class_id')
    class_group = get_object_or_404(Class, pk=class_id)

    frais_mensuel  = to_decimal(request.POST.get('frais_mensuel', ''))
    montant_global = to_decimal(request.POST.get('montant_global', ''))

    cfg, _ = FraisMensuelClasse.objects.get_or_create(class_group=class_group)
    if frais_mensuel is not None:
        cfg.frais_mensuel = frais_mensuel
    if montant_global is not None:
        cfg.montant_global = montant_global
    cfg.updated_by = request.user
    cfg.save()

    messages.success(
        request,
        f"Mensualité de « {class_group.name} » mise à jour : {frais_mensuel or '—'} FCFA/mois. "
        f"Automatiquement prise en compte pour tous les étudiants sans mensualité individuelle."
    )

    redirect_url = reverse('accounting:mensualite_list')
    params = [f'classe={class_group.pk}']
    year_id = request.POST.get('year_id', '').strip()
    if year_id:
        params.append(f'year={year_id}')
    redirect_url += '?' + '&'.join(params)
    return redirect(redirect_url)


@login_required
def mensualite_update_soutenance(request, enrollment_pk):
    """
    Modifie directement le frais de soutenance (normale ou spéciale) d'une
    inscription depuis la page Paiement des Mensualités (classes L3/M2
    uniquement). Purement informatif : n'affecte ni le statut de paiement des
    mensualités, ni la validation/invalidation de la carte étudiant.
    """
    if not _require_mensualite_access(request.user):
        from django.http import JsonResponse
        return JsonResponse({'error': 'Accès refusé.'}, status=403)

    from django.http import JsonResponse
    from academic_core.apps.students.models import Enrollment
    from decimal import InvalidOperation

    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    enrollment = get_object_or_404(Enrollment, pk=enrollment_pk)

    field = request.POST.get('field', '')
    if field not in ('frais_soutenance', 'frais_soutenance_speciale'):
        return JsonResponse({'error': 'Champ invalide.'}, status=400)

    raw = request.POST.get('amount', '').strip()
    try:
        amount = Decimal(raw) if raw else None
    except InvalidOperation:
        return JsonResponse({'error': 'Montant invalide.'}, status=400)

    setattr(enrollment, field, amount)
    enrollment.save(update_fields=[field])

    return JsonResponse({'status': 'ok', 'amount': str(amount) if amount is not None else None})


@login_required
def mensualite_payer(request, enrollment_pk):
    """Enregistrer ou annuler le paiement d'un mois pour un étudiant (AJAX POST)."""
    if not _require_mensualite_access(request.user):
        from django.http import JsonResponse
        return JsonResponse({'error': 'Accès refusé.'}, status=403)

    from django.http import JsonResponse
    from academic_core.apps.students.models import Enrollment, PaymentInstallment
    from academic_core.apps.accounting.models import FraisMensuelClasse, FraisGenerauxNiveau

    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)

    enrollment = get_object_or_404(Enrollment, pk=enrollment_pk)

    import datetime, json as _json
    try:
        month_year      = int(request.POST.get('month_year', 0))
        month_num       = int(request.POST.get('month_num', 0))
        action          = request.POST.get('action', 'pay')
        amount_raw      = request.POST.get('amount', '').strip()
        pay_date        = request.POST.get('pay_date', '') or str(date.today())
        notes           = request.POST.get('notes', '').strip()
        moratoire       = request.POST.get('moratoire', '0') == '1'
        moratoire_reste = request.POST.get('moratoire_reste', '0').strip()
        moratoire_dist  = int(request.POST.get('moratoire_distrib', '1'))
        moratoire_months_raw = request.POST.get('moratoire_months', '[]')
        moratoire_months = _json.loads(moratoire_months_raw)   # [{"y":2026,"m":2}, ...]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Données invalides.'}, status=400)

    try:
        paid_date_obj = datetime.date.fromisoformat(pay_date)
    except Exception:
        paid_date_obj = date.today()

    # Montant attendu
    def _get_expected():
        # Boursier : cf. _get_frais_mensuel (mensualite_list) — aucune
        # mensualité générique de repli, uniquement les montants explicitement
        # renseignés via « Répartir le solde restant » (l'interface ne permet
        # d'ailleurs déjà pas d'agir sur un mois boursier non configuré).
        if enrollment.student.is_boursier:
            return Decimal('0')
        if enrollment.monthly_installment:
            return enrollment.monthly_installment
        full = None
        try:
            full = enrollment.class_group.frais_mensuel_config.frais_mensuel
        except Exception:
            pass
        if full is None:
            try:
                full = FraisGenerauxNiveau.objects.get(level=enrollment.class_group.level).frais_mensuel
            except Exception:
                pass
        return full or Decimal('0')

    expected = _get_expected()
    amount   = Decimal(amount_raw) if amount_raw else expected

    # Helper : récupérer ou créer un installment pour un mois donné
    def _get_or_create_inst(y, m, amount_expected_override=None):
        existing = PaymentInstallment.objects.filter(
            enrollment=enrollment,
            due_date__year=y,
            due_date__month=m,
        ).first()
        if existing:
            return existing, False
        cnt = enrollment.installments.count()
        new_inst = PaymentInstallment.objects.create(
            enrollment=enrollment,
            installment_number=cnt + 1,
            due_date=datetime.date(y, m, 5),
            amount_expected=amount_expected_override or expected or Decimal('0'),
        )
        return new_inst, True

    inst, _ = _get_or_create_inst(month_year, month_num)

    # ── Étudiant boursier : le Caissier ne peut qu'encaisser une échéance déjà
    # préparée (montant/infos définis) par le Trésorier Général — il ne peut
    # ni modifier ces informations, ni préparer/annuler lui-même. ─────────────
    is_boursier = enrollment.student.is_boursier
    if is_boursier and request.user.is_caissier():
        if action == 'unpay':
            return JsonResponse({
                'error': "Cet étudiant est boursier : seul le Trésorier Général peut annuler cet encaissement.",
            }, status=403)
        if not inst.prepared_by_id:
            return JsonResponse({
                'error': "Cet étudiant est boursier : cette échéance doit d'abord être préparée par le "
                         "Trésorier Général avant que vous puissiez l'encaisser.",
            }, status=403)
        # Le Caissier valide simplement l'échéance déjà préparée — le montant
        # et les observations restent ceux définis par le Trésorier Général.
        amount = inst.amount_expected
        notes  = inst.notes

    if action == 'prepare':
        # Le Trésorier Général définit le montant/les informations de cette
        # échéance boursier À L'AVANCE, sans encore l'encaisser — le Caissier
        # pourra ensuite seulement valider (payer) ce montant figé.
        if request.user.is_caissier():
            return JsonResponse({
                'error': "Seul le Trésorier Général peut préparer une échéance boursier.",
            }, status=403)
        inst.amount_expected = amount if amount_raw else (expected or inst.amount_expected)
        inst.notes           = notes
        inst.prepared_by     = request.user
        inst.prepared_at     = timezone.now()
        inst.save()
        return JsonResponse({
            'status':  'prepared',
            'amount':  str(inst.amount_expected),
            'message': f"Échéance préparée pour {enrollment.student.user.get_full_name()} — "
                       f"le Caissier peut désormais l'encaisser.",
        })

    if action == 'unpay':
        inst.is_paid     = False
        inst.amount_paid = None
        inst.paid_date   = None
        inst.notes       = ''
        inst.save()
        return JsonResponse({
            'status': 'unpaid',
            'message': f"Paiement annulé pour {enrollment.student.user.get_full_name()}",
        })

    # ── Paiement ──────────────────────────────────────────────────────────────
    inst.is_paid     = True
    inst.amount_paid = amount
    inst.paid_date   = paid_date_obj
    inst.notes       = notes
    if is_boursier and request.user.is_caissier():
        # Validation Caissier d'une échéance boursier déjà préparée : le
        # montant dû ne doit surtout pas être re-synchronisé sur la mensualité
        # par défaut — il reste celui figé par le Trésorier Général.
        pass
    else:
        inst.amount_expected = expected or inst.amount_expected
        if is_boursier:
            # Le Trésorier Général (ou un autre rôle de gestion) définit/prépare
            # l'échéance de cet étudiant boursier.
            inst.prepared_by = request.user
            inst.prepared_at = timezone.now()
    inst.save()

    # Enregistrement CaissePayment
    from academic_core.apps.accounting.models import CaissePayment
    if not CaissePayment.objects.filter(
        student=enrollment.student,
        payment_type=CaissePayment.TYPE_SCOLARITE,
        payment_date=paid_date_obj,
        payment_month=month_num,
        academic_year=enrollment.academic_year,
    ).exists():
        CaissePayment.objects.create(
            student=enrollment.student,
            payment_type=CaissePayment.TYPE_SCOLARITE,
            amount=amount,
            payment_date=paid_date_obj,
            payment_month=month_num,
            academic_year=enrollment.academic_year,
            notes=notes or f"Mensualité {month_num}/{month_year}",
            created_by=request.user,
        )

    # ── Moratoire : répartir le reste sur les mois suivants ───────────────────
    moratoire_applied = False
    if moratoire and moratoire_months:
        try:
            reste = Decimal(moratoire_reste)
        except Exception:
            reste = Decimal('0')

        if reste > 0:
            n       = len(moratoire_months)  # 1 ou 2
            from decimal import ROUND_CEILING
            per_mo  = (reste / n).quantize(Decimal('1'), rounding=ROUND_CEILING)
            for i, nm in enumerate(moratoire_months):
                ny, nm_num = int(nm['y']), int(nm['m'])
                # Montant additionnel à ajouter à la mensualité du mois concerné
                extra = per_mo if i < n - 1 else (reste - per_mo * (n - 1))
                fut_inst, _ = _get_or_create_inst(ny, nm_num)
                # On augmente amount_expected du reste reporté
                fut_inst.amount_expected = (fut_inst.amount_expected or expected or Decimal('0')) + extra
                fut_inst.notes = (fut_inst.notes or '') + f" [Moratoire +{extra} FCFA reporté de {month_num}/{month_year}]"
                fut_inst.save()
            moratoire_applied = True

    student_name = enrollment.student.user.get_full_name()
    msg = f"Mensualité enregistrée pour {student_name}"
    if moratoire_applied:
        msg += f" (moratoire : reste réparti sur {len(moratoire_months)} mois suivant{'s' if len(moratoire_months)>1 else ''})"

    from django.urls import reverse
    receipt_url = reverse('accounting:mensualite_recu_pdf',
                          kwargs={'enrollment_pk': enrollment_pk,
                                  'year': month_year, 'month': month_num})
    return JsonResponse({
        'status': 'paid',
        'amount': str(amount),
        'date': paid_date_obj.strftime('%d/%m/%Y'),
        'message': msg,
        'moratoire_applied': moratoire_applied,
        'receipt_url': receipt_url,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SUIVI DES BOURSIERS — régularisation avec les partenaires (Trésorier Général)
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def boursier_list(request):
    """
    Suivi séparé de tous les étudiants boursiers : montant restant à recouvrer
    auprès du partenaire (part non payée par l'étudiant à l'inscription),
    échéance de régularisation fixée au cas par cas, et statut (en attente /
    régularisé). Réservé au Trésorier Général et aux autres rôles de gestion
    financière (mêmes droits que Mensualités / Validation inscription).
    """
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Enrollment
    from academic_core.apps.academic_structure.models import Class
    from .models import PartenaireBourse
    from django.db.models import Q

    _global_view = request.user.is_controleur() or request.user.is_comptable()
    faculty = None if _global_view else getattr(request, 'active_faculty', None)
    dept    = None if _global_view else getattr(request, 'active_department', None)

    years       = AcademicYear.objects.order_by('-start_date')
    partenaires = PartenaireBourse.objects.order_by('intitule')

    year_id       = request.GET.get('year')
    status_filt   = request.GET.get('status', '')
    partenaire_id = request.GET.get('partenaire', '')
    class_id      = request.GET.get('classe', '')
    search        = request.GET.get('q', '').strip()

    selected_year = None
    if year_id:
        selected_year = years.filter(pk=year_id).first()
    if not selected_year and years.exists():
        selected_year = years.filter(is_current=True).first() or years.first()

    selected_partenaire = partenaires.filter(pk=partenaire_id).first() if partenaire_id else None

    # Classes disponibles pour le filtre — uniquement celles ayant au moins un
    # étudiant boursier, dans le même périmètre département/faculté.
    classes_qs = Class.objects.filter(students__student__is_boursier=True).distinct()
    if dept:
        classes_qs = classes_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)
    classes_qs = classes_qs.order_by('name')
    selected_classe = classes_qs.filter(pk=class_id).first() if class_id else None

    qs = Enrollment.objects.filter(
        student__is_boursier=True,
    ).exclude(status=Enrollment.STATUS_REJECTED).select_related(
        'student__user', 'student__partenaire_bourse',
        'class_group__program__department', 'class_group__level',
        'academic_year', 'bourse_regularized_by',
    )

    if selected_year:
        qs = qs.filter(academic_year=selected_year)
    if dept:
        qs = qs.filter(class_group__program__department=dept)
    elif faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)
    if selected_classe:
        qs = qs.filter(class_group=selected_classe)
    if status_filt == 'attente':
        qs = qs.filter(bourse_regularized=False)
    elif status_filt == 'regularise':
        qs = qs.filter(bourse_regularized=True)
    if selected_partenaire:
        qs = qs.filter(student__partenaire_bourse=selected_partenaire)
    if search:
        qs = qs.filter(
            Q(student__user__first_name__icontains=search) |
            Q(student__user__last_name__icontains=search) |
            Q(student__matricule__icontains=search)
        )

    enrollments = list(qs.order_by(
        'class_group__name', 'bourse_regularized', 'bourse_deadline', 'student__user__last_name',
    ))

    today = date.today()
    nb_attente        = sum(1 for e in enrollments if not e.bourse_regularized)
    nb_regularise     = sum(1 for e in enrollments if e.bourse_regularized)
    nb_en_retard      = sum(
        1 for e in enrollments
        if not e.bourse_regularized and e.bourse_deadline and e.bourse_deadline < today
    )
    total_a_recouvrer = sum(
        (e.bourse_montant_a_recouvrer or Decimal('0')) for e in enrollments if not e.bourse_regularized
    )

    # Regroupement par classe — chaque classe s'affiche en liste déroulante
    # (accordéon) contenant ses propres étudiants boursiers, paginés à 10
    # par page (cf. filterClassTable/paginateClassTable en JS).
    class_groups = []
    groups_by_id = {}
    for enr in enrollments:
        cg = enr.class_group
        key = cg.pk if cg else 0
        group = groups_by_id.get(key)
        if group is None:
            group = {'class_group': cg, 'rows': []}
            groups_by_id[key] = group
            class_groups.append(group)
        group['rows'].append(enr)

    return render(request, 'accounting/boursier_list.html', {
        'enrollments':          enrollments,
        'class_groups':         class_groups,
        'years':                years,
        'selected_year':        selected_year,
        'status_filter':        status_filt,
        'partenaires':          partenaires,
        'selected_partenaire':  selected_partenaire,
        'classes':              classes_qs,
        'selected_classe':      selected_classe,
        'search':               search,
        'today':                today,
        'nb_attente':           nb_attente,
        'nb_regularise':        nb_regularise,
        'nb_en_retard':         nb_en_retard,
        'total_a_recouvrer':    total_a_recouvrer,
    })


@login_required
def boursier_update(request, pk):
    """Fixer l'échéance de régularisation ou marquer/annuler la régularisation
    d'un étudiant boursier auprès de son partenaire."""
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:boursier_list')

    from academic_core.apps.students.models import Enrollment

    enrollment = get_object_or_404(Enrollment, pk=pk, student__is_boursier=True)

    if request.method != 'POST':
        return redirect('accounting:boursier_list')

    action = request.POST.get('action')

    if action == 'set_deadline':
        deadline_raw = request.POST.get('bourse_deadline', '').strip()
        enrollment.bourse_deadline = deadline_raw or None
        enrollment.save(update_fields=['bourse_deadline'])
        messages.success(request, f"Échéance mise à jour pour {enrollment.student.full_name}.")

    elif action == 'regulariser':
        def to_decimal(raw):
            try:
                return Decimal(raw) if raw and raw.strip() else None
            except Exception:
                return None
        enrollment.bourse_regularized        = True
        enrollment.bourse_regularized_date   = request.POST.get('regularized_date') or date.today().isoformat()
        enrollment.bourse_regularized_amount = to_decimal(request.POST.get('regularized_amount', ''))
        enrollment.bourse_regularized_by     = request.user
        enrollment.bourse_regularisation_notes = request.POST.get('notes', '').strip()
        enrollment.save(update_fields=[
            'bourse_regularized', 'bourse_regularized_date', 'bourse_regularized_amount',
            'bourse_regularized_by', 'bourse_regularisation_notes',
        ])
        messages.success(request, f"Régularisation enregistrée pour {enrollment.student.full_name}.")

    elif action == 'supprimer_regularisation':
        # Efface complètement l'historique de régularisation (contrairement à
        # un simple retour à « en attente ») — remet le dossier à zéro.
        enrollment.bourse_regularized          = False
        enrollment.bourse_regularized_date     = None
        enrollment.bourse_regularized_amount   = None
        enrollment.bourse_regularized_by       = None
        enrollment.bourse_regularisation_notes = ''
        enrollment.save(update_fields=[
            'bourse_regularized', 'bourse_regularized_date', 'bourse_regularized_amount',
            'bourse_regularized_by', 'bourse_regularisation_notes',
        ])
        messages.warning(request, f"Régularisation supprimée pour {enrollment.student.full_name} — dossier remis à zéro.")

    return redirect('accounting:boursier_list')


@login_required
def boursier_attestation_pdf(request, pk):
    """Attestation de régularisation (ou de situation) d'un étudiant boursier — PDF."""
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:boursier_list')

    from academic_core.apps.students.models import Enrollment
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from academic_core.pdf_utils import get_institut_config_for_request, logo_image

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'student__partenaire_bourse', 'class_group', 'academic_year', 'bourse_regularized_by',
        ),
        pk=pk, student__is_boursier=True,
    )

    inst_config = get_institut_config_for_request(request)
    school_name = (inst_config.nom if inst_config and inst_config.nom else 'GROUPE ISI')

    navy = colors.HexColor('#1e3a5f')
    purple = colors.HexColor('#6d28d9')
    h_style = ParagraphStyle('H', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, spaceAfter=4)
    norm_style = ParagraphStyle('N', fontSize=10, fontName='Helvetica', leading=15)
    right_style = ParagraphStyle('R', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.5*cm, rightMargin=2.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    story = []

    logo = logo_image(config=inst_config, width=2.2*cm, height=1.4*cm)
    hdr = Table([[
        logo or Paragraph('ISI', h_style),
        Paragraph(f'<b>{school_name.upper()}</b><br/><font size="10">ATTESTATION DE RÉGULARISATION — ÉTUDIANT BOURSIER</font>',
                  ParagraphStyle('hj', fontSize=13, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER, leading=18)),
        Paragraph('', h_style),
    ]], colWidths=[3*cm, 11*cm, 3*cm])
    hdr.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story.append(hdr)
    story.append(HRFlowable(width='100%', thickness=2, color=navy))
    story.append(Spacer(1, 0.6*cm))

    rows = [
        ['Étudiant', enrollment.student.full_name],
        ['Matricule', enrollment.student.matricule or '—'],
        ['Classe', str(enrollment.class_group) if enrollment.class_group else '—'],
        ['Année académique', str(enrollment.academic_year) if enrollment.academic_year else '—'],
        ['Partenaire de bourse', enrollment.student.partenaire_bourse.intitule if enrollment.student.partenaire_bourse else '—'],
        ['Pourcentage à la charge de l\'étudiant', f"{enrollment.bourse_pourcentage:.0f} %" if enrollment.bourse_pourcentage is not None else '—'],
        ['Montant global de la formation', f"{enrollment.total_fees:,.0f} FCFA" if enrollment.total_fees else '—'],
        ['Montant à payer par l\'étudiant', f"{enrollment.bourse_montant_etudiant:,.0f} FCFA" if enrollment.bourse_montant_etudiant is not None else '—'],
        ['Montant à recouvrer auprès du partenaire', f"{enrollment.bourse_montant_a_recouvrer:,.0f} FCFA" if enrollment.bourse_montant_a_recouvrer is not None else '—'],
        ['Échéance de régularisation', enrollment.bourse_deadline.strftime('%d/%m/%Y') if enrollment.bourse_deadline else 'Non définie'],
        ['Statut', 'Régularisé' if enrollment.bourse_regularized else 'En attente de régularisation'],
    ]
    if enrollment.bourse_regularized:
        rows += [
            ['Montant régularisé', f"{enrollment.bourse_regularized_amount:,.0f} FCFA" if enrollment.bourse_regularized_amount is not None else '—'],
            ['Date de régularisation', enrollment.bourse_regularized_date.strftime('%d/%m/%Y') if enrollment.bourse_regularized_date else '—'],
            ['Régularisé par', enrollment.bourse_regularized_by.get_full_name() if enrollment.bourse_regularized_by else '—'],
            ['Observations', enrollment.bourse_regularisation_notes or '—'],
        ]

    t = Table(rows, colWidths=[8*cm, 8*cm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), navy),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 1.2*cm))
    story.append(Paragraph(f"Établi par : {request.user.get_full_name() or request.user.username}", right_style))
    story.append(Paragraph(f"Le {date.today().strftime('%d/%m/%Y')}", right_style))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="attestation_boursier_{enrollment.student.matricule or enrollment.pk}.pdf"'
    return response


@login_required
def boursier_attestation_word(request, pk):
    """Attestation de régularisation (ou de situation) d'un étudiant boursier — Word."""
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('accounting:boursier_list')

    from academic_core.apps.students.models import Enrollment
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            'student__user', 'student__partenaire_bourse', 'class_group', 'academic_year', 'bourse_regularized_by',
        ),
        pk=pk, student__is_boursier=True,
    )

    def set_cell_bg(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color)
        shd.set(qn('w:val'), 'clear')
        tcPr.append(shd)

    doc = Document()
    section = doc.sections[0]
    section.left_margin = Cm(2.5); section.right_margin = Cm(2.5)
    section.top_margin = Cm(2); section.bottom_margin = Cm(2)

    title = doc.add_heading('', level=0)
    run = title.add_run("ATTESTATION DE RÉGULARISATION — ÉTUDIANT BOURSIER")
    run.font.color.rgb = RGBColor(0, 23, 59)
    run.font.size = Pt(14)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    rows = [
        ('Étudiant', enrollment.student.full_name),
        ('Matricule', enrollment.student.matricule or '—'),
        ('Classe', str(enrollment.class_group) if enrollment.class_group else '—'),
        ('Année académique', str(enrollment.academic_year) if enrollment.academic_year else '—'),
        ('Partenaire de bourse', enrollment.student.partenaire_bourse.intitule if enrollment.student.partenaire_bourse else '—'),
        ("Pourcentage à la charge de l'étudiant", f"{enrollment.bourse_pourcentage:.0f} %" if enrollment.bourse_pourcentage is not None else '—'),
        ('Montant global de la formation', f"{enrollment.total_fees:,.0f} FCFA" if enrollment.total_fees else '—'),
        ("Montant à payer par l'étudiant", f"{enrollment.bourse_montant_etudiant:,.0f} FCFA" if enrollment.bourse_montant_etudiant is not None else '—'),
        ('Montant à recouvrer auprès du partenaire', f"{enrollment.bourse_montant_a_recouvrer:,.0f} FCFA" if enrollment.bourse_montant_a_recouvrer is not None else '—'),
        ('Échéance de régularisation', enrollment.bourse_deadline.strftime('%d/%m/%Y') if enrollment.bourse_deadline else 'Non définie'),
        ('Statut', 'Régularisé' if enrollment.bourse_regularized else 'En attente de régularisation'),
    ]
    if enrollment.bourse_regularized:
        rows += [
            ('Montant régularisé', f"{enrollment.bourse_regularized_amount:,.0f} FCFA" if enrollment.bourse_regularized_amount is not None else '—'),
            ('Date de régularisation', enrollment.bourse_regularized_date.strftime('%d/%m/%Y') if enrollment.bourse_regularized_date else '—'),
            ('Régularisé par', enrollment.bourse_regularized_by.get_full_name() if enrollment.bourse_regularized_by else '—'),
            ('Observations', enrollment.bourse_regularisation_notes or '—'),
        ]

    tbl = doc.add_table(rows=0, cols=2)
    tbl.style = 'Table Grid'
    for label, val in rows:
        row_cells = tbl.add_row().cells
        set_cell_bg(row_cells[0], '1E3A5F')
        rn = row_cells[0].paragraphs[0].add_run(label)
        rn.font.bold = True
        rn.font.color.rgb = RGBColor(255, 255, 255)
        row_cells[1].text = val

    doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run(f"Établi par : {request.user.get_full_name() or request.user.username}")
    r.font.size = Pt(9)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p2 = doc.add_paragraph()
    r2 = p2.add_run(f"Le {date.today().strftime('%d/%m/%Y')}")
    r2.font.size = Pt(9)
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="attestation_boursier_{enrollment.student.matricule or enrollment.pk}.docx"'
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# TAUX DE RECOUVREMENT — par classe & global département
# ═══════════════════════════════════════════════════════════════════════════════

_MOIS_FR_RECOUV   = ['', 'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
                      'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc']
_MOIS_LONG_RECOUV = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                     'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def _recouv_month_schedule(class_group, academic_year):
    """[(y, m), ...] pour une classe/année, selon sa répartition d'année
    académique (AcademicYearDistribution) — mêmes mois que sur « Paiement des
    Mensualités »."""
    from .models import AcademicYearDistribution
    try:
        distrib = AcademicYearDistribution.objects.get(
            academic_year=academic_year, class_group=class_group)
        start_m, nb = distrib.start_month, distrib.nb_months
    except AcademicYearDistribution.DoesNotExist:
        start_m, nb = 9, 10  # Défaut : sept → juin (10 mois)

    start_year = academic_year.start_date.year if academic_year.start_date else date.today().year
    result = []
    for i in range(nb):
        m = ((start_m - 1 + i) % 12) + 1
        y = start_year + ((start_m - 1 + i) // 12)
        result.append((y, m))
    return result


def _recouv_frais_mensuel(enr):
    """Mensualité effective d'une inscription : celle de l'enrollment, sinon
    celle de la classe, sinon celle du niveau."""
    from .models import FraisGenerauxNiveau
    if enr.monthly_installment:
        return enr.monthly_installment
    try:
        fm = enr.class_group.frais_mensuel_config.frais_mensuel
        if fm is not None:
            return fm
    except Exception:
        pass
    try:
        cfg = FraisGenerauxNiveau.objects.get(level=enr.class_group.level)
        return cfg.frais_mensuel
    except Exception:
        pass
    return Decimal('0')


def _class_recouvrement(class_group, academic_year, today):
    """
    Calcule le taux de recouvrement d'une classe pour une année académique :
    pour chaque mois de sa répartition (jusqu'à aujourd'hui), montant attendu
    (somme des mensualités des étudiants actifs) vs montant réellement
    encaissé (PaymentInstallment.is_paid), et le taux (%) correspondant.
    """
    from academic_core.apps.students.models import Enrollment

    enrollments = list(Enrollment.objects.filter(
        class_group=class_group, academic_year=academic_year,
        status=Enrollment.STATUS_VALIDATED,
    ).select_related(
        'class_group__level', 'class_group__frais_mensuel_config', 'student__user',
    ).prefetch_related('installments').order_by('student__user__last_name', 'student__user__first_name'))

    nb_students = len(enrollments)
    schedule = _recouv_month_schedule(class_group, academic_year)

    per_enr_fee = {}
    per_enr_insts = {}
    for enr in enrollments:
        per_enr_fee[enr.pk] = _recouv_frais_mensuel(enr)
        per_enr_insts[enr.pk] = {
            (i.due_date.year, i.due_date.month): i for i in enr.installments.all()
        }
    total_monthly_attendu = sum(per_enr_fee.values(), Decimal('0'))

    months_data = []
    total_attendu  = Decimal('0')
    total_encaisse = Decimal('0')

    for (y, m) in schedule:
        is_future = date(y, m, 1) > today
        encaisse = Decimal('0')
        student_rows = []
        for enr in enrollments:
            inst = per_enr_insts[enr.pk].get((y, m))
            is_paid = bool(inst and inst.is_paid)
            fee = per_enr_fee[enr.pk]
            if is_paid:
                encaisse += inst.amount_paid or fee
            student_rows.append({
                'student':  enr.student,
                'attendu':  fee,
                'encaisse': (inst.amount_paid or fee) if is_paid else Decimal('0'),
                'is_paid':  is_paid,
            })

        taux = float(encaisse / total_monthly_attendu * 100) if total_monthly_attendu > 0 else None
        months_data.append({
            'year': y, 'month': m,
            'label': _MOIS_FR_RECOUV[m], 'label_long': _MOIS_LONG_RECOUV[m],
            'attendu': total_monthly_attendu, 'encaisse': encaisse,
            'taux': taux, 'is_future': is_future,
            'students': student_rows,
        })
        if not is_future:
            total_attendu  += total_monthly_attendu
            total_encaisse += encaisse

    taux_global = float(total_encaisse / total_attendu * 100) if total_attendu > 0 else None

    return {
        'months':         months_data,
        'total_attendu':  total_attendu,
        'total_encaisse': total_encaisse,
        'taux_global':    taux_global,
        'nb_students':    nb_students,
    }


@login_required
def taux_recouvrement(request):
    """
    Taux de recouvrement des mensualités de scolarité :
      - Onglet « Par classe » : détail mois par mois pour une classe donnée.
      - Onglet « Global département » : agrégat sur toutes les classes du
        département (ou de la faculté/institut pour les rôles globaux).
    """
    if not _require_mensualite_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Class

    today = date.today()
    _global_view = request.user.is_controleur() or request.user.is_comptable()
    faculty  = None if _global_view else getattr(request, 'active_faculty', None)
    dept_req = None if _global_view else getattr(request, 'active_department', None)

    years = AcademicYear.objects.order_by('-start_date')
    if faculty and not request.user.is_super_admin():
        fy = years.filter(faculty=faculty)
        years = fy if fy.exists() else years

    year_id = request.GET.get('year')
    selected_year = None
    if year_id:
        try:
            selected_year = years.get(pk=year_id)
        except AcademicYear.DoesNotExist:
            pass
    if not selected_year and years.exists():
        selected_year = years.filter(is_current=True).first() or years.first()

    # ── Départements disponibles (onglet « Global département ») ───────────
    departments_qs = Department.objects.order_by('name')
    if faculty:
        departments_qs = departments_qs.filter(faculty=faculty)

    dept_id = request.GET.get('departement')
    selected_dept = dept_req
    if dept_id:
        try:
            selected_dept = departments_qs.get(pk=dept_id)
        except Department.DoesNotExist:
            pass
    if not selected_dept and not dept_req:
        # Par défaut, privilégier un département qui a effectivement des
        # classes pour l'année sélectionnée (sinon le premier alphabétique).
        candidates = departments_qs
        if selected_year:
            candidates = departments_qs.filter(programs__classes__academic_year=selected_year).distinct()
        selected_dept = candidates.first() or departments_qs.first()

    # ── Classes disponibles (onglet « Par classe ») ─────────────────────────
    classes_qs = Class.objects.select_related('level', 'program__department').order_by('name')
    if dept_req:
        classes_qs = classes_qs.filter(program__department=dept_req)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)
    if selected_year:
        classes_qs = classes_qs.filter(academic_year=selected_year)

    class_id = request.GET.get('classe')
    selected_class = None
    if class_id:
        try:
            selected_class = classes_qs.get(pk=class_id)
        except Class.DoesNotExist:
            pass
    if not selected_class and classes_qs.exists():
        selected_class = classes_qs.first()

    # ── Onglet 1 : par classe ────────────────────────────────────────────────
    class_recouvrement = None
    if selected_class and selected_year:
        class_recouvrement = _class_recouvrement(selected_class, selected_year, today)

    # ── Onglet 2 : global département ────────────────────────────────────────
    dept_classes_qs = Class.objects.select_related('level', 'program__department').order_by('name')
    if selected_dept:
        dept_classes_qs = dept_classes_qs.filter(program__department=selected_dept)
    elif faculty:
        dept_classes_qs = dept_classes_qs.filter(program__department__faculty=faculty)
    if selected_year:
        dept_classes_qs = dept_classes_qs.filter(academic_year=selected_year)

    dept_rows = []
    dept_total_attendu  = Decimal('0')
    dept_total_encaisse = Decimal('0')
    if selected_year:
        for cg in dept_classes_qs:
            data = _class_recouvrement(cg, selected_year, today)
            dept_rows.append({'class_group': cg, **data})
            dept_total_attendu  += data['total_attendu']
            dept_total_encaisse += data['total_encaisse']
    dept_taux_global = (
        float(dept_total_encaisse / dept_total_attendu * 100) if dept_total_attendu > 0 else None
    )

    return render(request, 'accounting/taux_recouvrement.html', {
        'years':                years,
        'selected_year':        selected_year,
        'classes':              classes_qs,
        'selected_class':       selected_class,
        'class_recouvrement':   class_recouvrement,
        'departments':          departments_qs,
        'selected_dept':        selected_dept,
        'dept_rows':            dept_rows,
        'dept_total_attendu':   dept_total_attendu,
        'dept_total_encaisse':  dept_total_encaisse,
        'dept_taux_global':     dept_taux_global,
        'today':                today,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Liste des étudiants — Direction Financière
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def financial_student_list(request):
    """
    Vue : liste des étudiants par année académique et classe.
    Accessible à tous les profils ayant accès aux onglets Inscriptions ou Direction Financière.
    Actions suspension/abandon réservées au trésorier.
    """
    user = request.user
    allowed = (
        user.is_comptable()
        or user.is_admin()
        or user.is_inst_admin()
        or user.is_admin_direction()
        or getattr(user, 'role_name', None) in ('CONTROLEUR', 'RESPONSABLE', 'ASSISTANTE', 'CIAQ')
    )
    if not allowed:
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

    from academic_core.apps.students.models import Student, Enrollment
    from academic_core.apps.academic_structure.models import Class
    from django.db.models import OuterRef, Subquery, Count

    faculty = getattr(request, 'active_faculty', None)
    dept    = getattr(request, 'active_department', None)

    all_years = AcademicYear.objects.order_by('-start_date')
    fac_for_years = faculty or (dept.faculty if dept else None)
    if fac_for_years:
        all_years = all_years.filter(faculty=fac_for_years)

    selected_year_id = request.GET.get('year_id')
    selected_year = None
    class_groups = []

    # Année académique : par défaut l'année en cours — les étudiants d'une
    # année précédente ne doivent pas apparaître par défaut.
    if selected_year_id:
        selected_year = AcademicYear.objects.filter(pk=selected_year_id).first()
    else:
        selected_year = all_years.filter(is_current=True).first()

    if selected_year:
        classes_qs = Class.objects.filter(
            academic_year=selected_year
        ).select_related('program__department', 'level').order_by('level__order', 'name')

        if dept:
            classes_qs = classes_qs.filter(program__department=dept)
        elif faculty:
            classes_qs = classes_qs.filter(program__department__faculty=faculty)

        STATUS_LABELS = {
            Enrollment.STATUS_VALIDATED: ('Actif',     'success'),
            Enrollment.STATUS_SUSPENDED: ('Suspendu',  'warning'),
            Enrollment.STATUS_ABANDONED: ('Abandon',   'danger'),
            Enrollment.STATUS_PENDING:   ('En attente','secondary'),
        }

        for cls in classes_qs:
            enrollments = (
                Enrollment.objects
                .filter(class_group=cls, academic_year=selected_year)
                .select_related('student__user')
                .order_by('student__user__last_name', 'student__user__first_name')
            )
            rows = []
            for enr in enrollments:
                status_label, status_color = STATUS_LABELS.get(enr.status, (enr.status, 'secondary'))
                rows.append({
                    'enrollment': enr,
                    'student':    enr.student,
                    'status_label': status_label,
                    'status_color': status_color,
                })
            class_groups.append({
                'cls':   cls,
                'rows':  rows,
                'total': len(rows),
                'actifs':   sum(1 for r in rows if r['enrollment'].status == Enrollment.STATUS_VALIDATED),
                'suspendus': sum(1 for r in rows if r['enrollment'].status == Enrollment.STATUS_SUSPENDED),
                'abandons':  sum(1 for r in rows if r['enrollment'].status == Enrollment.STATUS_ABANDONED),
            })

    return render(request, 'accounting/financial_student_list.html', {
        'all_years':     all_years,
        'selected_year': selected_year,
        'class_groups':  class_groups,
    })


@login_required
def financial_student_list_pdf(request):
    """Exporte en PDF la liste des étudiants d'une classe (vue financière)."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from academic_core.apps.students.models import Enrollment
    from academic_core.apps.academic_structure.models import Class
    from academic_core.pdf_utils import logo_image as _logo_fn, get_institut_config_for_request as _gcfr

    class_pk = request.GET.get('class_pk')
    year_id  = request.GET.get('year_id')
    if not class_pk or not year_id:
        messages.error(request, "Classe et année académique requises.")
        return redirect('accounting:financial_student_list')

    cls       = get_object_or_404(Class.objects.select_related('program__department', 'level'), pk=class_pk)
    acad_year = get_object_or_404(AcademicYear, pk=year_id)
    enrollments = (
        Enrollment.objects
        .filter(class_group=cls, academic_year=acad_year)
        .select_related('student__user')
        .order_by('student__user__last_name', 'student__user__first_name')
    )

    STATUS_LABELS = {
        Enrollment.STATUS_VALIDATED: 'Actif',
        Enrollment.STATUS_SUSPENDED: 'Suspendu',
        Enrollment.STATUS_ABANDONED: 'Abandon',
        Enrollment.STATUS_PENDING:   'En attente',
    }

    inst_config = _gcfr(request)
    nom_inst    = getattr(inst_config, 'nom', None) or "Institut Supérieur d'Informatique"
    navy        = rl_colors.HexColor('#00173B')
    grey        = rl_colors.HexColor('#64748B')
    light_bg    = rl_colors.HexColor('#EFF6FF')
    stripe      = rl_colors.HexColor('#F8FAFC')

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                               rightMargin=1.5*cm, leftMargin=1.5*cm,
                               topMargin=1.2*cm, bottomMargin=1.2*cm)

    ss = getSampleStyleSheet()
    s_title   = ParagraphStyle('title',  parent=ss['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=navy, alignment=TA_CENTER)
    s_sub     = ParagraphStyle('sub',    parent=ss['Normal'], fontSize=9,  textColor=grey,            alignment=TA_CENTER)
    s_head    = ParagraphStyle('thead',  parent=ss['Normal'], fontSize=9,  fontName='Helvetica-Bold', textColor=rl_colors.white, alignment=TA_CENTER)
    s_cell    = ParagraphStyle('tcell',  parent=ss['Normal'], fontSize=9)
    s_cell_c  = ParagraphStyle('tcellc', parent=ss['Normal'], fontSize=9,  alignment=TA_CENTER)

    logo = _logo_fn(config=inst_config, width=2*cm, height=2*cm)

    elems = []
    # En-tête
    header_data = [[
        logo or Paragraph('', s_title),
        Paragraph(f"{nom_inst}<br/><font size='9' color='#64748B'>Liste des étudiants — {cls.name}</font>", s_title),
        Paragraph(f"<font size='8' color='#64748B'>Année académique</font><br/><font size='11' color='#00173B'><b>{acad_year.label}</b></font>",
                  ParagraphStyle('yr', parent=ss['Normal'], alignment=TA_RIGHT, leading=14)),
    ]]
    header_tbl = Table(header_data, colWidths=[3*cm, None, 5*cm])
    header_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,-1), light_bg),
        ('BOX', (0,0), (-1,-1), 1, rl_colors.HexColor('#CBD5E1')),
        ('ROUNDEDCORNERS', [6]),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
    ]))
    elems.append(header_tbl)
    elems.append(Spacer(1, 0.4*cm))

    # Tableau étudiants
    col_headers = ['N°', 'Matricule', 'Nom complet', 'Email', 'Statut']
    col_widths  = [1*cm, 4*cm, 7*cm, 8*cm, 3*cm]
    data = [[Paragraph(h, s_head) for h in col_headers]]
    for i, enr in enumerate(enrollments, 1):
        st = enr.student
        data.append([
            Paragraph(str(i), s_cell_c),
            Paragraph(st.matricule or '—', s_cell),
            Paragraph(st.user.get_full_name(), s_cell),
            Paragraph(st.user.email or '—', s_cell),
            Paragraph(STATUS_LABELS.get(enr.status, enr.status), s_cell_c),
        ])

    tbl_style = TableStyle([
        ('BACKGROUND',   (0,0), (-1,0), navy),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [rl_colors.white, stripe]),
        ('GRID',         (0,0), (-1,-1), 0.4, rl_colors.HexColor('#E2E8F0')),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',   (0,0), (-1,-1), 6),
        ('BOTTOMPADDING',(0,0), (-1,-1), 6),
        ('LEFTPADDING',  (0,0), (-1,-1), 8),
    ])
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(tbl_style)
    elems.append(tbl)
    elems.append(Spacer(1, 0.4*cm))

    # Pied de page : total
    total_actifs = sum(1 for e in enrollments if e.status == Enrollment.STATUS_VALIDATED)
    elems.append(Paragraph(
        f"Total : {enrollments.count()} étudiant(s)  |  Actifs : {total_actifs}  |  "
        f"Généré le {date.today().strftime('%d/%m/%Y')}",
        ParagraphStyle('foot', parent=ss['Normal'], fontSize=8, textColor=grey, alignment=TA_RIGHT)
    ))
    from academic_core.pdf_utils import watermark_canvas
    doc.build(elems, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    fname = f"liste_{cls.name.replace(' ', '_')}_{acad_year.label}.pdf"
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


@login_required
def financial_student_list_word(request):
    """Exporte en Word la liste des étudiants d'une classe (vue financière)."""
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from academic_core.apps.students.models import Enrollment
    from academic_core.apps.academic_structure.models import Class

    class_pk = request.GET.get('class_pk')
    year_id  = request.GET.get('year_id')
    if not class_pk or not year_id:
        messages.error(request, "Classe et année académique requises.")
        return redirect('accounting:financial_student_list')

    cls       = get_object_or_404(Class.objects.select_related('program__department', 'level'), pk=class_pk)
    acad_year = get_object_or_404(AcademicYear, pk=year_id)
    enrollments = (
        Enrollment.objects
        .filter(class_group=cls, academic_year=acad_year)
        .select_related('student__user')
        .order_by('student__user__last_name', 'student__user__first_name')
    )

    STATUS_LABELS = {
        Enrollment.STATUS_VALIDATED: 'Actif',
        Enrollment.STATUS_SUSPENDED: 'Suspendu',
        Enrollment.STATUS_ABANDONED: 'Abandon',
        Enrollment.STATUS_PENDING:   'En attente',
    }

    def set_cell_bg(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color)
        shd.set(qn('w:val'), 'clear')
        tcPr.append(shd)

    doc = Document()
    sec = doc.sections[0]
    sec.page_width  = Inches(11.69)
    sec.page_height = Inches(8.27)
    sec.left_margin = sec.right_margin = Cm(2)
    sec.top_margin  = sec.bottom_margin = Cm(1.5)

    # Titre
    h = doc.add_heading('', level=1)
    r = h.add_run(f"Liste des étudiants — {cls.name}")
    r.font.color.rgb = RGBColor(0, 23, 59)
    r.font.size = Pt(14)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph()
    rs = sub.add_run(f"Année académique : {acad_year.label}  |  Généré le {date.today().strftime('%d/%m/%Y')}")
    rs.font.size = Pt(9)
    rs.font.color.rgb = RGBColor(100, 116, 139)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # Tableau
    headers = ['N°', 'Matricule', 'Nom complet', 'Email', 'Statut']
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.style = 'Table Grid'
    hdr_row = tbl.rows[0]
    for i, h_txt in enumerate(headers):
        cell = hdr_row.cells[i]
        set_cell_bg(cell, '00173B')
        p = cell.paragraphs[0]
        run = p.add_run(h_txt)
        run.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)
        run.font.size = Pt(9)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for i, enr in enumerate(enrollments, 1):
        st  = enr.student
        row = tbl.add_row()
        bg  = 'FFFFFF' if i % 2 else 'F8FAFC'
        vals = [str(i), st.matricule or '—', st.user.get_full_name(),
                st.user.email or '—', STATUS_LABELS.get(enr.status, enr.status)]
        for j, val in enumerate(vals):
            cell = row.cells[j]
            set_cell_bg(cell, bg)
            p = cell.paragraphs[0]
            run = p.add_run(val)
            run.font.size = Pt(9)
            if j in (0, 4):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Total
    doc.add_paragraph()
    total_p = doc.add_paragraph()
    tr = total_p.add_run(
        f"Total : {enrollments.count()} étudiant(s)  |  "
        f"Actifs : {sum(1 for e in enrollments if e.status == Enrollment.STATUS_VALIDATED)}"
    )
    tr.font.size = Pt(9)
    tr.bold = True
    tr.font.color.rgb = RGBColor(0, 23, 59)
    total_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    from academic_core.pdf_utils import add_docx_watermark
    add_docx_watermark(doc)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    fname = f"liste_{cls.name.replace(' ', '_')}_{acad_year.label}.docx"
    response = HttpResponse(buf, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


# ─── Vue : Liste attestations de passage par classe ──────────────────────────

@login_required
def attestation_passage_list(request):
    """
    Affiche par classe les étudiants éligibles à l'attestation de passage.
    Éligible = inscription TYPE_REINSCRIPTION + STATUS_VALIDATED + mensualités soldées.
    Accessible à tous sauf trésorier général.
    """
    from academic_core.apps.students.models import Enrollment, Student
    from academic_core.apps.academic_structure.models import Class, AcademicYear
    from decimal import Decimal

    user = request.user

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    # Années académiques disponibles — par défaut l'année en cours.
    all_years = AcademicYear.objects.order_by('-start_date')
    fac_for_years = faculty or (dept.faculty if dept else None)
    all_years = all_years.filter(faculty=fac_for_years) if fac_for_years else all_years
    year_id   = request.GET.get('year_id')
    selected_year = None
    if year_id:
        selected_year = all_years.filter(pk=year_id).first()
    if not selected_year:
        selected_year = all_years.filter(is_current=True).first() or all_years.first()

    # Classes du département/faculty
    classes_qs = Class.objects.select_related('program__department', 'level').order_by('name')
    if dept:
        classes_qs = classes_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)

    # Récupérer les réinscriptions validées de l'année sélectionnée
    reinscriptions = (
        Enrollment.objects
        .filter(
            class_group__in=classes_qs,
            academic_year=selected_year,
            status=Enrollment.STATUS_VALIDATED,
            enrollment_type=Enrollment.TYPE_REINSCRIPTION,
        )
        .select_related(
            'student__user', 'student__current_class',
            'class_group__level', 'previous_class', 'previous_class__level',
        )
        .order_by('class_group__name', 'student__user__last_name')
    )

    # Récupérer l'année précédente pour chercher les mensualités antérieures
    prev_year = all_years.filter(start_date__lt=selected_year.start_date).order_by('-start_date').first() if selected_year else None

    # Pré-charger les inscriptions de l'année précédente pour les étudiants concernés
    student_ids = [enr.student_id for enr in reinscriptions]
    prev_enr_map = {}
    if prev_year and student_ids:
        prev_enrollments = (
            Enrollment.objects
            .filter(student_id__in=student_ids, academic_year=prev_year)
            .prefetch_related('installments')
        )
        for pe in prev_enrollments:
            prev_enr_map[pe.student_id] = pe

    # Grouper par classe et calculer l'éligibilité sur les mensualités de l'année précédente
    from collections import defaultdict
    class_groups = defaultdict(list)
    for enr in reinscriptions:
        prev_enr = prev_enr_map.get(enr.student_id)
        if prev_enr:
            paid       = sum(i.amount for i in prev_enr.installments.all() if i.is_paid)
            total_fees = prev_enr.total_fees or Decimal('0')
            remaining  = max(total_fees - paid, Decimal('0'))
        else:
            remaining = Decimal('0')  # Pas d'inscription précédente trouvée → considéré soldé
        eligible = (remaining == Decimal('0'))

        class_groups[enr.class_group].append({
            'enrollment': enr,
            'student':    enr.student,
            'remaining':  remaining,
            'eligible':   eligible,
        })

    groups = [
        {'class_group': cg, 'rows': rows}
        for cg, rows in sorted(class_groups.items(), key=lambda x: x[0].name)
    ]

    return render(request, 'accounting/attestation_passage_list.html', {
        'all_years':     all_years,
        'selected_year': selected_year,
        'groups':        groups,
    })
