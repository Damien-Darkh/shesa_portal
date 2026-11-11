"""Leave endpoints (JSON)."""
from datetime import date



from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.common.audit import record
from apps.common.http import api_admin_required, api_login_required, error, has_permission, ok, read_json
from apps.common.utils import utcnow

from .models import LEAVE_TYPES, LeaveBalance, LeaveRequest
from .services import PtoError, cancel, create_request, decide


def _serialize(req: LeaveRequest) -> dict:
    return {
        "id": req.id,
        "user_id": req.user_id,
        "leave_type": req.leave_type,
        "start_date": req.start_date.isoformat(),
        "end_date": req.end_date.isoformat(),
        "days_requested": req.days_requested,
        "reason": req.reason,
        "status": req.status,
        "approver_id": req.approver_id,
        "approver_comment": req.approver_comment,
        "created_at": req.created_at.isoformat(),
    }


@api_login_required
@require_GET
def balances(request):
    year = request.GET.get("year")
    year = int(year) if year and year.isdigit() else utcnow().year
    rows = LeaveBalance.objects.filter(user=request.user, year=year)
    return ok({"year": year, "balances": [
        {"leave_type": b.leave_type, "accrued_days": b.accrued_days, "carryover_days": b.carryover_days,
         "used_days": b.used_days, "pending_days": b.pending_days, "available_days": b.available_days}
        for b in rows
    ]})


@api_login_required
@require_GET
def requests_list(request):
    """Own requests by default. ?scope=team lists everyone's, for users who may approve."""
    if request.GET.get("scope") == "team":
        if not has_permission(request.user, "approve_leave"):
            return error(403, "Not allowed.")
        qs = LeaveRequest.objects.select_related("user")
    else:
        qs = LeaveRequest.objects.filter(user=request.user)
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status.upper())
    return ok({"requests": [_serialize(r) for r in qs[:500]]})


@api_login_required
@require_POST
def request_create(request):
    try:
        data = read_json(request)
        start = date.fromisoformat(str(data.get("start_date", "")))
        end = date.fromisoformat(str(data.get("end_date", "")))
        days = float(data.get("days_requested", 0))
    except (ValueError, TypeError) as exc:
        return error(400, f"Invalid request: {exc}")
    try:
        leave = create_request(request.user, str(data.get("leave_type", "")).lower(), start, end, days,
                               (data.get("reason") or "").strip() or None)
    except PtoError as exc:
        return error(422, str(exc))
    record(request, "PTO_REQUEST", "leave_request", leave.id, details={"type": leave.leave_type})
    return ok(_serialize(leave), status=201)


def _decision(request, leave_id: int, approve: bool):
    if not has_permission(request.user, "approve_leave"):
        return error(403, "Not allowed.")
    leave = get_object_or_404(LeaveRequest, pk=leave_id)
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))
    try:
        leave = decide(leave, request.user, approve, (data.get("comment") or "").strip() or None)
    except PtoError as exc:
        return error(422, str(exc))
    record(request, "PTO_APPROVE" if approve else "PTO_REJECT", "leave_request", leave.id)
    return ok(_serialize(leave))


@api_login_required
@require_POST
def request_approve(request, leave_id):
    return _decision(request, leave_id, approve=True)


@api_login_required
@require_POST
def request_reject(request, leave_id):
    return _decision(request, leave_id, approve=False)


@api_login_required
@require_POST
def request_cancel(request, leave_id):
    leave = get_object_or_404(LeaveRequest, pk=leave_id)
    if leave.user_id != request.user.id and not request.user.is_admin:
        return error(403, "Not allowed.")
    try:
        leave = cancel(leave)
    except PtoError as exc:
        return error(422, str(exc))
    record(request, "UPDATE", "leave_request", leave.id, details={"action": "cancel"})
    return ok(_serialize(leave))


@api_admin_required
@require_http_methods(["GET", "PUT"])
def admin_user_balances(request, user_id):
    """Admin sets accrual/carryover for an employee: PUT {year, leave_type, accrued_days, carryover_days}."""
    from apps.accounts.models import User

    owner = get_object_or_404(User, pk=user_id)
    if request.method == "GET":
        rows = LeaveBalance.objects.filter(user=owner).order_by("-year", "leave_type")
        return ok({"balances": [
            {"year": b.year, "leave_type": b.leave_type, "accrued_days": b.accrued_days,
             "carryover_days": b.carryover_days, "used_days": b.used_days,
             "pending_days": b.pending_days, "available_days": b.available_days}
            for b in rows
        ]})
    try:
        data = read_json(request)
        year = int(data["year"])
        leave_type = str(data["leave_type"]).lower()
        accrued = float(data["accrued_days"])
        carry = float(data.get("carryover_days", 0))
    except (KeyError, ValueError, TypeError) as exc:
        return error(400, f"Invalid balance: {exc}")
    if leave_type not in LEAVE_TYPES:
        return error(422, f"leave_type must be one of: {', '.join(LEAVE_TYPES)}.")
    if accrued < 0 or carry < 0:
        return error(422, "Days cannot be negative.")
    balance, _ = LeaveBalance.objects.get_or_create(
        user=owner, year=year, leave_type=leave_type, defaults={"accrued_days": 0.0},
    )
    balance.accrued_days = accrued
    balance.carryover_days = carry
    balance.save()
    record(request, "UPDATE", "leave_balance", balance.id, details={"user_id": owner.id, "year": year, "type": leave_type})
    return ok({"available_days": balance.available_days})


def _parse_day(value: str | None):
    if not value:
        return None
    return date.fromisoformat(value)


@api_login_required
@require_GET
def calendar(request):
    """Leave events for a date range. Privacy: colleagues see who is away (approved only) but not the leave type."""
    from django.db.models import Q

    try:
        start, end = _parse_day(request.GET.get("start")), _parse_day(request.GET.get("end"))
    except ValueError:
        return error(400, "start and end must be YYYY-MM-DD.")

    qs = LeaveRequest.objects.select_related("user").exclude(
        status__in=[LeaveRequest.STATUS_REJECTED, LeaveRequest.STATUS_CANCELLED])
    if start:
        qs = qs.filter(end_date__gte=start)
    if end:
        qs = qs.filter(start_date__lte=end)
    privileged = has_permission(request.user, "approve_leave")

    events = []
    for r in qs.order_by("start_date")[:1000]:
        own = r.user_id == request.user.id
        if not (privileged or own) and r.status != LeaveRequest.STATUS_APPROVED:
            continue
        events.append({
            "id": r.id,
            "user_id": r.user_id,
            "user_name": r.user.full_name,
            "leave_type": r.leave_type if (privileged or own) else None,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat(),
            "status": r.status,
            "own": own,
        })
    return ok({"events": events})
