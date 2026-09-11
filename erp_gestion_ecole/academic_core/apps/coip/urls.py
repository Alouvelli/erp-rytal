from django.urls import path

from . import (
    views_activities, views_alumni, views_archives, views_dashboard,
    views_internships, views_opportunities, views_orientation,
    views_partnerships, views_recommendations, views_reports, views_visits,
)

app_name = 'coip'

urlpatterns = [
    path('', views_dashboard.index, name='index'),

    # Alumni
    path('alumni/', views_alumni.alumni_list, name='alumni_list'),
    path('alumni/nouveau/', views_alumni.AlumniCreateView.as_view(), name='alumni_create'),
    path('alumni/<int:pk>/', views_alumni.alumni_detail, name='alumni_detail'),
    path('alumni/<int:pk>/modifier/', views_alumni.AlumniUpdateView.as_view(), name='alumni_edit'),
    path('alumni/<int:pk>/supprimer/', views_alumni.AlumniDeleteView.as_view(), name='alumni_delete'),
    path('alumni/<int:pk>/carriere/ajouter/', views_alumni.alumni_career_event_add, name='alumni_career_event_add'),
    path('alumni/<int:pk>/carriere/<int:event_pk>/supprimer/', views_alumni.alumni_career_event_delete, name='alumni_career_event_delete'),

    # Partenaires
    path('partenaires/', views_partnerships.partner_list, name='partner_list'),
    path('partenaires/nouveau/', views_partnerships.PartnerCreateView.as_view(), name='partner_create'),
    path('partenaires/<int:pk>/', views_partnerships.partner_detail, name='partner_detail'),
    path('partenaires/<int:pk>/modifier/', views_partnerships.PartnerUpdateView.as_view(), name='partner_edit'),
    path('partenaires/<int:pk>/supprimer/', views_partnerships.PartnerDeleteView.as_view(), name='partner_delete'),
    path('partenaires/<int:pk>/contacts/ajouter/', views_partnerships.partner_contact_add, name='partner_contact_add'),
    path('partenaires/<int:pk>/contacts/<int:contact_pk>/supprimer/', views_partnerships.partner_contact_delete, name='partner_contact_delete'),

    # Conventions / Partenariats
    path('conventions/', views_partnerships.partnership_list, name='partnership_list'),
    path('conventions/nouvelle/', views_partnerships.PartnershipCreateView.as_view(), name='partnership_create'),
    path('conventions/<int:pk>/', views_partnerships.partnership_detail, name='partnership_detail'),
    path('conventions/<int:pk>/modifier/', views_partnerships.PartnershipUpdateView.as_view(), name='partnership_edit'),
    path('conventions/<int:pk>/supprimer/', views_partnerships.PartnershipDeleteView.as_view(), name='partnership_delete'),
    path('conventions/<int:pk>/historique/ajouter/', views_partnerships.partnership_history_add, name='partnership_history_add'),

    # Offres de stage
    path('offres-stage/', views_internships.offer_list, name='offer_list'),
    path('offres-stage/nouvelle/', views_internships.OfferCreateView.as_view(), name='offer_create'),
    path('offres-stage/<int:pk>/modifier/', views_internships.OfferUpdateView.as_view(), name='offer_edit'),
    path('offres-stage/<int:pk>/supprimer/', views_internships.OfferDeleteView.as_view(), name='offer_delete'),

    # Stages
    path('stages/', views_internships.internship_list, name='internship_list'),
    path('stages/nouveau/', views_internships.InternshipCreateView.as_view(), name='internship_create'),
    path('stages/<int:pk>/modifier/', views_internships.InternshipUpdateView.as_view(), name='internship_edit'),
    path('stages/<int:pk>/supprimer/', views_internships.InternshipDeleteView.as_view(), name='internship_delete'),

    # Orientation
    path('orientation/', views_orientation.orientation_session_list, name='orientation_session_list'),
    path('orientation/nouvelle/', views_orientation.OrientationSessionCreateView.as_view(), name='orientation_session_create'),
    path('orientation/<int:pk>/modifier/', views_orientation.OrientationSessionUpdateView.as_view(), name='orientation_session_edit'),
    path('orientation/<int:pk>/supprimer/', views_orientation.OrientationSessionDeleteView.as_view(), name='orientation_session_delete'),
    path('mes-seances-orientation/', views_orientation.my_orientation_sessions, name='my_orientation_sessions'),

    # Recommandations
    path('recommandations/', views_recommendations.recommendation_list, name='recommendation_list'),
    path('recommandations/<int:pk>/', views_recommendations.recommendation_detail, name='recommendation_detail'),
    path('recommandations/<int:pk>/pdf/generer/', views_recommendations.recommendation_pdf_generate, name='recommendation_pdf_generate'),
    path('mes-recommandations/', views_recommendations.my_recommendations, name='my_recommendations'),

    # Opportunités (staff)
    path('opportunites/', views_opportunities.opportunity_list, name='opportunity_list'),
    path('opportunites/nouvelle/', views_opportunities.OpportunityCreateView.as_view(), name='opportunity_create'),
    path('opportunites/<int:pk>/', views_opportunities.opportunity_detail, name='opportunity_detail'),
    path('opportunites/<int:pk>/modifier/', views_opportunities.OpportunityUpdateView.as_view(), name='opportunity_edit'),
    path('opportunites/<int:pk>/supprimer/', views_opportunities.OpportunityDeleteView.as_view(), name='opportunity_delete'),
    path('candidatures/<int:pk>/statut/', views_opportunities.job_application_update_status, name='job_application_update_status'),

    # Opportunités (étudiant)
    path('mes-opportunites/', views_opportunities.opportunities_browse, name='opportunities_browse'),
    path('mes-opportunites/<int:pk>/postuler/', views_opportunities.opportunity_apply, name='opportunity_apply'),
    path('mes-candidatures/', views_opportunities.my_applications, name='my_applications'),

    # Activités (staff)
    path('activites/', views_activities.activity_list, name='activity_list'),
    path('activites/nouvelle/', views_activities.ActivityCreateView.as_view(), name='activity_create'),
    path('activites/<int:pk>/', views_activities.activity_detail, name='activity_detail'),
    path('activites/<int:pk>/modifier/', views_activities.ActivityUpdateView.as_view(), name='activity_edit'),
    path('activites/<int:pk>/supprimer/', views_activities.ActivityDeleteView.as_view(), name='activity_delete'),
    path('activites/<int:pk>/participants/<int:participant_pk>/presence/', views_activities.activity_participant_toggle_present, name='activity_participant_toggle_present'),
    path('activites/<int:pk>/participants/<int:participant_pk>/retirer/', views_activities.activity_participant_remove, name='activity_participant_remove'),

    # Activités (auto-inscription)
    path('mes-activites/', views_activities.activities_browse, name='activities_browse'),
    path('mes-activites/<int:pk>/inscrire/', views_activities.activity_register, name='activity_register'),
    path('mes-activites/<int:pk>/desinscrire/', views_activities.activity_unregister, name='activity_unregister'),

    # Sorties pédagogiques (staff)
    path('sorties/', views_visits.visit_list, name='visit_list'),
    path('sorties/nouvelle/', views_visits.VisitCreateView.as_view(), name='visit_create'),
    path('sorties/<int:pk>/', views_visits.visit_detail, name='visit_detail'),
    path('sorties/<int:pk>/modifier/', views_visits.VisitUpdateView.as_view(), name='visit_edit'),
    path('sorties/<int:pk>/supprimer/', views_visits.VisitDeleteView.as_view(), name='visit_delete'),
    path('sorties/<int:pk>/participants/<int:participant_pk>/<str:field>/', views_visits.visit_participant_toggle, name='visit_participant_toggle'),
    path('sorties/<int:pk>/participants/<int:participant_pk>/retirer/', views_visits.visit_participant_remove, name='visit_participant_remove'),

    # Sorties pédagogiques (auto-inscription)
    path('mes-sorties/', views_visits.visits_browse, name='visits_browse'),
    path('mes-sorties/<int:pk>/inscrire/', views_visits.visit_register, name='visit_register'),
    path('mes-sorties/<int:pk>/desinscrire/', views_visits.visit_unregister, name='visit_unregister'),

    # Rapports
    path('rapports/', views_reports.report_list, name='report_list'),
    path('rapports/insertion/', views_reports.insertion_report, name='insertion_report'),
    path('rapports/insertion/pdf/', views_reports.insertion_report_pdf, name='insertion_report_pdf'),

    # Archives
    path('archives/', views_archives.archive_list, name='archive_list'),
    path('archives/nouvelle/', views_archives.ArchiveCreateView.as_view(), name='archive_create'),
    path('archives/<int:pk>/', views_archives.archive_detail, name='archive_detail'),
    path('archives/<int:pk>/modifier/', views_archives.ArchiveUpdateView.as_view(), name='archive_edit'),
    path('archives/<int:pk>/supprimer/', views_archives.ArchiveDeleteView.as_view(), name='archive_delete'),
]
