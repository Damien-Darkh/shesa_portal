from django.core.management.base import BaseCommand

from apps.common.rbac import seed_roles_and_permissions


class Command(BaseCommand):
    help = "Create the default roles and permissions (safe to run more than once)."

    def handle(self, *args, **options):
        if seed_roles_and_permissions():
            self.stdout.write(self.style.SUCCESS("Default roles and permissions created."))
        else:
            self.stdout.write("Roles already exist - nothing to do.")
