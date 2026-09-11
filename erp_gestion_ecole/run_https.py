"""
Démarre le serveur Django en HTTPS sur le réseau local.
Requis : pip install pyOpenSSL Werkzeug  (déjà dans requirements-dev.txt)

Usage :
    python run_https.py              # 0.0.0.0:8443
    python run_https.py 8080         # 0.0.0.0:8080
    python run_https.py 192.168.1.5:8443

Le certificat auto-signé est généré dans ssl/cert.crt la première fois.
Les étudiants verront un avertissement "non approuvé" — cliquer sur
"Paramètres avancés" → "Continuer quand même" une seule fois suffit.
"""
import os
import sys
import subprocess
import pathlib
import warnings

BASE      = pathlib.Path(__file__).parent
SSL_DIR   = BASE / 'ssl'
CERT_FILE = SSL_DIR / 'cert.crt'

SETTINGS_MODULE = 'config.settings.development'


def generate_cert():
    SSL_DIR.mkdir(exist_ok=True)
    if CERT_FILE.exists():
        return
    print("[HTTPS] Génération du certificat auto-signé…")
    try:
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName(u"localhost"),
                x509.IPAddress(__import__('ipaddress').IPv4Address('127.0.0.1')),
            ]), critical=False)
            .sign(key, hashes.SHA256())
        )

        pem_cert = cert.public_bytes(serialization.Encoding.PEM)
        pem_key  = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )

        with open(CERT_FILE, 'wb') as f:
            f.write(pem_cert)
            f.write(pem_key)

        print(f"[HTTPS] Certificat créé : {CERT_FILE}")

    except ImportError:
        print("[HTTPS] Dépendance manquante — exécutez : pip install cryptography")
        sys.exit(1)


def main():
    addr = sys.argv[1] if len(sys.argv) > 1 else '0.0.0.0:8443'
    if addr.isdigit():
        addr = f'0.0.0.0:{addr}'

    generate_cert()

    print(f"[HTTPS] Démarrage sur https://{addr}/")
    print("[HTTPS] Les étudiants accèdent via https://<IP-du-serveur>:<port>/")
    print("[HTTPS] Appuyez sur Ctrl+C pour arrêter.\n")

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', SETTINGS_MODULE)

    subprocess.run([
        sys.executable, 'manage.py', 'runserver_plus',
        '--cert-file', str(CERT_FILE),
        '--nopin',
        addr,
    ])


if __name__ == '__main__':
    main()
