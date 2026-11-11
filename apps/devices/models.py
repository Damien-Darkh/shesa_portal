from django.conf import settings
from django.db import models

from apps.common.utils import utcnow


class Device(models.Model):
    """WireGuard VPN peer, one per physical machine."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="devices", db_index=True)

    device_name = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=utcnow, db_index=True)

    # WireGuard (OPNsense) configuration
    wg_uuid = models.CharField(max_length=64, unique=True)
    wg_api_name = models.CharField(max_length=64)
    wg_address = models.CharField(max_length=32)

    # Revocation
    revoked_at = models.DateTimeField(null=True, blank=True)
    auto_revoked = models.BooleanField(default=False)  # True when revoked by disabling the account

    # Windows launcher (one-time delivery). The script holds the WG private key until fetched.
    launcher_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    launcher_script = models.TextField(null=True, blank=True)
    launcher_token_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devices"
        ordering = ["-created_at"]

    @property
    def owner(self):
        return self.user

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    @property
    def launcher_available(self):
        return bool(
            self.launcher_token
            and self.launcher_token_expires_at
            and self.launcher_token_expires_at > utcnow()
        )

    def __str__(self):
        return self.device_name
