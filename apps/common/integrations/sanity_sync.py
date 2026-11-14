"""Push portal data to Sanity (the company website's content store).

Portal is the source of truth for every field it maps here. The website reads
only Sanity; the portal reads only Postgres. Every save that changes a mapped
field calls push_user(). Failures are recorded on the user so HR can see that
the public page is out of date, and the retry job picks them up later.

Each employee is identified in Sanity by their identity ID (externalId).
Photos are handled by sanity_photo.py and uploaded during push_user().
"""
import logging
import re
import secrets
import unicodedata

from django.conf import settings
from django.utils import timezone

from apps.common.integrations import sanity_client
from apps.common.integrations.sanity_client import SanityError

logger = logging.getLogger(__name__)

TEAM_TYPE = "teamMember"

# Portal field -> Sanity teamMember field. Photo is excluded (asset flow in sanity_photo.py).
FIELD_MAP = {
    "name": "name",
    "identity_id": "externalId",
    "job_title": "role",
    "department": "department",
    "office_location": "officeLocation",
    "email": "email",
    "phone": "phone",
    "other_emails": "otherEmails",
    "linkedin_url": "linkedinUrl",
    "bio": "bio",
    "profile_text": "profile",
    "display_order": "order",
    "show_on_website": "showOnWebsite",
}

# System accounts that must never appear on the website.
EXCLUDED_EMAILS = {"admin@shesa.local"}
EXCLUDED_USERNAMES = {"authentik-default-admin"}

RESERVED_SLUGS = {
    "about", "admin", "api", "careers", "contact", "expertise", "gallery", "login",
    "logout", "memberships", "news", "people", "portal", "privacy", "projects",
    "search", "studio",
}


class PushError(Exception):
    """A push failed. `retryable` tells the retry job whether another attempt can help."""

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def is_enabled() -> bool:
    return bool(settings.SANITY_SYNC_ENABLED and sanity_client.is_configured())


def is_excluded(user) -> bool:
    email = (user.email or "").strip().lower()
    username = (user.authentik_username or "").strip().lower()
    return email in EXCLUDED_EMAILS or username in EXCLUDED_USERNAMES


def _make_slug(name: str, identity_id: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "person"
    suffix = identity_id.lower()
    if base in RESERVED_SLUGS:
        base = f"{base}-{suffix}"
    taken = sanity_client.query(
        '*[_type=="teamMember" && slug.current==$s && externalId!=$ext][0]._id',
        {"s": base, "ext": identity_id},
    )
    if taken:
        base = f"{base}-{suffix}"
    return base[:90]


def _to_blocks(text: str | None) -> list:
    """Portable Text for the full profile. Always a list, never null (Sanity rejects null here)."""
    if not text or not text.strip():
        return []
    return [{
        "_type": "block", "_key": secrets.token_hex(6), "style": "normal", "markDefs": [],
        "children": [{"_type": "span", "_key": secrets.token_hex(6), "text": para.strip(), "marks": []}],
    } for para in text.split("\n\n") if para.strip()]


def _team_values(user) -> dict:
    """Current portal values for every mapped field, keyed by Sanity field name."""
    profile = getattr(user, "profile", None)
    source = {
        "name": user.full_name,
        "identity_id": user.identity_id,
        "email": user.email,
        "other_emails": list(user.other_emails or []),
        "linkedin_url": user.linkedin_url,
        "profile_text": _to_blocks(user.profile_text),
        "display_order": user.display_order,
        "job_title": profile.job_title if profile else None,
        "department": profile.department.name if profile and profile.department_id else None,
        "office_location": profile.office_location if profile else None,
        "phone": profile.phone if profile else None,
        "bio": profile.bio if profile else None,
        "show_on_website": not user.disabled and bool(user.show_on_website),
    }
    return {FIELD_MAP[key]: value for key, value in source.items()}


def _team_base_id(user) -> str | None:
    """Published id of this employee's teamMember document, or None if none exists."""
    if user.sanity_id:
        return user.sanity_id.removeprefix("drafts.")
    if user.identity_id:
        return sanity_client.query(
            '*[_type=="teamMember" && externalId==$ext][0]._id', {"ext": user.identity_id}
        ) or None
    return None


def hide_person(user) -> None:
    """Sets showOnWebsite to false. Used when an employee is disabled. The document is kept."""
    if not sanity_client.is_configured() or is_excluded(user):
        return
    doc_id = _team_base_id(user)
    if doc_id:
        sanity_client.mutate([{"patch": {"id": doc_id, "set": {"showOnWebsite": False}}}])


def _reference_fields(doc: dict, target: str) -> tuple[dict, list[str]]:
    """Set and unset operations that remove every direct reference to `target` from a document.

    Covers single reference fields and arrays of references (for example a project's teamMembers).
    References nested inside other objects are not touched.
    """
    def is_ref(item) -> bool:
        return isinstance(item, dict) and item.get("_ref") == target

    set_fields: dict = {}
    unset_fields: list[str] = []
    for key, value in doc.items():
        if key.startswith("_"):
            continue
        if is_ref(value):
            unset_fields.append(key)
        elif isinstance(value, list) and any(is_ref(item) for item in value):
            set_fields[key] = [item for item in value if not is_ref(item)]
    return set_fields, unset_fields


def _detach_from_documents(team_id: str) -> None:
    """Removes the employee from every document that references them, drafts included."""
    referencing = sanity_client.query('*[references($id)]', {"id": team_id}) or []
    patches = []
    for doc in referencing:
        set_fields, unset_fields = _reference_fields(doc, team_id)
        if not set_fields and not unset_fields:
            continue
        patch = {"id": doc["_id"], "ifRevisionID": doc["_rev"]}
        if set_fields:
            patch["set"] = set_fields
        if unset_fields:
            patch["unset"] = unset_fields
        patches.append({"patch": patch})
    if patches:
        sanity_client.mutate(patches)


def delete_team_document(team_id: str) -> None:
    """Hides, detaches from referencing documents, then deletes one teamMember (published and draft)."""
    base = team_id.removeprefix("drafts.")
    existing = sanity_client.query(
        '*[_id == $a || _id == $b]._id', {"a": base, "b": f"drafts.{base}"}
    ) or []
    if not existing:
        return
    if base in existing:
        sanity_client.mutate([{"patch": {"id": base, "set": {"showOnWebsite": False}}}])
    _detach_from_documents(base)
    sanity_client.mutate([{"delete": {"id": doc_id}} for doc_id in existing])


def delete_person(user) -> None:
    """Removes the employee's website record. Projects that listed them lose that link."""
    if not sanity_client.is_configured() or is_excluded(user):
        return
    team_id = _team_base_id(user)
    if team_id:
        delete_team_document(team_id)

def _classify(exc: SanityError) -> PushError:
    return PushError(str(exc), retryable=bool(exc.retryable))


def push_user(user) -> None:
    """Writes the employee's fields, project links and profile photo to Sanity.

    On success: sanity_pending=False, sanity_synced_at=now, sanity_last_error=None.
    On failure: sanity_pending=True and the error is stored; PushError is raised.
    Does nothing if Sanity is disabled or the account is a system account.
    """
    if not is_enabled() or is_excluded(user):
        return
    if not user.identity_id:
        msg = "No identity ID yet: add a mobile number to the profile to publish this employee."
        _mark(user, pending=False, error=msg)
        raise PushError(msg, retryable=False)
    try:
        _upsert_team_member(user)
        _sync_project_links(user)
        _sync_photo(user)
    except SanityError as exc:
        _mark(user, pending=True, error=str(exc))
        raise _classify(exc) from exc
    except PushError as exc:
        _mark(user, pending=True, error=str(exc))
        raise
    _mark(user, pending=False, error=None, synced=True)


def _doc_id_for(user) -> str:
    return f"teamMember-portal-{user.identity_id}"


def _upsert_team_member(user) -> None:
    values = _team_values(user)
    doc_id = _doc_id_for(user)
    mutations = [
        {"createIfNotExists": {
            "_id": doc_id,
            "_type": TEAM_TYPE,
            "slug": {"_type": "slug", "current": _make_slug(user.full_name, user.identity_id)},
        }},
        {"patch": {"id": doc_id, "set": values}},
    ]
    sanity_client.mutate(mutations)
    if user.sanity_id != doc_id:
        user.sanity_id = doc_id
        user.save(update_fields=["sanity_id"])


def _first_id(result: dict, default: str) -> str:
    ids = result.get("results") or []
    return ids[0].get("id", default) if ids else default


def _sync_photo(user) -> None:
    # Imported here because sanity_photo imports this module.
    from apps.common.integrations import sanity_photo
    try:
        sanity_photo.sync_profile_photo(user)
    except sanity_photo.PhotoError as exc:
        raise PushError(f"Photo not uploaded: {exc}", retryable=False) from exc


def _sync_project_links(user) -> None:
    """Makes each project's teamMembers match the portal's project_ids for this employee."""
    if not user.sanity_id:
        return
    wanted = set(user.project_ids or [])
    current = set(
        sanity_client.query(
            '*[_type == "project" && references($id)]._id', {"id": user.sanity_id}
        ) or []
    )
    for project_id in wanted | current:
        if project_id in wanted and project_id in current:
            continue
        _patch_project_members(project_id, user.sanity_id, add=project_id in wanted)


def _patch_project_members(project_id: str, team_id: str, add: bool) -> None:
    doc = sanity_client.query('*[_id == $id][0]{_id, _rev, teamMembers}', {"id": project_id})
    if not doc:
        raise PushError(f"Project {project_id} no longer exists in Sanity.", retryable=False)

    members = doc.get("teamMembers") or []
    refs = [m for m in members if m.get("_ref") != team_id]
    if add:
        refs.append({"_type": "reference", "_ref": team_id, "_key": f"tm{team_id[-12:]}"})

    sanity_client.mutate([{
        "patch": {
            "id": project_id,
            "ifRevisionID": doc["_rev"],
            "set": {"teamMembers": refs},
        }
    }])


def _mark(user, pending: bool, error: str | None, synced: bool = False) -> None:
    user.sanity_pending = pending
    user.sanity_last_error = error[:2000] if error else None
    if synced:
        user.sanity_synced_at = timezone.now()
    user.save(update_fields=["sanity_pending", "sanity_last_error", "sanity_synced_at"])