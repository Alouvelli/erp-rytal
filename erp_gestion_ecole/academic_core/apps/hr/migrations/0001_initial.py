from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffPresence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Date')),
                ('statut', models.CharField(
                    choices=[
                        ('PRESENT', 'Présent'),
                        ('ABSENT', 'Absent'),
                        ('RETARD', 'Retard'),
                        ('CONGE', 'En congé'),
                        ('DEMI_JOURNEE', 'Demi-journée'),
                        ('TELETRAVAIL', 'Télétravail'),
                        ('FERIE', 'Jour férié'),
                    ],
                    default='PRESENT', max_length=20, verbose_name='Statut',
                )),
                ('heure_arrivee', models.TimeField(blank=True, null=True, verbose_name="Heure d'arrivée")),
                ('heure_depart', models.TimeField(blank=True, null=True, verbose_name='Heure de départ')),
                ('justification', models.TextField(blank=True, verbose_name='Justification / Observations')),
                ('document', models.FileField(blank=True, null=True, upload_to='hr/justifications/', verbose_name='Document justificatif')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('enregistre_par', models.ForeignKey(
                    blank=True, db_constraint=False, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='presences_enregistrees',
                    to=settings.AUTH_USER_MODEL, verbose_name='Enregistré par',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='staff_presences',
                    to=settings.AUTH_USER_MODEL, verbose_name='Employé',
                )),
            ],
            options={
                'verbose_name': 'Présence personnel',
                'verbose_name_plural': 'Présences personnel',
                'db_table': 'staff_presences',
                'ordering': ['-date', 'user__last_name'],
            },
        ),
        migrations.CreateModel(
            name='DemandeConge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type_conge', models.CharField(
                    choices=[
                        ('ANNUEL', 'Congé annuel'),
                        ('MALADIE', 'Congé maladie'),
                        ('EXCEPTIONNEL', 'Congé exceptionnel'),
                        ('MATERNITE', 'Congé maternité/paternité'),
                        ('SANS_SOLDE', 'Congé sans solde'),
                        ('MISSION', 'Mission / Déplacement'),
                    ],
                    default='ANNUEL', max_length=20, verbose_name='Type de congé',
                )),
                ('date_debut', models.DateField(verbose_name='Date de début')),
                ('date_fin', models.DateField(verbose_name='Date de fin')),
                ('motif', models.TextField(verbose_name='Motif')),
                ('statut', models.CharField(
                    choices=[
                        ('EN_ATTENTE', 'En attente'),
                        ('APPROUVE', 'Approuvée'),
                        ('REJETE', 'Rejetée'),
                    ],
                    default='EN_ATTENTE', max_length=15, verbose_name='Statut',
                )),
                ('valide_le', models.DateTimeField(blank=True, null=True, verbose_name='Validé le')),
                ('commentaire_rh', models.TextField(blank=True, verbose_name='Commentaire RH')),
                ('document', models.FileField(blank=True, null=True, upload_to='hr/conges/', verbose_name='Document justificatif')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='demandes_conge',
                    to=settings.AUTH_USER_MODEL, verbose_name='Employé',
                )),
                ('valide_par', models.ForeignKey(
                    blank=True, db_constraint=False, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='conges_valides',
                    to=settings.AUTH_USER_MODEL, verbose_name='Validé par',
                )),
            ],
            options={
                'verbose_name': 'Demande de congé',
                'verbose_name_plural': 'Demandes de congé',
                'db_table': 'demandes_conge',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='staffpresence',
            index=models.Index(fields=['date'], name='staff_pres_date_idx'),
        ),
        migrations.AddIndex(
            model_name='staffpresence',
            index=models.Index(fields=['user', 'date'], name='staff_pres_user_date_idx'),
        ),
        migrations.AddIndex(
            model_name='staffpresence',
            index=models.Index(fields=['statut'], name='staff_pres_statut_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='staffpresence',
            unique_together={('user', 'date')},
        ),
        migrations.AddIndex(
            model_name='demandeconge',
            index=models.Index(fields=['user', 'statut'], name='conge_user_statut_idx'),
        ),
        migrations.AddIndex(
            model_name='demandeconge',
            index=models.Index(fields=['date_debut', 'date_fin'], name='conge_dates_idx'),
        ),
    ]
