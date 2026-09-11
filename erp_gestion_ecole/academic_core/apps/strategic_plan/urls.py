from django.urls import path
from . import views, pta_views

app_name = 'strategic_plan'

urlpatterns = [
    path('pta/mon-pta/', pta_views.pta_my_plan_view, name='pta_my_plan'),
    path('pta/tous/', pta_views.pta_all_plans_view, name='pta_all_plans'),
    path('pta/import/', pta_views.pta_import, name='pta_import'),
    path('pta/<int:pk>/', pta_views.pta_plan_detail_view, name='pta_plan_detail'),
    path('pta/<int:pk>/pdf/', pta_views.pta_pdf, name='pta_pdf'),
    path('pta/lignes/creer/', pta_views.pta_line_create, name='pta_line_create'),
    path('pta/lignes/<int:pk>/modifier/', pta_views.pta_line_edit, name='pta_line_edit'),
    path('pta/lignes/<int:pk>/supprimer/', pta_views.pta_line_delete, name='pta_line_delete'),

    path('cadrages/', views.cadrage_list, name='cadrage_list'),
    path('cadrages/creer/', views.cadrage_create, name='cadrage_create'),
    path('cadrages/<int:pk>/modifier/', views.cadrage_edit, name='cadrage_edit'),
    path('cadrages/<int:pk>/supprimer/', views.cadrage_delete, name='cadrage_delete'),
    path('cadrages/import/', views.cadrage_import, name='cadrage_import'),
    path('cadrages/pdf/', views.cadrage_pdf, name='cadrage_pdf'),

    path('axes/', views.axe_list, name='axe_list'),
    path('axes/creer/', views.axe_create, name='axe_create'),
    path('axes/<int:pk>/modifier/', views.axe_edit, name='axe_edit'),
    path('axes/<int:pk>/supprimer/', views.axe_delete, name='axe_delete'),
    path('axes/import/', views.axe_import, name='axe_import'),
    path('axes/pdf/', views.axe_pdf, name='axe_pdf'),

    path('objectifs/', views.objectif_list, name='objectif_list'),
    path('objectifs/creer/', views.objectif_create, name='objectif_create'),
    path('objectifs/<int:pk>/modifier/', views.objectif_edit, name='objectif_edit'),
    path('objectifs/<int:pk>/supprimer/', views.objectif_delete, name='objectif_delete'),
    path('objectifs/import/', views.objectif_import, name='objectif_import'),
    path('objectifs/pdf/', views.objectif_pdf, name='objectif_pdf'),

    path('programmes/', views.programme_list, name='programme_list'),
    path('programmes/creer/', views.programme_create, name='programme_create'),
    path('programmes/<int:pk>/modifier/', views.programme_edit, name='programme_edit'),
    path('programmes/<int:pk>/supprimer/', views.programme_delete, name='programme_delete'),
    path('programmes/import/', views.programme_import, name='programme_import'),
    path('programmes/pdf/', views.programme_pdf, name='programme_pdf'),

    path('projets/', views.projet_list, name='projet_list'),
    path('projets/creer/', views.projet_create, name='projet_create'),
    path('projets/<int:pk>/', views.projet_detail, name='projet_detail'),
    path('projets/<int:pk>/modifier/', views.projet_edit, name='projet_edit'),
    path('projets/<int:pk>/supprimer/', views.projet_delete, name='projet_delete'),
    path('projets/<int:pk>/gantt/', views.projet_gantt, name='projet_gantt'),
    path('projets/<int:pk>/kanban/', views.projet_kanban, name='projet_kanban'),
    path('projets/import/', views.projet_import, name='projet_import'),
    path('projets/pdf/', views.projet_pdf, name='projet_pdf'),

    path('activites/creer/', views.activite_create, name='activite_create'),
    path('activites/<int:pk>/modifier/', views.activite_edit, name='activite_edit'),
    path('activites/<int:pk>/supprimer/', views.activite_delete, name='activite_delete'),
    path('activites/<int:pk>/changer-statut/', views.activite_changer_statut, name='activite_changer_statut'),

    path('sous-activites/creer/', views.sous_activite_create, name='sous_activite_create'),
    path('sous-activites/<int:pk>/modifier/', views.sous_activite_edit, name='sous_activite_edit'),
    path('sous-activites/<int:pk>/supprimer/', views.sous_activite_delete, name='sous_activite_delete'),

    path('jalons/creer/', views.jalon_create, name='jalon_create'),
    path('jalons/<int:pk>/modifier/', views.jalon_edit, name='jalon_edit'),
    path('jalons/<int:pk>/supprimer/', views.jalon_delete, name='jalon_delete'),

    path('livrables/creer/', views.livrable_create, name='livrable_create'),
    path('livrables/<int:pk>/modifier/', views.livrable_edit, name='livrable_edit'),
    path('livrables/<int:pk>/supprimer/', views.livrable_delete, name='livrable_delete'),

    path('equipe/ajouter/', views.membre_create, name='membre_create'),
    path('equipe/<int:pk>/retirer/', views.membre_delete, name='membre_delete'),
]
