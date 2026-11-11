from pathlib import Path
from django.conf import settings
from django.contrib.auth import login

from apps.accounts.models import User

BACKEND_PATH = "django.contrib.auth.backends.ModelBackend"


class DevAuthMiddleware:
    """When USE_SSO is off (local development only), log in a dev user automatically."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.USE_SSO and not request.user.is_authenticated:
            user, _ = User.objects.get_or_create(
                email=settings.DEV_USER_EMAIL,
                defaults={"is_admin": True, "first_name": "Development", "last_name": "User"},
            )
            if user.is_active:
                login(request, user, backend=BACKEND_PATH)
        return self.get_response(request)


# While a user must still replace their temporary NAS password, only these paths work.
_LOCKED_ALLOWED_EXACT = {
    "/login", "/logout", "/api/me/", "/api/me/dsm-password", "/api/csrf/",
    "/force_password_change.html", "/account_disabled.html",
}
_STATIC_EXTENSIONS = (".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".ico", ".woff2")


class ForcedPasswordMiddleware:
    """Blocks the portal until the NAS password is changed (server-side, not just in the UI)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "dsm_must_change_password", False):
            path = request.path
            allowed = path in _LOCKED_ALLOWED_EXACT or path.lower().endswith(_STATIC_EXTENSIONS)
            if not allowed:
                if path.startswith("/api/"):
                    from django.http import JsonResponse
                    return JsonResponse(
                        {"error": "Change your NAS password before continuing.", "code": "password_change_required"},
                        status=403,
                    )
                from django.http import HttpResponseRedirect
                return HttpResponseRedirect("/force_password_change.html")
        return self.get_response(request)


class MovedPermanentlyPageMiddleware:
    """Gives browsers a readable page for 301 redirects (for example the HTTPS redirect).
    The Location header is unchanged; the redirect still happens. API routes keep their bare response."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.template = None

    def __call__(self, request):
        response = self.get_response(request)
        if (response.status_code == 301
                and not request.path.startswith("/api/")
                and "text/html" in request.headers.get("Accept", "")):
            from django.conf import settings
            from django.utils.html import escape
            if self.template is None:
                path = Path(settings.BASE_DIR) / "frontend" / "errors" / "301.html"
                self.template = path.read_text(encoding="utf-8")
            target = escape(response.get("Location", "/"))
            response.content = self.template.replace("{{location}}", target).encode("utf-8")
            response["Content-Type"] = "text/html; charset=utf-8"
        return response


class SignInProviderUnavailableMiddleware:
    """If the identity provider can't be reached during sign-in, show the 503 page instead of a 500."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        import logging
        import uuid
        from requests.exceptions import RequestException
        from apps.common.views import _respond
        if isinstance(exception, RequestException) and request.path.startswith("/accounts/oidc/"):
            reference = uuid.uuid4().hex[:8].upper()
            logging.getLogger("portal.errors").error(
                "Sign-in provider unreachable %s on %s: %s", reference, request.path, exception)
            return _respond(request, 503, reference=reference)
        return None