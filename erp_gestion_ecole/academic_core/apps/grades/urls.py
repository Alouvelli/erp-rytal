from django.urls import path
from . import views
from . import conseil_views
from . import annual_report_views
from . import reclamation_views

app_name = 'grades'

urlpatterns = [
    # ── Evaluations ──────────────────────────────────────────────────────────
    path('',                                    views.EvaluationListView.as_view(),  name='evaluation_list'),
    path('create/',                             views.evaluation_create_view,        name='evaluation_create'),
    path('<int:pk>/entry/',                     views.grade_entry_view,              name='grade_entry'),
    path('<int:pk>/detail/',                    views.evaluation_detail_view,        name='evaluation_detail'),
    path('<int:pk>/template/',                  views.download_grade_template,       name='grade_template'),
    path('<int:pk>/import/',                    views.import_grades,                 name='import_grades'),
    path('<int:pk>/lock/',                      views.lock_evaluation,               name='lock_evaluation'),
    path('<int:pk>/notes-saisies/',             views.mark_grades_entered,           name='mark_grades_entered'),
    path('<int:pk>/delete/',                    views.evaluation_delete_view,        name='evaluation_delete'),
    path('student/',                            views.student_grades_view,           name='student_grades'),
    path('averages/<int:semester_id>/compute/', views.compute_averages,              name='compute_averages'),

    # ── Maquettes (UE/EC) ─────────────────────────────────────────────────────
    path('maquette/list/',                      views.maquette_list,                 name='maquette_list'),
    path('maquette/ue/create/',                 views.maquette_ue_create,            name='maquette_ue_create'),
    path('maquette/ue/<int:pk>/edit/',          views.maquette_ue_edit,              name='maquette_ue_edit'),
    path('maquette/ue/<int:pk>/delete/',        views.maquette_ue_delete,            name='maquette_ue_delete'),
    path('maquette/ue/<int:pk>/subjects/',      views.maquette_assign_subjects,      name='maquette_assign_subjects'),
    path('maquette/dupliquer/',                 views.maquette_duplicate,            name='maquette_duplicate'),

    # ── Import CSV notes ──────────────────────────────────────────────────────
    path('import/notes/',                          views.import_notes_csv,              name='import_notes_csv'),
    path('import/notes/template/',                 views.download_notes_template,       name='download_notes_template'),
    path('import/notes/ecs/',                      views.get_ecs_for_import,            name='get_ecs_for_import'),

    # ── Saisie inline des notes (AJAX) ────────────────────────────────────────
    path('api/grade-inline/',                      views.grade_inline_update,           name='grade_inline_update'),

    # ── Export notes + archive bulletins ──────────────────────────────────────
    path('export/<int:class_id>/semester/<int:semester_id>/excel/', views.export_grades_excel,   name='export_grades_excel'),
    path('bulletins/class/<int:class_id>/semester/<int:semester_id>/archive/', views.archive_bulletins_zip, name='archive_bulletins_zip'),

    # ── Bulletins ─────────────────────────────────────────────────────────────
    path('bulletins/',                                                               views.bulletin_class_list,       name='bulletin_class_list'),
    path('bulletins/class/<int:class_id>/semester/<int:semester_id>/',               views.bulletin_list,             name='bulletin_list'),
    path('bulletins/class/<int:class_id>/semester/<int:semester_id>/generate/',      views.bulletin_generate_class,          name='bulletin_generate_class'),
    path('bulletins/class/<int:class_id>/semester/<int:semester_id>/enrollment/<int:enrollment_id>/toggle/', views.enrollment_toggle_active, name='enrollment_toggle_active'),
    path('bulletins/<int:pk>/',                                                      views.bulletin_detail,           name='bulletin_detail'),
    path('bulletins/<int:pk>/publish/',                                              views.bulletin_publish,          name='bulletin_publish'),
    path('bulletins/class/<int:class_id>/semester/<int:semester_id>/student/<int:student_id>/preview/', views.bulletin_preview, name='bulletin_preview'),
    path('bulletins/class/<int:class_id>/semester/<int:semester_id>/student/<int:student_id>/pdf/',     views.bulletin_pdf,     name='bulletin_pdf'),

    # ── Configuration bulletin ────────────────────────────────────────────────
    path('bulletins/config/',                                                          views.bulletin_config_edit,      name='bulletin_config_edit'),

    # ── Tableau de Conseil ────────────────────────────────────────────────────
    path('conseil/',                                                          conseil_views.conseil_list,          name='conseil_list'),
    path('conseil/<int:class_id>/semestre/<int:semester_id>/',                conseil_views.conseil_view,          name='conseil_view'),
    path('conseil/<int:class_id>/semestre/<int:semester_id>/excel/',          conseil_views.conseil_export_excel,  name='conseil_excel'),
    path('conseil/<int:class_id>/semestre/<int:semester_id>/pdf/',            conseil_views.conseil_export_pdf,    name='conseil_pdf'),
    path('conseil/<int:class_id>/semestre/<int:semester_id>/word/',           conseil_views.conseil_export_word,   name='conseil_word'),

    # ── Clôture de session (Contrôleur interne) ──────────────────────────────
    path('cloture/',                                                                                              views.gestion_cloture,         name='gestion_cloture'),
    path('cloture/<int:semester_id>/close-normale/',                                                              views.close_session_normale,   name='close_session_normale'),
    path('cloture/<int:semester_id>/reopen-normale/',                                                             views.reopen_session_normale,  name='reopen_session_normale'),
    path('cloture/<int:semester_id>/lock/',                                                                       views.lock_semester,           name='lock_semester'),
    path('cloture/<int:semester_id>/unlock/',                                                                     views.unlock_semester,         name='unlock_semester'),

    # ── Examens & Concours (Direction des Études) ────────────────────────────
    path('examens-concours/',                                                                                     views.examens_concours_class_list,  name='examens_concours_class_list'),
    path('examens-concours/class/<int:class_id>/semester/<int:semester_id>/',                                     views.examens_concours_detail,      name='examens_concours_detail'),
    path('examens-concours/class/<int:class_id>/semester/<int:semester_id>/ec/<int:subject_id>/',                 views.examens_concours_ec_notes,    name='examens_concours_ec_notes'),
    path('examens-concours/class/<int:class_id>/semester/<int:semester_id>/ec/<int:subject_id>/validate/',        views.examens_concours_ec_validate, name='examens_concours_ec_validate'),
    path('examens-concours/class/<int:class_id>/semester/<int:semester_id>/ec/<int:subject_id>/import/',          views.examens_concours_ec_import,   name='examens_concours_ec_import'),
    path('examens-concours/class/<int:class_id>/semester/<int:semester_id>/ec/<int:subject_id>/modele/',          views.examens_concours_ec_template, name='examens_concours_ec_template'),

    # ── Rapport Annuel de la Direction ───────────────────────────────────────
    path('rapport-annuel/',       annual_report_views.rapport_annuel_direction, name='rapport_annuel_direction'),
    path('rapport-annuel/pdf/',   annual_report_views.rapport_annuel_pdf,       name='rapport_annuel_pdf'),
    path('rapport-annuel/excel/', annual_report_views.rapport_annuel_excel,     name='rapport_annuel_excel'),
    path('rapport-annuel/resultats-classes/excel/', annual_report_views.class_results_excel, name='class_results_excel'),
    path('rapport-annuel/resultats-classes/pdf/',   annual_report_views.class_results_pdf,   name='class_results_pdf'),
    path('rapport-annuel/resultats-classes/word/',  annual_report_views.class_results_word,  name='class_results_word'),

    # ── Réclamations de notes ─────────────────────────────────────────────────
    path('reclamations/',                                                                                          reclamation_views.reclamation_class_list, name='reclamation_class_list'),
    path('reclamations/class/<int:class_id>/semester/<int:semester_id>/',                                          reclamation_views.reclamation_list,       name='reclamation_list'),
    path('reclamations/<int:pk>/delete/',                                                                          reclamation_views.reclamation_delete,     name='reclamation_delete'),

    # ── Rattrapages ───────────────────────────────────────────────────────────
    path('rattrapages/',                                                                                          views.rattrapage_class_list,   name='rattrapage_class_list'),
    path('rattrapage/class/<int:class_id>/semester/<int:semester_id>/',                                           views.rattrapage_list,          name='rattrapage_list'),
    path('rattrapage/class/<int:class_id>/semester/<int:semester_id>/student/<int:student_id>/preview/',          views.rattrapage_preview,       name='rattrapage_preview'),
    path('rattrapage/class/<int:class_id>/semester/<int:semester_id>/student/<int:student_id>/pdf/',              views.rattrapage_pdf,           name='rattrapage_pdf'),
    path('rattrapage/class/<int:class_id>/semester/<int:semester_id>/archive/',                                   views.rattrapage_archive_zip,  name='rattrapage_archive_zip'),
]
