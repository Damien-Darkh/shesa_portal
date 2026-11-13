"""WireGuard device lifecycle. Shared by the self-service and admin endpoints."""
import secrets
from datetime import timedelta

from django.conf import settings

from apps.common.integrations import windows_launcher, wg_manager
from apps.common.utils import utcnow

from .models import Device


def can_use_vpn(user) -> bool:
    """Admins always have VPN. Everyone else needs the per-employee flag."""
    return bool(user.is_admin or user.vpn_access)


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


def set_vpn_access(user, enabled: bool) -> list[str]:
    """Turns VPN access on or off without touching the account.
    Off: disables each live peer on OPNsense and marks it auto_revoked (kept, restorable).
    On: re-enables only peers this action auto-revoked.
    Returns warnings for any OPNsense call that failed."""
    warnings = []
    if enabled:
        for device in user.devices.filter(auto_revoked=True, revoked_at__isnull=False):
            try:
                wg_manager.enable_peer(device.wg_uuid)
            except wg_manager.WgApiError as exc:
                warnings.append(f"Could not re-enable '{device.device_name}': {exc}")
                continue
            device.revoked_at = None
            device.auto_revoked = False
            device.save(update_fields=["revoked_at", "auto_revoked"])
    else:
        for device in user.devices.filter(revoked_at__isnull=True):
            try:
                wg_manager.revoke_peer(device.wg_uuid)
            except wg_manager.WgApiError as exc:
                warnings.append(f"Could not disconnect '{device.device_name}' on the VPN server: {exc}")
            device.revoked_at = utcnow()
            device.auto_revoked = True
            device.save(update_fields=["revoked_at", "auto_revoked"])
    return warnings


def delete_all_devices(user) -> list[str]:
    """Removes every VPN peer of an employee, from OPNsense and from the database.
    Used when the account is disabled or deleted. Deleted devices cannot be restored.
    Returns warnings for any OPNsense call that failed."""
    warnings = []
    for device in list(user.devices.all()):
        try:
            wg_manager.delete_peer(device.wg_uuid)
        except wg_manager.WgApiError as exc:
            warnings.append(f"Could not remove '{device.device_name}' from the VPN server: {exc}")
        device.delete()
    return warnings
