"""Serves the static frontend (frontend/) from the same origin as the API.

HTML pages need a signed-in user (admin pages also need is_admin). Assets are public.
The leave calendar page is only served when LEAVE_MANAGEMENT_ENABLED is on.
"""
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from apps.common.http import api_admin_required

from apps.accounts.views import sso_login_url

FRONTEND = Path(settings.BASE_DIR) / "frontend"
PUBLIC_HTML = {"logout.html", "account_disabled.html"}
ADMIN_HTML = {"admin.html", "add_user.html", "edit_user.html", "admin_user_created.html", "admin_department.html"}
LEAVE_HTML = {"calander.html"}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2",
}

MANUAL_PATH = Path(settings.BASE_DIR) / "docs" / "manual.md"

def _resolve(rel: str) -> Path:
    base = FRONTEND.resolve()
    path = (FRONTEND / rel).resolve()
    if base not in path.parents or not path.is_file():
        raise Http404
    return path


@api_admin_required
@require_GET
@never_cache
def manual(request):
    if not MANUAL_PATH.is_file():
        raise Http404
    return FileResponse(
        open(MANUAL_PATH, "rb"),
        content_type="text/markdown; charset=utf-8",
        as_attachment=True,
        filename="manual.md",
    )

@require_GET
@never_cache
def serve(request, path: str):
    if path in LEAVE_HTML and not settings.LEAVE_MANAGEMENT_ENABLED:
        raise Http404
    if path.endswith(".html") and path not in PUBLIC_HTML:
        if not request.user.is_authenticated:
            return HttpResponseRedirect(sso_login_url())
        if path in ADMIN_HTML and not request.user.is_admin:
            return HttpResponseRedirect("/index.html")
    file = _resolve(path)
    content_type = CONTENT_TYPES.get(file.suffix.lower(), "application/octet-stream")
    return FileResponse(open(file, "rb"), content_type=content_type)


@never_cache
def root(request):
    if not request.user.is_authenticated:
        return HttpResponseRedirect(sso_login_url())
    return HttpResponseRedirect("/index.html")