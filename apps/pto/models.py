"""Leave (PTO) balances, requests and the approval trail."""
from django.conf import settings
from django.db import models

from apps.common.utils import utcnow

LEAVE_TYPES = ("vacation", "sick", "personal")


class LeaveBalance(models.Model):
    """Accrued PTO per employee, per year, per leave type."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="leave_balances", db_index=True)
    year = models.IntegerField()
    leave_type = models.CharField(max_length=32)

    accrued_days = models.FloatField()
    used_days = models.FloatField(default=0.0)
    pending_days = models.FloatField(default=0.0)
    carryover_days = models.FloatField(default=0.0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leave_balance"
        constraints = [
            models.UniqueConstraint(fields=["user", "year", "leave_type"], name="leave_balance_uc"),
        ]
        indexes = [models.Index(fields=["user", "year"], name="idx_leave_balance_user_year")]

    @property
    def available_days(self) -> float:
        return self.accrued_days + self.carryover_days - self.used_days - self.pending_days


class LeaveRequest(models.Model):
    """Status: PENDING -> APPROVED / REJECTED / CANCELLED."""
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "DENIED"  # UI vocabulary: PENDING / APPROVED / DENIED / CANCELLED
    STATUS_CANCELLED = "CANCELLED"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="leave_requests", db_index=True)
    leave_type = models.CharField(max_length=32)
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    days_requested = models.FloatField()  # can be 0.5
    reason = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=32, default=STATUS_PENDING, db_index=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="leave_requests_approved")
    approver_comment = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(default=utcnow)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leave_requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"], name="idx_leave_request_user_status"),
            models.Index(fields=["start_date", "end_date"], name="idx_leave_request_date_range"),
        ]


class LeaveApprovalWorkflow(models.Model):
    """Approval chain for a leave request (one step per decision for now)."""
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE,
                                      related_name="approval_workflow", db_index=True)
    step = models.IntegerField()
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="approval_steps")
    status = models.CharField(max_length=32, default="PENDING", db_index=True)
    comment = models.TextField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=utcnow)

    class Meta:
        db_table = "leave_approval_workflow"
        indexes = [models.Index(fields=["approver", "status"], name="idx_approval_workflow_approver")]
