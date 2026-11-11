"""Append-only audit trail helper. Call record() from views and services."""
from apps.accounts.models import AuditLog

from .http import client_ip
from .utils import utcnow


def record(request, action: str, resource_type: str, resource_id=None,
           details=None, status: str = "SUCCESS", user=None) -> None:
    if user is None and request is not None and request.user.is_authenticated:
        user = request.user
    AuditLog.objects.create(
        user=user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        status=status,
        ip_address=client_ip(request) if request is not None else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:255] or None,
        timestamp=utcnow(),
    )
