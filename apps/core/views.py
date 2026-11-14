"""Dashboard, people directory, departments, notifications, CSRF bootstrap (JSON)."""
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.accounts.models import User
from apps.common.audit import record
from apps.common.http import api_admin_required, api_login_required, error, ok, read_json
from apps.common.utils import utcnow

from .models import Department, Notification, UserProfile
from .services import department_tree_ids, profile_dict


@ensure_csrf_cookie
@require_GET
def csrf(request):
    return ok({"csrf": "set"})


@api_login_required
@require_GET
def dashboard(request):
    from apps.accounts.models import AuditLog
    from apps.devices.models import Device
    from apps.pto.models import LeaveBalance

    user = request.user
    year = utcnow().year
    balances = LeaveBalance.objects.filter(user=user, year=year)
    recent = AuditLog.objects.filter(user=user).order_by("-timestamp")[:10]
    return ok({
        "devices_count": Device.objects.filter(user=user).count(),
        "unread_notifications": Notification.objects.filter(user=user, is_read=False).count(),
        "leave_balances": [
            {"leave_type": b.leave_type, "year": b.year, "accrued_days": b.accrued_days,
             "used_days": b.used_days, "pending_days": b.pending_days, "carryover_days": b.carryover_days,
             "remaining_days": b.available_days}
            for b in balances
        ],
        "recent_activity": [
            {"action": a.action, "resource_type": a.resource_type, "status": a.status,
             "timestamp": a.timestamp.isoformat()}
            for a in recent
        ],
    })


def _person(u: User, full: bool) -> dict:
    data = {
        "id": u.id,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "full_name": u.full_name,
        "disabled": u.disabled,
        "profile": profile_dict(u),
        "identity_id": u.identity_id,
        "display_order": u.display_order,
    }
    if full:
        data.update({
            "device_count": getattr(u, "device_count", 0),
            "is_admin": u.is_admin,
            "dsm_username": u.dsm_username,
            "dsm_must_change_password": u.dsm_must_change_password,
            "created_at": u.created_at.isoformat(),
        })
    return data


@api_login_required
@require_GET
def people(request):
    """Everyone for admins (incl. disabled), active employees for everyone else."""
    is_admin = request.user.is_admin
    qs = (User.objects.select_related("profile")
          .annotate(device_count=Count("devices", filter=Q(devices__revoked_at__isnull=True)))
          .order_by("first_name", "last_name", "email"))
    if not is_admin:
        qs = qs.filter(disabled=False)
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search)
                       | Q(email__icontains=search) | Q(profile__job_title__icontains=search))
    dept_id = request.GET.get("department")
    if dept_id and dept_id.isdigit():
        qs = qs.filter(profile__department_id=int(dept_id))
    return ok({"people": [_person(u, full=is_admin) for u in qs]})


def _department(d: Department) -> dict:
    return {"id": d.id, "name": d.name, "description": d.description, "parent_id": d.parent_id,
            "manager_id": d.manager_id}


@api_login_required
@require_GET
def departments(request):
    return ok({"departments": [_department(d) for d in Department.objects.order_by("name")]})


def _validate_department_fields(data: dict, current: Department | None):
    """Returns (cleaned dict, error message or None)."""
    fields = {}
    if "name" in data or current is None:
        name = (data.get("name") or "").strip()
        if not name:
            return None, "Enter a department name."
        if len(name) > 128:
            return None, "Department name is too long."
        clash = Department.objects.filter(name__iexact=name)
        if current:
            clash = clash.exclude(pk=current.pk)
        if clash.exists():
            return None, "A department with this name already exists."
        fields["name"] = name
    if "description" in data:
        fields["description"] = (data.get("description") or "").strip()[:255] or None

    if "parent_id" in data:
        parent_id = data.get("parent_id") or None
        if parent_id is not None:
            parent = Department.objects.filter(pk=parent_id).first()
            if not parent:
                return None, "Parent department does not exist."
            if current and parent.pk in department_tree_ids(current.pk):
                return None, "A department can't be placed under itself or its sub-departments."
        fields["parent_id"] = parent_id

    if "manager_id" in data:
        manager_id = data.get("manager_id") or None
        if manager_id is not None:
            manager = User.objects.select_related("profile").filter(pk=manager_id).first()
            if not manager:
                return None, "Manager does not exist."
            if current is None:
                return None, "A new department has no members yet, so it can't have a manager."
            member_dept = getattr(getattr(manager, "profile", None), "department_id", None)
            if member_dept not in department_tree_ids(current.pk):
                return None, "The manager must be a member of this department or one of its sub-departments."
        fields["manager_id"] = manager_id
    return fields, None


@api_admin_required
@require_POST
def department_create(request):
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))
    fields, err = _validate_department_fields(data, None)
    if err:
        return error(422, err)
    fields.pop("manager_id", None)  # new departments can't have a manager yet
    dept = Department.objects.create(**fields)
    record(request, "CREATE", "department", dept.id, details={"name": dept.name})
    return ok(_department(dept), status=201)


@api_admin_required
@require_http_methods(["PATCH", "DELETE"])
def department_detail(request, dept_id):
    dept = get_object_or_404(Department, pk=dept_id)
    if request.method == "DELETE":
        members = UserProfile.objects.filter(department=dept).count()
        children = Department.objects.filter(parent=dept).count()
        if members or children:
            return error(409, "Move employees and sub-departments out of this department first.",
                         members=members, children=children)
        name = dept.name
        dept.delete()
        record(request, "DELETE", "department", dept_id, details={"name": name})
        return ok({"deleted": True})

    try:
        data = read_json(request)
    except ValueError as exc:
        return error(400, str(exc))
    fields, err = _validate_department_fields(data, dept)
    if err:
        return error(422, err)
    for key, value in fields.items():
        setattr(dept, key, value)
    dept.save()
    record(request, "UPDATE", "department", dept.id, details={"fields": sorted(fields)})
    return ok(_department(dept))


@api_login_required
@require_GET
def notifications(request):
    items = Notification.objects.filter(user=request.user).order_by("-sent_at")[:100]
    return ok({"notifications": [
        {"id": n.id, "type": n.notification_type, "title": n.title, "message": n.message,
         "link": n.link, "is_read": n.is_read, "sent_at": n.sent_at.isoformat()}
        for n in items
    ]})


@api_login_required
@require_POST
def notification_read(request, notification_id):
    note = get_object_or_404(Notification, pk=notification_id, user=request.user)
    if not note.is_read:
        note.is_read = True
        note.read_at = utcnow()
        note.save(update_fields=["is_read", "read_at"])
    return ok({"id": note.id, "is_read": True})


@api_login_required
@require_POST
def notifications_read_all(request):
    count = Notification.objects.filter(user=request.user, is_read=False).update(
        is_read=True, read_at=utcnow()
    )
    return ok({"marked_read": count})
