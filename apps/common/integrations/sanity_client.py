"""Sanity HTTP client. The only module that talks to the Sanity API.

Server-side only. The write token is never returned to callers or logged.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "")
DATASET = os.environ.get("SANITY_DATASET", "production")
API_VERSION = os.environ.get("SANITY_API_VERSION", "2026-01-01")
WRITE_TOKEN = os.environ.get("SANITY_WRITE_TOKEN", "")
TIMEOUT = (5, 20)  # connect, read seconds

_session = requests.Session()


class SanityError(Exception):
    """Raised for any failed Sanity call. The message never contains the token."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def is_configured() -> bool:
    return bool(PROJECT_ID and WRITE_TOKEN)


def _base() -> str:
    return f"https://{PROJECT_ID}.api.sanity.io/v{API_VERSION}"


def _headers() -> dict:
    if not WRITE_TOKEN:
        raise SanityError("SANITY_WRITE_TOKEN is not configured.")
    return {"Authorization": f"Bearer {WRITE_TOKEN}", "Content-Type": "application/json"}


def _raise_for(resp: requests.Response, action: str):
    if resp.ok:
        return
    retryable = resp.status_code in (409, 429) or resp.status_code >= 500
    try:
        detail = resp.json().get("error", {}).get("description", "")
    except ValueError:
        detail = ""
    raise SanityError(f"Sanity {action} failed ({resp.status_code}) {detail}".strip(),
                      status=resp.status_code, retryable=retryable)


def query(groq: str, params: dict | None = None):
    """Read with GROQ. Parameters are passed as $name values, never concatenated."""
    query_params = {"query": groq}
    for key, value in (params or {}).items():
        query_params[f"${key}"] = f'"{value}"' if isinstance(value, str) else str(value)
    try:
        resp = _session.get(f"{_base()}/data/query/{DATASET}", params=query_params,
                            headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SanityError(f"Sanity unreachable: {exc.__class__.__name__}", retryable=True) from exc
    _raise_for(resp, "query")
    return resp.json().get("result")


def mutate(mutations: list[dict], return_ids: bool = True) -> dict:
    """Send a batch of mutations (create, createIfNotExists, patch, delete) in one transaction."""
    body = {"mutations": mutations}
    url = f"{_base()}/data/mutate/{DATASET}"
    params = {"returnIds": "true"} if return_ids else None
    try:
        resp = _session.post(url, json=body, params=params, headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SanityError(f"Sanity unreachable: {exc.__class__.__name__}", retryable=True) from exc
    _raise_for(resp, "mutate")
    return resp.json()


def upload_asset(content: bytes, content_type: str, filename: str) -> dict:
    """Upload an image to the Sanity asset store. Returns the asset document (including _id)."""
    url = f"{_base()}/assets/images/{DATASET}"
    headers = {
        "Authorization": f"Bearer {WRITE_TOKEN}",
        "Content-Type": content_type,
    }
    try:
        resp = _session.post(url, data=content, params={"filename": filename},
                             headers=headers, timeout=(5, 60))
    except requests.RequestException as exc:
        raise SanityError(f"Sanity unreachable: {exc.__class__.__name__}", retryable=True) from exc
    _raise_for(resp, "asset upload")
    return resp.json().get("document", {})