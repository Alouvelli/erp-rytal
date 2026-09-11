from django.contrib import messages
from django.core.files.base import ContentFile
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import ReportGenerateForm
from .models import Report
from .permissions import coip_responsable_required
from .report_generation import generate_coip_report_excel, generate_coip_report_pdf
from .services import compute_insertion_by_filiere, insertion_filter_choices


@coip_responsable_required
def report_list(request):
    if request.method == 'POST':
        form = ReportGenerateForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.genere_par = request.user
            report.save()
            try:
                if report.format_fichier == Report.FORMAT_PDF:
                    buffer = generate_coip_report_pdf(request, report)
                    filename = f"rapport_coip_{report.pk}.pdf"
                else:
                    buffer = generate_coip_report_excel(report)
                    filename = f"rapport_coip_{report.pk}.xlsx"
                report.fichier.save(filename, ContentFile(buffer.getvalue()), save=False)
                report.status = Report.STATUT_GENERE
                report.generated_at = timezone.now()
                report.save()
                messages.success(request, "Rapport généré avec succès.")
            except Exception:
                report.status = Report.STATUT_ERREUR
                report.save()
                messages.error(request, "Une erreur est survenue lors de la génération du rapport.")
            return redirect('coip:report_list')
        else:
            messages.error(request, "Formulaire invalide.")
    else:
        form = ReportGenerateForm()
    reports = Report.objects.select_related('genere_par').order_by('-created_at')
    return render(request, 'coip/report_list.html', {'form': form, 'reports': reports})


def _insertion_filters(request):
    """Lit et normalise les filtres promotion/année communs à la page et à
    l'export PDF — factorisé pour que les deux restent exactement cohérents."""
    promotion = request.GET.get('promotion', '').strip()
    annee_raw = request.GET.get('annee', '').strip()
    annee = int(annee_raw) if annee_raw.isdigit() else None
    return promotion, annee


@coip_responsable_required
def insertion_report(request):
    """Taux d'insertion professionnelle par filière — vue d'ensemble à
    l'écran, avec filtres par promotion/année d'obtention et export PDF."""
    promotion, annee = _insertion_filters(request)
    data = compute_insertion_by_filiere(promotion=promotion, annee_obtention=annee)
    promotions, annees = insertion_filter_choices()
    return render(request, 'coip/insertion_report.html', {
        'data': data,
        'promotions': promotions,
        'annees': annees,
        'promotion_filtre': promotion,
        'annee_filtre': annee,
    })


@coip_responsable_required
def insertion_report_pdf(request):
    """Export PDF du rapport d'insertion — mêmes filtres/données que la page
    (voir _insertion_filters), un seul tableau donc réutilise simple_list_pdf
    plutôt que de dupliquer la mise en page de generate_coip_report_pdf."""
    from academic_core.pdf_utils import simple_list_pdf

    promotion, annee = _insertion_filters(request)
    data = compute_insertion_by_filiere(promotion=promotion, annee_obtention=annee)

    subtitle_parts = ["Cellule d'Orientation et d'Insertion Professionnelle"]
    if promotion:
        subtitle_parts.append(f"Promotion {promotion}")
    if annee:
        subtitle_parts.append(f"Année d'obtention {annee}")
    subtitle_parts.append(
        f"Taux global : {data['taux_global']} % ({data['total_employed']}/{data['total_alumni']} alumni en activité)"
    )

    rows = [
        [r['filiere_nom'], r['total'], r['employed'], f"{r['taux']} %"]
        for r in data['par_filiere']
    ]

    return simple_list_pdf(
        request,
        title="Rapport d'insertion par filière",
        subtitle=' · '.join(subtitle_parts),
        headers=['Filière', 'Alumni recensés', 'En activité', "Taux d'insertion"],
        rows=rows,
        filename='rapport_insertion_coip.pdf',
        col_widths=None,
        landscape_mode=False,
    )
