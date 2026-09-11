<!-- meta:title=Guide d'utilisation de la plateforme|subtitle=UniManager — Prise en main pas à pas, par profil|org=UniManager / RYTAL|version=1.0|date=29/08/2026|footer=Guide d'utilisation — diffusion restreinte -->

# 1. Bien démarrer

## 1.1 Accéder à la plateforme

Ouvrez votre navigateur (Chrome, Firefox ou Edge à jour) et saisissez
l'adresse fournie par votre établissement. Vous arrivez sur la page de
**connexion**.

> Si vous voyez à la place la page « Activation de la plateforme », c'est que
> la plateforme n'a pas encore été mise en service : voir le chapitre 3
> (Super Administrateur).

## 1.2 Se connecter

1. Saisissez votre **identifiant** et votre **mot de passe**.
2. Cochez éventuellement « Se souvenir de moi » (déconseillé sur un poste
   partagé).
3. Cliquez sur **Se connecter**.

En cas d'oubli, utilisez le lien **« Mot de passe oublié »** : un lien de
réinitialisation vous est envoyé par email.

## 1.3 Première connexion

Si votre compte a été créé par un administrateur, la plateforme vous demande
de **changer votre mot de passe** avant d'aller plus loin. Choisissez un mot
de passe d'au moins 8 caractères, différent de vos informations
personnelles.

## 1.4 Comprendre l'écran

| Zone | Rôle |
|------|------|
| **Barre latérale gauche** | Menu principal, adapté à votre rôle |
| **Sélecteur de département** (en haut) | Pour les profils de gestion : choisir / filtrer le département de travail |
| **Cloche de notifications** | Notifications non lues |
| **Bouton RYTAL** | Assistant d'aide conversationnel |
| **Menu profil** (votre nom) | Mon profil, changer le mot de passe, se déconnecter |

## 1.5 Mettre à jour son profil

Menu profil → **Mon profil** : photo, téléphone, informations personnelles.
Menu profil → **Changer le mot de passe** à tout moment.

## 1.6 Notifications

La cloche affiche le nombre de messages non lus. Cliquez pour voir la liste
(émargements à valider, absences signalées, demandes à traiter…). La plupart
des notifications sont aussi envoyées par email.

## 1.7 Assistant RYTAL

Cliquez sur le bouton **RYTAL** en bas de la barre latérale pour poser une
question en langage naturel sur l'utilisation de la plateforme. Vous pouvez
réinitialiser la conversation à tout moment.

## 1.8 Se déconnecter

Menu profil → **Se déconnecter**. Fermez ensuite l'onglet sur un poste
partagé.

---

# 2. Navigation commune à tous les profils de gestion

## 2.1 Choisir le département de travail

Les chefs de département, assistantes, directions, comptables et contrôleurs
disposent en haut de page d'un **sélecteur de département**.

- Pour les rôles de gestion pédagogique, il définit le périmètre affiché.
- Pour le contrôleur, le comptable et le chargé des examens, il sert de
  **filtre** (« Filtrer par département »).

Tant qu'aucun département n'est choisi, certaines listes restent vides : une
fenêtre vous invite à en sélectionner un.

## 2.2 Exports

De nombreux écrans proposent des boutons d'export **PDF**, **Word** ou
**Excel** (planning, émargements, notes, bulletins, honoraires, pointage,
rapports financiers…). Le fichier est téléchargé immédiatement.

## 2.3 Recherche et filtres

Les listes offrent une recherche plein texte et des filtres (classe,
semestre, statut, période). Les tableaux sont triables par colonne.

---

# 3. Super Administrateur

Le Super Administrateur exploite la plateforme et administre l'ensemble des
instituts. Il n'est rattaché à aucun institut et n'est jamais bloqué par une
suspension.

## 3.1 Activer la plateforme (tout premier démarrage)

1. À la première ouverture, la plateforme affiche
   **« Activation de la plateforme »**.
2. Saisissez le **code maître serveur** (fourni à l'installation, variable
   `PLATFORM_MASTER_KEY`).
3. Choisissez un **code d'activation** d'au moins 12 caractères et
   saisissez-le deux fois.
4. Validez : la plateforme est activée définitivement. Connectez-vous avec
   le compte `admin`.

> Conservez le code d'activation dans un coffre-fort numérique. Il n'est
> **jamais** récupérable en clair.

## 3.2 Changer le code d'activation (rotation)

1. Menu → **Code d'activation** (`/accounts/plateforme/rotation/`).
2. Saisissez le **code actuel** pour déverrouiller le formulaire (valable
   5 minutes).
3. Saisissez le **nouveau code** (≥ 12 caractères) deux fois. Validez.

Après 4 tentatives erronées, l'accès à cette page est bloqué 24 heures.

## 3.3 Code d'activation oublié

1. Menu → Code d'activation → **« Code oublié »**.
2. Un lien est envoyé aux deux adresses de secours configurées côté serveur
   (valable 60 minutes, usage unique).
3. Ouvrez le lien, saisissez les **10 premiers caractères de l'ancien code**
   puis définissez un nouveau code.

## 3.4 Créer un institut

1. Menu → **Les Institutions** → **Créer un institut**
   (`/structure/instituts/creer/`).
2. Renseignez l'identité : nom, sigle, code (court, sans espace — il sert au
   nom de la base et au portail public), coordonnées, logo.
3. Validez : la **base de données de l'institut est créée automatiquement**
   ainsi que son bloc de configuration.

## 3.5 Gérer les abonnements d'un institut

1. Menu → Les Institutions → institut → **Abonnements**.
2. Créez un abonnement avec une **date de fin**. Sans abonnement actif,
   l'institut est bloqué pour ses utilisateurs.
3. Vous pouvez suspendre un institut (case « actif ») avec un motif.

## 3.6 Activer / désactiver des fonctionnalités par institut

Menu → Les Institutions → institut → **Fonctionnalités** : cochez les
onglets et fonctions à masquer pour cet institut. Le blocage s'applique
aussi aux URL directes.

## 3.7 Créer les administrateurs d'institut

1. Menu → **Admins d'Institut** → **Nouveau**.
2. Choisissez l'institut, renseignez l'identité et l'email.
3. Le compte est créé dans la base maître **et** dans la base de l'institut.
   L'administrateur reçoit ses identifiants et devra changer son mot de
   passe.

## 3.8 Contrôleurs internes multi-instituts

Menu → **Contrôleurs multi-instituts** : créez un contrôleur et rattachez-le
à plusieurs instituts. À la connexion, s'il en gère au moins deux, il choisit
l'institut à consulter.

## 3.9 Archives d'instituts

La suppression d'un institut **archive** sa base (elle n'est pas détruite).
Menu → **Archives d'instituts** : restaurer un institut archivé ou le
supprimer définitivement.

## 3.10 Supervision

- **Journal d'audit** (`/accounts/audit/`) : toutes les actions, filtrables
  par utilisateur ; sauvegardes et rapport PDF.
- **Supervision générale** (SI) : vue d'ensemble technique.

---

# 4. Administrateur d'institut / Assistante DG

Vous paramétrez un institut et gérez ses utilisateurs.

## 4.1 Configurer l'institut

Menu → **Configuration Institut** : identité complète, dirigeants (DG, DE),
préfixe de matricule, slogan, articles de contrat, statut juridique, année
de création.

- **Mon Institut → Emails de notification** : expéditeur et destinataires
  des emails automatiques.
- **Mon Institut → Paiement en ligne** : activer et paramétrer le paiement
  en ligne des candidats / étudiants.
- **Suppléments de diplôme** : modèle par filière.

## 4.2 Créer la structure académique

Dans l'ordre :

1. **Année académique** (`/structure/years/`).
2. **Départements** (`/structure/departments/`).
3. **Filières** rattachées à un département et à un niveau
   (`/structure/programs/`).
4. **Classes** rattachées à une filière et une année
   (`/structure/classes/`).
5. **Semestres** (`/structure/semesters/`).
6. **Bâtiments et salles** (`/rooms/`).
7. **Modules / EC** (`/subjects/`) : type (CM/TD/TP), coefficient, crédits,
   volumes horaires.

## 4.3 Gérer les utilisateurs

Menu → **Utilisateurs** (`/accounts/users/`) :

1. **Créer** un utilisateur : identité, email, **rôle**, département ou
   direction selon le rôle.
2. Le mot de passe initial est généré ; l'utilisateur le change à la
   première connexion.
3. **Modifier** / **désactiver** un compte ; réinitialiser son mot de passe.
4. **Directions** : créez les directions administratives et affectez-y le
   personnel.
5. **Non affectés** : liste des comptes sans département ni direction, à
   régulariser.

## 4.4 Nommer un chef de département

Créez (ou modifiez) un utilisateur avec le rôle **Chef de Département** et
affectez-lui le ou les départements concernés. L'**Assistante de
département** partage les mêmes droits.

## 4.5 Journal d'audit de l'institut

Menu → **Journal d'audit** : suivi des actions au sein de l'institut.

---

# 5. Directions (Études, Financière, RH, Communication, Service Communauté, Qualité, Contrôle interne)

Chaque direction accède à son périmètre via la section correspondante de la
barre latérale.

## 5.1 Direction des Études

- **Référentiel des Maquettes** : UE et affectation des EC, duplication d'un
  semestre à l'autre.
- **Gestion des Bulletins** : génération par classe/semestre,
  prévisualisation, publication.
- **Tableau de Conseil** : synthèse de conseil de classe (export Excel /
  PDF / Word).
- **Rapport Annuel de la Direction**, **Suppléments de diplôme**.
- **Réclamations de Notes** : traitement des contestations.
- **Rattrapages** et **clôture de session**.
- **Suivi budget Direction**.

## 5.2 Direction Administrative et Financière (DAF)

- **Pilotage budgétaire** : lignes budgétaires, engagements, rectificatifs,
  sources de financement, suivi par direction.
- **Balanced Scorecard** et indicateurs.
- Accès aux **rapports financiers** et à la **caisse**.

## 5.3 Direction des Ressources Humaines

Voir le chapitre 9 (RH).

## 5.4 Direction Communication

- **Candidatures en ligne** : suivi des dossiers déposés sur le portail.
- **Comptes candidats** : modification, relance, suppression.
- **Dates d'inscription** : ouverture / fermeture des fenêtres par
  département.

## 5.5 Service à la Communauté

Menu → **Service à la Communauté** : saisir les **activités**, produire le
**rapport d'activités**.

## 5.6 Qualité (CIAQ) et Risques

- **Critères qualité**, **auto-évaluations**, **plans d'amélioration**.
- **Matrice des risques** et **suivi des risques**.
- **Indicateurs** de pilotage.

## 5.7 Contrôleur interne

Vision transverse en lecture sur un ou plusieurs instituts : structure,
scolarité, finances, émargements, état journalier de caisse, clôtures,
rapports. Utilisez le **filtre par département** en haut de page.

## 5.8 Plan de Travail Annuel (PTA)

Les directions concernées voient l'entrée **Plan de Travail Annuel** :
saisissez vos axes, activités et lignes de PTA pour l'année.

---

# 6. Chef de département / Assistante de département

Vous gérez la vie pédagogique d'un ou plusieurs départements. Sélectionnez
le département en haut de page si besoin.

## 6.1 Emplois du temps

1. Menu → **Planning & Émargement → Emplois du temps**
   (`/timetable/`).
2. **Créer une séance** : classe, module, enseignant, salle, date, créneau.
   La plateforme **refuse les conflits** (salle, enseignant ou classe déjà
   occupés) et propose les salles libres.
3. **Permutation de salles** : échanger la salle de deux séances.
4. **Suspendre un planning** : déclarer une période sans cours (férié,
   congé). Les séances impactées sont listées.
5. **Exporter** le planning (PDF / Word / Excel) ou l'**envoyer par email**
   aux étudiants d'une classe ou à un enseignant.

## 6.2 Émargements

1. Menu → **Émargements** (`/attendance/`).
2. Suivez les fiches : **à signer**, **signées**, **validées**, **rejetées**.
3. **Valider** une fiche signée par l'enseignant, ou la **rejeter** avec un
   motif.
4. **Cahier de texte** : vérifier et **valider** le contenu saisi par
   l'enseignant pour chaque séance.
5. **Modules planifiés** : suivre l'avancement horaire de chaque EC.
6. **Justifications d'absences** : traiter les justificatifs déposés par les
   étudiants.
7. **Seuil d'alerte absences** : définir le pourcentage déclenchant les
   alertes automatiques pour le département.
8. **Séances supplémentaires** : approuver ou refuser les demandes des
   enseignants.

## 6.3 Notes & évaluations

1. Menu → **Notes & Évaluations** (`/grades/`).
2. Suivre les évaluations créées par les enseignants ; **verrouiller** une
   évaluation une fois les notes définitives.
3. **Import notes CSV** : téléchargez le modèle, complétez-le, importez-le.
4. **Calculer les moyennes** d'un semestre.
5. **Bulletins** : générer pour une classe/semestre, prévisualiser,
   **publier**, exporter en PDF (individuel ou archive ZIP).
6. **Tableau de Conseil** : préparer le conseil de classe.
7. **Réclamations de Notes** : instruire les contestations.

## 6.4 Scolarité et inscriptions

- **Gestion de la Scolarité** : barèmes, échéanciers.
- **Inscriptions & Liste étudiants** : inscrire, consulter, éditer.
- **Réinscriptions**, **Changement de filière** (fiche PDF), **Abandons**,
  **Suspensions d'inscription** (avec réactivation).
- **Attestation de passage**, **Dossiers étudiants**.

## 6.5 Enseignants

Menu → **Nouveau & Liste des Enseignants** : créer une fiche enseignant
(permanent / vacataire, grade), gérer les **contrats**, affecter aux
modules.

## 6.6 Candidatures (portail)

Menu → **Candidatures en ligne**, **Mes filières (portail)** (éditer la
présentation publique), **Comptes candidats**, **Dates d'inscription**.

## 6.7 Rapports

Menu → **Rapports & Exports** : bulletins, relevés horaires, rapports
d'absences, exports Excel.

---

# 7. Enseignant

## 7.1 Consulter son planning

Menu → **Planning** : vos séances à venir, par jour et par semaine.

## 7.2 Émarger une séance

1. Menu → **Émargements**.
2. Ouvrez la fiche de la séance concernée.
3. Renseignez les **présences des étudiants** (présent / absent / retard).
   Vous pouvez aussi afficher un **QR code de séance** : les étudiants le
   scannent pour pointer eux-mêmes.
4. **Signez** la fiche. Elle part en validation chez le responsable.

> Les étudiants non pointés sont automatiquement marqués « Absent » peu après
> la fin de la séance.

## 7.3 Remplir le cahier de texte

Menu → **Cahier de Texte** (ou **Mes séances**) : pour chaque séance,
décrivez le contenu réellement traité. Le responsable le valide ensuite.

## 7.4 Mes modules

Menu → **Mes modules** : la liste de vos EC par classe et semestre, avec
l'avancement horaire et le **plan de cours**.

## 7.5 Saisir des notes

1. Menu → **Notes & Évaluations → Créer une évaluation** (type, barème,
   date, classe, module).
2. **Saisir les notes** à l'écran, ou **importer** un fichier à partir du
   modèle fourni.
3. Quand tout est saisi, marquez **« Notes saisies »**. Le responsable
   verrouille l'évaluation.

## 7.6 Partager un support de cours

Menu → **Mes supports de cours → Partager** : déposez un fichier pour une
classe. Les étudiants le téléchargent depuis leur espace. Le support est
**supprimé automatiquement après 72 heures**.

## 7.7 Demander des séances supplémentaires

Menu → **Séances supplémentaires** : soumettez une demande (motif, volume).
Le responsable l'approuve ou la refuse.

## 7.8 Honoraires et contrat

- Menu → **Mes Honoraires** : détail mensuel et annuel de vos honoraires.
- Menu → **Mon Contrat** : votre contrat d'enseignant.

## 7.9 Signaler une absence / un retard

Menu → **Notifications → Absence / Retard enseignant** : informer
l'administration en cas d'empêchement.

## 7.10 Carte du personnel

Si vous êtes permanent : Menu → **Ma carte du personnel** / **Ma carte de
pointage** (QR), **Mes attestations**.

---

# 8. Étudiant

## 8.1 Tableau de bord

À la connexion : prochaines séances, moyennes, absences récentes,
informations de scolarité.

## 8.2 Planning

Menu → **Planning** : votre emploi du temps. Il peut vous être envoyé par
email par le département.

## 8.3 Mes absences

Menu → **Mes absences** : la liste de vos absences par séance. Pour chacune,
vous pouvez **déposer un justificatif** (motif + pièce jointe) ;
l'administration l'accepte ou le refuse.

## 8.4 Émarger par QR

En séance, si l'enseignant affiche un **QR code**, scannez-le avec votre
téléphone pour enregistrer votre présence. Connectez-vous si demandé.

## 8.5 Notes et bulletins

Menu → **Notes & Évaluations** : vos notes par module et vos moyennes. Les
bulletins publiés sont téléchargeables en PDF.

## 8.6 Réclamation de note

Depuis vos notes, ouvrez une **réclamation** en précisant le motif. Vous
suivez son traitement.

## 8.7 Supports de cours

Menu → **Supports de cours** : téléchargez les documents partagés par vos
enseignants (disponibles 72 h).

## 8.8 Mon dossier et mes documents

- Menu → **Mon dossier** : votre dossier étudiant.
- **Ma carte d'apprenant** (PDF avec QR), **Ma carte de pointage**.
- **Attestation de passage** quand elle est disponible.

## 8.9 Scolarité et paiements

Consultez le solde de votre scolarité et vos échéances. Le paiement en ligne
peut être proposé par votre institut.

> Un compte peut être **suspendu pour impayé** après le 10 du mois. Il est
> **réactivé automatiquement** dès que la scolarité est à jour.

## 8.10 Orientation & insertion professionnelle

Menu → **Orientation & Insertion Pro.** : **Mes recommandations** (demander
une lettre de recommandation), **Mes séances d'orientation**,
**Opportunités** (offres de stage/emploi et candidatures), **Activités
COIP**, **Sorties pédagogiques**.

## 8.11 Responsable de classe

Si vous êtes nommé responsable (ou adjoint) de votre classe, vous accédez en
plus au **Cahier de Texte** de la classe et à des fonctions de suivi, tout
en conservant vos droits d'étudiant.

---

# 9. Comptable / Trésorier Général / Caissier

Section **Direction Financière** de la barre latérale. Utilisez le **filtre
par département** au besoin.

## 9.1 Valider les inscriptions

1. Menu → **Validation Inscription**.
2. Consultez chaque dossier : filière, classe, frais nets, montant versé.
3. Enregistrez le **paiement** (montant, date, référence) et **validez**
   l'inscription, ou renvoyez-la en caisse / rejetez-la.
4. Éditez le **certificat d'inscription**, l'**attestation de passage** ou
   de **réussite** en PDF.
5. **Preuves de paiement** : vérifiez les justificatifs déposés (caissier /
   trésorier).

## 9.2 Paiements de mensualités

Menu → **Paiements Mensualités** : suivez les échéances par étudiant,
enregistrez les versements, gérez les frais de **soutenance**.

## 9.3 Recouvrement et bourses

- Menu → **Taux de recouvrement** : synthèse des impayés (trésorier).
- Menu → **Suivi des boursiers** et **Partenaires de bourse**.

## 9.4 La Caisse

- Menu → **La Caisse** / **Entrée & Sortie Caisse** : enregistrez les
  mouvements.
- Menu → **État journalier** : arrêté de caisse du jour (contrôleur /
  admin / trésorier).
- Menu → **Clôtures** : clôture comptable d'une période, avec envoi
  d'email (trésorier / admin).

## 9.5 Honoraires enseignants

- Menu → **Taux horaires** : barèmes par grade / type d'heure.
- Menu → **Honoraires mensuels** et **Honoraires annuels** : calcul,
  ajustements, exports PDF / Word / Excel.
- Menu → **Budget honoraires mensuels**.

## 9.6 Dépenses et comptes

- Menu → **Demandes de dépense** : créer, suivre, approuver selon le rôle.
- Menu → **Comptes comptables** : plan comptable (trésorier / admin).
- Menu → **Rapports financiers** : synthèses exportables.

## 9.7 Salaires

Menu → **Gestion des Salaires** puis **Bulletins de Salaire** : configurer
et générer la paie du personnel (hors trésorier).

---

# 10. Ressources humaines

Section **Gestion Ressources Humaines**.

## 10.1 Tableau de bord RH

Vue d'ensemble : effectifs, présences du jour, congés en cours, alertes.

## 10.2 Personnel

Menu → **Gestion du Personnel** : fiches individuelles, archivage,
suppression. Génération des **cartes du personnel** (avec QR de pointage) et
des **matricules employés**.

## 10.3 Pointage

- Menu → **Pointage du jour** : saisie / correction des présences.
- Le personnel peut pointer via **QR** (carte de pointage) ou via l'écran
  **Contrôle Accueil**.
- Menu → **Liste des présences**, **Rapport mensuel** (PDF / Word), **Export
  Excel**.

## 10.4 Congés

Menu → **Congés** : le personnel dépose une demande ; le responsable RH la
**valide** ou la **refuse** (workflow avec historique).

## 10.5 Carrière et vie du contrat

**Contrats** et **avenants**, **affectations** (carrière), **discipline**
(dossiers disciplinaires), **évaluations** (campagnes et objectifs),
**missions**, **intérims**, **passations de service**.

## 10.6 Recrutement, intégration, stages

- **Recrutement** : besoins et candidats.
- **Intégration (onboarding)** : parcours et tâches d'accueil des nouveaux.
- **Stages** : conventions et suivi.

## 10.7 Documents RH

Menu → **Documents & Attestations RH** : modèles, demandes et délivrance
d'attestations.

---

# 11. Contrôle Accueil

Rôle dédié au **pointage d'entrée**.

1. Menu → **Contrôle Accueil Étudiants** : scannez les cartes des étudiants
   à l'entrée ; la liste se met à jour en temps réel.
2. Menu → **Pointage Personnel** : scannez les cartes du personnel.
3. Menu → **Afficher QR Contrôle Accueil** : affichez un QR que les
   personnes scannent elles-mêmes pour pointer.

---

# 12. Candidat — admission en ligne

## 12.1 Accéder au portail de l'institut

Rendez-vous sur l'adresse **`/admission-<code_institut>/`** communiquée par
l'établissement. Vous y trouvez le **catalogue des filières** et la
présentation des départements.

## 12.2 Créer un compte candidat

1. Cliquez sur **Créer un compte**.
2. Renseignez vos nom, email et mot de passe.
3. Vérifiez votre email si un lien de confirmation vous est envoyé.

## 12.3 Déposer une candidature

1. Connectez-vous, choisissez la **filière** visée.
2. Complétez le formulaire et **téléversez les pièces justificatives**
   demandées.
3. Soumettez : votre dossier passe au statut « en cours d'examen ».

## 12.4 Suivre son dossier

Espace **`/candidat/`** : statut de la candidature, messages de
l'administration, étapes restantes.

## 12.5 S'inscrire et payer en ligne

Si votre candidature est acceptée et que la fenêtre d'inscription est
ouverte, finalisez votre **inscription** et, le cas échéant, effectuez le
**paiement en ligne**. Vous récupérez ensuite vos identifiants d'étudiant.

---

# 13. Aide-mémoire par tâche

| Je veux… | Où aller |
|----------|----------|
| Changer mon mot de passe | Menu profil → Changer le mot de passe |
| Voir mes notifications | Cloche en haut à droite |
| Créer un institut | Super Admin → Les Institutions → Créer |
| Renouveler l'abonnement d'un institut | Super Admin → Les Institutions → Abonnements |
| Changer le code d'activation | Super Admin → Code d'activation |
| Créer un utilisateur | Admin institut → Utilisateurs → Créer |
| Créer une classe / un module | Structure → Classes / Modules (EC) |
| Planifier un cours | Chef de dép. → Emplois du temps → Créer |
| Valider un émargement | Chef de dép. → Émargements → fiche → Valider |
| Émarger une séance | Enseignant → Émargements → fiche → Signer |
| Saisir des notes | Enseignant → Notes & Évaluations → Créer une évaluation |
| Générer les bulletins | Chef de dép. / DE → Notes → Bulletins → Générer |
| Valider une inscription | Comptable → Validation Inscription |
| Enregistrer un paiement de scolarité | Comptable → Paiements Mensualités |
| Faire la clôture de caisse | Trésorier → Clôtures |
| Déclarer un congé | RH → Congés → Nouveau |
| Justifier une absence | Étudiant → Mes absences → Justifier |
| Télécharger ma carte étudiant | Étudiant → Ma carte d'apprenant |
| Candidater | Portail `/admission-<code>/` → Créer un compte |

---

# 14. Problèmes fréquents

| Symptôme | Cause probable | Solution |
|----------|----------------|----------|
| « Activation de la plateforme » au lieu de la connexion | Plateforme non activée | Super Admin : saisir le code maître puis définir le code d'activation |
| Page de suspension à la connexion | Institut inactif ou abonnement expiré | Contacter le Super Administrateur pour renouveler l'abonnement |
| Un onglet a disparu du menu | Fonctionnalité désactivée pour l'institut | Demander sa réactivation à l'administrateur (Fonctionnalités de l'institut) |
| Listes vides pour un chef de département | Aucun département sélectionné | Choisir un département dans le sélecteur en haut de page |
| Impossible de créer une séance | Conflit de salle / enseignant / classe | Choisir un autre créneau ou une salle libre proposée |
| Compte étudiant bloqué | Scolarité impayée après le 10 du mois | Régulariser le paiement ; réactivation automatique |
| Support de cours introuvable | Purge après 72 h | Redemander le fichier à l'enseignant |
| Email non reçu | Configuration SMTP de l'institut | Vérifier « Mon Institut → Emails de notification » |
| Déconnexion après le bouton « précédent » | Sécurité anti-cache | Se reconnecter ; ne pas utiliser le bouton précédent après déconnexion |
