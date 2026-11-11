"""Leave business rules. Balances are only touched inside transactions."""
from datetime import date, timedelta

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

    balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
        user=user, year=start.year, leave_type=leave_type,
        defaults={"accrued_days": 0.0},
    )
    if days > balance.available_days:
        raise PtoError(f"Not enough {leave_type} balance ({balance.available_days} days available).")

    balance.pending_days += days
    balance.save(update_fields=["pending_days", "updated_at"])
    return LeaveRequest.objects.create(
        user=user, leave_type=leave_type, start_date=start, end_date=end,
        days_requested=days, reason=reason,
    )


def _balance_for(req: LeaveRequest) -> LeaveBalance:
    return LeaveBalance.objects.select_for_update().get(
        user=req.user, year=req.start_date.year, leave_type=req.leave_type,
    )


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
