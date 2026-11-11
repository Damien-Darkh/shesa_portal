"""Organisation, directory, notifications and the search table."""
from django.conf import settings
from django.db import models

from apps.common.utils import utcnow


class Department(models.Model):
    name = models.CharField(max_length=128, unique=True, db_index=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="sub_departments")
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="departments_managed")
    created_at = models.DateTimeField(default=utcnow)

    class Meta:
        db_table = "departments"

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="users")

    job_title = models.CharField(max_length=128, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    office_location = models.CharField(max_length=255, null=True, blank=True)

    bio = models.TextField(null=True, blank=True)
    photo_url = models.TextField(null=True, blank=True)  # URL or data: URL (prototype uploads)
    start_date = models.DateField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_profiles"

    def __str__(self):
        return f"Profile of user {self.user_id}"


class SearchIndex(models.Model):
    """Denormalised search table (lightweight alternative to a search engine)."""
    document_type = models.CharField(max_length=64, db_index=True)  # "USER", "DOCUMENT", "DEPARTMENT"
    document_id = models.IntegerField()
    title = models.CharField(max_length=255, db_index=True)
    content = models.TextField()
    tags = models.CharField(max_length=255, null=True, blank=True)  # comma-separated
    created_at = models.DateTimeField(default=utcnow)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "search_index"
        constraints = [
            models.UniqueConstraint(fields=["document_type", "document_id"], name="idx_search_document"),
        ]


class TimeAttendance(models.Model):
    """Clock in/out records. Server time only."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="time_records", db_index=True)
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=utcnow)

    class Meta:
        db_table = "time_attendance"
        indexes = [models.Index(fields=["user", "clock_in"], name="idx_attendance_user_date")]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="notifications", db_index=True)
    notification_type = models.CharField(max_length=64, db_index=True)  # e.g. "LEAVE_APPROVED"
    title = models.CharField(max_length=255)
    message = models.TextField()
    link = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    sent_at = models.DateTimeField(default=utcnow)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        indexes = [
            models.Index(fields=["user", "is_read"], name="idx_notifications_user_read"),
            models.Index(fields=["sent_at"], name="idx_notifications_sent_at"),
        ]
