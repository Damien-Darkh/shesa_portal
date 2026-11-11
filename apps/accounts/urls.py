from django.urls import path

from . import views

urlpatterns = [
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("api/auth/config/", views.auth_config, name="auth_config"),
    path("api/me/", views.me, name="me"),
    path("api/me/dsm-password", views.change_dsm_password, name="change_dsm_password"),
]