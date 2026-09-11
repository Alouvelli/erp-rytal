from django.urls import path
from . import views

app_name = 'teachers'

urlpatterns = [
    path('',                    views.TeacherListView.as_view(),   name='list'),
    path('create/',             views.TeacherCreateView.as_view(), name='create'),
    path('ajax/generate-matricule/', views.ajax_generate_teacher_matricule, name='ajax_generate_matricule'),
    path('matricules/regenerer/',    views.regenerate_all_teacher_matricules, name='regenerate_matricules'),
    path('<int:pk>/',           views.TeacherDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/',      views.TeacherUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/',    views.TeacherDeleteView.as_view(), name='delete'),
    path('<int:pk>/nommer-chef-departement/', views.TeacherAssignDepartmentHeadView.as_view(), name='assign_department_head'),
    path('mes-honoraires/',     views.my_honoraires,                   name='my_honoraires'),
    path('grades/',             views.GradeListView.as_view(),         name='grades'),
    path('credentials-created/', views.TeacherCredentialsView.as_view(), name='credentials_created'),
    path('contrats/',            views.contrat_list, name='contrat_list'),
    path('contrats/modele/',     views.contrat_modele, name='contrat_modele'),
    path('contrats/<int:pk>/edit/', views.contrat_edit, name='contrat_edit'),
    path('contrats/<int:pk>/pdf/',  views.contrat_pdf,  name='contrat_pdf'),
    path('mes-contrats/',        views.mes_contrats, name='mes_contrats'),
]
