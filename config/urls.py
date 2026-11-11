from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from apps.common import pages
from apps.common import views as common_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.accounts.urls")),
    path("api/", include("apps.core.urls")),
    path("api/devices/", include("apps.devices.urls")),
    path("api/pto/", include("apps.pto.urls")),
    path("api/admin/", include("apps.accounts.admin_urls")),
    # Frontend (same origin). Static assets, then HTML pages behind login.
    path("favicon.ico", RedirectView.as_view(url="/logo.svg", permanent=True)),
    path("", pages.root),
    re_path(r"^(?P<path>(?:vendor/|pages/)?[\w.-]+\.(?:html|css|js|svg|png|jpe?g|ico|woff2))$", pages.serve),
]

handler400 = common_views.bad_request
handler403 = common_views.forbidden
handler404 = common_views.not_found
handler500 = common_views.server_error
