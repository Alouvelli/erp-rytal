from django.db import migrations


def seed_missing_roles(apps, schema_editor):
    # Voir 0029 : .using(alias) obligatoire, InstitutRouter route sinon vers 'default'.
    # ASSISTANTE_DG et ASSISTANTE_DIRECTION figurent dans les choices de Role.name
    # depuis la migration 0016, mais celle-ci ne faisait que modifier le champ
    # (AlterField) sans jamais créer les lignes correspondantes : aucune migration
    # ultérieure ne les a créées non plus. Toute affectation de ces deux rôles
    # échouait donc avec Role.DoesNotExist.
    alias = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    for code, label in [
        ("ASSISTANTE_DG", "Assistante du Directeur Général"),
        ("ASSISTANTE_DIRECTION", "Assistante de Direction"),
    ]:
        Role.objects.using(alias).get_or_create(name=code, defaults={"description": label})


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0029_add_admin_rh_assistante_de_roles"),
    ]

    operations = [
        migrations.RunPython(seed_missing_roles, migrations.RunPython.noop),
    ]
