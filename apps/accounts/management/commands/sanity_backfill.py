from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.common.integrations import sanity_sync


class Command(BaseCommand):
    help = ("Publish employees to Sanity. By default only employees without a Sanity document. "
            "Use --refresh to update everyone (sets externalId to the identity ID and uploads photos).")

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many employees.")
        parser.add_argument("--dry-run", action="store_true", help="List who would be pushed.")
        parser.add_argument("--refresh", action="store_true",
                            help="Also update employees who already have a Sanity document.")

    def handle(self, *args, **options):
        if not sanity_sync.is_enabled():
            self.stderr.write(self.style.ERROR(
                "Sanity sync is off. Set SANITY_SYNC_ENABLED=true, SANITY_PROJECT_ID and "
                "SANITY_WRITE_TOKEN, then run again."))
            return

        qs = User.objects.order_by("id")
        if not options["refresh"]:
            qs = qs.filter(sanity_id__isnull=True)
        users = [u for u in qs if not sanity_sync.is_excluded(u)]
        if options["limit"]:
            users = users[:options["limit"]]

        if options["dry_run"]:
            for user in users:
                self.stdout.write(f"would push: {user.id} {user.identity_id or 'NO ID'} {user.email}")
            return

        ok = failed = 0
        for user in users:
            try:
                sanity_sync.push_user(user)
                ok += 1
                self.stdout.write(f"ok: {user.identity_id} {user.email}")
            except sanity_sync.PushError as exc:
                failed += 1
                self.stderr.write(f"failed: {user.email}: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Pushed {ok}, failed {failed}."))