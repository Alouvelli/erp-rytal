"""Calculs partagés entre le tableau de bord COIP (coip:index) et le module
Rapports (génération PDF/Excel) — un seul endroit pour ces agrégations afin
que les deux restent cohérents (contrairement à GestionCOIP où l'Excel
n'affichait que 3 indicateurs contre 6 pour le PDF)."""
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    Activity, Alumni, EducationalVisit, Internship, Opportunity,
    OrientationSession, Partner, Partnership, RecommendationRequest,
)


def get_coip_dashboard_stats():
    today = timezone.localdate()
    alumni_qs = Alumni.objects.all()
    total_alumni = alumni_qs.count()
    employed_alumni = alumni_qs.filter(is_employed=True).count()
    taux_insertion = round((employed_alumni / total_alumni) * 100, 1) if total_alumni else 0.0

    alumni_by_sector = list(
        alumni_qs.exclude(secteur_activite='')
        .values('secteur_activite')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    activities_by_type = list(
        Activity.objects.values('type_activite')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    partners_by_type = list(
        Partner.objects.filter(is_active=True).values('type_partenaire')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    expiring_partnerships = (
        Partnership.objects.filter(
            status=Partnership.STATUT_ACTIVE,
            date_expiration__isnull=False,
            date_expiration__gte=today,
            date_expiration__lte=today + timezone.timedelta(days=30),
        )
        .select_related('partner')
        .order_by('date_expiration')
    )

    return {
        'total_alumni': total_alumni,
        'employed_alumni': employed_alumni,
        'taux_insertion': taux_insertion,
        'alumni_by_sector': alumni_by_sector,
        'activities_by_type': activities_by_type,
        'partners_by_type': partners_by_type,
        'total_partners': Partner.objects.filter(is_active=True).count(),
        'active_partnerships': Partnership.objects.filter(status=Partnership.STATUT_ACTIVE).count(),
        'expiring_partnerships': expiring_partnerships,
        'ongoing_internships': Internship.objects.filter(
            status__in=(Internship.STATUT_CONFIRME, Internship.STATUT_EN_COURS)
        ).count(),
        'open_opportunities': Opportunity.objects.filter(status=Opportunity.STATUT_PUBLIE).count(),
        'pending_recommendations': RecommendationRequest.objects.filter(
            status=RecommendationRequest.STATUT_EN_ATTENTE
        ).count(),
        'upcoming_activities': Activity.objects.filter(
            date_debut__gte=timezone.now(), status=Activity.STATUT_PLANIFIE
        ).order_by('date_debut')[:5],
        'recent_recommendations': RecommendationRequest.objects.select_related('student').order_by('-date_demande')[:5],
        'recent_alumni': alumni_qs.order_by('-created_at')[:5],
    }


def compute_coip_report_kpis(periode_debut, periode_fin):
    """Indicateurs communs au PDF et à l'Excel du module Rapports — même
    contenu dans les deux formats, contrairement à la source portée."""
    orientation_students = OrientationSession.objects.filter(
        date_session__date__gte=periode_debut, date_session__date__lte=periode_fin,
    ).values_list('student_id', flat=True)
    recommendation_students = RecommendationRequest.objects.filter(
        date_demande__date__gte=periode_debut, date_demande__date__lte=periode_fin,
    ).values_list('student_id', flat=True)
    internship_students = Internship.objects.filter(
        date_debut__gte=periode_debut, date_debut__lte=periode_fin,
    ).values_list('student_id', flat=True)
    etudiants_suivis = len(set(orientation_students) | set(recommendation_students) | set(internship_students))

    nouveaux_alumni = Alumni.objects.filter(
        created_at__date__gte=periode_debut, created_at__date__lte=periode_fin,
    ).count()
    partenariats_actifs = Partnership.objects.filter(status=Partnership.STATUT_ACTIVE).count()
    stages_realises = Internship.objects.filter(
        status=Internship.STATUT_TERMINE,
        date_fin__isnull=False, date_fin__gte=periode_debut, date_fin__lte=periode_fin,
    ).count()
    activites_organisees = Activity.objects.filter(
        date_debut__date__gte=periode_debut, date_debut__date__lte=periode_fin,
    ).count()
    recommandations_livrees = RecommendationRequest.objects.filter(
        status=RecommendationRequest.STATUT_LIVREE,
        date_livraison__isnull=False, date_livraison__date__gte=periode_debut, date_livraison__date__lte=periode_fin,
    ).count()
    seances_orientation = OrientationSession.objects.filter(
        date_session__date__gte=periode_debut, date_session__date__lte=periode_fin,
    ).count()

    return {
        'etudiants_suivis': etudiants_suivis,
        'nouveaux_alumni': nouveaux_alumni,
        'partenariats_actifs': partenariats_actifs,
        'stages_realises': stages_realises,
        'activites_organisees': activites_organisees,
        'recommandations_livrees': recommandations_livrees,
        'seances_orientation': seances_orientation,
    }


def compute_insertion_by_filiere(promotion='', annee_obtention=None):
    """Taux d'insertion professionnelle (emploi) par filière, calculé sur les
    Alumni enregistrés. Filtres optionnels : promotion (texte libre saisi sur
    Alumni.promotion) et année d'obtention — permet un rapport ciblé sur une
    cohorte précise plutôt que la totalité des alumni depuis toujours."""
    qs = Alumni.objects.all()
    if promotion:
        qs = qs.filter(promotion=promotion)
    if annee_obtention:
        qs = qs.filter(annee_obtention=annee_obtention)

    rows = (
        qs.values('filiere_id', 'filiere__name')
        .annotate(total=Count('id'), employed=Count('id', filter=Q(is_employed=True)))
        .order_by('filiere__name')
    )

    result = []
    total_general = employed_general = 0
    for r in rows:
        total = r['total']
        employed = r['employed']
        total_general += total
        employed_general += employed
        result.append({
            'filiere_id':   r['filiere_id'],
            'filiere_nom':  r['filiere__name'] or 'Filière non renseignée',
            'total':        total,
            'employed':     employed,
            'taux':         round((employed / total) * 100, 1) if total else 0.0,
        })
    # Trie par taux décroissant (plus lisible qu'un tri alphabétique pour un rapport)
    result.sort(key=lambda r: r['taux'], reverse=True)

    return {
        'par_filiere': result,
        'total_alumni': total_general,
        'total_employed': employed_general,
        'taux_global': round((employed_general / total_general) * 100, 1) if total_general else 0.0,
    }


def insertion_filter_choices():
    """Valeurs distinctes de promotion/année d'obtention déjà saisies sur les
    Alumni — pour peupler les filtres du rapport d'insertion sans lister des
    options qui ne correspondent à aucune donnée réelle."""
    promotions = list(
        Alumni.objects.exclude(promotion='').values_list('promotion', flat=True)
        .distinct().order_by('-promotion')
    )
    annees = list(
        Alumni.objects.exclude(annee_obtention__isnull=True).values_list('annee_obtention', flat=True)
        .distinct().order_by('-annee_obtention')
    )
    return promotions, annees


def compute_coip_annual_activities(periode_debut, periode_fin):
    """Détail complet de TOUTES les activités de la COIP sur une période —
    utilisé par le rapport annuel d'activités (contrairement à
    compute_coip_report_kpis, qui ne donne que des compteurs synthétiques,
    ceci renvoie les listes elles-mêmes pour une restitution exhaustive)."""
    activities = list(
        Activity.objects.filter(
            date_debut__date__gte=periode_debut, date_debut__date__lte=periode_fin,
        ).select_related('responsable').prefetch_related('participants').order_by('date_debut')
    )
    partnerships = list(
        Partnership.objects.filter(
            date_signature__gte=periode_debut, date_signature__lte=periode_fin,
        ).select_related('partner').order_by('date_signature')
    )
    internships = list(
        Internship.objects.filter(
            date_debut__gte=periode_debut, date_debut__lte=periode_fin,
        ).select_related('student', 'partner').order_by('date_debut')
    )
    visits = list(
        EducationalVisit.objects.filter(
            date_depart__date__gte=periode_debut, date_depart__date__lte=periode_fin,
        ).select_related('responsable').order_by('date_depart')
    )
    orientation_sessions = list(
        OrientationSession.objects.filter(
            date_session__date__gte=periode_debut, date_session__date__lte=periode_fin,
        ).select_related('student', 'conseiller').order_by('date_session')
    )
    recommendations = list(
        RecommendationRequest.objects.filter(
            date_demande__date__gte=periode_debut, date_demande__date__lte=periode_fin,
        ).select_related('student').order_by('date_demande')
    )
    opportunities = list(
        Opportunity.objects.filter(
            created_at__date__gte=periode_debut, created_at__date__lte=periode_fin,
        ).select_related('partner', 'filiere_cible').order_by('created_at')
    )

    return {
        'activities': activities,
        'partnerships': partnerships,
        'internships': internships,
        'visits': visits,
        'orientation_sessions': orientation_sessions,
        'recommendations': recommendations,
        'opportunities': opportunities,
    }
