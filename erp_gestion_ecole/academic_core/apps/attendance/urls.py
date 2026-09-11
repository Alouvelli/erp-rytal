from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    path('',                        views.attendance_dashboard,               name='sheet_list'),
    path('<int:pk>/',               views.AttendanceSheetDetailView.as_view(),name='sheet_detail'),
    path('<int:pk>/sign/',          views.sign_attendance_sheet,              name='sign_sheet'),
    path('<int:pk>/validate/',      views.validate_attendance_sheet,          name='validate_sheet'),
    path('<int:pk>/edit/',          views.edit_attendance_sheet,              name='sheet_edit'),
    path('<int:pk>/cahier-texte/',  views.fill_cahier_texte,                  name='fill_cahier_texte'),
    path('<int:pk>/delete/',        views.delete_attendance_sheet,            name='sheet_delete'),
    path('<int:pk>/reject/',        views.reject_attendance_sheet,            name='sheet_reject'),
    path('<int:sheet_pk>/record/',              views.record_student_attendance,      name='record_attendance'),
    path('attendance/<int:att_pk>/update/',     views.update_student_attendance,      name='update_attendance'),
    path('attendance/<int:att_pk>/delete/',     views.delete_student_attendance,      name='delete_attendance'),
    path('mes-absences/',                         views.my_absences,                     name='my_absences'),
    path('mes-absences/<int:att_pk>/justifier/',  views.justify_absence,                  name='justify_absence'),
    path('justifications/',                       views.absence_justifications_admin,    name='absence_justifications_admin'),
    path('justifications/<int:att_pk>/traiter/',  views.absence_justification_review,    name='absence_justification_review'),
    # Demandes de séances supplémentaires
    path('mes-modules/',                        views.my_modules,                      name='my_modules'),
    path('mes-modules/<int:subject_id>/<int:class_group_id>/<int:semester_id>/', views.module_detail, name='module_detail'),
    path('extra-request/create/',              views.extra_request_create,            name='extra_request_create'),
    path('extra-request/mes-demandes/',        views.my_extra_requests,               name='my_extra_requests'),
    path('extra-request/<int:pk>/review/',     views.extra_request_review,            name='extra_request_review'),
    path('extra-request/admin/',               views.extra_requests_admin,            name='extra_requests_admin'),
    # QR code de séance & auto-pointage
    path('<int:pk>/qr-seance/',                views.session_qr_display,              name='session_qr_display'),
    path('<int:pk>/qr-seance/pdf/',            views.session_qr_pdf,                  name='session_qr_pdf'),
    path('checkin/<str:token>/',               views.student_checkin,                 name='student_checkin'),
    path('<int:pk>/absences-seance/',          views.session_absence_list,            name='session_absence_list'),
    path('checkin-auth/<str:token>/',          views.student_authenticated_checkin,   name='student_authenticated_checkin'),
    path('modules-planifies/',                 views.planned_modules_admin,           name='planned_modules_admin'),
    path('modules-planifies/<int:teacher_id>/<int:subject_id>/<int:class_group_id>/<int:semester_id>/',
                                                views.module_detail,                   name='module_detail_admin'),
    path('<int:pk>/export/pdf/',               views.export_sheet_pdf,                name='export_pdf'),
    path('<int:pk>/export/word/',              views.export_sheet_word,               name='export_word'),
    path('alertes/seuil-absences/',            views.absence_alert_config_view,       name='absence_alert_config'),
    path('plan-de-cours/<int:subject_id>/<int:class_group_id>/<int:semester_id>/',
                                                views.course_plan_edit,                name='course_plan_edit'),
    path('plan-de-cours-admin/<int:teacher_id>/<int:subject_id>/<int:class_group_id>/<int:semester_id>/',
                                                views.course_plan_view,                name='course_plan_view'),
]
