from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subjects', '0002_subject_ue'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='volume_cm',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='Volume CM (h)'),
        ),
        migrations.AddField(
            model_name='subject',
            name='volume_td',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='Volume TD (h)'),
        ),
        migrations.AddField(
            model_name='subject',
            name='volume_tp',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='Volume TP (h)'),
        ),
        migrations.AddField(
            model_name='subject',
            name='volume_tpe',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='Volume TPE (h)'),
        ),
    ]
