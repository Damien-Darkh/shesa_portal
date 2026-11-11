from django.urls import path

from . import views

urlpatterns = [
    path("balances/", views.balances, name="pto_balances"),
    path("calendar/", views.calendar, name="pto_calendar"),
    path("requests/", views.requests_list, name="pto_requests"),
    path("requests/create", views.request_create, name="pto_request_create"),
    path("requests/<int:leave_id>/approve", views.request_approve, name="pto_request_approve"),
    path("requests/<int:leave_id>/reject", views.request_reject, name="pto_request_reject"),
    path("requests/<int:leave_id>/cancel", views.request_cancel, name="pto_request_cancel"),
]
