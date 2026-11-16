"""
synology_manager.py - Synology DSM user management via the SYNO.Core.User API.

Usernames are the employee's email address. The password is supplied by the
caller so it can match the Authentik password.
"""

import json
import logging
import os
import time

import requests

DSM_URL = os.environ.get("DSM_URL", "").rstrip("/")
DSM_USER = os.environ.get("DSM_ADMIN_USER") or os.environ.get("DSM_USER", "")
DSM_PASSWORD = os.environ.get("DSM_ADMIN_PASS") or os.environ.get("DSM_PASSWORD", "")
DSM_SHARE_GROUP = os.environ.get("DSM_SHARE_GROUP", "staff")
DSM_ADMIN_GROUP = os.environ.get("DSM_ADMIN_GROUP", DSM_SHARE_GROUP)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"

logger = logging.getLogger(__name__)

_session = requests.Session()
_session.verify = VERIFY_SSL
if not VERIFY_SSL:
    requests.packages.urllib3.disable_warnings()


class DsmApiError(Exception):
    pass


class PasswordPolicyError(Exception):
    pass


def _validate_password_policy(username: str, new_password: str, description: str = "") -> None:
    problems = []
    if len(new_password) < 8:
        problems.append("be at least 8 characters long")
    if not any(c.islower() for c in new_password):
        problems.append("include at least one lowercase letter")
    if not any(c.isupper() for c in new_password):
        problems.append("include at least one uppercase letter")
    if not any(c.isdigit() for c in new_password):
        problems.append("include at least one number")
    lowered = new_password.lower()
    if username and username.lower() in lowered:
        problems.append("not contain your username")
    if description:
        desc = description.lower().strip()
        if desc and desc in lowered:
            problems.append("not contain your name")
        else:
            for part in desc.split():
                if len(part) >= 3 and part in lowered:
                    problems.append("not contain your name")
                    break
    if problems:
        seen = []
        for p in problems:
            if p not in seen:
                seen.append(p)
        raise PasswordPolicyError("Password must " + "; ".join(seen) + ".")


def _login() -> tuple[str, str]:
    resp = _session.post(
        f"{DSM_URL}/webapi/entry.cgi",
        data={
            "api": "SYNO.API.Auth", "version": 7, "method": "login",
            "account": DSM_USER, "passwd": DSM_PASSWORD, "session": "Core", "format": "sid",
        },
    )
    data = resp.json()
    if not data.get("success"):
        raise DsmApiError(f"DSM Auth failed: {data}")
    return data["data"]["sid"], data["data"].get("synotoken", "")


def _logout(sid: str) -> None:
    try:
        _session.get(
            f"{DSM_URL}/webapi/auth.cgi",
            params={"api": "SYNO.API.Auth", "version": "6", "method": "logout",
                    "session": "Core", "_sid": sid},
            timeout=5,
        )
    except Exception:
        pass


def _api(sid: str, api: str, method: str, version: int = 1, synotoken: str = "", **params) -> dict:
    headers = {}
    if synotoken and synotoken != "--------":
        headers["SynoToken"] = synotoken
    r = _session.post(
        f"{DSM_URL}/webapi/entry.cgi",
        data={
            "api": api, "version": str(version), "method": method, "_sid": sid,
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


def _compound(sid, synotoken, payload):
    return _api(
        sid=sid, api="SYNO.Entry.Request", method="request", version=1, synotoken=synotoken,
        stop_when_error="false", mode='"sequential"', compound=json.dumps(payload),
    )


def create_user(
    username: str,
    email: str,
    password: str,
    first_name: str | None = None,
    last_name: str | None = None,
    group: str | None = None,
) -> None:
    """Creates the DSM user with `password` and adds it to `group`."""
    target_group = group if group is not None else DSM_SHARE_GROUP
    description = f"{first_name or ''} {last_name or ''}".strip()

    sid, synotoken = _login()
    try:
        _compound(sid, synotoken, [{
            "api": "SYNO.Core.User", "method": "create", "version": 1,
            "name": username, "description": description, "email": email,
            "password": password, "cannot_chg_passwd": False, "expired": "normal",
            "passwd_never_expire": True, "notify_by_email": False,
        }])
        if target_group:
            try:
                _add_user_to_group(sid, synotoken, username, target_group)
            except Exception as grp_err:
                logger.warning("Failed to add '%s' to group '%s': %s", username, target_group, grp_err)
    finally:
        _logout(sid)


def _add_user_to_group(sid: str, synotoken: str, username: str, group_name: str) -> None:
    join_data = _compound(sid, synotoken, [{
        "api": "SYNO.Core.User.Group", "method": "join", "version": 1,
        "name": username, "join_group": group_name, "leave_group": "",
    }])
    join_item = join_data["result"][0]
    if not join_item.get("success", True):
        raise DsmApiError(f"Failed to start group-join task for '{username}': {join_item}")
    task_id = join_item["data"]["task_id"]

    for _ in range(10):
        time.sleep(1)
        status_data = _compound(sid, synotoken, [{
            "api": "SYNO.Core.User.Group", "method": "join_status", "version": 1, "task_id": task_id,
        }])
        status_item = status_data["result"][0]
        if not status_item.get("success", True):
            raise DsmApiError(f"Failed to check join status for '{username}': {status_item}")
        task_status = status_item["data"]
        if task_status.get("finish"):
            if "error" in task_status:
                raise DsmApiError(f"Group-join task failed for '{username}': {task_status}")
            return
    raise DsmApiError(f"Timed out waiting for group-join task for '{username}'")


def delete_user(username: str) -> None:
    sid, synotoken = _login()
    try:
        _compound(sid, synotoken, [{
            "api": "SYNO.Core.User", "method": "delete", "version": 1, "name": username,
        }])
    finally:
        _logout(sid)


def user_exists(username: str) -> bool:
    sid, synotoken = _login()
    try:
        data = _api(sid, api="SYNO.Core.User", method="list", version=1,
                    synotoken=synotoken, offset=0, limit=0)
        return username in {u.get("name") for u in data.get("users", [])}
    finally:
        _logout(sid)


def update_password(username: str, new_password: str, description: str = "") -> None:
    """Sets the DSM password after checking the local policy."""
    _validate_password_policy(username, new_password, description)
    sid, synotoken = _login()
    try:
        try:
            _api(sid, api="SYNO.Core.User", method="set", version=1, synotoken=synotoken,
                 name=username, password=new_password)
        except DsmApiError as e:
            if "error code 3103" in str(e):
                raise PasswordPolicyError(
                    "Password does not meet the NAS password policy (check length, "
                    "uppercase/lowercase, numbers, and that it doesn't contain your name)."
                ) from e
            raise
    finally:
        _logout(sid)


def reset_password(username: str, new_password: str) -> None:
    """Admin reset to the supplied password."""
    update_password(username, new_password)