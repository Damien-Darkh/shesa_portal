from django.urls import path

from . import views

urlpatterns = [
    path("", views.device_list, name="device_list"),
    path("create", views.device_create, name="device_create"),
    path("<int:device_id>/revoke", views.device_revoke, name="device_revoke"),
    path("<int:device_id>/reconnect", views.device_reconnect, name="device_reconnect"),
    path("<int:device_id>/delete", views.device_delete, name="device_delete"),
    path("<int:device_id>/launcher.cmd", views.device_launcher_cmd, name="device_launcher_cmd"),
    path("<int:device_id>/launcher-script", views.device_launcher_script, name="device_launcher_script"),
]
