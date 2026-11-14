from django.urls import path

from apps.devices import views as device_views
from apps.pto import views as pto_views

from . import admin_views

urlpatterns = [
    path("users/", admin_views.users, name="admin_users"),
    path("users/<int:user_id>/", admin_views.user_detail, name="admin_user_detail"),
    path("users/<int:user_id>/toggle-disabled", admin_views.toggle_disabled, name="admin_toggle_disabled"),
    path("users/<int:user_id>/toggle-admin", admin_views.toggle_admin, name="admin_toggle_admin"),
    path("users/<int:user_id>/reset-nas-password", admin_views.reset_nas_password, name="admin_reset_nas_password"),
    path(
        "users/<int:user_id>/reset-authentik-password",
        admin_views.reset_authentik_password,
        name="admin_reset_authentik_password",
    ),
    path("users/<int:user_id>/identity-id/replace", admin_views.identity_id_replace,
         name="admin_identity_id_replace"),
    path("users/<int:user_id>/devices", device_views.admin_device_create, name="admin_device_create"),
    path("users/<int:user_id>/leave-balances", pto_views.admin_user_balances, name="admin_leave_balances"),
    path("audit-logs/", admin_views.audit_logs, name="admin_audit_logs"),
]