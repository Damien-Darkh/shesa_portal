"""WireGuard device lifecycle. Shared by the self-service and admin endpoints."""
import secrets
from datetime import timedelta

from django.conf import settings

from apps.common.integrations import windows_launcher, wg_manager
from apps.common.utils import utcnow

from .models import Device


def provision_device(owner, device_name: str):
    """Creates the WireGuard peer, the DB row and (if configured) the one-time launcher.
    Raises wg_manager.WgApiError if the peer cannot be created."""
    local_part = owner.email.split("@")[0]
    result = wg_manager.create_peer(f"{local_part}_{device_name}")

    device = Device.objects.create(
        user=owner,
        device_name=device_name,
        wg_uuid=result["uuid"],
        wg_api_name=result["api_name"],
        wg_address=result["address"],
    )

    if settings.NAS_IP and settings.NAS_SHARE_NAME:
        device.launcher_token = secrets.token_urlsafe(32)
        device.launcher_script = windows_launcher.render_ps1(
            device_id=device.id,
            tunnel_name=result["api_name"],
            nas_ip=settings.NAS_IP,
            share_name=settings.NAS_SHARE_NAME,
            wg=result,
        )
        device.launcher_token_expires_at = utcnow() + timedelta(minutes=settings.LAUNCHER_TOKEN_TTL_MINUTES)
        device.save()

    return device, result


def sync_devices_to_disabled_state(user, was_disabled: bool, now_disabled: bool) -> None:
    """Revoke/restore a user's VPN peers when the account is disabled or re-enabled.
    Only devices auto-revoked by this action are restored."""
    if now_disabled and not was_disabled:
        for device in user.devices.all():
            if not device.is_revoked:
                try:
                    wg_manager.revoke_peer(device.wg_uuid)
                except wg_manager.WgApiError:
                    pass
                device.revoked_at = utcnow()
                device.auto_revoked = True
                device.save()
    elif was_disabled and not now_disabled:
        for device in user.devices.all():
            if device.is_revoked and device.auto_revoked:
                try:
                    wg_manager.enable_peer(device.wg_uuid)
                except wg_manager.WgApiError:
                    pass
                device.revoked_at = None
                device.auto_revoked = False
                device.save()
