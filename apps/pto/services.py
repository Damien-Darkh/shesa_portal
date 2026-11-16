from datetime import date, timedelta

from django.conf import settings
from django.db import transaction

from apps.common.utils import utcnow
from apps.core.services import notify

from .models import LEAVE_TYPES, LeaveBalance, LeaveRequest


class PtoError(Exception):
    pass


def business_days(start: date, end: date) -> int:
    days, current = 0, start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def default_accrual(leave_type: str) -> float:
    return float(settings.LEAVE_DEFAULT_DAYS.get(leave_type, 0.0))


@transaction.atomic
def ensure_balance(user, year: int, leave_type: str) -> LeaveBalance:
    """Returns the balance row for this year and type, creating it from the .env defaults if missing.

    Runs in its own transaction so select_for_update() is valid when called from read-only views.
    """
    balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
        user=user, year=year, leave_type=leave_type,
        defaults={"accrued_days": default_accrual(leave_type)},
    )
    return balance


@transaction.atomic
def create_request(user, leave_type: str, start: date, end: date, days: float, reason: str | None) -> LeaveRequest:
    if leave_type not in LEAVE_TYPES:
        raise PtoError(f"leave_type must be one of: {', '.join(LEAVE_TYPES)}.")
    if end < start:
        raise PtoError("end_date must be on or after start_date.")
    if days <= 0 or days % 0.5:
        raise PtoError("days_requested must be a positive multiple of 0.5.")
    if days > business_days(start, end):
        raise PtoError("days_requested is larger than the business days in the requested range.")

    balance = ensure_balance(user, start.year, leave_type)
    if days > balance.available_days:
        raise PtoError(f"Not enough {leave_type} balance ({balance.available_days} days available).")

    balance.pending_days += days
    balance.save(update_fields=["pending_days", "updated_at"])
    return LeaveRequest.objects.create(
        user=user, leave_type=leave_type, start_date=start, end_date=end,
        days_requested=days, reason=reason,
    )


def _balance_for(req: LeaveRequest) -> LeaveBalance:
    return ensure_balance(req.user, req.start_date.year, req.leave_type)


@transaction.atomic
def decide(req: LeaveRequest, approver, approve: bool, comment: str | None) -> LeaveRequest:
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != LeaveRequest.STATUS_PENDING:
        raise PtoError("Only pending requests can be decided.")
    if req.user_id == approver.id:
        raise PtoError("You cannot approve or reject your own request.")

    balance = _balance_for(req)
    balance.pending_days -= req.days_requested
    if approve:
        balance.used_days += req.days_requested
    balance.save()

    req.status = LeaveRequest.STATUS_APPROVED if approve else LeaveRequest.STATUS_REJECTED
    req.approver = approver
    req.approver_comment = comment
    req.save()
    req.approval_workflow.create(step=1, approver=approver, status=req.status, comment=comment, completed_at=utcnow())

    verdict = "approved" if approve else "rejected"
    notify(
        req.user, "LEAVE_APPROVED" if approve else "LEAVE_REJECTED",
        f"Leave request {verdict}",
        f"Your {req.leave_type} request from {req.start_date} to {req.end_date} was {verdict}.",
        link=f"/api/pto/requests?id={req.id}",
    )
    return req


@transaction.atomic
def cancel(req: LeaveRequest) -> LeaveRequest:
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    balance = _balance_for(req)
    if req.status == LeaveRequest.STATUS_PENDING:
        balance.pending_days -= req.days_requested
    elif req.status == LeaveRequest.STATUS_APPROVED and req.start_date > utcnow().date():
        balance.used_days -= req.days_requested
    else:
        raise PtoError("Only pending requests or approved requests that have not started can be cancelled.")
    balance.save()
    req.status = LeaveRequest.STATUS_CANCELLED
    req.save()
    return req


@transaction.atomic
def edit_approved(req: LeaveRequest, editor, start: date, end: date, days: float, reason: str | None) -> LeaveRequest:
    """Changes an approved request. Reverses its effect on used_days, validates the new values
    against the restored balance, then applies them. Only the admin edit path calls this."""
    req = LeaveRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != LeaveRequest.STATUS_APPROVED:
        raise PtoError("Only approved requests can be edited here.")
    if end < start:
        raise PtoError("end_date must be on or after start_date.")
    if days <= 0 or days % 0.5:
        raise PtoError("days_requested must be a positive multiple of 0.5.")
    if days > business_days(start, end):
        raise PtoError("days_requested is larger than the business days in the requested range.")

    # Reverse the old approval first, so the check below sees the true remaining balance.
    old_balance = ensure_balance(req.user, req.start_date.year, req.leave_type)
    old_balance.used_days -= req.days_requested
    old_balance.save(update_fields=["used_days", "updated_at"])

    new_balance = ensure_balance(req.user, start.year, req.leave_type)
    if days > new_balance.available_days:
        raise PtoError(f"Not enough {req.leave_type} balance ({new_balance.available_days} days available).")

    new_balance.used_days += days
    new_balance.save(update_fields=["used_days", "updated_at"])

    req.start_date = start
    req.end_date = end
    req.days_requested = days
    req.reason = reason
    req.save()

    req.approval_workflow.create(step=1, approver=editor, status="EDITED",
                                 comment="Edited by administrator", completed_at=utcnow())
    notify(
        req.user, "LEAVE_EDITED", "Leave request changed",
        f"Your approved {req.leave_type} leave is now {start} to {end} ({days} days).",
        link=f"/api/pto/requests?id={req.id}",
    )
    return req