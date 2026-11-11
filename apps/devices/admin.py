from django.contrib import admin

from .models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("device_name", "user", "wg_address", "created_at", "revoked_at", "auto_revoked")
    list_filter = ("auto_revoked",)
    search_fields = ("device_name", "user__email", "wg_address")
    readonly_fields = ("wg_uuid", "wg_api_name", "launcher_token", "launcher_script")
