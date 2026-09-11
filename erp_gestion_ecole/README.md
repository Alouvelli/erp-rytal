# UniManager — Système de Gestion Académique

Application web complète de gestion académique universitaire construite avec Django 5, PostgreSQL, Celery et Bootstrap 5.

## Fonctionnalités

| Module | Description |
|--------|-------------|
| **Emplois du temps** | Calendrier FullCalendar, détection conflits, export PDF/Excel |
| **Émargements** | Signature électronique, workflow validation, taux réalisation |
| **Notes** | Saisie masse, verrouillage, moyennes automatiques, bulletins PDF |
| **Absences** | Suivi par séance, alertes automatiques, justificatifs |
| **Annulations** | Demande/validation, reprogrammation, notifications |
| **Rapports** | Bulletins, relevés, bilans horaires — PDF & Excel |
| **Notifications** | Internes + email, temps réel |
| **RBAC** | Admin / Responsable / Enseignant / Étudiant |

## Stack technique

- **Backend** : Django 5.1, Django REST Framework, JWT, Celery, Redis
- **Base de données** : PostgreSQL 16
- **Frontend** : Bootstrap 5.3, FullCalendar 6, DataTables, Chart.js
- **Rapports** : ReportLab (PDF), openpyxl (Excel)
- **Déploiement** : Docker, Docker Compose, Nginx, Gunicorn

---

## Démarrage rapide (Docker)

### 1. Cloner et configurer

```bash
git clone <repo-url>
cd GestionEmploisDuTemps
cp .env.example .env
# Éditer .env avec vos paramètres
```

### 2. Lancer avec Docker Compose

```bash
docker compose up -d --build
```

### 3. Initialiser la base de données

```bash
# Migrations
docker compose exec web python manage.py migrate

# Créer le superadmin
docker compose exec web python manage.py createsuperuser

# Charger les données de démonstration
docker compose exec web python manage.py loaddata \
  academic_core/apps/academic_structure/fixtures/demo_data.json \
  academic_core/apps/academic_structure/fixtures/timetable_demo.json
```

### 4. Accéder à l'application

| URL | Description |
|-----|-------------|
| `http://localhost` | Application principale |
| `http://localhost/admin/` | Interface d'administration Django |
| `http://localhost/api/docs/` | Documentation Swagger |
| `http://localhost/api/redoc/` | Documentation ReDoc |

---

## Développement local (sans Docker)

### Prérequis

- Python 3.12+
- PostgreSQL 16+
- Redis 7+

### Installation

```bash
# Environnement virtuel
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# Dépendances
pip install -r requirements-dev.txt

# Variables d'environnement
cp .env.example .env
# Modifier POSTGRES_HOST=localhost dans .env

# Migrations
python manage.py migrate --settings=config.settings.development

# Fixtures de démo
python manage.py loaddata \
  academic_core/apps/academic_structure/fixtures/demo_data.json \
  academic_core/apps/academic_structure/fixtures/timetable_demo.json \
  --settings=config.settings.development

# Lancer le serveur
python manage.py runserver --settings=config.settings.development
```

### Celery (dans un terminal séparé)

```bash
# Worker
celery -A config.celery worker -l info

# Beat scheduler (tâches planifiées)
celery -A config.celery beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## Comptes de démonstration

| Rôle | Identifiant | Mot de passe |
|------|-------------|--------------|
| Administrateur | `admin` | Défini lors de `createsuperuser` |
| Responsable pédagogique | `responsable1` | `UniManager2024!` |
| Enseignant | `prof_ndoye` | `UniManager2024!` |
| Étudiant | `etudiant_ba` | `UniManager2024!` |

> Réinitialiser les mots de passe via : `python manage.py changepassword <username>`

---

## Architecture du projet

```
GestionEmploisDuTemps/
├── academic_core/
│   ├── apps/
│   │   ├── accounts/           # Auth, RBAC, AuditLog
│   │   ├── academic_structure/ # Faculté, Dépt, Filière, Classe, Semestre
│   │   ├── teachers/           # Profils enseignants
│   │   ├── students/           # Profils étudiants, Inscriptions
│   │   ├── subjects/           # Matières
│   │   ├── rooms/              # Salles & Bâtiments
│   │   ├── timetable/          # Emplois du temps, détection conflits
│   │   ├── attendance/         # Émargements, présences
│   │   ├── grades/             # Notes, évaluations, moyennes
│   │   ├── cancellations/      # Annulations & reports de cours
│   │   ├── notifications/      # Système de notifications
│   │   ├── reports/            # Générateurs PDF & Excel
│   │   └── dashboard/          # Tableaux de bord par rôle
│   ├── static/                 # CSS, JS, images
│   ├── templates/              # Templates Bootstrap 5
│   └── media/                  # Fichiers uploadés
├── config/
│   ├── settings/               # base.py, development.py, production.py
│   ├── urls.py                 # Routing principal
│   ├── celery.py               # Config Celery + beat_schedule
│   └── wsgi.py
├── nginx/conf.d/app.conf       # Config Nginx SSL
├── Dockerfile                  # Multi-stage build
├── docker-compose.yml          # Stack complète
├── requirements.txt
└── manage.py
```

---

## API REST

Base URL : `/api/v1/`

| Endpoint | Méthodes | Description |
|----------|----------|-------------|
| `/api/v1/timetable/entries/` | GET POST PUT DELETE | Emplois du temps |
| `/api/v1/timetable/entries/calendar/` | GET | Format FullCalendar |
| `/api/v1/timetable/entries/check-conflicts/` | POST | Vérification conflits |
| `/api/v1/attendance/sheets/` | GET POST | Fiches d'émargement |
| `/api/v1/attendance/sheets/{id}/sign/` | POST | Signature enseignant |
| `/api/v1/attendance/sheets/{id}/validate/` | POST | Validation responsable |
| `/api/v1/grades/evaluations/` | GET POST | Évaluations |
| `/api/v1/grades/evaluations/{id}/lock/` | POST | Verrouillage notes |
| `/api/v1/grades/grades/` | GET POST PUT | Notes |
| `/api/v1/grades/averages/` | GET | Moyennes semestrielles |
| `/api/schema/` | GET | Schéma OpenAPI |
| `/api/docs/` | GET | Swagger UI |

### Authentification JWT

```bash
# Obtenir un token
curl -X POST /api/v1/accounts/token/ \
  -d '{"username":"admin","password":"your_password"}'

# Utiliser le token
curl -H "Authorization: Bearer <access_token>" /api/v1/timetable/entries/
```

---

## Tâches Celery planifiées

| Tâche | Fréquence | Description |
|-------|-----------|-------------|
| `generate_daily_sheets` | Quotidien 5h00 | Génère les fiches d'émargement |
| `check_absence_alerts` | Lundi 8h00 | Alertes taux d'absence ≥ 20% |
| `remind_unsigned_sheets` | Quotidien 18h00 | Rappels fiches non signées |
| `cleanup_expired_tokens` | Quotidien 2h00 | Nettoyage tokens expirés |

---

## Variables d'environnement (.env)

```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=localhost,your-domain.com
POSTGRES_DB=academic_db
POSTGRES_USER=academic_user
POSTGRES_PASSWORD=strongpassword
POSTGRES_HOST=db
CELERY_BROKER_URL=redis://redis:6379/0
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=your@email.com
EMAIL_HOST_PASSWORD=your-app-password
```

---

## Licence

Projet académique — Usage éducatif et institutionnel.
