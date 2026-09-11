-- Création de l'utilisateur et de la base de données pour UniManager
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'academic_user') THEN
    CREATE USER academic_user WITH PASSWORD 'academic_pass';
  END IF;
END
$$;

SELECT 'CREATE DATABASE academic_db OWNER academic_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'academic_db')\gexec

GRANT ALL PRIVILEGES ON DATABASE academic_db TO academic_user;
ALTER USER academic_user CREATEDB;
