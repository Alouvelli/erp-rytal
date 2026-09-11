from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_add_ciaq_role'),
    ]

    operations = [
        # Rename the existing CIAQ role label
        migrations.RunSQL(
            sql="UPDATE roles SET name='CIAQ' WHERE name='CIAQ';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Add the new CONTROLEUR role
        migrations.RunSQL(
            sql="""
                INSERT INTO roles (name, description, created_at)
                SELECT 'CONTROLEUR', 'Contrôleur Interne', NOW()
                WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name='CONTROLEUR');
            """,
            reverse_sql="DELETE FROM roles WHERE name='CONTROLEUR';",
        ),
    ]
