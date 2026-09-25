"app.py"
import io
import os
import re
import secrets
from datetime import datetime, timedelta
import qrcode
from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, redirect, render_template,
                    request, send_file, session, url_for)
from flask_login import (LoginManager, current_user, login_required,
                          login_user, logout_user)

load_dotenv()

import wg_manager  # noqa: E402  (must load after dotenv so env vars are set)
import windows_launcher  # noqa: E402
import workos_auth  # noqa: E402
from models import Device, User, db  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix
from mailer import send_welcome_email
# Used to build the logout return_to URL reliably - request.host isn't
# safe to use here since it'd differ (and fail WorkOS's allowlist check)
# whenever you're testing on the Synology's LAN IP instead of the real
# domain, e.g. http://192.168.10.2:8081 vs https://vpn.shesa.it.


try:
    import synology_manager
    SYNOLOGY_ENABLED = bool(os.environ.get("DSM_URL"))
except ImportError:
    SYNOLOGY_ENABLED = False
PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
USE_WORKOS = os.environ.get("USE_WORKOS", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# NAS LAN address and share name the Windows launcher points its
# desktop shortcut at, once WireGuard is connected. Separate from the
# WG_* values in wg_manager.py since those describe the VPN itself, not
# what's on the other end of it.
NAS_IP = os.environ.get("NAS_IP", "")
NAS_SHARE_NAME = os.environ.get("NAS_SHARE_NAME", "")
LAUNCHER_TOKEN_TTL_MINUTES = int(os.environ.get("LAUNCHER_TOKEN_TTL_MINUTES", "60"))

app = Flask(__name__)
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)

app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]

app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# DATABASE_PATH lets docker-compose point this at a mounted volume
# (/app/data/portal.db) so the database survives container rebuilds;
# defaults to living next to app.py for plain `python app.py` use.
db_path = os.environ.get(
    "DATABASE_PATH", os.path.join(os.path.dirname(__file__), "portal.db")
)
os.makedirs(os.path.dirname(db_path), exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
# There is still no local login form. WorkOS AuthKit shows its own hosted
# login page (email + one-time code) before traffic ever lands on
# dashboard/admin routes - see the before_request hook below.


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# -------------------------------------------------------- WorkOS AuthKit ----

@app.before_request
def require_login():
    """Require an authenticated session.

    Production uses WorkOS AuthKit.
    Development can bypass WorkOS and use a local development user.
    """
    if "_pending_conf" in session and request.endpoint not in (
        "device_created",
        "device_qr",
        "static",
    ):
        session.pop("_pending_conf", None)
        session.pop("_pending_device_id", None)

    if current_user.is_authenticated:
        return

    # Development authentication bypass
    if not USE_WORKOS:
        dev_email = os.environ.get(
            "DEV_USER_EMAIL",
            "developer@localhost",
        )

        user = User.query.filter_by(email=dev_email).first()

        if user is None:
            user = User(
                email=dev_email,
                is_admin=True,
                first_name="Development",
                last_name="User",
            )
            db.session.add(user)
            db.session.commit()

        login_user(user)
        return

    # Production / WorkOS authentication
    if request.endpoint in (
        "static",
        "login",
        "callback",
        "device_launcher_script",
    ):
        return

    return redirect(url_for("login", next=request.full_path))

@app.route("/login")
def login():
    if not USE_WORKOS:
        return redirect(url_for("dashboard"))

    next_url = request.args.get("next", "")
    session["_oauth_next"] = (
        next_url if next_url.startswith("/")
        else url_for("dashboard")
    )

    state = secrets.token_urlsafe(24)
    session["_oauth_state"] = state

    return redirect(workos_auth.get_authorization_url(state=state))


@app.route("/callback")
def callback():
    if not USE_WORKOS:
        return redirect(url_for("dashboard"))
    """WorkOS redirects here after the employee finishes logging in on
    AuthKit's hosted page. We verify the code, look up (or create, on
    first-ever visit) the matching local User row purely to track admin
    status and device ownership - no password is ever involved."""
    error = request.args.get("error")
    if error:
        flash(f"Login was not completed ({request.args.get('error_description', error)}).",
              "error")
        return redirect(url_for("login"))

    code = request.args.get("code")
    returned_state = request.args.get("state")
    expected_state = session.pop("_oauth_state", None)
    next_url = session.pop("_oauth_next", None) or url_for("dashboard")

    if not code or not returned_state or not secrets.compare_digest(returned_state, expected_state or ""):
        flash("Login could not be verified - please try again.", "error")
        return redirect(url_for("login"))

    try:
        email, workos_session_id, workos_user_id, first_name, last_name = workos_auth.exchange_code(code)
    except workos_auth.AuthKitError as e:
        return f"Access denied: {e}", 403

    user = User.query.filter_by(email=email).first()
    if user is None:
        # First time this email has ever reached the app. If this is the
        # very first user in the whole database, make them admin - this
        # is how you (the first person to log in) become the initial
        # portal admin, with no manual setup step.
        is_first_ever_user = User.query.count() == 0
        user = User(email=email, is_admin=is_first_ever_user, workos_user_id=workos_user_id,
                     first_name=first_name, last_name=last_name)
        db.session.add(user)
        db.session.commit()
    else:
        # Backfills anything missing on rows created before these
        # columns existed, or added locally via admin_add_user before
        # WorkOS confirmed a name/id.
        changed = False
        if not user.workos_user_id and workos_user_id:
            user.workos_user_id = workos_user_id
            changed = True
        if not user.first_name and first_name:
            user.first_name = first_name
            changed = True
        if not user.last_name and last_name:
            user.last_name = last_name
            changed = True
        if changed:
            db.session.commit()

    if user.disabled:
        return "Your account has been disabled. Contact IT.", 403

    login_user(user)
    session["_workos_session_id"] = workos_session_id

    # Force a password change on first login if the employee hasn't set
    # their own NAS password yet - this fires whenever
    # dsm_must_change_password is set, so it also works if an admin
    # resets someone's password later, and stays true even after the
    # admin has already viewed (and cleared) the one-time reveal.
    if SYNOLOGY_ENABLED and user.dsm_username and user.dsm_must_change_password:
        flash("Please set a new NAS password before continuing.", "error")
        return redirect(url_for("change_dsm_password"))

    return redirect(next_url)


@app.route("/logout")
@login_required
def logout():
    """Ends both sessions: our local one (so login_required routes are
    blocked again), and AuthKit's own hosted one (so /login actually
    shows a login prompt again instead of silently re-authenticating the
    still-active AuthKit session)."""
    workos_session_id = session.get("_workos_session_id")
    logout_user()
    session.clear()

    if workos_session_id:
        return_to = f"{PUBLIC_APP_URL}/login" if PUBLIC_APP_URL else url_for("login", _external=True)
        return redirect(workos_auth.get_logout_url(
            session_id=workos_session_id,
            return_to=return_to,
        ))
    return redirect(url_for("login"))


# ---------------------------------------------------------- employee UI ----

@app.route("/")
@login_required
def dashboard():
    devices = Device.query.filter_by(user_id=current_user.id).order_by(
        Device.created_at.desc()
    ).all()
    return render_template("dashboard.html", devices=devices)


@app.route("/account/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Employee self-service profile page: update name (synced to WorkOS)
    and NAS password. Email is intentionally read-only here - it's the
    WorkOS login identity and changing it would desync authentication."""
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()

        current_user.first_name = first_name or None
        current_user.last_name = last_name or None

        try:
            workos_auth.update_user(current_user.workos_user_id, first_name, last_name)
        except workos_auth.AuthKitError as e:
            flash(f"Profile saved locally, but WorkOS sync failed: {e}", "error")

        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html")


@app.route("/devices/add", methods=["GET", "POST"])
@login_required
def add_device():
    if request.method == "POST":
        device_name = request.form.get("device_name", "").strip()
        if not device_name:
            flash("Please name this device (e.g. 'iPhone', 'Work Laptop').", "error")
            return render_template("add_device.html")

        local_part = current_user.email.split("@")[0]
        peer_display_name = f"{local_part}_{device_name}"
        try:
            result = wg_manager.create_peer(peer_display_name)
        except wg_manager.WgApiError as e:
            flash(f"Could not create VPN access: {e}", "error")
            return render_template("add_device.html")

        device = Device(
            user_id=current_user.id,
            device_name=device_name,
            wg_uuid=result["uuid"],
            wg_api_name=result["api_name"],
            wg_address=result["address"],
        )
        db.session.add(device)
        db.session.commit()

        # Windows launcher support: cache a one-time token + the fully
        # rendered script, so /devices/<id>/launcher-script can serve it
        # later to a PowerShell subprocess that has no browser session.
        # Skipped quietly if NAS_IP/NAS_SHARE_NAME aren't configured -
        # the QR/.conf flow still works fine without this.
        if NAS_IP and NAS_SHARE_NAME:
            from datetime import datetime, timedelta
            device.launcher_token = secrets.token_urlsafe(32)
            device.launcher_script = windows_launcher.render_ps1(
                device_id=device.id,
                tunnel_name=result["api_name"],
                nas_ip=NAS_IP,
                share_name=NAS_SHARE_NAME,
                wg=result,
            )
            device.launcher_token_expires_at = datetime.utcnow() + timedelta(
                minutes=LAUNCHER_TOKEN_TTL_MINUTES
            )
            db.session.commit()

        session["_pending_conf"] = result["conf"]
        session["_pending_device_id"] = device.id
        return redirect(url_for("device_created", device_id=device.id))

    return render_template("add_device.html")


@app.route("/devices/<int:device_id>/created")
@login_required
def device_created(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    if device.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    conf = session.get("_pending_conf")
    if session.get("_pending_device_id") != device_id:
        conf = None

    if conf is None:
        flash("This setup file was already shown once and cannot be "
              "displayed again. If you need it, revoke this device and "
              "add it again.", "error")
        return redirect(url_for("dashboard"))

    return render_template("device_created.html", device=device, conf=conf)


@app.route("/devices/<int:device_id>/qr")
@login_required
def device_qr(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    if device.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    conf = session.get("_pending_conf")
    if session.get("_pending_device_id") != device_id or conf is None:
        abort(404)

    img = qrcode.make(conf)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/devices/<int:device_id>/launcher.cmd")
@login_required
def device_launcher_cmd(device_id):
    """Downloads the tiny, generic .cmd - safe to leave lying around,
    since it contains no secrets, just a device id and a one-time
    token. Gated the same way as the QR/.conf: must be the owner, and
    the token must still be pending (not yet fetched, not expired)."""
    device = Device.query.filter_by(id=device_id, user_id=current_user.id).first_or_404()
    if not device.launcher_available or not PUBLIC_APP_URL:
        abort(404)

    cmd_text = windows_launcher.render_cmd(
        device_id=device.id,
        token=device.launcher_token,
        portal_url=PUBLIC_APP_URL,
    )
    return Response(
        cmd_text,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=Connect Company Network.cmd"},
    )


@app.route("/devices/<int:device_id>/launcher-script")
def device_launcher_script(device_id):
    """Fetched by the .cmd's own `irm ... | iex` call - a PowerShell
    subprocess on the employee's machine, not a browser, so there's no
    session/cookie to check here. Gated purely by the one-time token
    instead. Deliberately not @login_required: whoever downloaded the
    .cmd is already the person who's supposed to run it, and it's their
    own machine making this request."""
    from datetime import datetime

    device = db.session.get(Device, device_id)
    token = request.args.get("token", "")

    # Guard: secrets.compare_digest requires both args to be str, never None.
    # device.launcher_token may be None after expiry or a race condition
    # (two concurrent fetches), so we normalise to "" first - the bool()
    # check then catches that case before compare_digest is ever called.
    stored_token = device.launcher_token if device is not None else ""
    valid = (
        device is not None
        and bool(stored_token)
        and secrets.compare_digest(stored_token, token)
        and device.launcher_token_expires_at is not None
        and device.launcher_token_expires_at > datetime.utcnow()
    )

    if not valid:
        # Returned as plain text that the .cmd's `iex` will happily just
        # print - keeps the failure visible to the employee instead of
        # `irm` throwing a raw HTTP-error stack trace at them.
        message = "This one-time setup link has expired or was already used. Please re-download the launcher from the portal."
        return Response(f"Write-Host '{message}' -ForegroundColor Red",
                         mimetype="text/plain")

    script = device.launcher_script
    # Single-use: wiped immediately on the first successful fetch, not
    # just left to expire - this is the one place a private key touches
    # disk at all in this app, so it shouldn't sit there longer than it
    # has to.
    device.launcher_token = None
    device.launcher_script = None
    device.launcher_token_expires_at = None
    db.session.commit()

    return Response(script, mimetype="text/plain")


@app.route("/devices/<int:device_id>/revoke", methods=["POST"])
@login_required
def revoke_device(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    if device.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if not device.is_revoked:
        wg_manager.revoke_peer(device.wg_uuid)
        device.revoked_at = datetime.utcnow()
        db.session.commit()
    flash(f"'{device.device_name}' has been disconnected.", "success")
    if device.user_id != current_user.id:
        return redirect(url_for("edit_user", user_id=device.user_id))
    return redirect(url_for("dashboard"))


@app.route("/devices/<int:device_id>/reconnect", methods=["POST"])
@login_required
def reconnect_device(device_id):
    """Re-enables a device that was revoked. The WireGuard keys were
    never deleted (only the on-screen .conf display was one-time) - this
    just flips the same peer back on at OPNsense, so whatever's still
    configured on the device starts working again immediately, no new
    QR code needed. Devices auto-revoked by an admin disabling the
    whole account aren't offered here - those come back only if the
    admin re-enables the account."""
    device = db.session.get(Device, device_id) or abort(404)
    if device.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if device.is_revoked and not device.auto_revoked:
        wg_manager.enable_peer(device.wg_uuid)
        device.revoked_at = None
        db.session.commit()
        flash(f"'{device.device_name}' has been reconnected.", "success")
    if device.user_id != current_user.id:
        return redirect(url_for("edit_user", user_id=device.user_id))
    return redirect(url_for("dashboard"))


@app.route("/devices/<int:device_id>/delete", methods=["POST"])
@login_required
def delete_device(device_id):
    """Admin-only: permanently removes a device's WireGuard peer and its
    record, rather than just disconnecting it. Employees use Revoke/
    Reconnect for their own devices; this is for an admin cleaning up
    devices that are gone for good (lost/replaced hardware, offboarding
    a single device without removing the whole employee)."""
    admin_required()
    device = db.session.get(Device, device_id) or abort(404)
    owner_id = device.user_id
    try:
        wg_manager.delete_peer(device.wg_uuid)
    except wg_manager.WgApiError as e:
        flash(f"Could not remove VPN peer: {e}", "error")
        return redirect(url_for("edit_user", user_id=owner_id))

    device_name = device.device_name
    db.session.delete(device)
    db.session.commit()
    flash(f"Deleted device '{device_name}'.", "success")
    return redirect(url_for("edit_user", user_id=owner_id))


@app.route("/admin/users/<int:user_id>/devices/add", methods=["POST"])
@login_required
def admin_add_device(user_id):
    """Admin action: creates a new device/VPN peer on behalf of an
    employee. Reuses the same one-time reveal page (device_created,
    now permission-relaxed above to allow admin access) rather than a
    separate template."""
    admin_required()
    user = db.session.get(User, user_id) or abort(404)

    device_name = request.form.get("device_name", "").strip()
    if not device_name:
        flash("Please name this device (e.g. 'iPhone', 'Work Laptop').", "error")
        return redirect(url_for("edit_user", user_id=user.id))

    local_part = user.email.split("@")[0]
    peer_display_name = f"{local_part}_{device_name}"
    try:
        result = wg_manager.create_peer(peer_display_name)
    except wg_manager.WgApiError as e:
        flash(f"Could not create VPN access: {e}", "error")
        return redirect(url_for("edit_user", user_id=user.id))

    device = Device(
        user_id=user.id,
        device_name=device_name,
        wg_uuid=result["uuid"],
        wg_api_name=result["api_name"],
        wg_address=result["address"],
    )
    db.session.add(device)
    db.session.commit()

    if NAS_IP and NAS_SHARE_NAME:
        device.launcher_token = secrets.token_urlsafe(32)
        device.launcher_script = windows_launcher.render_ps1(
            device_id=device.id,
            tunnel_name=result["api_name"],
            nas_ip=NAS_IP,
            share_name=NAS_SHARE_NAME,
            wg=result,
        )
        device.launcher_token_expires_at = datetime.utcnow() + timedelta(
            minutes=LAUNCHER_TOKEN_TTL_MINUTES
        )
        db.session.commit()

    session["_pending_conf"] = result["conf"]
    session["_pending_device_id"] = device.id
    return redirect(url_for("device_created", device_id=device.id))


# ------------------------------------------------------------- admin UI ----

def admin_required():
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


@app.route("/admin")
@login_required
def admin_panel():
    admin_required()
    users = User.query.order_by(User.email).all()
    return render_template("admin.html", users=users)


@app.route("/admin/users/new")
@login_required
def new_employee_page():
    admin_required()
    return render_template("add_user.html")


@app.route("/admin/users/add", methods=["POST"])
@login_required
def admin_add_user():
    """Lets an admin pre-create an account for someone before they've
    ever logged in. Provisions WorkOS, local DB, Synology NAS, and emails
    the user their temporary NAS credentials."""
    admin_required()

    email = request.form.get("email", "").strip().lower()
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    make_admin = request.form.get("is_admin") == "on"

    # 1. Input Validation
    if not email or "@" not in email:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("admin_panel"))

    if User.query.filter_by(email=email).first():
        flash(f"{email} already has an account.", "error")
        return redirect(url_for("admin_panel"))

    # 2. WorkOS Pre-Creation
    try:
        workos_user_id = workos_auth.create_user(email, first_name, last_name)
    except workos_auth.AuthKitError as e:
        workos_user_id = None
        flash(f"Added locally, but WorkOS rejected the pre-creation: {e}", "error")

    # 3. Create Local DB Record
    user = User(
        email=email,
        is_admin=make_admin,
        workos_user_id=workos_user_id,
        first_name=first_name or None,
        last_name=last_name or None,
    )
    db.session.add(user)
    db.session.commit()

    # 4. Provision Synology NAS Account & Dispatch Welcome Email
    if SYNOLOGY_ENABLED:
        dsm_group = synology_manager.DSM_ADMIN_GROUP if make_admin else synology_manager.DSM_SHARE_GROUP
        dsm_username = re.sub(r"[^a-zA-Z0-9_-]", "_", email.split("@")[0])[:32]
        try:
            if not synology_manager.user_exists(dsm_username):
                nas_password = synology_manager.create_user(
                    username=dsm_username,
                    email=email,
                    first_name=first_name or None,
                    last_name=last_name or None,
                    group=dsm_group,
                )
                user.dsm_username = dsm_username

                # Setup single-use reveal token (15 min TTL)
                user.dsm_password_token = secrets.token_urlsafe(32)
                user.dsm_temp_password = nas_password
                user.dsm_password_expires_at = datetime.utcnow() + timedelta(minutes=15)
                user.dsm_must_change_password = True
                db.session.commit()
                flash(f"DSM account '{dsm_username}' created on the NAS.", "success")

                # Send welcome email containing generated credentials
                try:
                    send_welcome_email(
                        recipient_email=email,
                        username=dsm_username,
                        passphrase=nas_password,
                        first_name=first_name,
                        last_name=last_name
                    )
                    flash("Welcome email sent to user with credentials.", "info")
                except Exception as mail_err:
                    print(f"[app] Failed to send email to {email}: {mail_err}")
                    flash(f"NAS account created, but email failed: {mail_err}", "warning")

        except synology_manager.DsmApiError as e:
            flash(f"Portal account created, but NAS account failed: {e}", "error")

    return redirect(url_for("admin_user_created", user_id=user.id))
@app.route("/admin/users/<int:user_id>/created")
@login_required
def admin_user_created(user_id):
    admin_required()
    user = db.session.get(User, user_id) or abort(404)
    from datetime import datetime

    temp_password = None
    if (
        user.dsm_temp_password
        and user.dsm_password_expires_at
        and user.dsm_password_expires_at > datetime.utcnow()
    ):
        temp_password = user.dsm_temp_password
        # Single-use: wiped immediately after being rendered once
        user.dsm_temp_password = None
        user.dsm_password_token = None
        user.dsm_password_expires_at = None
        db.session.commit()

    return render_template("admin_user_created.html", user=user, temp_password=temp_password)


@app.route("/admin/users/<int:user_id>/reset-dsm-password", methods=["POST"])
@login_required
def admin_reset_dsm_password(user_id):
    """Admin action: generates a fresh random NAS password for an
    employee and forces them to set their own on next login - reuses
    the same reveal-once page and dsm_must_change_password flag as the
    account-creation flow."""
    admin_required()
    user = db.session.get(User, user_id) or abort(404)

    if not SYNOLOGY_ENABLED or not user.dsm_username:
        flash("This user doesn't have a NAS account.", "error")
        return redirect(url_for("edit_user", user_id=user.id))

    try:
        new_password = synology_manager.reset_password(user.dsm_username)
    except synology_manager.DsmApiError as e:
        flash(f"Could not reset NAS password: {e}", "error")
        return redirect(url_for("edit_user", user_id=user.id))

    user.dsm_password_token = secrets.token_urlsafe(32)
    user.dsm_temp_password = new_password
    user.dsm_password_expires_at = datetime.utcnow() + timedelta(minutes=15)
    user.dsm_must_change_password = True
    db.session.commit()

    flash(f"NAS password reset for {user.email}. They'll be asked to set their own on next login.", "success")
    return redirect(url_for("admin_user_created", user_id=user.id))


@app.route("/account/change-dsm-password", methods=["GET", "POST"])
@login_required
def change_dsm_password():
    if not SYNOLOGY_ENABLED or not current_user.dsm_username:
        flash("NAS account management is disabled for your user.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not new_password:
            flash("Password is required.", "error")
            return render_template("change_dsm_password.html")

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("change_dsm_password.html")

        description = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()

        try:
            synology_manager.update_password(
                current_user.dsm_username, new_password, description=description
            )
            # Clear the temp password flag so this forced-change prompt
            # doesn't fire again on the next login.
            current_user.dsm_temp_password = None
            current_user.dsm_password_token = None
            current_user.dsm_password_expires_at = None
            current_user.dsm_must_change_password = False
            db.session.commit()
            flash("Your NAS password has been updated successfully.", "success")
            return redirect(url_for("dashboard"))
        except synology_manager.PasswordPolicyError as e:
            flash(str(e), "error")
        except synology_manager.DsmApiError as e:
            flash(f"Could not update NAS password: {e}", "error")

    return render_template("change_dsm_password.html")

@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def admin_toggle_user(user_id):
    admin_required()
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You can't disable your own account.", "error")
        return redirect(url_for("admin_panel"))

    from datetime import datetime

    user.disabled = not user.disabled

    if user.disabled:
        for device in user.devices:
            if not device.is_revoked:
                try:
                    wg_manager.revoke_peer(device.wg_uuid)
                except wg_manager.WgApiError:
                    pass
                device.revoked_at = datetime.utcnow()
                device.auto_revoked = True
    else:
        for device in user.devices:
            if device.is_revoked and device.auto_revoked:
                try:
                    wg_manager.enable_peer(device.wg_uuid)
                except wg_manager.WgApiError:
                    pass
                device.revoked_at = None
                device.auto_revoked = False

    db.session.commit()
    flash(f"{'Disabled' if user.disabled else 'Re-enabled'} {user.email}.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/<int:user_id>/toggle_admin", methods=["POST"])
@login_required
def admin_toggle_admin(user_id):
    admin_required()
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You can't change your own admin status.", "error")
        return redirect(url_for("admin_panel"))

    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{'Granted' if user.is_admin else 'Removed'} admin access for {user.email}.",
          "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    """The employee detail/edit page: correct an email typo, flip admin
    or disabled status from one place instead of the quick-toggle
    buttons, and see/manage their devices without leaving the page."""
    admin_required()
    user = db.session.get(User, user_id) or abort(404)

    if request.method == "POST":
        new_email = request.form.get("email", "").strip().lower()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        if not new_email or "@" not in new_email:
            flash("Enter a valid email address.", "error")
            return render_template("edit_user.html", user=user)

        if new_email != user.email and User.query.filter_by(email=new_email).first():
            flash(f"{new_email} is already in use by another account.", "error")
            return render_template("edit_user.html", user=user)

        user.email = new_email
        user.first_name = first_name or None
        user.last_name = last_name or None
        if user.id != current_user.id:
            user.is_admin = request.form.get("is_admin") == "on"

            was_disabled = user.disabled
            now_disabled = request.form.get("disabled") == "on"
            user.disabled = now_disabled

            if now_disabled and not was_disabled:
                from datetime import datetime
                for device in user.devices:
                    if not device.is_revoked:
                        try:
                            wg_manager.revoke_peer(device.wg_uuid)
                        except wg_manager.WgApiError:
                            pass
                        device.revoked_at = datetime.utcnow()
                        device.auto_revoked = True
            elif was_disabled and not now_disabled:
                for device in user.devices:
                    if device.is_revoked and device.auto_revoked:
                        try:
                            wg_manager.enable_peer(device.wg_uuid)
                        except wg_manager.WgApiError:
                            pass
                        device.revoked_at = None
                        device.auto_revoked = False

        db.session.commit()
        flash(f"Saved changes for {user.email}.", "success")
        return redirect(url_for("admin_panel"))

    return render_template("edit_user.html", user=user)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    """Permanently removes the employee: revokes and deletes every
    WireGuard peer they have, deletes the account on WorkOS's side (so
    they can't even reach the login page again), then removes the local
    record. Unlike Disable, this cannot be undone - there's no
    "re-enable" from here."""
    admin_required()
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin_panel"))

    for device in list(user.devices):
        try:
            wg_manager.delete_peer(device.wg_uuid)
        except wg_manager.WgApiError:
            pass
        db.session.delete(device)

    try:
        workos_auth.delete_user(user.workos_user_id)
    except workos_auth.AuthKitError as e:
        flash(f"Removed locally, but WorkOS deletion failed: {e}", "error")

    # Delete from NAS first - if this fails, we still remove the portal
    # record (a ghost NAS account is recoverable; a portal record with no
    # NAS account is a confused state that's harder to reason about), but
    # critically we do NOT commit the portal deletion until after the NAS
    # call, so if the NAS call raises an exception we haven't lost the
    # portal record yet either.
    if SYNOLOGY_ENABLED and user.dsm_username:
        try:
            synology_manager.delete_user(user.dsm_username)
        except synology_manager.DsmApiError as e:
            flash(f"NAS account deletion failed: {e} — removing from portal anyway.", "error")

    email = user.email
    db.session.delete(user)
    db.session.commit()
    flash(f"Deleted {email} and all of their devices.", "success")
    return redirect(url_for("admin_panel"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="127.0.0.1", port=5000, debug=True)