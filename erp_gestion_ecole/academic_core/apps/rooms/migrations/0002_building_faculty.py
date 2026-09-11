from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0001_initial'),
        ('academic_structure', '0009_abonnement_institut'),
    ]

    operations = [
        migrations.AddField(
            model_name='building',
            name='faculty',
            field=models.ForeignKey(
                to='academic_structure.Faculty',
                on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True,
                related_name='buildings',
                verbose_name='Institut',
            ),
        ),
    ]
