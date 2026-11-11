"""Default roles and permissions. Run via `manage.py seed_rbac` (idempotent)."""
from django.db import transaction

from apps.accounts.models import Permission, Role

PERMISSIONS = [
    ("view_user", "user", "view", "View user profiles"),
    ("edit_user", "user", "edit", "Edit user details"),
    ("create_user", "user", "create", "Create new user"),
    ("delete_user", "user", "delete", "Delete user account"),
    ("view_device", "device", "view", "View VPN devices"),
    ("create_device", "device", "create", "Add new VPN device"),
    ("revoke_device", "device", "revoke", "Disconnect VPN device"),
    ("delete_device", "device", "delete", "Delete VPN device"),
    ("view_own_leave", "pto", "view_own", "View own PTO balance"),
    ("request_leave", "pto", "request", "Request time off"),
    ("approve_leave", "pto", "approve", "Approve leave requests"),
    ("view_team_leave", "pto", "view_team", "View team leave requests"),
    ("view_audit_log", "audit", "view", "View audit logs"),
    ("manage_roles", "rbac", "manage", "Manage roles and permissions"),
    ("view_directory", "directory", "view", "View employee directory"),
]

ROLES = {
    "admin": {
        "description": "System administrator",
        "permissions": ["view_user", "edit_user", "create_user", "delete_user",
                        "view_device", "create_device", "revoke_device", "delete_device",
                        "approve_leave", "view_team_leave",
                        "view_audit_log", "manage_roles", "view_directory"],
    },
    "manager": {
        "description": "Department manager",
        "permissions": ["view_user", "view_device", "approve_leave", "view_team_leave", "view_directory"],
    },
    "employee": {
        "description": "Standard employee",
        "permissions": ["view_own_leave", "request_leave", "view_device", "create_device", "view_directory"],
    },
    "hr": {
        "description": "Human Resources",
        "permissions": ["view_user", "edit_user", "view_team_leave", "approve_leave",
                        "view_audit_log", "view_directory"],
    },
    "it": {
        "description": "IT Support",
        "permissions": ["view_user", "view_device", "create_device", "revoke_device", "view_audit_log"],
    },
}


def seed_roles_and_permissions() -> bool:
    """Creates any missing roles/permissions. Returns True if anything was created."""
    created_any = False
    with transaction.atomic():
        perms = {}
        for name, resource, action, description in PERMISSIONS:
            perm, created = Permission.objects.get_or_create(
                name=name,
                defaults={"resource": resource, "action": action, "description": description},
            )
            perms[name] = perm
            created_any = created_any or created

        for role_name, data in ROLES.items():
            role, created = Role.objects.get_or_create(
                name=role_name, defaults={"description": data["description"]}
            )
            if created:
                role.permissions.set([perms[p] for p in data["permissions"]])
                created_any = True
    return created_any
