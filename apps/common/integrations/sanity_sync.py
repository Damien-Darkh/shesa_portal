"""Push portal data to Sanity (the company website's content store).

Portal is the source of truth for every field it maps here. The website reads
only Sanity; the portal reads only Postgres. Every save that changes a mapped
field calls push_user(). Failures are recorded on the user so HR can see that
the public page is out of date, and the retry job picks them up later.

Photo uploads are NOT handled here (see sanity_photo.py).
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.integrations import sanity_client
from apps.common.integrations.sanity_client import SanityError

import re, unicodedata, secrets

logger = logging.getLogger(__name__)

TEAM_TYPE = "teamMember"
PROJECT_TYPE = "project"

# Portal field -> Sanity teamMember field. Photo is excluded (asset flow).
FIELD_MAP = {
    "name": "name",
    "job_title": "role",
    "department": "department",
    "office_location": "officeLocation",
    "email": "email",
    "phone": "phone",
    "other_emails": "otherEmails",
    "linkedin_url": "linkedinUrl",
    "bio": "bio",
    "profile_text": "profile",
    "show_on_website": "showOnWebsite",
}

RESERVED_SLUGS = {"about","admin","api","careers","contact","expertise","gallery","login",
                  "logout","memberships","news","people","portal","privacy","projects",
                  "search","studio"}

class PushError(Exception):
    """A push failed. `retryable` decides whether the retry job should try again."""

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def _make_slug(name: str, user_id: int) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or f"person-{user_id}"
    if base in RESERVED_SLUGS:
        base = f"{base}-{user_id}"
    taken = sanity_client.query('*[_type=="teamMember" && slug.current==$s][0]._id', {"s": base})
    if taken:
        base = f"{base}-{user_id}"
    return base[:90]

def is_enabled() -> bool:
    return bool(settings.SANITY_SYNC_ENABLED and sanity_client.is_configured())

def _to_blocks(text: str | None):
    if not text or not text.strip():
        return None
    return [{
        "_type": "block", "_key": secrets.token_hex(6), "style": "normal", "markDefs": [],
        "children": [{"_type": "span", "_key": secrets.token_hex(6), "text": para.strip(), "marks": []}],
    } for para in text.split("\n\n") if para.strip()]

def _team_values(user) -> dict:
    """The current portal values for every mapped field, keyed by Sanity field name."""
    profile = getattr(user, "profile", None)
    source = {
        "name": user.full_name,
        "email": user.email,
        "other_emails": user.other_emails or [],
        "linkedin_url": user.linkedin_url,
        "profile": _to_blocks(user.profile_text),
        "job_title": profile.job_title if profile else None,
        "department": profile.department.name if profile and profile.department_id else None,
        "office_location": profile.office_location if profile else None,
        "phone": profile.phone if profile else None,
        "bio": profile.bio if profile else None,
        "show_on_website": not user.disabled and bool(getattr(user, "show_on_website", False)),
    }
    return {FIELD_MAP[key]: value for key, value in source.items()}

def hide_person(user) -> None:
    if not sanity_client.is_configured():
        return
    doc_id = user.sanity_id or sanity_client.query(
        '*[_type=="teamMember" && externalId==$ext][0]._id', {"ext": str(user.id)})
    if doc_id:
        sanity_client.mutate([{"patch": {"id": doc_id, "set": {"showOnWebsite": False}}}])

def _classify(exc: SanityError) -> PushError:
    return PushError(str(exc), retryable=bool(exc.retryable))


def push_user(user) -> None:
    """Writes the employee's portal-owned fields and project links to Sanity.

    On success: sanity_pending=False, sanity_synced_at=now, sanity_last_error=None.
    On failure: sanity_pending=True and the error is stored; PushError is raised.
    Does nothing if Sanity is disabled or not configured.
    """
    if not is_enabled():
        return
    try:
        _upsert_team_member(user)
        _sync_project_links(user)
    except SanityError as exc:
        _mark(user, pending=True, error=str(exc))
        raise _classify(exc) from exc
    except PushError as exc:
        _mark(user, pending=True, error=str(exc))
        raise
    _mark(user, pending=False, error=None, synced=True)


def _upsert_team_member(user) -> None:
    values = _team_values(user)
    if user.sanity_id:
        mutations = [{"patch": {"id": user.sanity_id, "set": values}}]
    else:
        # First push: create the document, carrying the portal id so reconciliation can match it.
        doc_id = f"teamMember.portal-{user.id}"
        mutations = [{
            "createIfNotExists": {
                "_id": doc_id, "_type": TEAM_TYPE, "externalId": str(user.id),
                "slug": {"_type": "slug", "current": _make_slug(user.full_name, user.id)},
                **values,
            }
        }]
    result = sanity_client.mutate(mutations)
    if not user.sanity_id:
        user.sanity_id = _first_id(result, default=f"teamMember.portal-{user.id}")
        user.save(update_fields=["sanity_id"])


def _first_id(result: dict, default: str) -> str:
    ids = result.get("results") or []
    return ids[0].get("id", default) if ids else default


def _sync_project_links(user) -> None:
    """Makes each project's teamMembers match the portal's project_ids for this employee.

    Adds the reference to projects newly chosen, removes it from projects no longer chosen.
    Uses ifRevisionID so a concurrent Studio edit causes a failure and retry, not an overwrite.
    """
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