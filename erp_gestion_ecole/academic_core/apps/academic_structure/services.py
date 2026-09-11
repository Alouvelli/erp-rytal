"""
Logique métier partagée de l'app academic_structure — pour l'instant,
uniquement la nomination d'un chef de département (Department.admin),
factorisée pour être appelée depuis plusieurs points d'entrée (gestion des
départements, action rapide depuis la liste des enseignants) sans dupliquer
les 3 écritures nécessaires (rôle, département, FK Department.admin).
"""


def assign_department_head(department, user):
    """
    Nomme `user` chef de département (RESPONSABLE) de `department` :
      1. Détache l'ancien chef s'il y en avait un (department = None
         uniquement — il garde son rôle, comme _assign_admin le faisait déjà).
      2. Bascule le rôle de `user` vers RESPONSABLE (sans quoi la personne
         pointée par Department.admin n'a pas réellement les permissions
         d'un chef de département — is_responsable()/can_manage_dept()
         vérifient User.role, pas Department.admin).
      3. Rattache `user` à `department` (User.department) et le pose comme
         Department.admin.

    Utilisée par DepartmentManageView._assign_admin (Gestion des départements)
    et par la nouvelle action « Nommer chef de département » de la liste des
    enseignants — un enseignant existant doit pouvoir être promu directement,
    sans passer par la création d'un nouveau compte.
    """
    from academic_core.apps.accounts.models import Role

    if department.admin_id and department.admin_id != user.pk:
        old = department.admin
        old.department = None
        old.save(update_fields=['department'])

    responsable_role = Role.objects.filter(name=Role.RESPONSABLE).first()
    if responsable_role:
        user.role = responsable_role
    user.department = department
    user.save(update_fields=['role', 'department'])

    department.admin = user
    department.save(update_fields=['admin'])
    return user
