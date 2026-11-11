from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from apps.common.audit import record


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    record(request, "LOGIN", "user", user.id, user=user)


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    if user is not None:
        record(request, "LOGOUT", "user", user.id, user=user)
