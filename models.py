from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # Identity comes from WorkOS AuthKit's verified email claim - this
    # app never stores or checks a password itself.
    email = db.Column(db.String(255), unique=True, nullable=False)
    # WorkOS's own user ID (e.g. "user_01ABC..."). Needed to delete the
    # account on WorkOS's side too, not just locally. May be null for
    # rows created before this column existed - backfilled automatically
    # the next time that person logs in (see app.py's /callback).
    workos_user_id = db.Column(db.String(64), nullable=True)
    dsm_username = db.Column(db.String(64), nullable=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    disabled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Temporary single-use DSM password reveal token + expiry
    dsm_password_token = db.Column(db.String(64), nullable=True)
    dsm_temp_password = db.Column(db.String(128), nullable=True)
    dsm_password_expires_at = db.Column(db.DateTime, nullable=True)
    # Persists independently of the reveal-to-admin fields above: set True
    # whenever a temp password is issued, only cleared once the employee
    # themselves actually sets their own NAS password. dsm_temp_password
    # gets wiped as soon as the admin views it once, so it can't be used
    # to decide whether the employee still needs to change it.
    dsm_must_change_password = db.Column(db.Boolean, default=False, nullable=False)

    devices = db.relationship("Device", backref="owner", lazy=True)
    

    # Flask-Login uses this to decide if a session is allowed to stay active
    @property
    def is_active(self):
        return not self.disabled


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    device_name = db.Column(db.String(64), nullable=False)   # e.g. "iPhone"
    wg_uuid = db.Column(db.String(64), nullable=False)        # OPNsense peer uuid
    wg_api_name = db.Column(db.String(64), nullable=False)    # sanitized name on OPNsense
    wg_address = db.Column(db.String(32), nullable=False)     # e.g. 10.10.10.7
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)
    # True only when this device was revoked as a side-effect of an admin
    # disabling the whole account - NOT when the employee revoked it
    # themselves (e.g. lost phone). Used so re-enabling the account only
    # restores devices it auto-revoked, never a device the employee
    # deliberately disconnected on their own.
    auto_revoked = db.Column(db.Boolean, default=False, nullable=False)

    # Supports the Windows launcher's "irm <url>?token=... | iex" flow:
    # the fully-rendered PowerShell script (with WireGuard keys already
    # filled in) is cached here briefly, keyed by a random one-time
    # token, so it can be fetched by a PowerShell subprocess later that
    # has no browser session/cookies of its own. Cleared immediately
    # after the first successful fetch (see app.py's launcher_script
    # route), or after launcher_token_expires_at passes, whichever
    # comes first - this is the one place in the app a private key
    # touches disk at all, and only ever briefly, single-use.
    launcher_token = db.Column(db.String(64), nullable=True)
    launcher_script = db.Column(db.Text, nullable=True)
    launcher_token_expires_at = db.Column(db.DateTime, nullable=True)

    @property
    def launcher_available(self):
        """True until the launcher is either run once (launcher_script
        gets wiped in app.py's /launcher-script route) or the expiry
        passes - independent of the QR/.conf's own session-based "shown
        once" flow, so this stays valid across navigation, not just on
        the device_created page itself."""
        from datetime import datetime
        return bool(
            self.launcher_token
            and self.launcher_token_expires_at
            and self.launcher_token_expires_at > datetime.utcnow()
        )

    @property
    def is_revoked(self):
        return self.revoked_at is not None