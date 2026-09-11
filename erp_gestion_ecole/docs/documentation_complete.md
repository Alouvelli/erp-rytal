<!-- meta:title=Documentation complète de la plateforme|subtitle=UniManager — Système de gestion académique universitaire (multi-instituts)|org=UniManager / RYTAL|version=1.0|date=29/08/2026|footer=Documentation complète — diffusion restreinte -->

# 1. Présentation générale

## 1.1 Objet de la plateforme

**UniManager** (moteur applicatif *RYTAL*) est une application web de gestion
académique et administrative destinée à l'enseignement supérieur. Elle couvre
l'intégralité du cycle de vie d'un établissement : admission des candidats,
inscription et scolarité des étudiants, emplois du temps, émargement des
séances, notes et bulletins, gestion financière (scolarité, honoraires,
budget, caisse), ressources humaines, qualité, risques, plan stratégique,
achats, relations extérieures et insertion professionnelle.

La plateforme est **multi-instituts** : une seule installation héberge
plusieurs établissements (« instituts »), chacun disposant de sa propre base
de données isolée, de sa configuration, de sa charte visuelle et de ses
utilisateurs.

## 1.2 Publics visés

| Public | Usage principal |
|--------|-----------------|
| Super Administrateur | Exploite la plateforme, crée et administre les instituts |
| Administrateur d'institut / Assistante DG | Paramètre un institut, gère ses utilisateurs |
| Directions (Études, Financière, RH, Communication, Service Communauté, Qualité) | Pilotage métier de leur périmètre |
| Chef de département / Assistante | Gestion pédagogique d'un ou plusieurs départements |
| Enseignant | Émargement, cahier de texte, notes, honoraires, supports |
| Étudiant | Planning, notes, absences, dossier, paiements, orientation |
| Comptable / Trésorier Général / Caissier | Scolarité, encaissements, caisse, clôtures |
| Contrôleur interne | Supervision transverse d'un ou plusieurs instituts |
| Contrôle Accueil | Pointage d'entrée des étudiants et du personnel |
| Candidat | Candidature et inscription en ligne via le portail public |

## 1.3 Principes directeurs

- **Pas d'interface d'administration Django générique** (`/admin/` est
  volontairement désactivé). Toute la gestion passe par des rôles applicatifs
  dédiés et des écrans métier.
- **Isolation des données par institut** : une base PostgreSQL par institut,
  plus une base maître (`default`) pour les données partagées (comptes,
  configuration des instituts, journal d'audit, activation).
- **Verrou d'activation global** : rien n'est accessible tant que la
  plateforme n'a pas été activée par un code (voir chapitre 7).
- **Traçabilité** : journal d'audit, événements de sécurité, sauvegardes.
- **Langue et localisation** : français, fuseau `Africa/Dakar`, dates
  `JJ/MM/AAAA`, devise FCFA.

---

# 2. Concepts clés

## 2.1 Institut (multi-tenant)

Un **institut** correspond à un établissement. Techniquement il est représenté
par :

- un objet `Faculty` (identité : nom, code) dans la base maître ;
- un objet `InstitutConfig` (paramétrage complet : sigle, slogan, logo,
  coordonnées, dirigeants, préfixe de matricule, articles de contrat…) ;
- une **base de données PostgreSQL dédiée** (`db_rytal_<code>`), créée
  automatiquement à la création de l'institut ;
- un bloc de configuration ajouté automatiquement au fichier `.env`
  (`DB_RYTAL_<CODE>_NAME/HOST/PORT/USER/PASSWORD`).

Chaque requête est routée vers la bonne base selon le profil de
l'utilisateur connecté (voir chapitre 3.4).

## 2.2 Abonnement et suspension

Chaque institut possède des **abonnements** (`AbonnementInstitut`) avec une
date de fin. Si l'institut est marqué inactif (`actif = False`) **ou** si
aucun abonnement actif n'est en cours, l'accès est bloqué pour tous les
utilisateurs de cet institut : ils sont déconnectés et redirigés vers une
page de suspension. **Seul le Super Administrateur global reste toujours
autorisé** (voir `InstitutSuspensionMiddleware`).

## 2.3 Départements et directions

- **Département** (`Department`) : unité pédagogique rattachée à un institut,
  contenant filières, classes et étudiants.
- **Direction** (`Direction`) : unité administrative (Direction des Études,
  Direction Administrative et Financière, etc.) à laquelle est rattaché le
  personnel non enseignant.

Un sélecteur en haut de page permet aux profils de gestion de choisir le
département sur lequel ils travaillent (ou de filtrer les données).

## 2.4 Structure académique

```
Institut (Faculty)
 └── Département (Department)
      └── Filière (Program)  ── rattachée à un Niveau (Level)
           └── Classe (Class) ── rattachée à une Année académique
                └── Semestre (Semester)
                     └── Module / EC (Subject : CM / TD / TP, coefficient, crédits ECTS)
```

Les **maquettes pédagogiques** regroupent les EC en **Unités d'Enseignement
(UE)** pour le calcul des moyennes et la génération des bulletins.

## 2.5 Rôles

La plateforme définit une trentaine de rôles (`accounts.Role`). Ils sont
regroupés fonctionnellement — voir la matrice complète au chapitre 6.

---

# 3. Architecture technique

## 3.1 Vue d'ensemble

| Couche | Technologie |
|--------|-------------|
| Langage / framework | Python 3.12, Django 5.1 |
| API REST | Django REST Framework 3.15, JWT (SimpleJWT), drf-spectacular (OpenAPI) |
| Base de données | PostgreSQL 16 — une base maître + une base par institut |
| Tâches asynchrones | Celery 5.4 + Redis 7 (worker + beat) |
| Frontend | Templates Django + Bootstrap 5.3, Bootstrap Icons, FullCalendar, Chart.js, DataTables |
| Documents | ReportLab (PDF), python-docx (Word), openpyxl / XlsxWriter (Excel) |
| QR codes | bibliothèque `qrcode` (cartes étudiant/personnel, émargement par QR) |
| Assistant IA | RYTAL — API Anthropic Claude (`anthropic`) |
| Fichiers statiques | WhiteNoise |
| Serveur WSGI | Gunicorn |
| Reverse proxy | Nginx (TLS) |
| Conteneurisation | Docker, Docker Compose |

## 3.2 Organisation du code

```
erp_gestion_ecole/
├── academic_core/
│   ├── apps/                 # ~25 applications Django métier
│   │   ├── accounts/         # Auth, rôles, audit, activation plateforme
│   │   ├── academic_structure/ # Instituts, départements, filières, classes, semestres, config
│   │   ├── admissions/       # Candidatures & inscription en ligne (portail public)
│   │   ├── teachers/         # Enseignants, contrats, grades
│   │   ├── students/         # Étudiants, inscriptions, échéances, abandons
│   │   ├── subjects/         # Modules / EC
│   │   ├── rooms/            # Bâtiments & salles
│   │   ├── timetable/        # Emplois du temps, conflits, cahier de texte, supports
│   │   ├── attendance/       # Émargement, présences, alertes d'absence, plans de cours
│   │   ├── grades/           # Évaluations, notes, moyennes, UE, bulletins, conseil, réclamations
│   │   ├── cancellations/    # Annulations & reports de cours
│   │   ├── accounting/       # Scolarité, honoraires, caisse, budget, dépenses, clôtures
│   │   ├── hr/               # Personnel, pointage, congés, contrats, paie, discipline, stages
│   │   ├── community_service/# Service à la communauté
│   │   ├── coip/             # Orientation & insertion pro., alumni, partenariats, stages
│   │   ├── strategic_plan/   # Plan stratégique, PTA, projets, jalons, livrables
│   │   ├── indicators/       # Indicateurs de pilotage / Balanced Scorecard
│   │   ├── procurement/      # Achats : fournisseurs, appels d'offres, commandes, factures
│   │   ├── quality/          # Critères qualité, auto-évaluation, plans d'amélioration
│   │   ├── risks/            # Cartographie et suivi des risques
│   │   ├── api_gateway/      # Catalogue d'API, demandes et clés d'accès externes
│   │   ├── notifications/    # Notifications internes + email
│   │   ├── reports/          # Générateurs de documents (PDF / Excel)
│   │   ├── dashboard/        # Tableaux de bord par rôle
│   │   └── chatbot/          # Assistant RYTAL
│   ├── middleware.py         # Routage multi-tenant, activation, suspension, feature gates
│   ├── db_router.py          # Routeur de base de données par institut
│   ├── tenant_databases.py   # Découverte / enregistrement dynamique des bases instituts
│   ├── templates/  static/  media/  locale/
├── config/
│   ├── settings/  (base.py, development.py, production.py)
│   ├── urls.py    celery.py   wsgi.py
├── nginx/         docker/     ssl/
├── docs/          # cette documentation
├── manage.py  run.py  run_https.py
├── requirements.txt  requirements-dev.txt
└── docker-compose.yml  Dockerfile
```

## 3.3 Chaîne de middlewares

L'ordre est significatif (`config/settings/base.py`) :

1. `SecurityMiddleware`, `WhiteNoiseMiddleware`, `CorsMiddleware` — standard.
2. `SessionMiddleware`, `CommonMiddleware`, `CsrfViewMiddleware` — standard.
3. **`ResetDBMiddleware`** — réinitialise le routeur de base au début de
   chaque requête et restaure la base de l'institut depuis la session
   (`_auth_db`), avec auto-guérison si l'alias est mort.
4. **`PlatformActivationMiddleware`** — bloque toute la plateforme tant que
   le code d'activation n'a pas été validé (voir chapitre 7).
5. `AuthenticationMiddleware`, `MessageMiddleware`, `XFrameOptionsMiddleware`.
6. **`AuditMiddleware`** — journalise les actions des utilisateurs.
7. **`InstitutSuspensionMiddleware`** — bloque les instituts suspendus /
   expirés.
8. **`DepartmentMiddleware`** — résout `request.active_faculty` /
   `request.active_department` et **active la base de données de l'institut**.
9. **`FeatureGateMiddleware`** — empêche l'accès aux vues dont l'onglet ou la
   fonctionnalité a été désactivé pour l'institut.
10. **`NoCacheMiddleware`** — empêche la mise en cache des pages
    authentifiées (sécurité du bouton « précédent »).

## 3.4 Routage multi-base

- La base **`default`** contient les modèles « maîtres » : `auth`,
  `accounts` (`User`, `Role`, `AuditLog`, `PlatformActivation`…),
  `Faculty`, `InstitutConfig`, `AbonnementInstitut`, jetons.
- Chaque **institut** a sa base `db_rytal_<code>` contenant toutes les
  données opérationnelles (structure, étudiants, notes, comptabilité…).
- `InstitutRouter` (`academic_core/db_router.py`) aiguille chaque modèle
  selon un thread-local positionné par les middlewares.
- `discover_tenant_databases()` lit les blocs `DB_RYTAL_*` du `.env` au
  démarrage ; `register_tenant_db()` enregistre à chaud une base créée par
  un autre worker.
- `MultiDBAuthBackend` authentifie un utilisateur d'abord dans `default`
  puis dans la base de son institut ; le mot de passe est synchronisé entre
  les deux copies pour éviter les déconnexions fantômes.

## 3.5 Modèle d'authentification

- `AUTH_USER_MODEL = accounts.User` (hérite de `AbstractUser`).
- Connexion par identifiant + mot de passe ; option « se souvenir de moi ».
- `must_change_password` force le changement au premier accès.
- JWT pour l'API (`/api/v1/accounts/token/`), sessions pour l'interface web.
- Clé d'API pour les accès externes (`api_gateway`).
- Politique de mot de passe : longueur minimale 8, validators Django
  standard ; hachage PBKDF2.

---

# 4. Modèle de données (synthèse par domaine)

Cette section résume les entités principales. Les noms entre parenthèses sont
les classes du modèle Django.

## 4.1 Comptes & sécurité (`accounts`)

| Entité | Rôle |
|--------|------|
| `User` | Compte : rôle, département, direction, institut administré, matricule employé, jeton QR de pointage, avatar, `must_change_password` |
| `Role` | ~30 rôles applicatifs (liste au chapitre 6) |
| `Direction` | Direction administrative rattachée à un institut |
| `ControllerInstitut` | Rattachement d'un contrôleur interne à plusieurs instituts |
| `AuditLog` / `AuditBackup` | Journal d'audit et ses sauvegardes |
| `SecurityEvent` | Échecs de connexion, tentatives de force brute (avec sévérité) |
| `PasswordResetToken` / `EmailVerificationToken` | Jetons à usage unique |
| `PlatformActivation` / `PlatformActivationResetToken` | Verrou d'activation global |

## 4.2 Structure académique (`academic_structure`)

`AcademicYear`, `Faculty` (institut), `Department`, `Program` (filière),
`Level` (niveau), `Semester`, `Class`, `BulletinConfig`, `InstitutConfig`,
`InstitutEmailConfig`, `InstitutPaymentConfig`, `AbonnementInstitut`,
`ContratArticle`, `InstitutFiliation`, `ArchivedInstitutDatabase`,
`InstitutDisabledTab` / `InstitutDisabledFeature` (feature gates),
`DiplomaSupplementConfig`.

## 4.3 Enseignants & étudiants

- **`teachers`** : `Teacher` (statut permanent / vacataire, grade),
  `ContratEnseignant`, `Grade`.
- **`students`** : `Student` (état civil, matricule, rôle de responsable de
  classe), `Enrollment` (inscription : statut `PENDING` →
  `PENDING_CAISSE` → `VALIDATED` / `REJECTED` / `ABANDONED` / `SUSPENDED`,
  type nouvelle / réinscription, montant versé, référence de paiement),
  `PaymentInstallment` (échéances de scolarité).

## 4.4 Enseignements & planning

- **`subjects`** : `Subject` (EC — type CM/TD/TP, coefficient, crédits,
  volumes horaires CM/TD/TP/TPE).
- **`rooms`** : `Building`, `Room` (capacité, équipements).
- **`timetable`** : `TimetableEntry` (séance planifiée), `TimetableConflict`
  (détection automatique de conflits salle / enseignant / classe),
  `SessionLog` (cahier de texte), `CourseSupport` (support de cours partagé,
  purge automatique après 72 h), `PlanningHoliday` (suspension de planning).

## 4.5 Émargement & assiduité (`attendance`)

`AttendanceSheet` (fiche d'émargement : brouillon → signée → validée /
rejetée), `StudentAttendance` (présence par étudiant et par séance),
`SubjectProgress` (avancement d'un EC), `ExtraSessionRequest` (demande de
séances supplémentaires), `AbsenceAlertConfig` / `StudentAbsenceAlert`
(seuils et alertes), `CoursePlan` / `CoursePlanSession` (plan de cours).

## 4.6 Notes & bulletins (`grades`)

`EvaluationType`, `Evaluation` (verrouillable), `Grade`, `SubjectAverage`,
`SemesterAverage`, `UniteEnseignement` (maquette), `Bulletin` +
`BulletinUEResult` / `BulletinECResult`, `ECValidation` (Examens & Concours),
`GradeComplaint` (réclamation de note).

## 4.7 Comptabilité & finances (`accounting`)

Scolarité (`FraisGenerauxNiveau`, `FraisMensuelClasse`,
`AcademicYearDistribution`, `PaymentInstallment`), honoraires enseignants
(`HourlyRate`, `TeacherHonoraire`, `HonoraireBudgetLine` /
`HonoraireBudgetMonth`), caisse (`CaissePayment`, `PaymentProof`,
`OnlinePaymentTransaction`, `CaisseMovement`), plan comptable
(`CompteComptable`), budget (`SourceFinancement`, `LigneBudgetaire`,
`BudgetRectificatif`, `EngagementBudgetaire`, `DemandeDepense`), clôtures
(`AccountingClosure`, `ClosureEmailConfig`), bourses (`PartenaireBourse`).

## 4.8 Ressources humaines (`hr`)

`FichePersonnel`, `StaffPresence` (pointage), `DemandeConge`, `Contract` /
`ContractAmendment`, `Assignment` (carrière), `DisciplinaryCase`,
`EvaluationCampaign` / `Evaluation` / `EvaluationObjective`, `Mission`,
`Interim`, `Handover`, `Internship`, `Onboarding` / `OnboardingTask`,
`RecruitmentRequest` / `Candidate`, `Document` / `DocumentRequest`,
`SalaireConfig` / `BulletinSalaire`, `AccueilScanEvent` (contrôle accueil).

## 4.9 Autres domaines

| App | Entités clés |
|-----|--------------|
| `admissions` | `Candidature` (workflow de candidature), `CandidatureDocument` |
| `community_service` | `CommunityServiceActivity` |
| `coip` | `Alumni`, `Partner` / `Partnership`, `InternshipOffer` / `Internship`, `EducationalVisit`, `Activity`, `RecommendationRequest`, `OrientationSession`, `Opportunity` / `JobApplication`, `Report` |
| `strategic_plan` | `CadrageStrategique`, `AxeStrategique`, `ObjectifStrategique`, `Programme`, `Projet`, `Activite`, `Jalon`, `Livrable`, `PlanTravailAnnuel` |
| `indicators` | `Indicateur`, `ValeurIndicateur` |
| `procurement` | `Fournisseur`, `DemandeAchat`, `AppelOffres`, `OffreFournisseur`, `CommandeAchat`, `ReceptionAchat`, `FactureAchat`, `PaiementAchat` |
| `quality` | `CritereQualite`, `AutoEvaluation`, `PlanAmelioration` |
| `risks` | `Risque`, `SuiviRisque` |
| `api_gateway` | `APIResource`, `APIAccessRequest`, `APIAccessGrant` |
| `notifications` | `Notification` |
| `chatbot` | `ChatConversation`, `ChatMessage` |

---

# 5. Modules fonctionnels

## 5.1 Tableau de bord (`/dashboard/`)

Écran d'accueil après connexion. Le contenu est **spécifique au rôle** :
indicateurs Super Admin (nombre d'instituts, d'utilisateurs), synthèse
pédagogique (chef de département), recouvrement et caisse (comptable /
trésorier / caissier), suivi qualité (CIAQ), planning du jour (enseignant),
notes et absences (étudiant), etc.

## 5.2 Emplois du temps (`/timetable/`)

- Création / édition de séances avec **détection automatique de conflits**
  (salle, enseignant, classe occupés simultanément).
- Vue calendrier (FullCalendar), API `events`, recherche de salles libres.
- **Permutation de salles** entre deux séances.
- **Suspension de planning** (jours fériés, congés) avec détection des
  séances impactées.
- Export **PDF / Word / Excel** ; envoi du planning par email aux étudiants
  d'une classe ou à un enseignant.
- **Cahier de texte** (`SessionLog`) : saisie du contenu réalisé par séance,
  validation par le responsable, export PDF / Word.
- **Supports de cours** : partage de fichiers par l'enseignant, téléchargement
  par les étudiants, purge automatique après 72 h.

## 5.3 Émargement (`/attendance/`)

- Génération automatique des **fiches d'émargement** (tâche quotidienne 5 h).
- Signature électronique par l'enseignant, **validation** ou **rejet** par le
  responsable.
- Saisie des présences étudiant par séance ; **émargement par QR code**
  (l'étudiant scanne un QR affiché en séance : `checkin` / `checkin-auth`).
- **Marquage automatique « Absent »** des non-pointés en fin de séance
  (tâche toutes les 5 min).
- **Justifications d'absence** : dépôt par l'étudiant, revue par
  l'administration.
- **Seuils d'alerte d'absence** par département ; alertes email au tuteur, au
  chef de département et à l'assistante quand un étudiant dépasse le seuil.
- **Modules planifiés** et **plans de cours** : suivi de l'avancement de
  chaque EC.
- **Demandes de séances supplémentaires** (workflow demande / revue).
- Export des fiches en **PDF / Word**.

## 5.4 Notes, moyennes et bulletins (`/grades/`)

- **Évaluations** : création, saisie des notes (écran de saisie ou import
  CSV via un modèle), **verrouillage** d'une évaluation.
- Calcul des **moyennes par EC**, **par UE** et **semestrielles**.
- **Référentiel des maquettes** : définition des UE et affectation des EC,
  duplication d'une maquette d'un semestre à l'autre.
- **Bulletins** : génération par classe et par semestre, prévisualisation,
  publication, export **PDF individuel** ou **archive ZIP**, export Excel des
  notes.
- **Tableau de conseil de classe** : synthèse par classe/semestre, export
  Excel / PDF / Word.
- **Rapport annuel de la direction**, **suppléments de diplôme**.
- **Réclamations de notes** (`GradeComplaint`) : dépôt par l'étudiant, suivi.
- **Examens & Concours** (`ECValidation`) : validation d'EC par le Chargé des
  Examens & Concours.
- **Clôture de session** (normale / rattrapage) par semestre, avec
  ré-ouverture possible.
- **Rattrapages**.

## 5.5 Étudiants & scolarité (`/students/`)

- Création individuelle ou **import en masse** ; génération automatique du
  **matricule** et des identifiants de connexion.
- **Réinscriptions**, **changement de filière** (avec fiche PDF),
  **abandons** et **suspensions d'inscription** (avec réactivation).
- **Dossier étudiant** complet, listes par classe, **cartes d'apprenant**
  avec QR (`student_card_pdf`), **fiche d'inscription PDF**.
- **Attestation de passage** ; **carte de présence** / pointage.
- Nomination d'un **responsable de classe** et d'un **adjoint** (droits
  étendus sur leur classe).
- **Contrôle Accueil** : scan des cartes étudiant à l'entrée
  (`controle_scan`, poll temps réel).
- Tâche quotidienne (6 h) : **suspension des comptes impayés** après le 10 du
  mois, réactivation automatique au solde.

## 5.6 Enseignants (`/teachers/`)

Fiches enseignants (permanent / vacataire, grade), **contrats enseignants**,
rattachement aux modules, coordonnées, statut. Côté enseignant : « Mes
modules », « Mon contrat », « Mes honoraires », « Séances supplémentaires »,
« Mes supports de cours ».

## 5.7 Structure & salles (`/structure/`, `/rooms/`, `/subjects/`)

Gestion des **années académiques**, **instituts**, **départements**,
**filières**, **niveaux**, **classes**, **semestres**, **bâtiments et
salles**, **modules (EC)**. Écrans de configuration de l'institut (identité,
emails, paiement en ligne, supplément de diplôme).

## 5.8 Annulations / reports (`/cancellations/`)

Demande d'annulation ou de report d'une séance, validation, reprogrammation,
notifications automatiques aux parties concernées.

## 5.9 Comptabilité & finances (`/accounting/`, `/hr/`)

- **Scolarité** : barèmes de frais par niveau et par classe, **répartition
  sur l'année académique**, échéanciers, **validation des inscriptions**
  (workflow avec passage en caisse), **preuves de paiement**, certificats et
  attestations (inscription, passage, réussite).
- **Recouvrement** : taux de recouvrement, suivi des **boursiers** et des
  **partenaires de bourse**, gestion des frais de **soutenance**.
- **Honoraires enseignants** : **taux horaires**, calcul mensuel et annuel,
  **budget honoraires mensuels**, exports PDF / Word / Excel.
- **Caisse** : entrées / sorties, **état journalier**, **clôtures
  comptables** (avec envoi d'email), plan comptable, **demandes de dépense**.
- **Pilotage budgétaire** : lignes budgétaires, engagements, rectificatifs,
  sources de financement, suivi par direction.
- **Paie** (module RH) : configuration salariale, génération des **bulletins
  de salaire**.

## 5.10 Ressources humaines (`/hr/`)

Tableau de bord RH ; **gestion du personnel** (fiches, archivage) ;
**pointage** (du jour, listes, rapport mensuel PDF / Word, export Excel,
pointage par QR) ; **congés** (demande / revue) ; **discipline** ;
**évaluations** (campagnes, objectifs) ; **missions**, **intérims**,
**passations de service** ; **stages** ; **intégration (onboarding)** ;
**recrutement** ; **cartes du personnel** avec QR ; **documents &
attestations RH**.

## 5.11 Admissions — portail public (`/admission-<code>/`, `/candidat/`)

- **Portail captif par institut** : catalogue de filières, présentation des
  départements, création de compte candidat, dépôt de **candidature** en
  ligne avec pièces justificatives.
- **Espace candidat** : suivi du dossier, statut, inscription en ligne,
  paiement.
- Côté interne : liste et détail des candidatures, gestion des **comptes
  candidats** (modification, relance, suppression), édition du contenu des
  filières, **fenêtres de dates d'inscription** par département.

## 5.12 Service à la communauté (`/service-communaute/`)

Enregistrement des **activités de service à la communauté**, rapport
d'activités.

## 5.13 COIP — Orientation & insertion professionnelle (`/coip/`)

Tableau de bord ; **Alumni** (annuaire, événements de carrière) ;
**Partenariats** (partenaires, contacts, conventions, historique de
collaboration) ; **offres et suivis de stage** ; **séances d'orientation** ;
**recommandations** (workflow de demande) ; **opportunités** et
**candidatures** ; **activités COIP** et **sorties pédagogiques** (avec
participants et photos) ; **rapports** ; **archives**. Côté étudiant : « Mes
recommandations », « Mes séances d'orientation », opportunités, activités.

## 5.14 Plan stratégique & indicateurs (`/plan-strategique/`, `/indicateurs/`)

Cadrages et **axes stratégiques**, **objectifs**, **programmes**,
**projets** (équipe, jalons, livrables, sous-activités), **Plan de Travail
Annuel (PTA)** par direction, **indicateurs** de pilotage et **Balanced
Scorecard**.

## 5.15 Achats (`/achats/`)

**Fournisseurs**, **demandes d'achat**, **appels d'offres** et **offres
fournisseurs**, **commandes**, **réceptions**, **factures & paiements**.

## 5.16 Qualité & risques (`/qualite/`, `/risques/`)

**Critères qualité**, **auto-évaluations**, **plans d'amélioration** ;
**cartographie des risques** (matrice) et **suivi des risques**.

## 5.17 API de consommation (`/api-consommation/`)

Catalogue des API exposées, **demandes d'accès** externes, **accès
accordés** (clés d'API), suivi de consommation.

## 5.18 Notifications (`/notifications/`)

Notifications internes (badge « non lues » dans la barre) doublées d'emails.
Signalement rapide « Absence / Retard enseignant ».

## 5.19 Assistant RYTAL (`/chatbot/`)

Assistant conversationnel (API Anthropic Claude) accessible depuis la barre
latérale : historique de conversation, envoi de message, réinitialisation.

## 5.20 Rapports (`/reports/`)

Point d'entrée transversal : bulletins PDF, relevé horaire enseignant PDF,
rapport d'absences PDF, export Excel des notes et de l'emploi du temps.

---

# 6. Rôles et permissions

## 6.1 Liste des rôles (`accounts.Role`)

| Code | Libellé | Périmètre |
|------|---------|-----------|
| `ADMIN` | Administrateur (Super Admin) | Toute la plateforme, tous les instituts |
| `INST_ADMIN` | Administrateur d'institut | Un institut |
| `SI_ADMIN` | Administrateur du SI | Un institut (supervision, audit) |
| `ASSISTANTE_DG` | Assistante du Directeur Général | Un institut |
| `ADMIN_DIRECTION` | Administrateur de direction | Une direction |
| `ADMIN_DE` | Directeur des Études | Direction des Études |
| `ADMIN_DAF` | Directeur Administratif et Financier | Direction Financière |
| `ADMIN_COM` | Administrateur Direction (Communication) | Communication / admissions |
| `ADMIN_RH` | Directeur des Ressources Humaines | RH |
| `ADMIN_SC` | Responsable Service à la Communauté | Service Communauté |
| `ASSISTANTE_DE` / `ASSISTANTE_DIRECTION` | Assistantes de direction | Support direction |
| `CIAQ` | Cellule Interne d'Assurance Qualité | Qualité, indicateurs |
| `COIP` / `ASSISTANTE_COIP` | Orientation & Insertion Pro. | Module COIP |
| `CONTROLEUR` | Contrôleur interne | Un ou plusieurs instituts (lecture transverse) |
| `RESPONSABLE` | Chef de Département | Département(s) de l'institut |
| `ASSISTANTE` | Assistante de département | Département(s) |
| `RESPONSABLE_CLASSE` / `ADJOINT_RESPONSABLE_CLASSE` | Responsable / adjoint de classe | Une classe |
| `COMPTABLE` | Comptable | Finances de l'institut |
| `TRESORIER_GENERAL` | Trésorier Général | Trésorerie, clôtures |
| `CAISSIER` | Caissier | Caisse, encaissements |
| `CHARGE_EXAMENS_CONCOURS` | Chargé des Examens & Concours | Validation d'EC |
| `ENSEIGNANT` | Enseignant | Ses modules et classes |
| `ETUDIANT` | Étudiant | Son dossier |
| `CONTROLE_ACCUEIL` | Contrôle Accueil | Pointage d'entrée |
| `CANDIDAT` | Candidat | Portail d'admission uniquement |

## 6.2 Regroupements techniques (méthodes de `User`)

- `is_super_admin()` → `ADMIN` **sans** rattachement institut : accès total,
  jamais bloqué par suspension ni feature gate.
- `is_inst_admin()` → `INST_ADMIN`, `SI_ADMIN`, `ASSISTANTE_DG`, `CONTROLEUR`.
- `is_admin_direction()` → rôles `ADMIN_*` de direction + assistantes + COIP.
- `is_responsable()` → `RESPONSABLE`, `ASSISTANTE` (droits sur tout
  l'institut, sélection de département par confort).
- `is_responsable_classe()` → responsable / adjoint de classe, **ou** un
  étudiant nommé sur sa propre classe (cumul de droits).
- `is_comptable()` → `COMPTABLE`, `TRESORIER_GENERAL`, `CAISSIER`.
- `is_enseignant()`, `is_etudiant()`, `is_controle_accueil()`,
  `is_candidat()` → rôles isolés.
- `can_manage_dept()` → admin, inst-admin, responsable, assistante.
- `can_manage_pta()` → rôles autorisés à définir un Plan de Travail Annuel.

## 6.3 Visibilité des menus

La barre latérale (`templates/base/base.html`) affiche chaque section selon
le rôle. Exemples :

- **Super Admin** : Les Institutions, Admins d'Institut, Contrôleurs
  multi-instituts, Code d'activation, Archives d'instituts.
- **Enseignant** : Planning, Émargements, Mes modules, Cahier de texte, Mes
  honoraires, Mon contrat, Séances supplémentaires, Mes supports, ma carte.
- **Étudiant** : Tableau de bord, Ma carte d'apprenant, Planning, Mes
  absences, Supports de cours, Notes, Attestation de passage, Mon dossier,
  Orientation & Insertion Pro.
- **Comptable / Trésorier / Caissier** : Direction Financière (honoraires,
  mensualités, soutenance, recouvrement, boursiers, validation inscription,
  caisse, état journalier, clôtures, comptes comptables, demandes de dépense,
  rapports financiers).
- **Chef de département / Assistante** : Planning & Émargement, Notes &
  Évaluations, Scolarité, Inscriptions, Enseignants, Étudiants, Rapports,
  Candidatures en ligne.

Une fonctionnalité **masquée** l'est aussi **au niveau des URL** grâce à
`FeatureGateMiddleware` (registre `feature_registry`) : un onglet désactivé
pour un institut renvoie vers le tableau de bord avec un message d'erreur.

---

# 7. Sécurité

## 7.1 Verrou d'activation de la plateforme

> **Mécanisme critique.** Il conditionne l'accès à *toute* la plateforme,
> tous instituts confondus, et il est protégé par une règle projet
> (`CLAUDE.md`) : aucune modification sans demande explicite **et**
> confirmation que le code d'activation en vigueur a été saisi.

**Principe.** Tant que la plateforme n'a jamais été activée,
`PlatformActivationMiddleware` redirige toute requête (authentifiée ou non)
vers la page `/accounts/plateforme/activer/`. Les seuls chemins exemptés sont
`/accounts/plateforme/*`, `/static/`, `/media/`, `/favicon`.

**Premier démarrage (`/accounts/plateforme/activer/`).** L'opérateur saisit :

1. le **code maître serveur** (`PLATFORM_MASTER_KEY`, variable
   d'environnement, jamais dans le dépôt) ;
2. un **code d'activation** de son choix (≥ 12 caractères), saisi deux fois.

Le code d'activation n'est **jamais stocké en clair** : seul un hash à sens
unique (PBKDF2, même mécanisme que les mots de passe) est conservé, ainsi
qu'un hash séparé des 10 premiers caractères (utilisé lors d'une
réinitialisation). Aucune opération de « déchiffrement » n'est possible.

**Anti force brute.** Après `MAX_ATTEMPTS = 4` tentatives échouées, la
vérification est bloquée `LOCKOUT_MINUTES = 24 h` sans même comparer le code.

**Rotation (`/accounts/plateforme/rotation/`).** Réservée au Super Admin
global. L'onglet est verrouillé par défaut : il faut d'abord saisir le code
**actuel** pour déverrouiller le formulaire (fenêtre de 5 minutes), puis
définir le nouveau code (≥ 12 caractères, saisi deux fois).

**Code oublié (`/accounts/plateforme/oubli/` → `/reset/<token>/`).**
Réservé au Super Admin global connecté. Envoie un lien de réinitialisation
**uniquement** aux adresses `PLATFORM_RESET_EMAIL_1` /
`PLATFORM_RESET_EMAIL_2` (variables d'environnement du serveur, absentes du
dépôt, de la base et de toute page web). Le lien est à usage unique, valable
60 minutes, avec un délai de 15 minutes entre deux demandes. Pour consommer
le lien, il faut **en plus** fournir les 10 premiers caractères de l'ancien
code (second facteur indépendant de la boîte mail).

**Limite honnête.** Cette protection est une politique applicative, pas une
garantie absolue : quiconque a un accès direct au système de fichiers ou à
la base peut contourner le mécanisme. Le hachage garantit seulement qu'on ne
peut pas *retrouver* le code, pas qu'on ne peut pas le *remplacer*.

## 7.2 Suspension d'institut

`InstitutSuspensionMiddleware` + contrôle à la connexion : un institut
inactif ou sans abonnement actif bloque tous ses utilisateurs (page 403 de
suspension), sauf le Super Admin global.

## 7.3 Journal d'audit et événements de sécurité

- `AuditMiddleware` + `AuditLog` : actions des utilisateurs (connexion,
  créations, modifications, suppressions) avec IP et user-agent.
- `SecurityEvent` : échecs de connexion (sévérité faible) et détection de
  **force brute** (≥ 5 échecs en 10 min depuis une IP → événement
  critique).
- **Sauvegardes d'audit** (`AuditBackup`) : export et purge du journal,
  téléchargement, rapport d'audit PDF, supervision DSI.

## 7.4 Autres mesures

- `NoCacheMiddleware` : pas de cache navigateur sur les pages authentifiées.
- CSRF activé, cookies `Secure` en production, `X-Frame-Options`.
- Rate limiting (`django-ratelimit`).
- Assainissement HTML des contenus riches (`bleach`).
- Séparation stricte des bases : une faille sur un institut n'expose pas les
  autres.
- Isolement du portail d'admission (compte `CANDIDAT` cantonné au portail).

---

# 8. Installation et configuration

## 8.1 Prérequis

- Python 3.12+
- PostgreSQL 16+ (un compte administrateur unique gère la base maître **et**
  toutes les bases instituts)
- Redis 7+
- (Production) Docker + Docker Compose, ou Gunicorn + Nginx

## 8.2 Installation locale (développement)

```
# 1. Environnement virtuel
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Linux / macOS

# 2. Dépendances
pip install -r requirements-dev.txt

# 3. Configuration
copy .env.example .env           # puis éditer .env
#   - POSTGRES_HOST=localhost
#   - POSTGRES_USER / POSTGRES_PASSWORD (compte admin PostgreSQL)
#   - PLATFORM_MASTER_KEY = valeur longue et aléatoire
#   - PLATFORM_RESET_EMAIL_1 / _2 = adresses de secours
#   - ANTHROPIC_API_KEY (assistant RYTAL, facultatif)

# 4. Base de données + compte initial
python run.py --setup            # migrate + rôles + superuser "admin"

# 5. Lancer le serveur
python run.py --port 8000
#   ou : python manage.py runserver --settings=config.settings.development
```

`run.py --setup` applique les migrations, crée les rôles de base
(`ADMIN`, `RESPONSABLE`, `ENSEIGNANT`, `ETUDIANT`) et un superutilisateur
`admin` si absent.

Pour un accès HTTPS sur le réseau local (utile pour l'émargement par QR
depuis un téléphone) : `python run_https.py 8443` (certificat auto-signé
généré dans `ssl/`).

## 8.3 Déploiement Docker

```
cp .env.example .env             # renseigner les valeurs de production
docker compose up -d --build
```

`docker-compose.yml` démarre six services :

| Service | Rôle |
|---------|------|
| `db` | PostgreSQL 16 (volume `postgres_data`) |
| `redis` | Redis 7 (broker Celery) |
| `web` | Django + Gunicorn (migrate + collectstatic au démarrage, 4 workers) |
| `celery_worker` | Worker Celery (concurrence 4) |
| `celery_beat` | Planificateur Celery (scheduler base de données) |
| `nginx` | Reverse proxy TLS (ports 80 / 443) |

Le `Dockerfile` est multi-étapes (`base` → `development` / `production`,
utilisateur non-root en production).

## 8.4 Premier accès

1. Ouvrir l'application → redirection vers **`/accounts/plateforme/activer/`**.
2. Saisir le **code maître serveur** (`PLATFORM_MASTER_KEY`) et définir le
   **code d'activation** (≥ 12 caractères).
3. Se connecter avec le compte `admin`.
4. Créer le premier **institut** (`/structure/instituts/creer/`) — sa base
   de données et son bloc `.env` sont générés automatiquement.
5. Créer l'**abonnement** de l'institut et l'activer.
6. Créer l'**Administrateur d'institut** (`/accounts/inst-admins/nouveau/`).

## 8.5 Variables d'environnement principales (`.env`)

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Clé secrète Django |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` ou `.development` |
| `ALLOWED_HOSTS` | Hôtes autorisés (séparés par des virgules) |
| `POSTGRES_DB` / `USER` / `PASSWORD` / `HOST` / `PORT` | Base maître + compte admin PostgreSQL |
| `POSTGRES_MAINTENANCE_DB` | Base de maintenance pour `CREATE DATABASE` (par défaut `postgres`) |
| `DB_RYTAL_<CODE>_*` | Blocs générés automatiquement, un par institut |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis |
| `EMAIL_HOST` / `PORT` / `HOST_USER` / `HOST_PASSWORD` / `DEFAULT_FROM_EMAIL` | SMTP |
| `DEV_FORCE_REAL_EMAIL` | En dev, force l'envoi réel (sinon console) |
| `CORS_ALLOWED_ORIGINS` | Origines autorisées pour l'API |
| `ANTHROPIC_API_KEY` | Assistant RYTAL |
| `PLATFORM_MASTER_KEY` | Code maître serveur (activation) — obligatoire en production |
| `PLATFORM_RESET_EMAIL_1` / `PLATFORM_RESET_EMAIL_2` | Adresses de réinitialisation du code d'activation |

---

# 9. Exploitation

## 9.1 Tâches planifiées (Celery beat)

| Tâche | Fréquence | Effet |
|-------|-----------|-------|
| `attendance.generate_daily_sheets` | Quotidien 5 h 00 | Génère les fiches d'émargement du jour |
| `attendance.auto_mark_absent_after_session` | Toutes les 5 min | Marque « Absent » les non-pointés en fin de séance |
| `attendance.check_student_absence_alerts_task` | Quotidien 7 h 00 | Alerte email tuteur / chef de département / assistante au-dessus du seuil |
| `attendance.check_absence_alerts` | Lundi 8 h 00 | Alerte absences excessives (hebdomadaire) |
| `attendance.remind_unsigned_sheets` | Quotidien 18 h 00 | Rappelle les fiches non signées |
| `students.check_tuition_deadlines` | Quotidien 6 h 00 | Suspend les comptes impayés après le 10 du mois, réactive au solde |
| `timetable.cleanup_expired_course_supports` | Toutes les heures | Supprime les supports partagés depuis plus de 72 h |
| `accounts.cleanup_expired_tokens` | Quotidien 2 h 00 | Purge les jetons expirés |

Lancement manuel (hors Docker) :

```
celery -A config.celery worker -l info
celery -A config.celery beat  -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## 9.2 Sauvegardes

- **Bases PostgreSQL** : `pg_dump` de la base maître **et** de chaque base
  `db_rytal_<code>` (script d'exploitation à planifier côté serveur).
- **Médias** : sauvegarder `academic_core/media/` (logos, avatars, pièces
  justificatives, supports, preuves de paiement).
- **Journal d'audit** : sauvegardes applicatives via `/accounts/audit/backups/`.
- Les instituts supprimés sont **archivés** (base renommée,
  `ArchivedInstitutDatabase`) et restaurables depuis
  `/accounts/instituts/archives/`.

## 9.3 Emails

Configuration SMTP globale dans `.env` ; configuration email **par institut**
(`InstitutEmailConfig`, écran « Mon Institut → Emails de notification »).
En développement, les emails s'affichent dans la console sauf
`DEV_FORCE_REAL_EMAIL=True`.

## 9.4 Fichiers statiques et médias

`collectstatic` au démarrage du conteneur `web` ; service par WhiteNoise
(statiques) et Nginx (médias). Volumes Docker `static_volume` /
`media_volume`.

## 9.5 Supervision

- Journaux Gunicorn / Celery sur la sortie standard des conteneurs.
- Healthchecks Docker sur `db` et `redis`.
- Écran **Supervision générale** (`/accounts/dsi/supervision/`) et **rapport
  d'audit** pour le SI Admin / Contrôleur.

---

# 10. API REST

## 10.1 Accès

- Base : `/api/v1/`
- Authentification : **JWT** (`/api/v1/accounts/token/`, en-tête
  `Authorization: Bearer <token>`), session, ou **clé d'API**
  (`api_gateway`).
- Permissions : authentification requise par défaut ; filtres et pagination
  DRF.

## 10.2 Documentation interactive

| URL | Contenu |
|-----|---------|
| `/api/schema/` | Schéma OpenAPI (drf-spectacular) |
| `/api/docs/` | Swagger UI |
| `/api/redoc/` | ReDoc |

## 10.3 Espaces de noms exposés

`/api/v1/` regroupe : `accounts/`, `timetable/`, `attendance/`, `grades/`,
`students/`, `teachers/`, `structure/`, `rooms/`, `subjects/`,
`cancellations/`, `notifications/`, `accounting/`, `hr/`,
`service-communaute/`, `plan-strategique/`, `indicateurs/`, `achats/`,
`qualite/`, `risques/`, `coip/`, `admissions/`.

## 10.4 Exemple

```
# Obtenir un jeton
curl -X POST https://<hote>/api/v1/accounts/token/ \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"<mot_de_passe>"}'

# Appeler une ressource protégée
curl -H "Authorization: Bearer <access_token>" \
     https://<hote>/api/v1/timetable/entries/
```

## 10.5 API de consommation externe

Les partenaires demandent un accès via `/api-consommation/` : l'administration
publie un **catalogue de ressources**, traite les **demandes d'accès** et
délivre des **clés d'API** (`APIAccessGrant`) dont la consommation est
suivie.

---

# 11. Annexes

## 11.1 Comptes par défaut (développement)

| Rôle | Identifiant | Mot de passe |
|------|-------------|--------------|
| Super Administrateur | `admin` | `Admin@1234` (à changer immédiatement) |

Les autres comptes sont créés depuis l'application. Réinitialiser un mot de
passe : `python manage.py changepassword <username>`.

## 11.2 URL principales

| Chemin | Usage |
|--------|-------|
| `/` | Redirige vers la connexion |
| `/accounts/login/` | Connexion |
| `/accounts/plateforme/activer/` | Activation initiale de la plateforme |
| `/accounts/plateforme/rotation/` | Rotation du code d'activation (Super Admin) |
| `/dashboard/` | Tableau de bord (selon rôle) |
| `/structure/instituts/` | Gestion des instituts (Super Admin) |
| `/admission-<code_institut>/` | Portail public d'admission d'un institut |
| `/candidat/` | Espace candidat |
| `/api/docs/` | Documentation API (Swagger) |

## 11.3 Glossaire

| Terme | Définition |
|-------|------------|
| EC | Élément Constitutif (module élémentaire : CM, TD ou TP) |
| UE | Unité d'Enseignement (regroupement d'EC pour le calcul des moyennes) |
| Maquette | Référentiel UE/EC d'une filière pour un semestre |
| Cahier de texte | Journal du contenu réellement enseigné par séance (`SessionLog`) |
| Émargement | Fiche de présence d'une séance, signée par l'enseignant et validée |
| CIAQ | Cellule Interne d'Assurance Qualité |
| COIP | Centre / Cellule d'Orientation et d'Insertion Professionnelle |
| PTA | Plan de Travail Annuel d'une direction |
| DAF | Direction Administrative et Financière |
| DE | Direction des Études |
| RYTAL | Moteur applicatif de la plateforme (et nom de l'assistant IA intégré) |
| Institut (tenant) | Établissement hébergé, avec sa base de données dédiée |
| Feature gate | Désactivation d'un onglet / d'une fonctionnalité pour un institut donné |

## 11.4 Références de fichiers

| Sujet | Fichier(s) |
|-------|-----------|
| Routage multi-tenant | `academic_core/db_router.py`, `academic_core/tenant_databases.py`, `academic_core/middleware.py` |
| Activation plateforme | `academic_core/apps/accounts/models.py` (`PlatformActivation`), `.../platform_activation.py`, `.../views.py`, `academic_core/middleware.py` |
| Rôles & permissions | `academic_core/apps/accounts/models.py` (`Role`, `User`) |
| Réglages | `config/settings/base.py`, `development.py`, `production.py` |
| Tâches planifiées | `config/celery.py` |
| Navigation / menus | `academic_core/templates/base/base.html` |
| Routes | `config/urls.py` + `academic_core/apps/*/urls.py` |
