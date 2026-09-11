"""
Script de lancement de l'application Institut Supérieur d'Informatique - ISI.
Usage : python run.py [--port 8000] [--host 127.0.0.1] [--setup]
  --setup  : crée la DB, applique les migrations et crée un superuser si absent
"""
import os
import sys
import subprocess
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS = "config.settings.development"
MANAGE   = os.path.join(BASE_DIR, "manage.py")


def run(cmd, check=True):
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if check and result.returncode != 0:
        print(f"\n[ERREUR] La commande a échoué (code {result.returncode}). Arrêt.")
        sys.exit(result.returncode)
    return result.returncode


def django_cmd(*args):
    return [sys.executable, MANAGE] + list(args) + [f"--settings={SETTINGS}"]


def setup():
    print("\n" + "="*60)
    print("  SETUP — Initialisation de la base de données")
    print("="*60)

    # 1. Migrations
    run(django_cmd("migrate"))

    # 2. Superuser + rôles via script inline
    script = """
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
django.setup()
from academic_core.apps.accounts.models import User, Role

for code in ["ADMIN", "RESPONSABLE", "ENSEIGNANT", "ETUDIANT"]:
    Role.objects.get_or_create(name=code)
print("  [OK] Rôles créés/vérifiés")

if not User.objects.filter(username="admin").exists():
    r = Role.objects.get(name="ADMIN")
    u = User.objects.create_superuser("admin", "admin@university.edu", "Admin@1234")
    u.role = r; u.first_name = "Super"; u.last_name = "Admin"; u.save()
    print("  [OK] Superuser créé  →  login: admin  /  mot de passe: Admin@1234")
else:
    print("  [OK] Superuser 'admin' déjà présent")
"""
    run([sys.executable, "-c", script])

    print("\n" + "="*60)
    print("  SETUP terminé avec succès !")
    print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Lance Institut Supérieur d'Informatique - ISI")
    parser.add_argument("--port",  default="8000",      help="Port HTTP (défaut: 8000)")
    parser.add_argument("--host",  default="127.0.0.1", help="Hôte (défaut: 127.0.0.1)")
    parser.add_argument("--setup", action="store_true", help="Initialise la DB avant de démarrer")
    args = parser.parse_args()

    os.chdir(BASE_DIR)

    if args.setup:
        setup()

    addr = f"{args.host}:{args.port}"
    print(f"\n{'='*60}")
    print(f"  Démarrage du serveur Institut Supérieur d'Informatique - ISI")
    print(f"  URL : http://{addr}/")
    print(f"  Admin Django : http://{addr}/admin/")
    print(f"  Identifiants : admin / Admin@1234")
    print(f"  Arrêt : Ctrl+C")
    print(f"{'='*60}\n")

    run(django_cmd("runserver", addr), check=False)


if __name__ == "__main__":
    main()