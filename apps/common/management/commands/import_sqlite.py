"""One-off migration: copy data from the old SQLite portal database into PostgreSQL.

    python manage.py import_sqlite /path/to/portal.db            # dry run (default)
    python manage.py import_sqlite /path/to/portal.db --commit   # write

Tables are matched by db_table name, which the models keep identical to the old schema.
Everything runs in one transaction; the target tables must be empty. Columns that no
longer exist (e.g. workos_user_id) are skipped. Primary keys are preserved, then the
PostgreSQL sequences are reset so new rows continue after the imported ids.
"""
import sqlite3

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.core.management.color import no_style

# Parents before children, so foreign keys point at rows that already exist.
ORDER = [
    "accounts.Permission", "accounts.Role", "core.Department", "accounts.User",
    "core.UserProfile", "devices.Device", "pto.LeaveBalance", "pto.LeaveRequest",
    "pto.LeaveApprovalWorkflow", "core.Notification", "core.SearchIndex",
    "core.TimeAttendance", "accounts.AuditLog",
]
# Many-to-many join tables: (model label, field name)
M2M = [("accounts.User", "roles"), ("accounts.Role", "permissions")]
BATCH = 500


class Command(BaseCommand):
    help = "Import data from the legacy SQLite portal database into the configured PostgreSQL database."

    def add_arguments(self, parser):
        parser.add_argument("sqlite_path")
        parser.add_argument("--commit", action="store_true", help="Actually write. Without it: dry run.")

    def handle(self, *args, **opts):
        src = sqlite3.connect(f"file:{opts['sqlite_path']}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        plan = []
        for label in ORDER:
            model = apps.get_model(label)
            plan.append((model, self._rows_for(src, tables, model)))

        for model, rows in plan:
            self.stdout.write(f"{model._meta.db_table:28} {len(rows):6} rows")

        if not opts["commit"]:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --commit to write."))
            return

        with transaction.atomic():
            for model, rows in plan:
                if model.objects.exists():
                    raise CommandError(f"{model._meta.db_table} is not empty; refusing to import into it.")
            for model, rows in plan:
                model.objects.bulk_create(rows, batch_size=BATCH)
            for label, field_name in M2M:
                self._copy_m2m(src, tables, label, field_name)
            self._reset_sequences([apps.get_model(label) for label in ORDER])

        self.stdout.write(self.style.SUCCESS("Import complete."))

    def _rows_for(self, src, tables, model):
        table = model._meta.db_table
        if table not in tables:
            return []
        legacy_cols = {r[1] for r in src.execute(f"PRAGMA table_info({table})")}
        fields = [f for f in model._meta.concrete_fields]
        usable = [f for f in fields if f.column in legacy_cols]
        out = []
        for row in src.execute(f"SELECT * FROM {table}"):
            kwargs = {}
            for f in usable:
                kwargs[f.attname] = f.to_python(row[f.column]) if row[f.column] is not None else None
            out.append(model(**kwargs))
        return out

    def _copy_m2m(self, src, tables, label, field_name):
        model = apps.get_model(label)
        through = model._meta.get_field(field_name).remote_field.through
        table = through._meta.db_table
        if table not in tables:
            return
        src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
        left, right = [f.column for f in through._meta.fields if f.column in src_cols and f.name != "id"][:2]
        through.objects.bulk_create(
            [through(**{left: r[left], right: r[right]}) for r in src.execute(f"SELECT {left},{right} FROM {table}")],
            batch_size=BATCH,
        )

    def _reset_sequences(self, models):
        statements = connection.ops.sequence_reset_sql(no_style(), models)
        with connection.cursor() as cursor:
            for sql in statements:
                cursor.execute(sql)
