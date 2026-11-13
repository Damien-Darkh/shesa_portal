from django.core.management.base import BaseCommand
from django.conf import settings

from apps.accounts.models import User
from apps.common.integrations import sanity_sync


class Command(BaseCommand):
    help = "Retry Sanity pushes that failed. Run every few minutes from cron."

    def handle(self, *args, **options):
        if not sanity_sync.is_enabled():
            self.stdout.write("Sanity sync disabled; nothing to do.")
            return
        pending = User.objects.filter(sanity_pending=True)
        ok_count, failed = 0, 0
        for user in pending:
            try:
                sanity_sync.push_user(user)
                ok_count += 1
            except sanity_sync.PushError as exc:
                failed += 1
                self.stderr.write(f"{user.email}: {exc}")
        self.stdout.write(f"Retried {pending.count()}: {ok_count} ok, {failed} failed.")