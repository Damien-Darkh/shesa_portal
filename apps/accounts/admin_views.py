"""Administrator endpoints: employee lifecycle, NAS provisioning, roles, audit log."""
import re
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.common.audit import record
from apps.common.http import api_admin_required, error, ok, read_json
from apps.common.integrations import authentik_manager, mailer, synology_manager, wg_manager
from apps.common.utils import utcnow
from apps.core.models import Department, UserProfile
from apps.core.services import profile_dict, reconcile_manager_roles
from apps.devices.models import Device
from apps.devices.services import can_use_vpn, delete_all_devices, set_vpn_access

from .models import AuditLog, Role, User

NAS_PASSWORD_TTL = timedelta(minutes=15)
PROFILE_FIELDS = ("job_title", "phone", "office_location", "bio", "photo_url", "start_date")


def _serialize_user(user: User, detail: bool = False) -> dict:
    data = {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "disabled": user.disabled,
        "vpn_access": bool(user.vpn_access),
        "can_use_vpn": can_use_vpn(user),
        "nas_account": user.dsm_username,
        "authentik_account": user.authentik_username,
        "created_at": user.created_at.isoformat(),
        "profile": profile_dict(user),
        "device_count": Device.objects.filter(user=user, revoked_at__isnull=True).count(),
    }
    if detail:
        from apps.pto.models import LeaveBalance, LeaveRequest

        data["roles"] = [r.name for r in user.roles.all()]
        data["dsm_must_change_password"] = bool(user.dsm_must_change_password)
        data["leave_balances"] = [
            {"year": b.year, "leave_type": b.leave_type, "accrued_days": b.accrued_days,
             "carryover_days": b.carryover_days, "used_days": b.used_days,
             "pending_days": b.pending_days, "available_days": b.available_days}
            for b in LeaveBalance.objects.filter(user=user).order_by("-year", "leave_type")
        ]
        data["leave_requests"] = [
            {"id": r.id, "leave_type": r.leave_type, "start_date": r.start_date.isoformat(),
             "end_date": r.end_date.isoformat(), "days_requested": r.days_requested, "reason": r.reason,
             "status": r.status, "approver_comment": r.approver_comment, "created_at": r.created_at.isoformat()}
            for r in LeaveRequest.objects.filter(user=user).order_by("-created_at")[:200]
        ]
        data["devices"] = [
            {"id": d.id, "device_name": d.device_name, "is_revoked": d.is_revoked,
             "auto_revoked": d.auto_revoked, "wg_address": d.wg_address,
             "created_at": d.created_at.isoformat()}
            for d in Device.objects.filter(user=user)
        ]
    return data


def _apply_profile(user, data) -> str | None:
    """Writes the profile fields present in `data`. Returns an error message, or None on success."""
    if not any(k in data for k in PROFILE_FIELDS + ("department_id",)):
        return None
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if "department_id" in data:
        dept_id = data["department_id"] or None
        if dept_id is not None and not Department.objects.filter(pk=dept_id).exists():
            return "Department does not exist."
        profile.department_id = dept_id
    for field in PROFILE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if isinstance(value, str):
            value = value.strip() or None
        if field == "start_date" and value:
            try:
                value = date.fromisoformat(value)
            except ValueError:
                return "Invalid start_date (use YYYY-MM-DD)."
        if field == "photo_url" and value and len(value) > 350_000:
            return "Photo is too large (max 300 KB)."
        setattr(profile, field, value)
    profile.save()
    return None


def _nas_username(email: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", email.split("@")[0])[:32]


def _provision_authentik(user: User, first_name, last_name, make_admin: bool) -> tuple[str | None, str | None]:
    if not settings.AUTHENTIK_API_URL:
        return None, None
    username = _nas_username(user.email)
    if authentik_manager.user_exists(username):
        return None, None
    _pk, password = authentik_manager.create_user(
        username=username, email=user.email, first_name=first_name, last_name=last_name, is_admin=make_admin,
    )
    user.authentik_username = username
    user.save(update_fields=["authentik_username"])
    return username, password


def _provision_nas(user: User, first_name, last_name, make_admin: bool) -> tuple[str | None, str | None]:
    if not settings.DSM_URL:
        return None, None
    group = synology_manager.DSM_ADMIN_GROUP if make_admin else synology_manager.DSM_SHARE_GROUP
    username = _nas_username(user.email)
    if synology_manager.user_exists(username):
        return None, None
    temp = synology_manager.create_user(
        username=username, email=user.email, first_name=first_name, last_name=last_name, group=group,
    )
    user.dsm_username = username
    user.dsm_password_token = secrets.token_urlsafe(32)
    user.dsm_temp_password = None
    user.dsm_password_expires_at = utcnow() + NAS_PASSWORD_TTL
    user.dsm_must_change_password = True
    user.save()
    return username, temp


@api_admin_required
@require_http_methods(["GET", "POST"])
def users(request):
    if request.method == "GET":
        qs = User.objects.order_by("email")
        search = request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(email__icontains=search)
        return ok({"users": [_serialize_user(u) for u in qs]})

    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))
    email = (data.get("email") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip() or None
    last_name = (data.get("last_name") or "").strip() or None
    make_admin = bool(data.get("is_admin"))
    if not email or "@" not in email:
        return error(400, "Enter a valid email address.")
    if User.objects.filter(email=email).exists():
        return error(409, f"{email} already has an account.")

    user = User.objects.create(
        email=email, is_admin=make_admin, first_name=first_name, last_name=last_name,
        vpn_access=bool(data.get("vpn_access")) and not make_admin,
    )
    profile_error = _apply_profile(user, data)
    if profile_error:
        user.delete()
        return error(422, profile_error)
    warnings, nas_username, temp_password = [], None, None
    try:
        nas_username, temp_password = _provision_nas(user, first_name, last_name, make_admin)
    except synology_manager.DsmApiError as exc:
        warnings.append(f"Portal account created, but NAS account failed: {exc}")

    authentik_username, authentik_temp_password = None, None
    try:
        authentik_username, authentik_temp_password = _provision_authentik(user, first_name, last_name, make_admin)
    except authentik_manager.AuthentikApiError as exc:
        warnings.append(f"Portal account created, but Authentik sign-in account failed: {exc}")

    if nas_username and temp_password:
        try:
            mailer.send_welcome_email(
                recipient_email=email, username=nas_username, passphrase=temp_password,
                first_name=first_name, last_name=last_name,
            )
        except Exception as exc:
            warnings.append(f"Welcome email failed: {exc}")

    record(request, "CREATE", "user", user.id, details={
        "email": email, "nas": bool(nas_username), "authentik": bool(authentik_username),
    })
    return ok({
        "user": _serialize_user(user, detail=True),
        "nas_temporary_password": temp_password,
        "authentik_username": authentik_username,
        "authentik_temporary_password": authentik_temp_password,
        "warnings": warnings,
    }, status=201)


@api_admin_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    if request.method == "GET":
        return ok(_serialize_user(user, detail=True))

    if request.method == "DELETE":
        if user.id == request.user.id:
            return error(422, "You can't delete your own account.")
        warnings = delete_all_devices(user)
        if settings.DSM_URL and user.dsm_username:
            try:
                synology_manager.delete_user(user.dsm_username)
            except synology_manager.DsmApiError as exc:
                warnings.append(f"NAS account deletion failed: {exc}")
        if settings.AUTHENTIK_API_URL and user.authentik_username:
            try:
                authentik_manager.delete_user(user.authentik_username)
            except authentik_manager.AuthentikApiError as exc:
                warnings.append(f"Authentik account deletion failed: {exc}")
        elif not user.authentik_username:
            warnings.append("No linked Authentik account on record; remove it there manually if one exists.")
        email, uid = user.email, user.id
        user.delete()
        record(request, "DELETE", "user", uid, details={"email": email})
        return ok({"deleted": True, "warnings": warnings})

    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))

    warnings: list[str] = []
    changed: list[str] = []

    if "email" in data:
        new_email = (data["email"] or "").strip().lower()
        if not new_email or "@" not in new_email:
            return error(400, "Enter a valid email address.")
        if new_email != user.email and User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
            return error(409, f"{new_email} is already in use by another account.")
        user.email = new_email
        changed.append("email")
    for name in ("first_name", "last_name"):
        if name in data:
            setattr(user, name, (data[name] or "").strip() or None)
            changed.append(name)

    if "is_admin" in data and user.id != request.user.id:
        user.is_admin = bool(data["is_admin"])
        changed.append("is_admin")

    if "disabled" in data and user.id != request.user.id:
        now_disabled = bool(data["disabled"])
        if now_disabled and not user.disabled:
            warnings += delete_all_devices(user)
        user.disabled = now_disabled
        changed.append("disabled")

    if "vpn_access" in data and not user.is_admin:
        want_vpn = bool(data["vpn_access"])
        if want_vpn != bool(user.vpn_access):
            user.vpn_access = want_vpn
            changed.append("vpn_access")
            warnings += set_vpn_access(user, want_vpn)

    if "roles" in data:
        names = data["roles"] or []
        roles = list(Role.objects.filter(name__in=names))
        if len(roles) != len(set(names)):
            return error(422, "One or more roles do not exist.")
        user.roles.set(roles)
        changed.append("roles")

    profile_error = _apply_profile(user, data)
    if profile_error:
        return error(422, profile_error)
    if "department_id" in data:
        changed.append("department")

    user.save()
    lost = reconcile_manager_roles(user) if "department_id" in data else []
    record(request, "UPDATE", "user", user.id, details={"fields": changed})

    body = _serialize_user(user, detail=True)
    body["warnings"] = warnings + [f"No longer manages: {name}." for name in lost]
    return ok(body)


@api_admin_required
@require_POST
def toggle_disabled(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user.id == request.user.id:
        return error(422, "You can't disable your own account.")
    warnings = []
    if not user.disabled:
        warnings += delete_all_devices(user)
    user.disabled = not user.disabled
    user.save()
    if settings.AUTHENTIK_API_URL and user.authentik_username:
        try:
            authentik_manager.set_active(user.authentik_username, active=not user.disabled)
        except authentik_manager.AuthentikApiError as exc:
            warnings.append(f"Portal status changed, but Authentik account was not updated: {exc}")
    record(request, "UPDATE", "user", user.id, details={"disabled": user.disabled})
    body = _serialize_user(user)
    body["warnings"] = warnings
    return ok(body)


@api_admin_required
@require_POST
def toggle_admin(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user.id == request.user.id:
        return error(422, "You can't change your own admin status.")
    user.is_admin = not user.is_admin
    user.save()
    record(request, "UPDATE", "user", user.id, details={"is_admin": user.is_admin})
    return ok(_serialize_user(user))


@api_admin_required
@require_POST
def reset_nas_password(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if not settings.DSM_URL or not user.dsm_username:
        return error(422, "This user doesn't have a NAS account.")
    try:
        new_password = synology_manager.reset_password(user.dsm_username)
    except synology_manager.DsmApiError as exc:
        return error(502, f"Could not reset NAS password: {exc}")
    user.dsm_password_token = secrets.token_urlsafe(32)
    user.dsm_temp_password = None
    user.dsm_password_expires_at = utcnow() + NAS_PASSWORD_TTL
    user.dsm_must_change_password = True
    user.save()
    record(request, "UPDATE", "nas_password", user.id, details={"reset_by_admin": True})
    return ok({"nas_temporary_password": new_password, "must_change_password": True})


@api_admin_required
@require_POST
def reset_authentik_password(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if not settings.AUTHENTIK_API_URL or not user.authentik_username:
        return error(422, "This user doesn't have an Authentik account on record.")
    try:
        new_password = authentik_manager.reset_password(user.authentik_username)
    except authentik_manager.AuthentikApiError as exc:
        return error(502, f"Could not reset Authentik password: {exc}")
    record(request, "UPDATE", "authentik_password", user.id, details={"reset_by_admin": True})
    return ok({"authentik_temporary_password": new_password})


@api_admin_required
@require_GET
def audit_logs(request):
    qs = AuditLog.objects.select_related("user").order_by("-timestamp")
    user_id = request.GET.get("user_id")
    if user_id and user_id.isdigit():
        qs = qs.filter(user_id=int(user_id))
    action = request.GET.get("action")
    if action:
        qs = qs.filter(action=action.upper())
    return ok({"logs": [
        {"id": a.id, "user": a.user.email if a.user else None, "action": a.action,
         "resource_type": a.resource_type, "resource_id": a.resource_id, "status": a.status,
         "details": a.details, "ip_address": a.ip_address, "timestamp": a.timestamp.isoformat()}
        for a in qs[:500]
    ]})