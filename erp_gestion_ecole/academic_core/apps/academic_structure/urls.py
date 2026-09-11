from django.urls import path
from . import views

app_name = 'academic_structure'

urlpatterns = [
    path('',                      views.structure_index,                    name='index'),
    path('select-department/',    views.select_department,                  name='select_department'),
    path('departments/manage/',   views.DepartmentManageView.as_view(),     name='departments_manage'),
    path('years/',                views.AcademicYearListView.as_view(),     name='years'),
    path('faculties/',            views.FacultyListView.as_view(),          name='faculties'),
    path('departments/',          views.DepartmentListView.as_view(),       name='departments'),
    path('programs/',             views.ProgramListView.as_view(),          name='programs'),
    path('classes/',              views.ClassListView.as_view(),            name='classes'),
    path('semesters/',            views.SemesterListView.as_view(),         name='semesters'),
    path('levels/',                views.LevelListView.as_view(),            name='levels'),
    # Les formulaires de création postent sur la même URL que la liste (POST géré par post())
    path('years/create/',         views.AcademicYearListView.as_view(),     name='year_create'),
    path('faculties/create/',     views.FacultyListView.as_view(),          name='faculty_create'),
    path('departments/create/',   views.DepartmentListView.as_view(),       name='department_create'),
    path('programs/create/',      views.ProgramListView.as_view(),          name='program_create'),
    path('classes/create/',       views.ClassListView.as_view(),            name='class_create'),
    path('semesters/create/',     views.SemesterListView.as_view(),         name='semester_create'),
    path('levels/create/',         views.LevelListView.as_view(),            name='level_create'),
    # Gestion des instituts (Super Admin)
    path('instituts/',                               views.institut_list,      name='institut_list'),
    path('instituts/creer/',                         views.institut_create_view, name='institut_create'),
    path('instituts/<int:config_pk>/modifier/',      views.institut_edit_view,   name='institut_edit'),
    path('instituts/<int:config_pk>/abonnements/',   views.abonnement_list,    name='abonnement_list'),
    path('instituts/<int:config_pk>/fonctionnalites/', views.institut_feature_flags, name='institut_feature_flags'),
    path('configuration-institut/', views.institut_config_view, name='institut_config'),
    path('mon-institut/emails/', views.institut_email_config_view, name='institut_email_config'),
    path('mon-institut/paiement/', views.institut_payment_config_view, name='institut_payment_config'),
    path('supplement-diplome/', views.diploma_supplement_config_list, name='diploma_supplement_config_list'),
    path('supplement-diplome/<int:program_id>/', views.diploma_supplement_config_edit, name='diploma_supplement_config_edit'),
]
