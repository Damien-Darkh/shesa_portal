from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Apply migrations and seed roles/permissions."

    def handle(self, *args, **options):
        call_command("migrate", verbosity=0)
        call_command("seed_rbac", verbosity=0)
        self.stdout.write(self.style.SUCCESS(
            "Database ready. The first person to sign in through SSO becomes the admin."
        ))
