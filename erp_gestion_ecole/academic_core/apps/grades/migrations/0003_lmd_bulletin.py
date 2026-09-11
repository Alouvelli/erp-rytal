from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0002_evaluation_class_group_evaluation_coefficient_and_more'),
        ('academic_structure', '0001_initial'),
        ('students', '0001_initial'),
        ('subjects', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UniteEnseignement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, verbose_name='Code UE')),
                ('title', models.CharField(max_length=200, verbose_name='Intitulé')),
                ('credits', models.PositiveSmallIntegerField(default=6, verbose_name='Crédits UE')),
                ('order', models.PositiveSmallIntegerField(default=1, verbose_name="Ordre d'affichage")),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unites_enseignement', to='academic_structure.program', verbose_name='Filière')),
                ('semester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unites_enseignement', to='academic_structure.semester', verbose_name='Semestre')),
            ],
            options={
                'verbose_name': "Unité d'Enseignement",
                'verbose_name_plural': "Unités d'Enseignement",
                'db_table': 'unites_enseignement',
                'ordering': ['semester', 'order', 'code'],
                'unique_together': {('code', 'program', 'semester')},
            },
        ),
        migrations.CreateModel(
            name='Bulletin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('DRAFT', 'Brouillon'), ('PUBLISHED', 'Publié'), ('LOCKED', 'Verrouillé')], default='DRAFT', max_length=15)),
                ('semester_average', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, verbose_name='Moyenne semestrielle')),
                ('total_credits_obtained', models.PositiveSmallIntegerField(default=0)),
                ('total_credits_possible', models.PositiveSmallIntegerField(default=0)),
                ('mention', models.CharField(blank=True, max_length=50)),
                ('jury_decision', models.CharField(blank=True, max_length=200)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('class_group', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bulletins', to='academic_structure.class', verbose_name='Classe')),
                ('generated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generated_bulletins', to=settings.AUTH_USER_MODEL)),
                ('semester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bulletins', to='academic_structure.semester', verbose_name='Semestre')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bulletins', to='students.student', verbose_name='Etudiant')),
            ],
            options={
                'verbose_name': 'Bulletin',
                'verbose_name_plural': 'Bulletins',
                'db_table': 'bulletins',
                'unique_together': {('student', 'semester')},
            },
        ),
        migrations.CreateModel(
            name='BulletinUEResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('average', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('credits_obtained', models.PositiveSmallIntegerField(default=0)),
                ('is_validated', models.BooleanField(default=False)),
                ('order', models.PositiveSmallIntegerField(default=1)),
                ('bulletin', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ue_results', to='grades.bulletin')),
                ('ue', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bulletin_results', to='grades.uniteenseignement')),
            ],
            options={
                'db_table': 'bulletin_ue_results',
                'ordering': ['order'],
                'unique_together': {('bulletin', 'ue')},
            },
        ),
        migrations.CreateModel(
            name='BulletinECResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cc_average', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('exam_score', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('rattrapage_score', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('final_average', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('appreciation', models.CharField(blank=True, max_length=20)),
                ('is_validated', models.BooleanField(default=False)),
                ('bulletin', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ec_results', to='grades.bulletin')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bulletin_results', to='subjects.subject')),
                ('ue_result', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='ec_results', to='grades.bulletinueresult')),
            ],
            options={
                'db_table': 'bulletin_ec_results',
                'unique_together': {('bulletin', 'subject')},
            },
        ),
    ]
