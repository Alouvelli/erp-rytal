# GestionEDT — Système de Gestion Académique Universitaire

Application web complète de gestion académique : emplois du temps, émargements, notes, absences et annulations de cours.

## Stack Technique

| Couche | Technologie |
|--------|-------------|
| Frontend | React 18 + TypeScript + Tailwind CSS + Vite |
| Backend | Node.js + Express + TypeScript |
| Base de données | PostgreSQL + Prisma ORM |
| Auth | JWT (access + refresh tokens) + bcrypt |
| Conteneurs | Docker + docker-compose |
| API Docs | Swagger / OpenAPI |

## Lancement rapide (Docker)

```bash
# 1. Cloner et aller dans le projet
cd GestionEmploiDuTemps

# 2. Lancer tous les services
docker-compose up -d

# 3. Appliquer les migrations et le seed
docker exec gestion_edt_backend npx prisma migrate dev --name init
docker exec gestion_edt_backend npm run db:seed
```

Accès :
- **Frontend** : http://localhost:3000
- **Backend API** : http://localhost:4000/api/v1
- **Swagger** : http://localhost:4000/docs

## Lancement en développement (sans Docker)

### Prérequis
- Node.js 18+
- PostgreSQL 14+

### Backend

```bash
cd backend
npm install

# Copier et configurer le .env
cp .env.example .env
# Modifier DATABASE_URL si nécessaire

# Migrations
npm run db:generate
npm run db:migrate

# Données de test
npm run db:seed

# Démarrer
npm run dev
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Comptes de démonstration

| Rôle | Email | Mot de passe |
|------|-------|--------------|
| Administrateur | admin@universite.fr | Admin@1234 |
| Scolarité | scolarite@universite.fr | Scol@1234 |
| Enseignant | prof.martin@universite.fr | Prof@1234 |
| Étudiant | alice.dupont@etu.fr | Student@1234 |

## Fonctionnalités

### Emploi du temps
- Vue calendrier hebdomadaire avec code couleur par matière
- Détection automatique des conflits (enseignant, salle, classe)
- Filtres par classe et semestre
- CRUD complet (Admin / Scolarité)

### Émargements
- Signature numérique de présence par l'enseignant
- Validation / rejet par l'administration
- Statistiques des heures réalisées vs prévues

### Notes
- Création d'évaluations (CC, TP, Examen, Rattrapage)
- Saisie groupée des notes par évaluation
- Calcul automatique des moyennes pondérées
- Publication avec notification automatique aux étudiants

### Absences
- Saisie par séance (enseignant / scolarité)
- Workflow de justification (étudiant → scolarité)
- Statistiques par étudiant

### Annulations de cours
- Demande avec motif (enseignant)
- Validation et reprogrammation (scolarité)
- Notifications automatiques aux étudiants et enseignants concernés

## Architecture

```
GestionEmploiDuTemps/
├── backend/
│   ├── prisma/
│   │   ├── schema.prisma       # Modèle de données
│   │   └── seed.ts             # Données initiales
│   └── src/
│       ├── controllers/        # Logique métier
│       ├── routes/             # Endpoints API
│       ├── middlewares/        # Auth, erreurs, rate limit
│       └── utils/              # JWT, Prisma, Logger, Swagger
└── frontend/
    └── src/
        ├── components/layout/  # Sidebar, Header
        ├── context/            # Auth, Theme
        ├── pages/              # Toutes les pages
        ├── services/           # Appels API (axios)
        └── types/              # Types TypeScript
```

## Exemples d'appels API

```bash
# Connexion
curl -X POST http://localhost:4000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@universite.fr","password":"Admin@1234"}'

# Créer un créneau (avec token)
curl -X POST http://localhost:4000/api/v1/timetables \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"classId":"...","teacherId":"...","subjectId":"...","roomId":"...","dayOfWeek":0,"startTime":"08:00","endTime":"10:00","semester":1}'

# Dashboard
curl http://localhost:4000/api/v1/dashboard \
  -H "Authorization: Bearer <token>"
```
