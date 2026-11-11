"""VPN device endpoints (JSON)."""
import base64
import io
import secrets

import qrcode
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from apps.common.audit import record
from apps.common.http import api_admin_required, api_login_required, error, ok, read_json
from apps.common.integrations import windows_launcher, wg_manager
from apps.common.utils import utcnow

from .models import Device
from .services import provision_device

LAUNCHER_INVALID_MESSAGE = (
    "This one-time setup link has expired or was already used. "
    "Please re-download the launcher from the portal."
)


def _serialize(device: Device) -> dict:
    return {
        "id": device.id,
        "device_name": device.device_name,
        "wg_address": device.wg_address,
        "created_at": device.created_at.isoformat(),
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
        "is_revoked": device.is_revoked,
        "auto_revoked": device.auto_revoked,
        "launcher_available": device.launcher_available,
        "owner_id": device.user_id,
    }


def _can_manage(request, device: Device) -> bool:
    return device.user_id == request.user.id or request.user.is_admin


@api_login_required
@require_GET
def device_list(request):
    devices = Device.objects.select_related("user").all()
    if not request.user.is_admin:
        devices = devices.filter(user=request.user)
    return ok({"devices": [_serialize(d) for d in devices]})


def _qr_png_base64(conf: str) -> str:
    buf = io.BytesIO()
    qrcode.make(conf).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _create_response(request, owner, device_name: str):
    try:
        device, result = provision_device(owner, device_name)
    except wg_manager.WgApiError as exc:
        return error(502, f"Could not create VPN access: {exc}")
    record(request, "CREATE", "device", device.id, details={"owner_id": owner.id, "name": device_name})
    # The WireGuard config (contains the private key) is returned exactly once here.
    return ok({
        "device": _serialize(device),
        "config": result["conf"],
        "qr_png_base64": _qr_png_base64(result["conf"]),
    }, status=201)


@api_login_required
@require_POST
def device_create(request):
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))
    device_name = (data.get("device_name") or "").strip()
    if not device_name:
        return error(400, "Please name this device (e.g. 'iPhone', 'Work Laptop').")
    if Device.objects.filter(user=request.user, device_name=device_name).exists():
        return error(409, "You already have a device with this name.")
    return _create_response(request, request.user, device_name)


@api_admin_required
@require_POST
def admin_device_create(request, user_id):
    from apps.accounts.models import User

    owner = get_object_or_404(User, pk=user_id)
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))
    device_name = (data.get("device_name") or "").strip()
    if not device_name:
        return error(400, "Please name this device (e.g. 'iPhone', 'Work Laptop').")
    return _create_response(request, owner, device_name)


@api_login_required
@require_POST
def device_revoke(request, device_id):
    device = get_object_or_404(Device, pk=device_id)
    if not _can_manage(request, device):
        return error(403, "Not allowed.")
    if not device.is_revoked:
        try:
            wg_manager.revoke_peer(device.wg_uuid)
        except wg_manager.WgApiError as exc:
            return error(502, f"Could not disconnect VPN peer: {exc}")
        device.revoked_at = utcnow()
        device.save()
        record(request, "DEVICE_REVOKE", "device", device.id)
    return ok(_serialize(device))


@api_login_required
@require_POST
def device_reconnect(request, device_id):
    device = get_object_or_404(Device, pk=device_id)
    if not _can_manage(request, device):
        return error(403, "Not allowed.")
    if device.is_revoked and not device.auto_revoked:
        try:
            wg_manager.enable_peer(device.wg_uuid)
        except wg_manager.WgApiError as exc:
            return error(502, f"Could not reconnect VPN peer: {exc}")
        device.revoked_at = None
        device.save()
        record(request, "UPDATE", "device", device.id, details={"action": "reconnect"})
    return ok(_serialize(device))


@api_admin_required
@require_POST
def device_delete(request, device_id):
    device = get_object_or_404(Device, pk=device_id)
    try:
        wg_manager.delete_peer(device.wg_uuid)
    except wg_manager.WgApiError as exc:
        return error(502, f"Could not remove VPN peer: {exc}")
    name, owner_id = device.device_name, device.user_id
    device.delete()
    record(request, "DELETE", "device", device_id, details={"name": name, "owner_id": owner_id})
    return ok({"deleted": True})


@api_login_required
@require_GET
def device_launcher_cmd(request, device_id):
    """The generic .cmd. It holds only a device id and a one-time token, so it is safe to download."""
    device = get_object_or_404(Device, pk=device_id, user=request.user)
    if not device.launcher_available or not settings.PUBLIC_APP_URL:
        return error(404, "No launcher available for this device.")
    cmd_text = windows_launcher.render_cmd(
        device_id=device.id, token=device.launcher_token, portal_url=settings.PUBLIC_APP_URL,
    )
    response = HttpResponse(cmd_text, content_type="text/plain")
    response["Content-Disposition"] = 'attachment; filename="Connect Company Network.cmd"'
    return response


@require_GET
def device_launcher_script(request, device_id):
    """Fetched by the .cmd's PowerShell one-liner. No browser session here, so access
    is gated only by the one-time token. Deliberately not login-protected."""
    device = Device.objects.filter(pk=device_id).first()
    token = request.GET.get("token", "")
    valid = (
        device is not None
        and bool(device.launcher_token)
        and token.isascii()
        and secrets.compare_digest(device.launcher_token, token)
        and device.launcher_token_expires_at is not None
        and device.launcher_token_expires_at > utcnow()
    )
    if not valid:
        return HttpResponse(f"Write-Host '{LAUNCHER_INVALID_MESSAGE}' -ForegroundColor Red", content_type="text/plain")

    # Single-use claim: only the first fetch wins, and the script (with the WG private key) is wiped.
    script = device.launcher_script
    claimed = Device.objects.filter(pk=device.pk, launcher_token=device.launcher_token).update(
        launcher_token=None, launcher_script=None, launcher_token_expires_at=None,
    )
    if claimed != 1:
        return HttpResponse(f"Write-Host '{LAUNCHER_INVALID_MESSAGE}' -ForegroundColor Red", content_type="text/plain")
    return HttpResponse(script, content_type="text/plain")
