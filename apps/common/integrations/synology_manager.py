"""
synology_manager.py - Synology DSM user management via the SYNO.Core.User API.
"""

import json
import os
import secrets
import string
import time

import logging
import requests

# Base URL of your Synology NAS (e.g., "https://192.168.10.3:5001")
DSM_URL = os.environ.get("DSM_URL", "").rstrip("/")

# Admin credentials for the portal to log into DSM API
DSM_USER = os.environ.get("DSM_ADMIN_USER") or os.environ.get("DSM_USER", "")
DSM_PASSWORD = os.environ.get("DSM_ADMIN_PASS") or os.environ.get("DSM_PASSWORD", "")

# Optional DSM local group to automatically assign new employees (e.g., "vpn-users")
DSM_SHARE_GROUP = os.environ.get("DSM_SHARE_GROUP", "staff")

# DSM group for portal admins' NAS accounts. Falls back to DSM_SHARE_GROUP
# if not set, so admins get the same access as everyone else unless you
# explicitly configure a different group for them.
DSM_ADMIN_GROUP = os.environ.get("DSM_ADMIN_GROUP", DSM_SHARE_GROUP)

# SSL Certificate verification setting (defaults to False for self-signed NAS certs)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"

logger = logging.getLogger(__name__)

_session = requests.Session()
_session.verify = VERIFY_SSL
if not VERIFY_SSL:
    requests.packages.urllib3.disable_warnings()


class DsmApiError(Exception):
    pass


class PasswordPolicyError(Exception):
    """Raised when a password fails DSM's configured password policy."""
    pass


def _validate_password_policy(username: str, new_password: str, description: str = "") -> None:
    """Validates a password against DSM's configured policy before sending it to the API.

    Current DSM policy (Control Panel -> Security -> Account -> Password Rules):
      - minimum length: 8
      - must include both uppercase and lowercase letters
      - must include at least one numeric character
      - must not contain the username or the account's description/full name
    """
    problems = []

    if len(new_password) < 8:
        problems.append("be at least 8 characters long")
    if not any(c.islower() for c in new_password):
        problems.append("include at least one lowercase letter")
    if not any(c.isupper() for c in new_password):
        problems.append("include at least one uppercase letter")
    if not any(c.isdigit() for c in new_password):
        problems.append("include at least one number")

    lowered_pwd = new_password.lower()
    if username and username.lower() in lowered_pwd:
        problems.append("not contain your username")

    # description often holds "First Last" - check the whole string and each word,
    # so a password containing just the first or last name is also caught
    if description:
        desc_lower = description.lower().strip()
        if desc_lower and desc_lower in lowered_pwd:
            problems.append("not contain your name")
        else:
            for part in desc_lower.split():
                if len(part) >= 3 and part in lowered_pwd:
                    problems.append("not contain your name")
                    break

    if problems:
        # de-duplicate while preserving order
        seen = []
        for p in problems:
            if p not in seen:
                seen.append(p)
        raise PasswordPolicyError("Password must " + "; ".join(seen) + ".")


def _login() -> tuple[str, str]:
    """Logs into DSM and returns (sid, synotoken)."""
    resp = _session.post(
        f"{DSM_URL}/webapi/entry.cgi",
        data={
            "api": "SYNO.API.Auth",
            "version": 7,
            "method": "login",
            "account": DSM_USER,
            "passwd": DSM_PASSWORD,
            "session": "Core",
            "format": "sid",
        },
    )
    data = resp.json()
    if not data.get("success"):
        raise DsmApiError(f"DSM Auth failed: {data}")

    sid = data["data"]["sid"]
    synotoken = data["data"].get("synotoken", "")
    return sid, synotoken


def _logout(sid: str) -> None:
    try:
        _session.get(
            f"{DSM_URL}/webapi/auth.cgi",
            params={
                "api": "SYNO.API.Auth",
                "version": "6",
                "method": "logout",
                "session": "Core",
                "_sid": sid,
            },
            timeout=5,
        )
    except Exception:
        pass


def _api(sid: str, api: str, method: str, version: int = 1, synotoken: str = "", **params) -> dict:
    """Makes a SYNO API call using _session and returns the data dict."""
    headers = {}
    if synotoken and synotoken != "--------":
        headers["SynoToken"] = synotoken

    r = _session.post(
        f"{DSM_URL}/webapi/entry.cgi",
        data={
            "api": api,
            "version": str(version),
            "method": method,
            "_sid": sid,
            **{k: v for k, v in params.items() if v is not None},
        },
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    result = r.json()
    if not result.get("success"):
        code = result.get("error", {}).get("code", "?")
        raise DsmApiError(f"DSM API {api}.{method} failed (error code {code}): {result}")
    return result.get("data") or {}


def _random_password(username: str, length: int = 20) -> str:
    """Generates a random password guaranteed to pass DSM complexity rules."""
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

def create_user(
    username: str,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
    group: str | None = None,
) -> str:
    """Creates a DSM user and adds them to `group` (falls back to
    DSM_SHARE_GROUP if not given). Pass an explicit group to put certain
    users - e.g. admins - into a different DSM group than everyone else."""
    target_group = group if group is not None else DSM_SHARE_GROUP

    password = _random_password(username, 20)
    description = f"{first_name or ''} {last_name or ''}".strip() if (first_name or last_name) else ""

    sid, synotoken = _login()
    try:
        # Step 1: Create the User
        compound_payload = [
            {
                "api": "SYNO.Core.User",
                "method": "create",
                "version": 1,
                "name": username,
                "description": description,
                "email": email,
                "password": password,
                "cannot_chg_passwd": False,
                "expired": "normal",
                "passwd_never_expire": True,
                "notify_by_email": False,
            }
        ]

        create_data = _api(
            sid=sid,
            api="SYNO.Entry.Request",
            method="request",
            version=1,
            synotoken=synotoken,
            stop_when_error="false",
            mode='"sequential"',
            compound=json.dumps(compound_payload),
        )
        logger.debug("DSM create_user response: %s", create_data)

        # Step 2: Add User to the Target Group
        if target_group:
            try:
                _add_user_to_group(sid, synotoken, username, target_group)
            except Exception as grp_err:
                logger.warning("Failed to add '%s' to group '%s': %s", username, target_group, grp_err)

    finally:
        _logout(sid)

    return password


def _add_user_to_group(sid: str, synotoken: str, username: str, group_name: str) -> None:
    """Adds a user to a DSM group via SYNO.Core.User.Group (async join + status poll)."""

    join_payload = [
        {
            "api": "SYNO.Core.User.Group",
            "method": "join",
            "version": 1,
            "name": username,
            "join_group": group_name,
            "leave_group": "",
        }
    ]
    join_data = _api(
        sid=sid,
        api="SYNO.Entry.Request",
        method="request",
        version=1,
        synotoken=synotoken,
        stop_when_error="false",
        mode='"sequential"',
        compound=json.dumps(join_payload),
    )
    logger.debug("DSM group join response: %s", join_data)

    join_item = join_data["result"][0]
    if not join_item.get("success", True):
        raise DsmApiError(f"Failed to start group-join task for '{username}': {join_item}")

    task_id = join_item["data"]["task_id"]
    logger.debug("DSM group-join task_id: %s", task_id)

    # This is an asynchronous DSM task: poll join_status until DSM reports finish=true.
    for attempt in range(10):
        time.sleep(1)
        status_payload = [
            {
                "api": "SYNO.Core.User.Group",
                "method": "join_status",
                "version": 1,
                "task_id": task_id,
            }
        ]
        status_data = _api(
            sid=sid,
            api="SYNO.Entry.Request",
            method="request",
            version=1,
            synotoken=synotoken,
            stop_when_error="false",
            mode='"sequential"',
            compound=json.dumps(status_payload),
        )
        logger.debug("DSM group-join status attempt %d: %s", attempt + 1, status_data)

        status_item = status_data["result"][0]
        if not status_item.get("success", True):
            raise DsmApiError(f"Failed to check join status for '{username}': {status_item}")

        task_status = status_item["data"]
        if task_status.get("finish"):
            if "error" in task_status:
                raise DsmApiError(f"Group-join task failed for '{username}': {task_status}")
            logger.debug("DSM group-join task finished for '%s': %s", username, task_status)
            return

    raise DsmApiError(f"Timed out waiting for group-join task to finish for '{username}'")


  
def delete_user(username: str) -> None:
    """Deletes a DSM user using the DSM 7 compound API."""
    sid, synotoken = _login()
    try:
        compound_payload = [
            {
                "api": "SYNO.Core.User",
                "method": "delete",
                "version": 1,
                "name": username,  # DSM 7 accepts the single name parameter in compound mode
            }
        ]

        _api(
            sid=sid,
            api="SYNO.Entry.Request",
            method="request",
            version=1,
            synotoken=synotoken,
            stop_when_error="false",
            mode='"sequential"',
            compound=json.dumps(compound_payload),
        )
    finally:
        _logout(sid)


def user_exists(username: str) -> bool:
    """Returns True if a DSM user with this username already exists."""
    sid, synotoken = _login()
    try:
        data = _api(sid, api="SYNO.Core.User", method="list", version=1, synotoken=synotoken, offset=0, limit=0)
        existing = {u.get("name") for u in data.get("users", [])}
        return username in existing
    finally:
        _logout(sid)


def reset_password(username: str) -> str:
    """Admin action: generates a new random password for an existing user
    and sets it on DSM. Returns the new password - caller is responsible
    for showing it to the admin exactly once and storing it securely
    (or not at all) after that."""
    new_password = _random_password(username, 20)
    update_password(username, new_password)
    return new_password


def update_password(username: str, new_password: str, description: str = "") -> None:
    """Updates an existing DSM user's password using SYNO.Core.User set.

    Validates against DSM's password policy first so callers get a specific,
    human-readable reason instead of an opaque DSM error code.
    """
    logger.debug("DSM update_password called for user: %s", username)

    _validate_password_policy(username, new_password, description)
    logger.debug("DSM password policy validation passed for: %s", username)

    sid, synotoken = _login()
    try:
        logger.debug("DSM User.set called for: %s", username)
        try:
            set_data = _api(
                sid,
                api="SYNO.Core.User",
                method="set",
                version=1,
                synotoken=synotoken,
                name=username,
                password=new_password,
            )
            logger.debug("DSM User.set response: %s", set_data)
        except DsmApiError as e:
            logger.debug("DSM User.set failed: %s", e)
            if "error code 3103" in str(e):
                # Fallback in case DSM's live policy is stricter than what we checked above
                raise PasswordPolicyError(
                    "Password does not meet the NAS password policy (check length, "
                    "uppercase/lowercase, numbers, and that it doesn't contain your name)."
                ) from e
            raise
    finally:
        _logout(sid)