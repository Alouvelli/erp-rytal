"""
Registre central des onglets et fonctionnalités de la sidebar, utilisé pour le
système d'activation/désactivation par institut (voir InstitutDisabledTab /
InstitutDisabledFeature dans models.py).

Source unique de vérité, réutilisée par :
  - academic_core/templates/base/base.html (filtrage de la sidebar)
  - feature_gate.py (blocage effectif des URLs, pas seulement visuel)
  - academic_structure/views.py::institut_feature_flags (page de gestion Super Admin)

Chaque fonctionnalité est identifiée par son nom d'URL Django (`app_label:url_name`)
plutôt que par sa position dans le template, pour qu'une fonctionnalité désactivée
le soit dans TOUTES ses apparitions (certains onglets ont des variantes de contenu
selon le rôle qui se recouvrent partiellement).
"""

TAB_LABELS = {
    'planning': 'Planning & Émargement',
    'pedagogie': 'Direction Pédagogique',
    'personnes': 'Inscriptions',
    'comptabilite': 'Direction Financière',
    'grh': 'Gestion Ressources Humaines',
    'administration': 'Direction Générale',
    'communication': 'Direction Communication',
    'service_communaute': 'Service à la Communauté',
    'dsi': 'Direction des SI',
    'coip': "Cellule d'Orientation et d'Insertion Professionnelle",
    'api_gateway': 'API de Consommation',
    'notifications': 'Notifications',
    'rapports': 'Rapports',
    'budget': 'Pilotage et Suivi Budgétaire',
}

TAB_FEATURES = {
    'planning': [
        ('timetable:index', 'Emplois du temps'),
        ('attendance:sheet_list', 'Émargements'),
        ('cancellations:list', 'Annulations / Reports'),
        ('timetable:room_swap', 'Permutation de salles'),
        ('attendance:planned_modules_admin', 'Modules planifiés'),
        ('timetable:holiday_list', 'Suspendre un planning'),
        ('attendance:absence_alert_config', 'Seuil d\'alerte absences'),
        ('attendance:absence_justifications_admin', 'Justifications d\'absences'),
    ],
    'pedagogie': [
        ('grades:evaluation_list', 'Notes & Évaluations'),
        ('grades:rapport_annuel_direction', 'Rapport Annuel de la Direction'),
        ('academic_structure:diploma_supplement_config_list', 'Suppléments de diplôme'),
        ('grades:reclamation_class_list', 'Réclamations de Notes'),
        ('grades:maquette_list', 'Référentiel des Maquettes'),
        ('grades:bulletin_class_list', 'Gestion des Bulletins'),
        ('grades:conseil_list', 'Tableau de Conseil'),
        ('grades:rattrapage_class_list', 'Rattrapages'),
        ('grades:gestion_cloture', 'Clôture des sessions'),
        ('grades:import_notes_csv', 'Import notes CSV'),
        ('teachers:contrat_list', 'Contrats Enseignants'),
        ('grades:examens_concours_class_list', 'Examens & Concours'),
        ('academic_structure:index', 'Gestion de la Scolarité'),
        ('rooms:list', 'Salles'),
        ('subjects:list', 'Modules (EC)'),
        ('timetable:cahier_texte_list', 'Cahier de Texte'),
        ('attendance:extra_requests_admin', 'Demande de séances supplémentaires'),
        ('accounting:budget_honoraires', 'Budget honoraires mensuels'),
    ],
    'personnes': [
        ('teachers:list', 'Nouveau & Liste des Enseignants'),
        ('students:list', 'Inscriptions & Liste étudiants'),
        ('students:reinscription', 'Réinscriptions étudiants'),
        ('students:changement_filiere', 'Changement de filière'),
        ('students:abandon_list', 'Abandons'),
        ('students:suspension_list', 'Suspensions d\'inscription'),
        ('accounting:financial_student_list', 'Liste des étudiants'),
        ('accounting:attestation_passage_list', 'Attestation de passage'),
        ('students:dossier_list', 'Dossiers étudiants'),
    ],
    'comptabilite': [
        ('accounting:dashboard', 'Honoraires mensuels'),
        ('accounting:honoraires_annuels', 'Honoraires annuels'),
        ('accounting:mensualite_list', 'Paiements Mensualités'),
        ('accounting:soutenance_dashboard', 'Gestion frais Soutenance'),
        ('accounting:taux_recouvrement', 'Taux de recouvrement'),
        ('accounting:boursier_list', 'Suivi des boursiers'),
        ('accounting:validation_inscription_list', 'Validation Inscription'),
        ('accounting:repartition_annee_list', 'Répartition Année Académique'),
        ('accounting:rate_list', 'Taux horaires'),
        ('accounting:partenaire_bourse_list', 'Partenaires de bourse'),
        ('accounting:caisse_dashboard', 'La Caisse'),
        ('accounting:caisse_movement_list', 'Entrée & Sortie Caisse'),
        ('accounting:compte_comptable_list', 'Comptes comptables'),
        ('accounting:demande_depense_list', 'Demandes de dépense'),
        ('accounting:rapports_financiers', 'Rapports financiers'),
        ('students:controle_scan', 'Contrôle Accueil'),
        ('accounting:etat_journalier', 'État journalier'),
        ('accounting:clotures_list', 'Clôtures'),
        ('hr:salaire_list', 'Gestion des Salaires'),
        ('hr:bulletin_list', 'Bulletins de Salaire'),
    ],
    'grh': [
        ('hr:dashboard', 'Tableau de bord RH'),
        ('hr:personnel_list', 'Gestion du Personnel'),
        ('hr:pointage_jour', 'Pointage du jour'),
        ('hr:presence_list', 'Liste des présences'),
        ('hr:conge_list', 'Congés'),
        ('hr:discipline_list', 'Discipline'),
        ('hr:evaluation_list', 'Évaluations'),
        ('hr:mission_list', 'Missions'),
        ('hr:interim_list', 'Intérims'),
        ('hr:handover_list', 'Passations de service'),
        ('hr:internship_list', 'Stages'),
        ('hr:onboarding_list', 'Intégration'),
        ('hr:recruitment_list', 'Recrutement'),
        ('hr:cartes_personnel', 'Cartes du Personnel'),
        ('hr:document_request_list', 'Documents & Attestations RH'),
        ('hr:rapport_mensuel_pointage', 'Rapport mensuel'),
        ('hr:export_excel', 'Export Excel'),
    ],
    'administration': [
        ('academic_structure:institut_list', 'Mon Institut'),
        ('accounts:users_list', 'Utilisateurs'),
        ('accounts:direction_list', 'Directions'),
        ('accounts:unassigned_users', 'Non affectés'),
        ('academic_structure:departments_manage', 'Gestion des départements'),
        ('accounts:audit_log', 'Journal d\'audit'),
    ],
    'communication': [
        ('accounting:demande_depense_list', 'Demandes de dépense'),
    ],
    'service_communaute': [
        ('community_service:list', 'Activités'),
        ('community_service:report', "Rapport d'activités"),
    ],
    'dsi': [
        ('accounts:supervision_generale', 'Supervision générale'),
        ('accounts:audit_log', 'Journal d\'audit'),
        ('accounts:audit_rapport', 'Rapport d\'audit'),
    ],
    'coip': [
        ('coip:index', 'Tableau de bord COIP'),
        ('coip:alumni_list', 'Alumni'),
        ('coip:partner_list', 'Partenaires'),
        ('coip:partnership_list', 'Conventions'),
        ('coip:offer_list', 'Offres de stage'),
        ('coip:internship_list', 'Stages'),
        ('coip:orientation_session_list', "Séances d'orientation"),
        ('coip:recommendation_list', 'Recommandations'),
        ('coip:opportunity_list', 'Opportunités (gestion)'),
        ('coip:activity_list', 'Activités COIP (gestion)'),
        ('coip:visit_list', 'Sorties pédagogiques (gestion)'),
        ('coip:report_list', 'Rapports COIP'),
        ('coip:archive_list', 'Archives COIP'),
        ('coip:my_recommendations', 'Mes recommandations'),
        ('coip:my_orientation_sessions', "Mes séances d'orientation"),
        ('coip:opportunities_browse', 'Opportunités (étudiant)'),
        ('coip:activities_browse', 'Activités COIP (auto-inscription)'),
        ('coip:visits_browse', 'Sorties pédagogiques (auto-inscription)'),
    ],
    'notifications': [
        ('notifications:list', 'Notifications'),
        ('notifications:notify_absence', 'Absence / Retard enseignant'),
        ('api_gateway:my_access_requests', 'Demander un accès API'),
    ],
    'api_gateway': [
        ('api_gateway:catalog_list', 'Catalogue des API'),
        ('api_gateway:access_requests_list', 'Demandes d\'accès'),
        ('api_gateway:grants_list', 'Accès accordés'),
    ],
    'rapports': [
        ('reports:index', 'Rapports & Exports'),
    ],
    'budget': [
        ('accounting:budget_dashboard', 'Pilotage'),
        ('accounting:ligne_budgetaire_list', 'Lignes budgétaires'),
        ('accounting:engagement_list', 'Engagements'),
        ('accounting:rectificatif_list', 'Rectificatifs'),
        ('accounting:source_financement_list', 'Sources de financement'),
        ('accounting:bsc_dashboard', 'Balanced Scorecard'),
        ('strategic_plan:cadrage_list', 'Cadrages stratégiques'),
        ('strategic_plan:axe_list', 'Axes stratégiques'),
        ('strategic_plan:objectif_list', 'Objectifs stratégiques'),
        ('strategic_plan:programme_list', 'Programmes'),
        ('strategic_plan:projet_list', 'Projets'),
        ('indicators:indicateur_list', 'Indicateurs'),
        ('procurement:demande_list', "Demandes d'achat"),
        ('procurement:fournisseur_list', 'Fournisseurs'),
        ('procurement:appel_offres_list', "Appels d'offres"),
        ('procurement:commande_list', 'Commandes'),
        ('procurement:facture_list', 'Factures & Paiements'),
        ('quality:quality_dashboard', 'Qualité'),
        ('quality:critere_list', 'Critères qualité'),
        ('quality:plan_list', "Plans d'amélioration"),
        ('risks:matrice', 'Matrice des risques'),
        ('risks:risque_list', 'Risques'),
    ],
}


def get_url_to_tab():
    """Index inversé {url_name: tab_key}, construit à la demande depuis TAB_FEATURES."""
    mapping = {}
    for tab_key, features in TAB_FEATURES.items():
        for url_name, _label in features:
            mapping.setdefault(url_name, tab_key)
    return mapping


URL_TO_TAB = get_url_to_tab()
