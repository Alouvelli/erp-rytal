from django.db import migrations, models


def disable_fk(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.connection.cursor().execute("PRAGMA foreign_keys = OFF")


def enable_fk(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.connection.cursor().execute("PRAGMA foreign_keys = ON")


class Migration(migrations.Migration):
    """
    'auth' est dans MASTER_APP_LABELS (academic_core/db_router.py) : ses
    tables (auth_group, auth_permission) ne sont jamais migrées sur les bases
    tenant. Or User (modèle tenant, app 'accounts') hérite de AbstractUser,
    dont les champs groups/user_permissions pointent vers auth.Group/
    auth.Permission avec une contrainte FK réelle par défaut — cette
    application n'utilise de toute façon jamais ces deux modèles (RBAC maison
    via accounts.Role). Sous SQLite, l'absence de auth_group/auth_permission
    sur une base tenant passait inaperçue (FK non validée à la création de
    table) ; PostgreSQL valide l'existence de la table référencée dès
    l'ALTER TABLE / CREATE TABLE, provoquant "relation auth_group n'existe
    pas" à la toute première migration d'une base tenant. db_constraint=False
    supprime la contrainte FK réelle, comme déjà fait pour role/department/
    institut_config (voir les migrations *_fix_cross_db_fk_constraints.py).
    """

    atomic = False

    dependencies = [
        ("accounts", "0037_alter_platformactivation_code_prefix_hash"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(disable_fk, reverse_code=enable_fk),
        migrations.AlterField(
            model_name="user",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                db_constraint=False,
                help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
                related_name="user_set",
                related_query_name="user",
                to="auth.group",
                verbose_name="groups",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="user_permissions",
            field=models.ManyToManyField(
                blank=True,
                db_constraint=False,
                help_text="Specific permissions for this user.",
                related_name="user_set",
                related_query_name="user",
                to="auth.permission",
                verbose_name="user permissions",
            ),
        ),
        migrations.RunPython(enable_fk, reverse_code=disable_fk),
    ]
