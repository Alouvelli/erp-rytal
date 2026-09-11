from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [
    path('', RedirectView.as_view(url='/accounts/login/', permanent=False)),

    # Pas d'interface d'administration Django (/admin/) : toute la gestion de
    # la plateforme passe exclusivement par les rôles applicatifs dédiés
    # (Admin, Admin d'institut, etc. — voir academic_core/apps/accounts),
    # jamais par un accès générique au modèle de données.

    # Authentication
    path('accounts/', include('academic_core.apps.accounts.urls')),

    # Portail public d'admission (candidature en ligne) + espace candidat
    # /admission/... : routes internes (chef de département authentifié).
    # /admission-<code_institut>/... : portail public captif d'un institut
    # donné (catalogue de filières, création de compte, inscription en ligne).
    path('admission/', include('academic_core.apps.admissions.urls')),
    path('admission-<str:institut_code>/', include('academic_core.apps.admissions.portal_urls')),
    path('candidat/', include('academic_core.apps.admissions.candidat_urls')),

    # Main application modules
    path('dashboard/', include('academic_core.apps.dashboard.urls')),
    path('timetable/', include('academic_core.apps.timetable.urls')),
    path('attendance/', include('academic_core.apps.attendance.urls')),
    path('grades/', include('academic_core.apps.grades.urls')),
    path('students/', include('academic_core.apps.students.urls')),
    path('teachers/', include('academic_core.apps.teachers.urls')),
    path('structure/', include('academic_core.apps.academic_structure.urls')),
    path('rooms/', include('academic_core.apps.rooms.urls')),
    path('subjects/', include('academic_core.apps.subjects.urls')),
    path('cancellations/', include('academic_core.apps.cancellations.urls')),
    path('notifications/', include('academic_core.apps.notifications.urls')),
    path('reports/', include('academic_core.apps.reports.urls')),
    path('accounting/', include('academic_core.apps.accounting.urls')),
    path('hr/', include('academic_core.apps.hr.urls')),
    path('service-communaute/', include('academic_core.apps.community_service.urls')),
    path('chatbot/', include('academic_core.apps.chatbot.urls')),
    path('plan-strategique/', include('academic_core.apps.strategic_plan.urls')),
    path('indicateurs/', include('academic_core.apps.indicators.urls')),
    path('achats/', include('academic_core.apps.procurement.urls')),
    path('qualite/', include('academic_core.apps.quality.urls')),
    path('risques/', include('academic_core.apps.risks.urls')),
    path('api-consommation/', include('academic_core.apps.api_gateway.urls')),
    path('coip/', include('academic_core.apps.coip.urls')),

    # REST API
    path('api/v1/', include([
        path('accounts/', include('academic_core.apps.accounts.api_urls')),
        path('timetable/', include('academic_core.apps.timetable.api_urls')),
        path('attendance/', include('academic_core.apps.attendance.api_urls')),
        path('grades/', include('academic_core.apps.grades.api_urls')),
        path('students/', include('academic_core.apps.students.api_urls')),
        path('teachers/', include('academic_core.apps.teachers.api_urls')),
        path('structure/', include('academic_core.apps.academic_structure.api_urls')),
        path('rooms/', include('academic_core.apps.rooms.api_urls')),
        path('subjects/', include('academic_core.apps.subjects.api_urls')),
        path('cancellations/', include('academic_core.apps.cancellations.api_urls')),
        path('notifications/', include('academic_core.apps.notifications.api_urls')),
        path('accounting/', include('academic_core.apps.accounting.api_urls')),
        path('hr/', include('academic_core.apps.hr.api_urls')),
        path('service-communaute/', include('academic_core.apps.community_service.api_urls')),
        path('plan-strategique/', include('academic_core.apps.strategic_plan.api_urls')),
        path('indicateurs/', include('academic_core.apps.indicators.api_urls')),
        path('achats/', include('academic_core.apps.procurement.api_urls')),
        path('qualite/', include('academic_core.apps.quality.api_urls')),
        path('risques/', include('academic_core.apps.risks.api_urls')),
        path('coip/', include('academic_core.apps.coip.api_urls')),
        path('admissions/', include('academic_core.apps.admissions.api_urls')),
    ])),

    # API Schema & Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Page 404 personnalisée (pop-up conviviale) — n'entre en jeu que lorsque
# DEBUG=False ; Django affiche toujours sa page technique de débogage tant
# que DEBUG=True, quel que soit ce handler.
handler404 = 'academic_core.error_views.custom_404_view'
