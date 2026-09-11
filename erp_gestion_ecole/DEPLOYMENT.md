# Déploiement en production (VPS Linux + Docker Compose)

Guide bout-en-bout pour déployer **UniManager** (Django 5, PostgreSQL 16,
Celery/Redis, Nginx/Gunicorn) sur un serveur Linux avec Docker Compose.

L'application est **multi-tenant** : une base PostgreSQL par institut
(`db_rytal_<code>`) plus une base maître `default` (`academic_db`). Toutes les
bases sont hébergées sur le même serveur PostgreSQL, gérées par un seul compte
administrateur.

> Toutes les commandes s'exécutent depuis le dossier `erp_gestion_ecole/`
> (celui qui contient `docker-compose.yml`), sauf indication contraire.

---

## 0. Vue d'ensemble de la stack

| Service        | Rôle                                              | Port |
|----------------|---------------------------------------------------|------|
| `nginx`        | Reverse proxy + TLS, seul point d'entrée public   | 80/443 |
| `web`          | Gunicorn / Django                                 | interne (127.0.0.1:8000) |
| `celery_worker`| Tâches asynchrones                                | — |
| `celery_beat`  | Tâches planifiées                                 | — |
| `db`           | PostgreSQL 16                                     | interne (127.0.0.1:5432) |
| `redis`        | Broker Celery + cache                             | interne (127.0.0.1:6379) |

Seul Nginx est exposé à Internet. `db`, `redis` et `web` ne sont accessibles
que depuis la boucle locale du serveur (utile pour l'administration via tunnel
SSH), jamais publiquement.

---

## 1. Prérequis serveur

- Un VPS Linux (Ubuntu 22.04/24.04 LTS recommandé), **2 vCPU / 4 Go RAM
  minimum**, 20 Go+ de disque (les dumps + PostgreSQL + images Docker).
- Un nom de domaine pointant (enregistrement **A**/**AAAA**) vers l'IP du VPS.
- Un accès SSH avec un utilisateur non-root disposant de `sudo`.
- Ports **80** et **443** ouverts dans le pare-feu.

### Installer Docker + Compose

```bash
# Docker Engine + plugin compose (méthode officielle)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # puis reconnectez-vous
docker --version && docker compose version
```

### Pare-feu (ufw)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 2. Récupérer le code

```bash
git clone https://github.com/Alouvelli/erp-rytal.git
cd erp-rytal/erp_gestion_ecole
```

> **Important** : les fichiers sensibles (`.env`, dumps `bd/*`, certificats
> `ssl/*`) **ne sont pas dans le dépôt** (voir `.gitignore`). Ils doivent être
> créés ou transférés séparément (étapes suivantes).

### Transférer les dumps de bases

Copiez les dumps des instituts sur le serveur, par canal sécurisé (jamais par
le dépôt git) :

```bash
# depuis votre machine locale
scp bd/db_rytal_isi bd/db_rytal_isi_sedhiou bd/db_rytal_isi_suptech \
    user@VOTRE_SERVEUR:~/erp-rytal/erp_gestion_ecole/bd/
```

---

## 3. Créer le fichier `.env` de production

```bash
cp .env.example .env
```

### Générer les secrets

```bash
# DJANGO_SECRET_KEY
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'

# PLATFORM_MASTER_KEY (verrou de démarrage, voir §8)
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'

# Mot de passe PostgreSQL fort
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'
```

### Renseigner `.env`

Valeurs minimales à ajuster (le reste garde les valeurs par défaut adaptées à
Docker) :

```env
DJANGO_SECRET_KEY=<clé générée ci-dessus>
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=votre-domaine.com,www.votre-domaine.com

POSTGRES_DB=academic_db
POSTGRES_USER=academic_user
POSTGRES_PASSWORD=<mot de passe fort généré>
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_MAINTENANCE_DB=postgres

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=<compte SMTP>
EMAIL_HOST_PASSWORD=<mot de passe d'application>
DEFAULT_FROM_EMAIL=noreply@votre-domaine.com

CORS_ALLOWED_ORIGINS=https://votre-domaine.com

# Verrou d'activation de la plateforme (obligatoire pour démarrer)
PLATFORM_MASTER_KEY=<clé générée ci-dessus>
PLATFORM_RESET_EMAIL_1=admin1@votre-domaine.com
PLATFORM_RESET_EMAIL_2=admin2@votre-domaine.com
```

### Blocs de bases par institut

Pour chaque dump à restaurer, ajoutez un bloc `DB_RYTAL_<CODE>_*` (le `<CODE>`
correspond au suffixe du nom de base, en majuscules). Pour les trois dumps
fournis :

```env
# Institut ISI  -> base db_rytal_isi
DB_RYTAL_ISI_NAME=db_rytal_isi
DB_RYTAL_ISI_HOST=db
DB_RYTAL_ISI_PORT=5432
DB_RYTAL_ISI_USER=academic_user
DB_RYTAL_ISI_PASSWORD=<même mot de passe que POSTGRES_PASSWORD>

# Institut ISI_SEDHIOU -> base db_rytal_isi_sedhiou
DB_RYTAL_ISI_SEDHIOU_NAME=db_rytal_isi_sedhiou
DB_RYTAL_ISI_SEDHIOU_HOST=db
DB_RYTAL_ISI_SEDHIOU_PORT=5432
DB_RYTAL_ISI_SEDHIOU_USER=academic_user
DB_RYTAL_ISI_SEDHIOU_PASSWORD=<même mot de passe que POSTGRES_PASSWORD>

# Institut ISI_SUPTECH -> base db_rytal_isi_suptech
DB_RYTAL_ISI_SUPTECH_NAME=db_rytal_isi_suptech
DB_RYTAL_ISI_SUPTECH_HOST=db
DB_RYTAL_ISI_SUPTECH_PORT=5432
DB_RYTAL_ISI_SUPTECH_USER=academic_user
DB_RYTAL_ISI_SUPTECH_PASSWORD=<même mot de passe que POSTGRES_PASSWORD>
```

> Ces blocs sont lus au démarrage (`academic_core/tenant_databases.py`). À la
> création d'un nouvel institut depuis l'application, un bloc est ajouté
> automatiquement à ce `.env` — c'est pourquoi le fichier `.env` doit rester
> accessible en écriture au conteneur `web` (le montage `- .:/app` de
> `docker-compose.yml` s'en charge, ne pas le retirer).

---

## 4. Certificat TLS pour le premier démarrage

Nginx a besoin d'un certificat pour démarrer. Le dépôt n'en contient pas
(clés privées jamais commitées). Générez un certificat auto-signé temporaire
pour le premier boot (remplacé par Let's Encrypt à l'étape 7) :

```bash
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/cert.key -out nginx/ssl/cert.crt \
  -subj "/CN=votre-domaine.com"
```

---

## 5. Démarrer la stack

```bash
docker compose up -d --build
docker compose ps          # vérifier que tous les services sont "healthy"/"running"
docker compose logs -f web # suivre le démarrage de Django
```

Au démarrage, le service `web` applique automatiquement les migrations de la
base `default` et exécute `collectstatic`.

---

## 6. Initialiser les bases de données

### 6.1 Base maître `default`

Déjà migrée au démarrage. Créez le compte super-administrateur de la plateforme :

```bash
docker compose exec web python manage.py createsuperuser
```

### 6.2 Restaurer les bases des instituts

Pour chaque institut, on **crée la base** puis on **restaure le dump**, et
enfin on applique les migrations éventuellement plus récentes que le dump.

```bash
# 1) Créer les bases (le compte a le droit CREATEDB)
for db in db_rytal_isi db_rytal_isi_sedhiou db_rytal_isi_suptech; do
  docker compose exec -T db \
    psql -U academic_user -d postgres -c "CREATE DATABASE $db OWNER academic_user;"
done

# 2) Restaurer chaque dump
for db in db_rytal_isi db_rytal_isi_sedhiou db_rytal_isi_suptech; do
  docker compose exec -T db \
    psql -U academic_user -d "$db" < "bd/$db"
done

# 3) Appliquer les migrations à jour sur chaque base institut
for db in db_rytal_isi db_rytal_isi_sedhiou db_rytal_isi_suptech; do
  docker compose exec web python manage.py migrate --database="$db" --noinput
done
```

> `docker compose exec -T db psql ... < fichier` envoie le dump depuis le dossier
> courant du serveur vers PostgreSQL. Les dumps ont été produits par `pg_dump`
> (PostgreSQL 17) ; ils se restaurent sans problème sur PostgreSQL 16+.

Vérifiez ensuite dans l'application (connexion super-admin) que chaque institut
est bien listé et que ses données remontent.

---

## 7. HTTPS avec Let's Encrypt

Une fois le domaine pointé sur le serveur et la stack démarrée (le port 80 sert
déjà les challenges ACME via `nginx/certbot`) :

```bash
# Émettre le certificat (webroot servi par nginx)
docker run --rm \
  -v "$(pwd)/nginx/certbot:/var/www/certbot" \
  -v "$(pwd)/letsencrypt:/etc/letsencrypt" \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d votre-domaine.com -d www.votre-domaine.com \
  --email admin@votre-domaine.com --agree-tos --no-eff-email
```

Installez le certificat émis là où nginx l'attend, puis rechargez :

```bash
cp letsencrypt/live/votre-domaine.com/fullchain.pem nginx/ssl/cert.crt
cp letsencrypt/live/votre-domaine.com/privkey.pem   nginx/ssl/cert.key
docker compose exec nginx nginx -s reload
```

Pensez aussi à remplacer `server_name _;` par votre domaine dans
`nginx/conf.d/app.conf`.

### Renouvellement automatique

Les certificats Let's Encrypt expirent tous les 90 jours. Ajoutez une tâche cron
(sur le serveur) :

```bash
# crontab -e  — renouvellement mensuel + rechargement nginx
0 3 1 * * cd ~/erp-rytal/erp_gestion_ecole && \
  docker run --rm -v "$(pwd)/nginx/certbot:/var/www/certbot" \
    -v "$(pwd)/letsencrypt:/etc/letsencrypt" certbot/certbot renew --webroot -w /var/www/certbot && \
  cp letsencrypt/live/votre-domaine.com/fullchain.pem nginx/ssl/cert.crt && \
  cp letsencrypt/live/votre-domaine.com/privkey.pem nginx/ssl/cert.key && \
  docker compose exec nginx nginx -s reload
```

---

## 8. Verrou d'activation de la plateforme

L'application possède **deux verrous** :

1. **`PLATFORM_MASTER_KEY`** (§3) — sans cette variable, le serveur de
   production refuse de démarrer.
2. **Code d'activation** — saisi une seule fois via l'interface web après le
   premier démarrage. Tant qu'il n'est pas saisi, l'accès à l'application est
   bloqué par `PlatformActivationMiddleware`.

Après le premier démarrage, connectez-vous et suivez la page d'activation.
La rotation du code se fait via `/accounts/plateforme/rotation/`. Les seules
adresses autorisées à recevoir le lien de réinitialisation sont
`PLATFORM_RESET_EMAIL_1` / `PLATFORM_RESET_EMAIL_2` (définies dans `.env`).

> Voir `CLAUDE.md` : ce mécanisme ne doit jamais être modifié ou contourné sans
> demande explicite de l'exploitant.

---

## 9. Sauvegardes

Sauvegarde quotidienne de **toutes** les bases (maître + instituts) :

```bash
# Toutes les bases du serveur PostgreSQL
docker compose exec -T db pg_dumpall -U academic_user \
  > backup_$(date +%F).sql

# Ou base par base
docker compose exec -T db pg_dump -U academic_user db_rytal_isi \
  > db_rytal_isi_$(date +%F).sql
```

Stockez les sauvegardes hors du serveur (elles contiennent des données
personnelles). N'oubliez pas d'inclure aussi le fichier `.env` (chiffré) dans
votre plan de reprise : il contient la liste des instituts.

---

## 10. Mises à jour applicatives

```bash
git pull
docker compose up -d --build          # reconstruit et redémarre
docker compose exec web python manage.py migrate --noinput          # base default
# puis migrer chaque institut (voir §6.2 étape 3)
docker compose exec web python manage.py collectstatic --noinput
```

---

## 11. Sécurité — historique et données exposées

L'historique git contenait des éléments qui n'auraient pas dû s'y trouver :

- **`bd/*`** — dumps PostgreSQL contenant des **données réelles**
  (étudiants, finances).
- **`erp_gestion_ecole/ssl/cert.crt` / `cert.key`** — un certificat de test
  auto-signé `localhost` et sa clé privée.

**Historique purgé** : ces fichiers ont été retirés de tout l'historique
(`git filter-branch`) et les branches `main` et
`claude/elegant-johnson-8xwmif` ont été **réécrites puis force-pushées**. Les
dumps restent présents **sur le disque** (dossier `bd/`, ignoré par git) pour
la restauration en production (§6.2).

Conséquences à connaître :

1. **Re-cloner** : tout clone antérieur du dépôt contient encore les anciens
   commits avec les données. Chaque personne concernée doit re-cloner (ou faire
   `git fetch && git reset --hard origin/<branche>`) — un `git pull` classique
   échouera ou réintroduira l'ancien historique.
2. **GitHub peut conserver temporairement** les anciens commits (accessibles
   par leur SHA, via le cache, les forks ou d'anciennes PR). Pour une purge
   garantie côté GitHub, ouvrez un ticket au support GitHub. Les **forks**
   éventuels conservent les données indépendamment.
3. **Considérer les données des dumps comme compromises** : elles ont été
   accessibles le temps où le dépôt les contenait. Évaluez vos obligations
   RGPD/notification selon la sensibilité.
4. **Ne jamais réutiliser** le certificat de test : les certificats de
   production sont émis par Let's Encrypt (§7) et n'entrent jamais dans le
   dépôt.
5. Aucun `.env` n'a été commité (vérifié) : les secrets applicatifs
   (`DJANGO_SECRET_KEY`, `PLATFORM_MASTER_KEY`, mots de passe DB, SMTP) sont à
   générer directement sur le serveur (§3) et n'existent que dans le `.env`
   local au serveur.

---

## Dépannage

| Symptôme | Cause probable | Solution |
|----------|----------------|----------|
| `web` redémarre en boucle, `ImproperlyConfigured: PLATFORM_MASTER_KEY` | Variable absente du `.env` | Définir `PLATFORM_MASTER_KEY` (§3) |
| nginx ne démarre pas, `cannot load certificate` | Certificat absent de `nginx/ssl/` | Générer le certificat (§4) |
| Écritures refusées `[DB-ROUTER] Écriture refusée vers default` | Aucun institut actif dans la requête | Accéder via le contexte d'un institut ; vérifier les blocs `DB_RYTAL_*` |
| Un institut n'apparaît pas | Bloc `DB_RYTAL_*` manquant ou base non restaurée | Ajouter le bloc dans `.env` (§3) + restaurer le dump (§6.2) |
| Emails non envoyés | Identifiants SMTP `.env` incorrects | Vérifier `EMAIL_HOST_USER` / mot de passe d'application |
