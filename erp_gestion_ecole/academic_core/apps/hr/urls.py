from django.urls import path
from . import views
from . import salary_views
from . import checkin_views
from . import export_views
from . import career_views
from . import discipline_views
from . import evaluation_views
from . import mission_views
from . import interim_views
from . import internship_views
from . import onboarding_views
from . import recruitment_views
from . import document_views

app_name = 'hr'

urlpatterns = [
    # ── Pointage self-service (public, sans connexion) ────────────────────────
    path('pointer/<str:token>/',              checkin_views.pointage_self_checkin,    name='pointage_self_checkin'),

    # ── QR Contrôle Accueil — le personnel scanne avec sa propre caméra ───────
    path('accueil-qr/',                       views.accueil_qr_display,               name='accueil_qr_display'),
    path('pointer-auth/<str:token>/',         checkin_views.accueil_self_checkin,     name='accueil_self_checkin'),
    path('ma-carte-pointage/',                views.ma_carte_pointage,                name='ma_carte_pointage'),

    # ── Contrôle Accueil Personnel ─────────────────────────────────────────────
    path('controle-accueil/',                 views.controle_accueil_personnel,       name='controle_accueil_personnel'),
    path('ajax/accueil-lookup/',              checkin_views.accueil_staff_lookup,     name='accueil_staff_lookup'),

    # ── Rapport mensuel de pointage ───────────────────────────────────────────
    path('rapport-mensuel/',                  views.rapport_mensuel_pointage,         name='rapport_mensuel_pointage'),
    path('rapport-mensuel/pdf/',              export_views.rapport_mensuel_pdf,       name='rapport_mensuel_pdf'),
    path('rapport-mensuel/word/',             export_views.rapport_mensuel_word,      name='rapport_mensuel_word'),

    path('',                          views.hr_dashboard,    name='dashboard'),
    path('pointage/',                 views.pointage_jour,   name='pointage_jour'),
    path('presences/',                views.presence_list,   name='presence_list'),
    path('presences/<int:pk>/edit/',  views.presence_edit,   name='presence_edit'),
    path('presences/<int:pk>/delete/', views.presence_delete, name='presence_delete'),
    path('employe/<int:pk>/',         views.employe_fiche,   name='employe_fiche'),
    path('conges/',                   views.conge_list,      name='conge_list'),
    path('conges/nouveau/',           views.conge_create,    name='conge_create'),
    path('conges/<int:pk>/review/',   views.conge_review,    name='conge_review'),
    path('export/excel/',             views.export_excel,    name='export_excel'),
    path('ajax/set-presence/',        views.ajax_set_presence,   name='ajax_set_presence'),
    path('cartes/',                   views.cartes_personnel,    name='cartes_personnel'),
    path('cartes/<int:pk>/',          views.carte_employe,       name='carte_employe'),
    path('ma-carte/',                 views.ma_carte_personnel,  name='ma_carte_personnel'),
    path('ajax/gen-matricule/',       views.ajax_gen_matricule,  name='ajax_gen_matricule'),

    # ── Gestion du personnel ──────────────────────────────────────────────────
    path('personnel/',                        salary_views.personnel_list,       name='personnel_list'),
    path('personnel/<int:pk>/fiche/',         salary_views.personnel_fiche_edit, name='personnel_fiche_edit'),
    path('personnel/<int:pk>/archiver/',      salary_views.personnel_archive,    name='personnel_archive'),
    path('personnel/<int:pk>/supprimer/',     salary_views.personnel_delete,     name='personnel_delete'),
    path('personnel/export/pdf/',             export_views.personnel_pdf,        name='personnel_pdf'),
    path('personnel/export/word/',            export_views.personnel_word,       name='personnel_word'),
    path('personnel/enseignants/pdf/',        export_views.personnel_enseignants_pdf,  name='personnel_enseignants_pdf'),
    path('personnel/enseignants/word/',       export_views.personnel_enseignants_word, name='personnel_enseignants_word'),

    # ── Gestion des salaires ──────────────────────────────────────────────────
    path('salaires/',                         salary_views.salaire_list,         name='salaire_list'),
    path('salaires/<int:pk>/edit/',           salary_views.salaire_edit,         name='salaire_edit'),
    path('salaires/export/pdf/',              export_views.salaire_pdf,          name='salaire_pdf'),
    path('salaires/export/word/',             export_views.salaire_word,         name='salaire_word'),

    # ── Bulletins de salaire ──────────────────────────────────────────────────
    path('bulletins/',                        salary_views.bulletin_list,        name='bulletin_list'),
    path('bulletins/generer/',                salary_views.bulletin_generate,    name='bulletin_generate'),
    path('bulletins/<int:pk>/',               salary_views.bulletin_detail,      name='bulletin_detail'),
    path('bulletins/<int:pk>/delete/',        salary_views.bulletin_delete,      name='bulletin_delete'),
    path('bulletins/<int:pk>/pdf/',           salary_views.bulletin_pdf,         name='bulletin_pdf'),
    path('bulletins/<int:pk>/word/',          salary_views.bulletin_word,        name='bulletin_word'),
    path('bulletins/export/pdf/',             export_views.bulletin_list_pdf,     name='bulletin_list_pdf'),
    path('bulletins/export/word/',            export_views.bulletin_list_word,    name='bulletin_list_word'),

    # ── Présences / absences ──────────────────────────────────────────────────
    path('presences/export/pdf/',             export_views.presence_pdf,         name='presence_pdf'),
    path('presences/export/word/',            export_views.presence_word,        name='presence_word'),

    # ── Pointage du jour ───────────────────────────────────────────────────────
    path('pointage/export/pdf/',              export_views.pointage_jour_pdf,     name='pointage_jour_pdf'),
    path('pointage/export/word/',             export_views.pointage_jour_word,    name='pointage_jour_word'),

    # ── Congés ─────────────────────────────────────────────────────────────────
    path('conges/export/pdf/',                export_views.conge_pdf,            name='conge_pdf'),
    path('conges/export/word/',               export_views.conge_word,           name='conge_word'),

    # ── Carrière & Contrats ────────────────────────────────────────────────────
    path('employe/<int:user_pk>/contrat/nouveau/',        career_views.contract_create,           name='contract_create'),
    path('contrat/<int:pk>/avenant/nouveau/',              career_views.contract_amendment_create, name='contract_amendment_create'),
    path('employe/<int:user_pk>/affectation/nouvelle/',    career_views.assignment_create,         name='assignment_create'),

    # ── Discipline ─────────────────────────────────────────────────────────────
    path('discipline/',                    discipline_views.discipline_list,   name='discipline_list'),
    path('discipline/nouveau/',            discipline_views.discipline_create, name='discipline_create'),
    path('discipline/<int:pk>/',           discipline_views.discipline_detail, name='discipline_detail'),
    path('discipline/<int:pk>/action/',    discipline_views.discipline_action, name='discipline_action'),
    path('discipline/<int:pk>/supprimer/', discipline_views.discipline_delete, name='discipline_delete'),

    # ── Évaluations ────────────────────────────────────────────────────────────
    path('evaluations/campagnes/',      evaluation_views.evaluation_campaign_list, name='evaluation_campaign_list'),
    path('evaluations/',                evaluation_views.evaluation_list,          name='evaluation_list'),
    path('evaluations/<int:pk>/',       evaluation_views.evaluation_detail,        name='evaluation_detail'),
    path('evaluations/<int:pk>/action/', evaluation_views.evaluation_action,       name='evaluation_action'),

    # ── Missions ───────────────────────────────────────────────────────────────
    path('missions/',                  mission_views.mission_list,      name='mission_list'),
    path('missions/nouvelle/',         mission_views.mission_create,    name='mission_create'),
    path('missions/<int:pk>/action/',  mission_views.mission_action,    name='mission_action'),
    path('missions/<int:pk>/supprimer/', mission_views.mission_delete,  name='mission_delete'),
    path('missions/<int:pk>/ordre/pdf/', mission_views.mission_order_pdf, name='mission_order_pdf'),

    # ── Intérims ───────────────────────────────────────────────────────────────
    path('interims/',                   interim_views.interim_list,   name='interim_list'),
    path('interims/nouveau/',           interim_views.interim_create, name='interim_create'),
    path('interims/<int:pk>/cloturer/', interim_views.interim_close,  name='interim_close'),
    path('interims/<int:pk>/supprimer/', interim_views.interim_delete, name='interim_delete'),

    # ── Passations de service ─────────────────────────────────────────────────
    path('passations/',                    interim_views.handover_list,     name='handover_list'),
    path('passations/nouvelle/',           interim_views.handover_create,   name='handover_create'),
    path('passations/<int:pk>/valider/',   interim_views.handover_validate, name='handover_validate'),
    path('passations/<int:pk>/supprimer/', interim_views.handover_delete,   name='handover_delete'),

    # ── Stages ─────────────────────────────────────────────────────────────────
    path('stages/',                    internship_views.internship_list,              name='internship_list'),
    path('stages/nouveau/',            internship_views.internship_create,            name='internship_create'),
    path('stages/<int:pk>/action/',    internship_views.internship_action,            name='internship_action'),
    path('stages/<int:pk>/supprimer/', internship_views.internship_delete,            name='internship_delete'),
    path('stages/<int:pk>/attestation/pdf/', internship_views.internship_attestation_pdf, name='internship_attestation_pdf'),

    # ── Intégration (Onboarding) ─────────────────────────────────────────────
    path('onboarding/',                        onboarding_views.onboarding_list,        name='onboarding_list'),
    path('onboarding/nouveau/',                onboarding_views.onboarding_create,      name='onboarding_create'),
    path('onboarding/<int:pk>/',               onboarding_views.onboarding_detail,      name='onboarding_detail'),
    path('onboarding/<int:pk>/cloturer/',      onboarding_views.onboarding_complete,    name='onboarding_complete'),
    path('onboarding/<int:pk>/tache/nouvelle/', onboarding_views.onboarding_task_create, name='onboarding_task_create'),
    path('onboarding/tache/<int:pk>/toggle/',  onboarding_views.onboarding_task_toggle, name='onboarding_task_toggle'),

    # ── Recrutement ────────────────────────────────────────────────────────────
    path('recrutement/',                    recruitment_views.recruitment_list,   name='recruitment_list'),
    path('recrutement/nouveau/',            recruitment_views.recruitment_create, name='recruitment_create'),
    path('recrutement/<int:pk>/action/',    recruitment_views.recruitment_action, name='recruitment_action'),
    path('recrutement/<int:pk>/supprimer/', recruitment_views.recruitment_delete, name='recruitment_delete'),
    path('recrutement/<int:request_pk>/candidat/nouveau/', recruitment_views.candidate_create, name='candidate_create'),
    path('recrutement/candidat/<int:pk>/action/',           recruitment_views.candidate_action, name='candidate_action'),
    path('recrutement/candidat/<int:pk>/embaucher/',        recruitment_views.candidate_hire,   name='candidate_hire'),

    # ── Documents & Attestations ─────────────────────────────────────────────
    path('mes-attestations/',                document_views.mes_attestations,        name='mes_attestations'),
    path('documents/',                       document_views.document_request_list,   name='document_request_list'),
    path('documents/<int:pk>/action/',       document_views.document_request_action, name='document_request_action'),
    path('documents/<int:pk>/supprimer/',    document_views.document_request_delete, name='document_request_delete'),
    path('documents/fichier/<int:pk>/telecharger/', document_views.document_download, name='document_download'),
]
