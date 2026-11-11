from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from apps.common.rbac import seed_roles_and_permissions


class Command(BaseCommand):
    help = "Seed roles/permissions and point the Sites framework (used by allauth) at PUBLIC_APP_URL."

    def handle(self, *args, **options):
        seed_roles_and_permissions()
        if settings.PUBLIC_APP_URL:
            host = settings.PUBLIC_APP_URL.split("://", 1)[-1].split("/")[0]
            Site.objects.update_or_create(id=settings.SITE_ID, defaults={"domain": host, "name": host})
        self.stdout.write(self.style.SUCCESS("Seed data applied."))
