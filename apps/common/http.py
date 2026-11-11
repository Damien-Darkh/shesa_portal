"""Small JSON helpers shared by the API views."""
import functools
import json

from django.http import JsonResponse


def error(status: int, message: str, **extra) -> JsonResponse:
    return JsonResponse({"error": message, **extra}, status=status)


def ok(data=None, status: int = 200) -> JsonResponse:
    return JsonResponse(data if data is not None else {}, status=status)


def read_json(request) -> dict:
    """Body as a dict. Empty body -> {}. Raises ValueError on bad JSON / wrong shape."""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.META.get("REMOTE_ADDR")


def api_login_required(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error(401, "Authentication required.")
        return view(request, *args, **kwargs)

    return wrapper


def api_admin_required(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error(401, "Authentication required.")
        if not request.user.is_admin:
            return error(403, "Administrator access required.")
        return view(request, *args, **kwargs)

    return wrapper


def has_permission(user, name: str) -> bool:
    """Admins hold every permission; others get them through their roles."""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_admin:
        return True
    return user.roles.filter(permissions__name=name).exists()
