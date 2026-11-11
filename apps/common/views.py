"""Error handlers. Browser requests get the designed HTML pages from frontend/errors/;
API requests (/api/...) keep receiving JSON."""
import logging
import uuid
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse

logger = logging.getLogger("portal.errors")
ERRORS_DIR = Path(settings.BASE_DIR) / "frontend" / "errors"
JSON_MESSAGES = {400: "Bad request.", 403: "Forbidden.", 404: "Not found.", 500: "Internal server error.",
                 503: "Service unavailable."}


def _respond(request, status: int, reference: str | None = None):
    if request.path.startswith("/api/"):
        body = {"error": JSON_MESSAGES[status]}
        if reference:
            body["reference"] = reference
        return JsonResponse(body, status=status)
    html = (ERRORS_DIR / f"{status}.html").read_text(encoding="utf-8")
    html = html.replace("{{reference}}", reference or "")
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


def bad_request(request, exception=None):
    return _respond(request, 400)


def forbidden(request, exception=None):
    return _respond(request, 403)


def not_found(request, exception=None):
    return _respond(request, 404)


def server_error(request):
    # The full traceback is already logged by Django; the reference ties the page the user sees to that entry.
    reference = uuid.uuid4().hex[:8].upper()
    logger.error("Server error %s on %s %s", reference, request.method, request.path)
    return _respond(request, 500, reference=reference)


def csrf_failure(request, reason=""):
    logger.warning("CSRF check failed on %s: %s", request.path, reason)
    return _respond(request, 403)