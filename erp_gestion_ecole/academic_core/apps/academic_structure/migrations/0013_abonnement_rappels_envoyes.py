from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academic_structure', '0012_fix_cross_db_fk_constraints'),
    ]

    operations = [
        migrations.AddField(
            model_name='abonnementinstitut',
            name='rappels_envoyes',
            field=models.JSONField(blank=True, default=list, verbose_name='Rappels envoyés'),
        ),
    ]
