from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_add_controleur_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='url',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='details',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('LOGIN', 'Connexion'),
                    ('LOGOUT', 'Déconnexion'),
                    ('VIEW', 'Consultation'),
                    ('CREATE', 'Création'),
                    ('UPDATE', 'Modification'),
                    ('DELETE', 'Suppression'),
                    ('VALIDATE', 'Validation'),
                    ('CANCEL', 'Annulation'),
                ],
            ),
        ),
    ]
