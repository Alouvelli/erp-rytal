from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subjects', '0003_subject_volume_detail'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='volume_total_ue',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='Volume total UE (h)'),
        ),
    ]
