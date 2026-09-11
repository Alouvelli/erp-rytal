from django.db import migrations


CATALOG = [
    # ── Structure académique ────────────────────────────────────────────────
    ('Départements', 'STRUCTURE', '/api/v1/structure/departments/',
     "Départements de l'institut (code, nom, faculté, chef de département)."),
    ('Filières', 'STRUCTURE', '/api/v1/structure/programs/',
     "Filières (programmes) proposées, avec leur département et leur durée."),
    ('Classes', 'STRUCTURE', '/api/v1/structure/classes/',
     "Classes de l'institut (filière, niveau, année académique, effectif)."),

    # ── Salles & Bâtiments ───────────────────────────────────────────────────
    ('Bâtiments', 'ROOMS', '/api/v1/rooms/buildings/',
     "Bâtiments de l'institut."),
    ('Salles', 'ROOMS', '/api/v1/rooms/rooms/',
     "Salles (capacité, type, équipements, disponibilité)."),

    # ── Matières ─────────────────────────────────────────────────────────────
    ('Modules (EC)', 'SUBJECTS', '/api/v1/subjects/',
     "Modules enseignés (coefficient, crédits, volumes horaires, enseignant responsable)."),

    # ── Annulations de cours ─────────────────────────────────────────────────
    ('Annulations / Reports de cours', 'CANCELLATIONS', '/api/v1/cancellations/',
     "Demandes d'annulation ou de report de séance, avec leur statut de traitement."),

    # ── Notifications ────────────────────────────────────────────────────────
    ('Mes notifications', 'NOTIFICATIONS', '/api/v1/notifications/',
     "Notifications du compte à l'origine de l'appel (toujours restreint au destinataire)."),

    # ── Comptabilité ─────────────────────────────────────────────────────────
    ('Mouvements de caisse', 'ACCOUNTING', '/api/v1/accounting/caisse-movements/',
     "Entrées et sorties de caisse (hors paiements étudiants)."),
    ('Demandes de dépense', 'ACCOUNTING', '/api/v1/accounting/demandes-depense/',
     "Demandes de dépense soumises par les directions et leur statut de traitement."),
    ('Lignes budgétaires', 'ACCOUNTING', '/api/v1/accounting/lignes-budgetaires/',
     "Suivi budgétaire par direction (montants initial, révisé, engagé, exécuté)."),

    # ── Ressources Humaines ──────────────────────────────────────────────────
    ('Fiches personnel', 'HR', '/api/v1/hr/fiches-personnel/',
     "Fiches employé (poste, type de contrat, date d'embauche, ancienneté)."),
    ('Contrats', 'HR', '/api/v1/hr/contracts/',
     "Historique des contrats de travail (type, dates, statut)."),
    ('Demandes de congé', 'HR', '/api/v1/hr/demandes-conge/',
     "Demandes de congé/absence du personnel et leur statut."),

    # ── Service à la communauté ──────────────────────────────────────────────
    ('Activités de service à la communauté', 'COMMUNITY', '/api/v1/service-communaute/',
     "Actions menées par le service à la communauté (sensibilisation, formation, dons…)."),

    # ── Plan stratégique ─────────────────────────────────────────────────────
    ('Projets stratégiques', 'STRATEGIC', '/api/v1/plan-strategique/projets/',
     "Projets du Plan Stratégique de Développement (statut, budget, avancement)."),
    ('Plans de Travail Annuels', 'STRATEGIC', '/api/v1/plan-strategique/pta/',
     "Plans de Travail Annuels par titulaire et par exercice."),

    # ── Indicateurs ──────────────────────────────────────────────────────────
    ('Indicateurs KPI', 'INDICATORS', '/api/v1/indicateurs/',
     "Indicateurs du Balanced Scorecard (valeur cible, valeur actuelle, taux de réalisation)."),

    # ── Achats ───────────────────────────────────────────────────────────────
    ("Demandes d'achat", 'PROCUREMENT', '/api/v1/achats/demandes/',
     "Demandes d'achat soumises par les directions et leur statut."),
    ('Commandes', 'PROCUREMENT', '/api/v1/achats/commandes/',
     "Commandes passées auprès des fournisseurs."),
    ('Factures fournisseurs', 'PROCUREMENT', '/api/v1/achats/factures/',
     "Factures reçues des fournisseurs et leur statut de paiement."),

    # ── Qualité ──────────────────────────────────────────────────────────────
    ('Critères qualité', 'QUALITY', '/api/v1/qualite/criteres/',
     "Critères des référentiels qualité (CAMES / ANAQ-Sup)."),
    ("Plans d'amélioration", 'QUALITY', '/api/v1/qualite/plans-amelioration/',
     "Plans d'amélioration qualité rattachés à un critère."),

    # ── Risques ──────────────────────────────────────────────────────────────
    ('Cartographie des risques', 'RISKS', '/api/v1/risques/',
     "Risques identifiés (catégorie, gravité, probabilité, plan de mitigation)."),

    # ── COIP ─────────────────────────────────────────────────────────────────
    ('Partenaires COIP', 'COIP', '/api/v1/coip/partners/',
     "Partenaires de la Cellule Orientation Insertion Professionnelle."),
    ('Stages', 'COIP', '/api/v1/coip/internships/',
     "Stages étudiants (partenaire, dates, statut, note)."),
    ('Activités COIP', 'COIP', '/api/v1/coip/activities/',
     "Activités organisées par la COIP (conférences, ateliers, forums…)."),
    ('Alumni', 'COIP', '/api/v1/coip/alumni/',
     "Anciens diplômés (promotion, situation professionnelle actuelle)."),

    # ── Admissions ───────────────────────────────────────────────────────────
    ('Candidatures', 'ADMISSIONS', '/api/v1/admissions/',
     "Candidatures déposées sur le portail public d'admission et leur statut."),
]


def seed_catalog(apps, schema_editor):
    APIResource = apps.get_model('api_gateway', 'APIResource')
    db_alias = schema_editor.connection.alias
    for name, functionality, path, description in CATALOG:
        APIResource.objects.using(db_alias).get_or_create(
            endpoint_path=path,
            defaults={'name': name, 'functionality': functionality, 'description': description},
        )


def remove_catalog(apps, schema_editor):
    APIResource = apps.get_model('api_gateway', 'APIResource')
    db_alias = schema_editor.connection.alias
    APIResource.objects.using(db_alias).filter(
        endpoint_path__in=[c[2] for c in CATALOG]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('api_gateway', '0003_extend_functionality_choices'),
    ]

    operations = [
        migrations.RunPython(seed_catalog, remove_catalog),
    ]
