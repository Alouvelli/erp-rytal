from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('subjects', '0001_initial'),
        ('grades', '0003_lmd_bulletin'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='ue',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='subjects',
                to='grades.uniteenseignement',
                verbose_name="Unité d'Enseignement",
            ),
        ),
    ]
