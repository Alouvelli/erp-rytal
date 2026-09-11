from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    path('',               views.StudentListView.as_view(),   name='list'),
    path('create/',        views.StudentCreateView.as_view(), name='create'),
    path('import/',        views.StudentImportView.as_view(), name='import'),
    path('abandons/',                    views.abandon_list,             name='abandon_list'),
    path('abandons/reactiver-tous/',     views.abandon_reactivate_all,   name='abandon_reactivate_all'),
    path('suspensions/',                 views.suspension_list,          name='suspension_list'),
    path('<int:pk>/abandon/',            views.student_mark_abandoned,   name='mark_abandoned'),
    path('<int:pk>/suspendre/',          views.student_mark_suspended,   name='mark_suspended'),
    path('<int:pk>/class-rep/',          views.student_set_class_rep,    name='set_class_rep'),
    path('enrollment/<int:pk>/reactiver/', views.enrollment_reactivate,  name='enrollment_reactivate'),
    path('<int:pk>/',      views.StudentDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.StudentUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.StudentDeleteView.as_view(), name='delete'),
    path('reinscription/',        views.ReinscriptionView.as_view(),      name='reinscription'),
    path('changement-filiere/',                    views.ChangementFiliereView.as_view(), name='changement_filiere'),
    path('changement-filiere/confirmation/',       views.changement_filiere_confirm,      name='changement_filiere_confirm'),
    path('changement-filiere/<int:pk>/fiche-pdf/', views.fiche_changement_filiere_pdf,     name='fiche_changement_filiere_pdf'),
    path('assign-department/',    views.assign_department_view,           name='assign_department'),
    path('credentials-created/', views.StudentCredentialsView.as_view(), name='credentials_created'),
    path('ajax/generate-matricule/',   views.ajax_generate_matricule,    name='ajax_generate_matricule'),
    path('ajax/classes-by-institut/',  views.ajax_classes_by_institut,   name='ajax_classes_by_institut'),
    path('liste-pdf/',           views.class_list_pdf,                   name='class_list_pdf'),
    path('<int:pk>/fiche-inscription/', views.fiche_inscription_pdf,     name='fiche_inscription_pdf'),
    path('<int:pk>/carte/',            views.student_card_pdf,           name='student_card_pdf'),
    path('paiement/<int:student_pk>/', views.payment_status_check,       name='payment_status'),
    path('<int:pk>/photo/',            views.update_student_photo,       name='update_photo'),
    path('ma-carte-presence/',         views.my_presence_card,           name='my_presence_card'),
    path('controle/',                  views.controle_scan,              name='controle_scan'),
    path('controle/poll/',             views.controle_scan_poll,         name='controle_scan_poll'),
    path('controle/lookup/',           views.controle_scan_lookup,       name='controle_scan_lookup'),
    path('<int:pk>/dossier/',          views.dossier_etudiant,           name='dossier'),
    path('dossiers/',                  views.dossier_list_by_class,      name='dossier_list'),
]
