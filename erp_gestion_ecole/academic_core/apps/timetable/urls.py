from django.urls import path
from . import views
from . import cahier_views
from . import support_views
from . import holiday_views
from . import planning_views

app_name = 'timetable'

urlpatterns = [
    path('',               views.TimetableIndexView.as_view(),  name='index'),
    path('create/',        views.TimetableCreateView.as_view(), name='create'),
    path('<int:pk>/edit/', views.TimetableUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.TimetableDeleteView.as_view(), name='delete'),
    path('api/events/',            views.timetable_events_api,        name='events_api'),
    path('api/available-rooms/',   views.available_rooms_api,         name='available_rooms_api'),
    path('api/subjects-by-semester/', views.subjects_by_semester_api, name='subjects_by_semester_api'),
    path('room-swap/',    views.room_swap_view,                 name='room_swap'),
    # Planning (grille) — export par classe / enseignant / salle
    path('planning/pdf/',   planning_views.planning_pdf,   name='planning_pdf'),
    path('planning/word/',  planning_views.planning_word,  name='planning_word'),
    path('planning/excel/', planning_views.planning_excel, name='planning_excel'),
    path('planning/envoyer-etudiants/',  planning_views.send_class_planning_emails,   name='send_class_planning_emails'),
    path('planning/envoyer-enseignants/', planning_views.send_teacher_planning_emails, name='send_teacher_planning_emails'),
    # Cahier de Texte — enseignant
    path('mes-seances/',                                           cahier_views.mes_seances,       name='mes_seances'),
    path('mes-seances/<int:entry_pk>/<str:session_date_str>/',     cahier_views.session_log_edit,  name='session_log_edit'),
    # Cahier de Texte — admin/responsable
    path('cahier-texte/',                                                  cahier_views.cahier_texte_list,    name='cahier_texte_list'),
    path('cahier-texte/log/create/',                                       cahier_views.cahier_session_create, name='cahier_session_create'),
    path('cahier-texte/log/<int:log_pk>/modifier/',                        cahier_views.cahier_session_edit,   name='cahier_session_edit'),
    path('cahier-texte/log/<int:log_pk>/supprimer/',                       cahier_views.cahier_session_delete, name='cahier_session_delete'),
    path('cahier-texte/log/<int:log_pk>/valider/',                         cahier_views.validate_session_log,   name='validate_session_log'),
    path('cahier-texte/log/<int:log_pk>/devalider/',                      cahier_views.unvalidate_session_log, name='unvalidate_session_log'),
    path('cahier-texte/<int:class_id>/<int:semester_id>/pdf/',             cahier_views.cahier_texte_pdf,      name='cahier_texte_pdf'),
    path('cahier-texte/<int:class_id>/<int:semester_id>/word/',            cahier_views.cahier_texte_word,     name='cahier_texte_word'),
    path('cahier-texte/<int:class_id>/<int:semester_id>/',                 cahier_views.cahier_texte_view,     name='cahier_texte_view'),
    # Suspensions de planning
    path('suspensions/',              holiday_views.holiday_list,   name='holiday_list'),
    path('suspensions/nouvelle/',     holiday_views.holiday_create, name='holiday_create'),
    path('suspensions/<int:pk>/modifier/', holiday_views.holiday_edit,   name='holiday_edit'),
    path('suspensions/<int:pk>/supprimer/', holiday_views.holiday_delete, name='holiday_delete'),
    path('api/teacher-conflicts/',    holiday_views.teacher_conflicts_api, name='teacher_conflicts_api'),
    # Supports de cours
    path('supports/mes-supports/',           support_views.teacher_supports_list,   name='teacher_supports_list'),
    path('supports/partager/',               support_views.teacher_support_upload,  name='teacher_support_upload'),
    path('supports/<int:pk>/supprimer/',     support_views.teacher_support_delete,  name='teacher_support_delete'),
    path('supports/etudiant/',               support_views.student_supports_list,   name='student_supports_list'),
    path('supports/<int:pk>/telecharger/',   support_views.support_download,        name='support_download'),
]
