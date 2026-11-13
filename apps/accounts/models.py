"""Identity, RBAC and audit models.

There are no passwords. User extends AbstractBaseUser only for Django's
session plumbing; the password field always holds an unusable hash. Logins
come from the OIDC provider (Authentik) through django-allauth.
"""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password
from django.db import models

from apps.common.utils import utcnow


class UserManager(BaseUserManager):
    def create_user(self, email, **extra):
        user = self.model(email=email.lower().strip(), **extra)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    email = models.EmailField(max_length=255, unique=True)

    # Identity provider link (OIDC subject). Filled by allauth on first login.
    oidc_subject = models.CharField(max_length=255, null=True, blank=True, unique=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)

    is_admin = models.BooleanField(default=False)
    language = models.CharField(max_length=5, default="it")  # UI language: it | en
    disabled = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=utcnow, db_index=True)

    # Authentik (identity provider) account created for this user by the portal.
    # Stored separately from oidc_subject: this is the username the portal used
    # when it created the account via the Admin API, kept stable even if the
    # user's email changes later, so delete/disable actions target the right account.
    authentik_username = models.CharField(max_length=150, null=True, blank=True, unique=True)

    # Synology NAS
    dsm_username = models.CharField(max_length=64, null=True, blank=True, unique=True)
    dsm_password_token = models.CharField(max_length=64, null=True, blank=True)
    dsm_temp_password = models.CharField(max_length=128, null=True, blank=True)
    dsm_password_expires_at = models.DateTimeField(null=True, blank=True)
    dsm_must_change_password = models.BooleanField(default=False)

    roles = models.ManyToManyField("Role", related_name="users", db_table="user_roles", blank=True)

    vpn_access = models.BooleanField(default=False)

    # Sanity (company website) link
    sanity_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    sanity_pending = models.BooleanField(default=False, db_index=True)
    sanity_last_error = models.TextField(null=True, blank=True)
    sanity_synced_at = models.DateTimeField(null=True, blank=True)
    photo_uri = models.CharField(max_length=255, null=True, blank=True)
    show_on_website = models.BooleanField(default=False)

    # Employee-facing profile fields stored in Postgres
    other_emails = models.JSONField(default=list, blank=True)
    linkedin_url = models.URLField(max_length=255, null=True, blank=True)
    profile_text = models.TextField(null=True, blank=True)
    project_ids = models.JSONField(default=list, blank=True)

    website_consent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "users"

    def save(self, *args, **kwargs):
        if not self.password:
            self.password = make_password(None)  # unusable: no password login exists
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        """Disabled accounts cannot use the portal (Django's session auth checks this)."""
        return not self.disabled

    @property
    def full_name(self):
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.email

    def __str__(self):
        return self.email


class Role(models.Model):
    name = models.CharField(max_length=64, unique=True, db_index=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=utcnow)
    permissions = models.ManyToManyField("Permission", related_name="roles", db_table="role_permissions", blank=True)

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.name


class Permission(models.Model):
    name = models.CharField(max_length=64, unique=True, db_index=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    resource = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=utcnow)

    class Meta:
        db_table = "permissions"

    def __str__(self):
        return self.name


class AuditLog(models.Model):
    """Append-only. Never update or delete rows."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=255, db_index=True)
    resource_type = models.CharField(max_length=64, db_index=True)
    resource_id = models.BigIntegerField(null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=32)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.CharField(max_length=255, null=True, blank=True)
    timestamp = models.DateTimeField(default=utcnow, db_index=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["user", "timestamp"], name="idx_audit_user_timestamp"),
            models.Index(fields=["action", "timestamp"], name="idx_audit_action_timestamp"),
            models.Index(fields=["resource_type", "resource_id"], name="idx_audit_resource"),
        ]

    def __str__(self):
        return f"{self.action} at {self.timestamp}"