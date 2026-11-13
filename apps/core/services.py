from apps.common.utils import utcnow
from apps.common.integrations import sanity_photo

from .models import Department, Notification


def notify(user, notification_type: str, title: str, message: str, link: str | None = None) -> None:
    Notification.objects.create(
        user=user, notification_type=notification_type, title=title, message=message, link=link,
    )


def department_tree_ids(dept_id: int) -> set[int]:
    """The department plus every sub-department below it."""
    children = {}
    for d in Department.objects.values("id", "parent_id"):
        children.setdefault(d["parent_id"], []).append(d["id"])
    out, stack = set(), [dept_id]
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        stack.extend(children.get(current, []))
    return out


def profile_dict(user) -> dict:
    p = getattr(user, "profile", None) if user.pk else None
    return {
        "department_id": p.department_id if p else None,
        "job_title": p.job_title if p else None,
        "phone": p.phone if p else None,
        "office_location": p.office_location if p else None,
        "bio": p.bio if p else None,
        "photo_url": sanity_photo.display_url(user) or (p.photo_url if p else None),
        "start_date": p.start_date.isoformat() if p and p.start_date else None,
        "updated_at": p.updated_at.isoformat() if p and p.updated_at else None,
    }


def reconcile_manager_roles(user) -> list[str]:
    """A manager must belong to their department or one below it. Clears the role where that no longer holds.
    Returns the names of departments they stopped managing."""
    from .models import UserProfile

    profile = UserProfile.objects.filter(user=user).first()
    dept_id = profile.department_id if profile else None
    lost = []
    for dept in Department.objects.filter(manager=user):
        if dept_id is None or dept_id not in department_tree_ids(dept.id):
            dept.manager = None
            dept.save(update_fields=["manager"])
            lost.append(dept.name)
    return lost
