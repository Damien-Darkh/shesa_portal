"""Sign-in/out and the signed-in user's own profile and NAS password."""
from urllib.parse import urlencode

from django.conf import settings
from django.views.decorators.cache import never_cache
from django.contrib.auth import logout as auth_logout
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.http import Http404, HttpResponse
from apps.common.integrations import unix_launcher

from apps.common.audit import record
from apps.common.http import api_login_required, error, ok, read_json
from apps.common.integrations import synology_manager
from apps.common.integrations import sanity_sync
from apps.common.integrations import sanity_photo, sanity_projects
from apps.common.integrations.sanity_client import SanityError
from apps.common.integrations import authentik_manager
from apps.common.utils import utcnow
from apps.core.services import profile_dict

LANGUAGES = ("it", "en")


def _safe_next(value: str | None) -> str | None:
    """Only same-site relative paths may be used after sign-in (blocks open redirects)."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return None


def sso_login_url(next_url: str | None = None) -> str:
    url = reverse("openid_connect_login", kwargs={"provider_id": settings.OIDC_PROVIDER_ID})
    return f"{url}?{urlencode({'next': next_url})}" if next_url else url


@never_cache
def login_view(request):
    """Sign-in starts at Authentik: anonymous visitors are sent there directly, signed-in users go to the dashboard."""
    if not settings.USE_SSO or request.user.is_authenticated:
        return HttpResponseRedirect("/index.html")
    return HttpResponseRedirect(sso_login_url(_safe_next(request.GET.get("next"))))


@require_GET
def auth_config(request):
    next_url = _safe_next(request.GET.get("next"))
    return ok({
        "sso_url": sso_login_url(next_url),
        "provider_name": settings.OIDC_PROVIDER_NAME,
        "sso_enabled": settings.USE_SSO,
        "leave_management_enabled": settings.LEAVE_MANAGEMENT_ENABLED,
    })


def sso_logout_url(post_logout_redirect: str) -> str:
    """Authentik's end-session endpoint. Ends the Authentik session as well, so the next
    sign-in actually shows the login form instead of silently re-logging the user in."""
    base = settings.OIDC_SERVER_URL.rstrip("/")
    return f"{base}/end-session/?{urlencode({'post_logout_redirect_uri': post_logout_redirect, 'client_id': settings.OIDC_CLIENT_ID})}"


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """GET: used by the nav link (logs out of the portal and Authentik, then back to the logout page).
    POST: JSON for scripts (portal session only)."""
    if request.user.is_authenticated:
        auth_logout(request)  # signal writes the LOGOUT audit row
    if request.method == "GET":
        landing = request.build_absolute_uri("/logout.html?signedout=1")
        if settings.USE_SSO and settings.OIDC_SERVER_URL:
            return HttpResponseRedirect(sso_logout_url(landing))
        return HttpResponseRedirect("/logout.html?signedout=1")
    return ok({"logged_out": True})


# apps/accounts/views.py (add), or wherever your signed-in user endpoints live
from django.http import Http404, HttpResponse
from django.conf import settings
from apps.common.http import api_login_required
from apps.common.integrations import unix_launcher


@api_login_required
@require_GET
def nas_logout_installer(request, platform):
    if not settings.NAS_IP:
        raise Http404
    if platform == "mac":
        body = unix_launcher.render_macos_installer(settings.NAS_IP)
        name = "Install NAS Sign-out Cleanup.command"
    elif platform == "linux":
        body = unix_launcher.render_linux_installer(settings.NAS_IP)
        name = "install-nas-signout-cleanup.sh"
    else:
        raise Http404
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Cache-Control"] = "no-store"
    return response

def _serialize_me(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "disabled": user.disabled,
        "language": user.language,
        "roles": [r.name for r in user.roles.all()],
        "dsm_username": user.dsm_username,
        "dsm_must_change_password": bool(user.dsm_must_change_password),
        "profile": profile_dict(user),
        "other_emails": user.other_emails or [],
        "linkedin_url": user.linkedin_url,
        "profile_text": user.profile_text,
        "project_ids": user.project_ids or [],
        "show_on_website": bool(user.show_on_website),
        "website_consent_at": user.website_consent_at.isoformat() if user.website_consent_at else None,
        "sanity_pending": bool(user.sanity_pending),
        "sanity_last_error": user.sanity_last_error,
        "photo_url": sanity_photo.display_url(user),
        "identity_id": user.identity_id,
        "leave_management_enabled": bool(settings.LEAVE_MANAGEMENT_ENABLED),
        "can_use_vpn": bool(user.is_admin or user.vpn_access),
        "vpn_access": bool(user.vpn_access),
    }

def _push_to_sanity_warning(user) -> list[str]:
    try:
        sanity_sync.push_user(user)
    except sanity_sync.PushError:
        return ["Saved in the portal, but the website is not updated yet. It will retry automatically."]
    return []

EMPLOYEE_EDITABLE = {"phone", "other_emails", "linkedin_url", "bio", "profile_text",
                     "project_ids", "show_on_website", "website_consent"}


@api_login_required
@require_http_methods(["GET", "PATCH"])
def me(request):
    user = request.user
    if request.method == "GET":
        return ok(_serialize_me(user))

    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))

    if "language" in data and data["language"] not in LANGUAGES:
        return error(422, "Unsupported language.")

    forbidden = [k for k in data if k not in EMPLOYEE_EDITABLE | {"language"}]
    if forbidden:
        return error(403, f"You cannot change: {', '.join(forbidden)}. Contact HR.")

    changed: list[str] = []
    try:
        if "language" in data:
            user.language = data["language"]
            changed.append("language")

        if "linkedin_url" in data:
            user.linkedin_url = _validate_linkedin(data["linkedin_url"])
            changed.append("linkedin_url")

        if "other_emails" in data:
            user.other_emails = [e.strip() for e in (data["other_emails"] or []) if e and e.strip()]
            changed.append("other_emails")

        if "profile_text" in data:
            user.profile_text = (data["profile_text"] or "").strip() or None
            changed.append("profile_text")

        if "project_ids" in data:
            ids = list(data["project_ids"] or [])
            new_ids = set(ids) - set(user.project_ids or [])
            if new_ids:
                # Only additions need checking, so removing a project still works if Sanity is slow.
                try:
                    available = {p["id"] for p in sanity_projects.list_projects()}
                except SanityError:
                    return error(503, "Projects are unavailable right now. Try again shortly.")
                if new_ids - available:
                    return error(422, "One or more selected projects are not available.")
            user.project_ids = ids
            changed.append("project_ids")

        if "show_on_website" in data:
            want = bool(data["show_on_website"])
            if want and not user.show_on_website:
                if not data.get("website_consent"):
                    return error(422, "Please confirm consent before publishing your profile.")
                user.website_consent_at = utcnow()
            user.show_on_website = want
            changed.append("show_on_website")
    except ValueError as exc:
        return error(422, str(exc))

    user.save()

    # Phone and bio live on the profile, not on the user.
    profile_fields = {k: data[k] for k in ("phone", "bio") if k in data}
    if profile_fields:
        from apps.accounts.admin_views import _apply_profile  # lazy import avoids a circular import
        _apply_profile(user, profile_fields)
        changed += list(profile_fields)

    if changed:
        record(request, "UPDATE", "user", user.id, details={"self_edit": changed})

    warnings = _push_to_sanity_warning(user) if changed else []
    body = _serialize_me(user)
    body["warnings"] = warnings
    return ok(body)


def _validate_linkedin(value: str | None) -> str | None:
    from urllib.parse import urlparse
    value = (value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith("linkedin.com"):
        raise ValueError("LinkedIn must be an https link on linkedin.com.")
    return value


@api_login_required
@require_POST
def change_dsm_password(request):
    user = request.user
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))

    new_password = (data.get("new_password") or "").strip()
    if not new_password:
        return error(400, "Password is required.")
    if new_password != (data.get("confirm_password") or "").strip():
        return error(400, "Passwords do not match.")
    if not user.dsm_must_change_password and not data.get("voluntary", False):
        pass  # voluntary change is allowed too

    description = f"{user.first_name or ''} {user.last_name or ''}".strip()
    changed = []
    try:
        if settings.AUTHENTIK_API_URL and user.authentik_username:
            authentik_manager.set_password(user.authentik_username, new_password)
            changed.append("authentik")
        if settings.DSM_URL and user.dsm_username:
            synology_manager.update_password(user.dsm_username, new_password, description=description)
            changed.append("nas")
    except synology_manager.PasswordPolicyError as exc:
        return error(422, str(exc))
    except (synology_manager.DsmApiError, authentik_manager.AuthentikApiError) as exc:
        return error(502, f"Could not update the password: {exc}")

    if not changed:
        return error(400, "No sign-in or NAS account is linked to your user.")

    user.dsm_must_change_password = False
    user.dsm_temp_password = None
    user.dsm_password_token = None
    user.dsm_password_expires_at = None
    user.save()
    record(request, "UPDATE", "shared_password", user.id, details={"updated": changed})
    return ok({"updated": True, "updated_accounts": changed})

@api_login_required
@require_GET
def my_projects(request):
    try:
        items = sanity_projects.list_projects()
    except SanityError:
        return error(503, "Projects are unavailable right now. Try again shortly.")
    return ok({"projects": items, "selected": request.user.project_ids or []})


@api_login_required
@require_http_methods(["POST", "DELETE"])
def my_photo(request):
    user = request.user
    try:
        if request.method == "DELETE":
            sanity_photo.remove_photo(user)
            record(request, "UPDATE", "user", user.id, details={"self_edit": ["photo"], "removed": True})
            return ok({"photo_url": None})
        upload = request.FILES.get("photo")
        if not upload:
            return error(400, "Choose a photo to upload.")
        url = sanity_photo.set_photo(user, upload)
    except sanity_photo.PhotoError as exc:
        return error(422, str(exc))
    record(request, "UPDATE", "user", user.id, details={"self_edit": ["photo"]})
    return ok({"photo_url": url})