from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.csrf, name="csrf"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("people/", views.people, name="people"),
    path("departments/", views.departments, name="departments"),
    path("departments/create", views.department_create, name="department_create"),
    path("departments/<int:dept_id>/", views.department_detail, name="department_detail"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/read-all", views.notifications_read_all, name="notifications_read_all"),
    path("notifications/<int:notification_id>/read", views.notification_read, name="notification_read"),
]
