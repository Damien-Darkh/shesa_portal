from django.contrib import admin

from .models import AuditLog, Permission, Role, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "is_admin", "disabled", "dsm_username")
    list_filter = ("is_admin", "disabled")
    search_fields = ("email", "first_name", "last_name")
    filter_horizontal = ("roles",)
    readonly_fields = ("password", "oidc_subject", "created_at")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    filter_horizontal = ("permissions",)


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("name", "resource", "action")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "resource_type", "resource_id", "status")
    list_filter = ("action", "status", "resource_type")
    search_fields = ("user__email",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # append-only
