import logging
import time

from apps.common.integrations import sanity_client
from apps.common.integrations.sanity_client import SanityError

logger = logging.getLogger(__name__)

TTL_SECONDS = 60
_cache = {"at": 0.0, "items": []}

PROJECTS_GROQ = (
    '*[_type == "project" && !(_id in path("drafts.**"))]'
    " | order(title asc){_id, title}"
)


def list_projects(force: bool = False) -> list[dict]:
    """[{id, title}] for every published project. Raises SanityError if Sanity is unavailable or not configured."""
    now = time.monotonic()
    if not force and now - _cache["at"] < TTL_SECONDS and _cache["items"]:
        return _cache["items"]
    if not sanity_client.is_configured():
        raise SanityError("Sanity is not configured (SANITY_PROJECT_ID / SANITY_WRITE_TOKEN).")
    rows = sanity_client.query(PROJECTS_GROQ) or []
    logger.info("Sanity returned %d project(s) from dataset %s", len(rows), sanity_client.DATASET)
    items = [{"id": r["_id"], "title": r.get("title") or r["_id"]} for r in rows]
    _cache.update(at=now, items=items)
    return items