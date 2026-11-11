"""
authentik_manager.py - Authentik identity-provider account management via its
REST Admin API (https://goauthentik.io/developer-docs/api/).

Mirrors synology_manager.py's shape on purpose: same style of module-level
config from the environment, a single <Thing>ApiError exception, and plain
functions rather than a client class. Used by admin_views.py so that adding
an employee in the portal also creates their sign-in account in Authentik,
instead of that being a separate manual step in the Authentik UI.
"""

import os
import secrets
import string

import logging
import requests

# Base URL of the Authentik instance, reachable from the *portal container*.
# Inside Docker this is the internal network alias (see docker-compose.authentik.yml),
# not the public-facing host the browser uses - those can differ.
AUTHENTIK_API_URL = os.environ.get("AUTHENTIK_API_URL", "").rstrip("/")

# A token for a user/service-account with permission to manage users in Authentik.
# Create one in Authentik: Admin interface -> Directory -> Tokens -> Create,
# attached to an account with enough rights to create/update/delete users
# (akadmin's own token works, but a dedicated service account is cleaner).
AUTHENTIK_API_TOKEN = os.environ.get("AUTHENTIK_API_TOKEN", "")

# Optional Authentik group *names* to add new users to. Looked up by name on
# each call rather than cached, so renaming/recreating the group in Authentik
# doesn't require restarting the portal. Leave blank to add no group.
AUTHENTIK_DEFAULT_GROUP = os.environ.get("AUTHENTIK_DEFAULT_GROUP", "")
AUTHENTIK_ADMIN_GROUP = os.environ.get("AUTHENTIK_ADMIN_GROUP", AUTHENTIK_DEFAULT_GROUP)

VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"

logger = logging.getLogger(__name__)

_session = requests.Session()
_session.verify = VERIFY_SSL
if not VERIFY_SSL:
    requests.packages.urllib3.disable_warnings()


class AuthentikApiError(Exception):
    pass


def _headers() -> dict:
    if not AUTHENTIK_API_TOKEN:
        raise AuthentikApiError("AUTHENTIK_API_TOKEN is not configured.")
    return {"Authorization": f"Bearer {AUTHENTIK_API_TOKEN}"}


def _request(method: str, path: str, **kwargs) -> dict | list:
    """Calls the Authentik API at `path` (e.g. '/api/v3/core/users/') and
    returns the parsed JSON body. Raises AuthentikApiError with Authentik's
    own error detail on any non-2xx response."""
    if not AUTHENTIK_API_URL:
        raise AuthentikApiError("AUTHENTIK_API_URL is not configured.")
    url = f"{AUTHENTIK_API_URL}{path}"
    resp = _session.request(method, url, headers=_headers(), timeout=15, **kwargs)
    if not resp.ok:
        detail = resp.text
        try:
            detail = resp.json()
        except ValueError:
            pass
        raise AuthentikApiError(f"Authentik API {method} {path} failed ({resp.status_code}): {detail}")
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def _random_password(username: str, length: int = 20) -> str:
    """Generates a random password Authentik's default policy will accept."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^*()_+-="
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            len(pwd) >= 12
            and any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^*()_+-=" for c in pwd)
            and username.lower() not in pwd.lower()
        ):
            return pwd


def _find_group_pk(name: str) -> str | None:
    """Looks up a group's pk (a UUID) by its exact name. Returns None if
    `name` is blank or no such group exists - callers treat that as
    'skip the group, but still create the user'."""
    if not name:
        return None
    data = _request("GET", "/api/v3/core/groups/", params={"name": name})
    results = data.get("results") or []
    if not results:
        logger.warning("Authentik group '%s' not found; user will be created without it.", name)
        return None
    return results[0]["pk"]


def user_exists(username: str) -> bool:
    """Returns True if an Authentik user with this exact username already exists."""
    data = _request("GET", "/api/v3/core/users/", params={"username": username})
    return bool(data.get("results"))


def create_user(
    username: str,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
    is_admin: bool = False,
) -> tuple[str, str]:
    """Creates an Authentik user, sets a random password on it, and returns
    (authentik_pk, password). The password is generated here (not asked for)
    the same way synology_manager.create_user does - callers are responsible
    for showing it to the admin once and never storing it in plaintext."""
    full_name = f"{first_name or ''} {last_name or ''}".strip() or username

    payload = {
        "username": username,
        "name": full_name,
        "email": email,
        "is_active": True,
        "path": "users",
        "type": "internal",
    }
    group_pk = _find_group_pk(AUTHENTIK_ADMIN_GROUP if is_admin else AUTHENTIK_DEFAULT_GROUP)
    if group_pk:
        payload["groups"] = [group_pk]

    created = _request("POST", "/api/v3/core/users/", json=payload)
    pk = created["pk"]

    password = _random_password(username, 20)
    _request("POST", f"/api/v3/core/users/{pk}/set_password/", json={"password": password})

    return pk, password


def reset_password(username: str) -> str:
    """Admin action: generates a new random password for an existing
    Authentik user and sets it. Returns the new password."""
    pk = _find_user_pk(username)
    password = _random_password(username, 20)
    _request("POST", f"/api/v3/core/users/{pk}/set_password/", json={"password": password})
    return password


def _find_user_pk(username: str) -> str:
    data = _request("GET", "/api/v3/core/users/", params={"username": username})
    results = data.get("results") or []
    if not results:
        raise AuthentikApiError(f"No Authentik user named '{username}'.")
    return results[0]["pk"]


def delete_user(username: str) -> None:
    """Deletes an Authentik user by username. No-op (raises) if not found -
    callers that want delete-if-exists semantics should catch AuthentikApiError."""
    pk = _find_user_pk(username)
    _request("DELETE", f"/api/v3/core/users/{pk}/")


def set_active(username: str, active: bool) -> None:
    """Enables/disables sign-in for an Authentik user without deleting the
    account - used when a portal admin disables/re-enables an employee."""
    pk = _find_user_pk(username)
    _request("PATCH", f"/api/v3/core/users/{pk}/", json={"is_active": active})