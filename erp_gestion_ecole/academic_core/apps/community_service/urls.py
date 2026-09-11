from django.urls import path
from . import views, report_views

app_name = 'community_service'

urlpatterns = [
    path('', views.ActivityListView.as_view(), name='list'),
    path('nouvelle/', views.ActivityCreateView.as_view(), name='create'),
    path('<int:pk>/modifier/', views.ActivityUpdateView.as_view(), name='edit'),
    path('<int:pk>/supprimer/', views.ActivityDeleteView.as_view(), name='delete'),

    path('rapport/', report_views.activity_report, name='report'),
    path('rapport/export/excel/', report_views.activity_report_export_excel, name='report_export_excel'),
    path('rapport/export/pdf/', report_views.activity_report_export_pdf, name='report_export_pdf'),
    path('rapport/export/word/', report_views.activity_report_export_word, name='report_export_word'),
]
