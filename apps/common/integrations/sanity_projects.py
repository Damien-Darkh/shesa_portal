"""Project list for the employee project picker. Read live from Sanity, cached briefly."""
import time

from apps.common.integrations import sanity_client

TTL_SECONDS = 60
_cache = {"at": 0.0, "items": []}

PROJECTS_GROQ = (
    '*[_type == "project" && !(_id in path("drafts.**"))]'
    " | order(title asc){_id, title}"
)


def list_projects(force: bool = False) -> list[dict]:
    """[{id, title}] for every published project. Raises SanityError if Sanity is unreachable."""
    now = time.monotonic()
    if not force and now - _cache["at"] < TTL_SECONDS:
        return _cache["items"]
    if not sanity_client.is_configured():
        return []
    rows = sanity_client.query(PROJECTS_GROQ) or []
    items = [{"id": r["_id"], "title": r.get("title") or r["_id"]} for r in rows]
    _cache.update(at=now, items=items)
    return items