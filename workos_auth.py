"""
workos_auth.py - Passwordless login via WorkOS AuthKit.

Replaces cf_access.py / Cloudflare Access. There is still no password
stored anywhere in this app. Instead:

  1. An unauthenticated request gets redirected to WorkOS's hosted
     AuthKit login page (email + a one-time code, by default).
  2. WorkOS handles that whole login UI - we never see or store a
     password.
  3. WorkOS redirects back to our /callback route with a short-lived
     authorization code, which we exchange (server-side, using our
     secret API key) for the verified user's email address.

This module only knows how to talk to WorkOS. app.py is what turns a
verified email into a local session (login_user()), same as before.
"""

import base64
import json
import os

from workos import WorkOSClient
from workos._errors import APIError

CLIENT_ID = os.environ["WORKOS_CLIENT_ID"]
REDIRECT_URI = os.environ["WORKOS_REDIRECT_URI"]  # e.g. https://vpn.shesa.it/callback

# Every employee created through this portal is added as a member of this
# WorkOS Organization. If you already know the org's WorkOS ID, set
# WORKOS_ORGANIZATION_ID directly to skip the lookup/create call entirely
# (safest option). Otherwise WORKOS_ORGANIZATION_NAME is used to find an
# existing org with that name, or create one if none exists yet.
WORKOS_ORGANIZATION_ID = os.environ.get("WORKOS_ORGANIZATION_ID", "")
WORKOS_ORGANIZATION_NAME = os.environ.get("WORKOS_ORGANIZATION_NAME", "Shesa")

_client = WorkOSClient(
    api_key=os.environ["WORKOS_API_KEY"],
    client_id=CLIENT_ID,
)

# Cached after first lookup/create so we don't hit the WorkOS API on every
# single employee creation.
_org_id_cache: str | None = None


def _get_or_create_organization_id() -> str | None:
    """Returns the WorkOS Organization ID every new employee should be
    added to. Returns None (and logs a warning) if this can't be
    resolved, so a WorkOS hiccup here never blocks account creation
    itself - it just means the org membership step gets skipped for
    that user, same as other soft-fail provisioning steps in this app."""
    global _org_id_cache

    if WORKOS_ORGANIZATION_ID:
        return WORKOS_ORGANIZATION_ID

    if _org_id_cache:
        return _org_id_cache

    try:
        existing = _client.organizations.list_organizations(name=WORKOS_ORGANIZATION_NAME)
        print(f"=== WORKOS list_organizations({WORKOS_ORGANIZATION_NAME!r}) response: {existing} ===")
        if existing.data:
            _org_id_cache = existing.data[0].id
            return _org_id_cache
    except Exception as e:
        print(f"=== WORKOS list_organizations failed: {e} ===")

    try:
        created = _client.organizations.create_organization(name=WORKOS_ORGANIZATION_NAME)
        print(f"=== WORKOS create_organization({WORKOS_ORGANIZATION_NAME!r}) response: {created} ===")
        _org_id_cache = created.id
        return _org_id_cache
    except Exception as e:
        print(f"=== WORKOS create_organization failed: {e} ===")
        return None


class AuthKitError(Exception):
    pass


def _extract_session_id(access_token: str) -> str | None:
    """Pulls the `sid` claim out of the access token's JWT payload. We
    don't need to verify the signature here - this token just came
    straight from WorkOS over HTTPS in exchange_code() below, it's not
    something an attacker could have handed us - we're only reading a
    claim out of it, not trusting it as a proof of identity."""
    try:
        payload_b64 = access_token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("sid")
    except Exception:
        return None


def get_authorization_url(state: str) -> str:
    """Build the URL to send an unauthenticated visitor to. `state` is an
    opaque, unguessable value we generate and stash in the Flask session;
    we check it matches on the way back in /callback so a forged callback
    can't log someone in (CSRF protection for the login flow itself)."""
    return _client.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=REDIRECT_URI,
        client_id=CLIENT_ID,
        state=state,
    )


def exchange_code(code: str):
    """Called from /callback with the one-time code AuthKit handed back.
    Exchanges it (server-side, using our secret key - this step can't be
    forged by someone who only has the code from a URL) for the verified
    user. Returns (email, session_id, workos_user_id). session_id is what
    /logout later needs to end WorkOS's own hosted session; workos_user_id
    is what a future /admin delete needs to remove the account on WorkOS's
    side too. Raises AuthKitError on any failure: expired/invalid/
    already-used code, unverified email, etc."""
    try:
        result = _client.user_management.authenticate_with_code(code=code)
    except Exception as e:
        raise AuthKitError(f"Could not verify AuthKit login: {e}") from e

    user = result.user
    if not user.email_verified:
        raise AuthKitError("WorkOS reports this email address is not verified.")

    session_id = _extract_session_id(result.access_token)
    return user.email.lower().strip(), session_id, user.id, user.first_name, user.last_name


def create_user(email: str, first_name: str | None = None, last_name: str | None = None) -> str | None:
    """Pre-creates the user on WorkOS's side too, so they show up in the
    WorkOS dashboard immediately rather than only appearing there after
    their first login. Doesn't set a password or send anything - they
    still authenticate via AuthKit's normal email-code flow the first
    time. Returns the WorkOS user id. If WorkOS already has this email
    (e.g. they'd already logged in once before an admin got around to
    adding them here), looks up and returns the existing id instead of
    treating that as an error.

    Also adds the user as a member of the configured WorkOS Organization
    (see WORKOS_ORGANIZATION_ID/WORKOS_ORGANIZATION_NAME above). This
    step is deliberately non-fatal - if it fails, the user account still
    gets created, we just log a warning, so a WorkOS org hiccup never
    blocks onboarding an employee."""
    try:
        result = _client.user_management.create_user(
            email=email,
            first_name=first_name or None,
            last_name=last_name or None,
        )
        user_id = result.id
    except APIError as e:
        error_codes = {err.get("code") for err in (e.errors or [])}
        if "email_not_available" in error_codes:
            user_id = find_user_id_by_email(email)
        else:
            raise AuthKitError(f"Could not create user in WorkOS: {e}") from e
    except Exception as e:
        raise AuthKitError(f"Could not create user in WorkOS: {e}") from e

    if user_id:
        org_id = _get_or_create_organization_id()
        if org_id:
            try:
                membership = _client.user_management.create_organization_membership(
                    user_id=user_id,
                    organization_id=org_id,
                )
                print(f"=== WORKOS create_organization_membership response: {membership} ===")
            except Exception as e:
                print(f"[workos_auth] Warning: could not add {email} to organization {org_id}: {e}")
        else:
            print(f"[workos_auth] Warning: no organization id available, skipping org membership for {email}")

    return user_id


def find_user_id_by_email(email: str) -> str | None:
    try:
        page = _client.user_management.list_users(email=email, limit=1)
    except Exception:
        return None
    return page.data[0].id if page.data else None


def update_user(workos_user_id: str, first_name: str | None, last_name: str | None) -> None:
    """Updates the user's name on WorkOS's side, keeping it in sync with
    what the employee edits in their portal profile. No-ops quietly if
    we don't have a workos_user_id yet (rare edge case for very old rows).
    We deliberately don't expose email changes here - email is the login
    identity and changing it via the portal would desync WorkOS auth."""
    if not workos_user_id:
        return
    try:
        _client.user_management.update_user(
            workos_user_id,
            first_name=first_name or None,
            last_name=last_name or None,
        )
    except Exception as e:
        raise AuthKitError(f"Could not update user in WorkOS: {e}") from e


def delete_user(workos_user_id: str | None) -> None:
    """Permanently removes the account on WorkOS's side. No-ops quietly
    if we never captured a workos_user_id for this person (e.g. a row
    from before this column existed, and they never logged in again to
    backfill it) - the local delete in app.py still goes ahead either
    way, this just can't reach across to WorkOS in that edge case."""
    if not workos_user_id:
        return
    try:
        _client.user_management.delete_user(workos_user_id)
    except Exception as e:
        raise AuthKitError(f"Could not delete user in WorkOS: {e}") from e


def get_logout_url(session_id: str, return_to: str) -> str:
    """Ends the AuthKit hosted session itself (not just our local Flask
    session). Without this step, /login after a "logout" silently
    re-authenticates the still-active AuthKit session instead of
    prompting again - this is what actually makes logout visible."""
    return _client.user_management.get_logout_url(
        session_id=session_id,
        return_to=return_to,
    )
