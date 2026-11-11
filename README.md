# Shesa Portal (Django backend)

Backend for the Shesa IT portal: VPN device provisioning (WireGuard via OPNsense),
NAS account provisioning (Synology DSM), leave management, directory, notifications and audit log.
Exposed as a JSON API and served together with the static frontend (`frontend/`) on the same origin.

## Stack
- Django 6.1 (5.x or later), PostgreSQL (latest), django-allauth (OpenID Connect, e.g. Authentik)
- gunicorn + whitenoise, Docker + docker-compose

## Local development
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in values; set USE_SSO=false for a local dev user
export DJANGO_SETTINGS_MODULE=config.settings.development
python manage.py init_db        # migrations + default roles/permissions
python manage.py seed_data      # roles + Sites domain
python manage.py runserver
```
PostgreSQL must be reachable with the `DB_*` variables.

## Production (Docker)
```bash
cp .env.example .env            # DJANGO_SECRET_KEY, DB_PASSWORD, OIDC_*, OPNSENSE_*, ...
docker compose up -d --build
```

## Sign-in (OIDC via Authentik)
1. In Authentik create an OAuth2/OIDC provider + application. Enable MFA in Authentik's flow; MFA is enforced by the IdP, not by Django.
2. Redirect URI: `{PUBLIC_APP_URL}/accounts/oidc/authentik/login/callback/`
3. Put client id/secret and `OIDC_SERVER_URL` (`https://<authentik>/application/o/<slug>/`) in `.env`.
4. `GET /login` starts the flow. The first user to sign in becomes admin; everyone else is created on first sign-in, matched by email to any pre-created account.

## Migrating from the old SQLite portal
```bash
python manage.py migrate
python manage.py import_sqlite /path/to/portal.db            # dry run: row counts only
python manage.py import_sqlite /path/to/portal.db --commit   # copies data in one transaction
```
The target tables must be empty. Primary keys are kept, PostgreSQL sequences are reset, and imported users are linked to their OIDC identity on their first sign-in.
Users keep their names and status. Passwords do not exist in either system.

## API overview (all JSON, session-authenticated)
| Area | Endpoints |
|---|---|
| Auth | `GET /login`, `POST /logout`, `GET/PATCH /api/me/`, `POST /api/me/dsm-password` |
| Devices | `GET /api/devices/`, `POST /api/devices/create`, `POST /api/devices/<id>/revoke|reconnect|delete`, `GET /api/devices/<id>/launcher.cmd` |
| Leave | `GET /api/pto/balances/`, `GET|POST /api/pto/requests/…`, `POST /api/pto/requests/<id>/approve|reject|cancel` |
| Core | `GET /api/dashboard/`, `GET /api/directory/?q=`, `GET /api/departments/`, `GET /api/notifications/` |
| Admin | `/api/admin/users/…`, `/api/admin/users/<id>/leave-balances`, `/api/admin/audit-logs/` |

Device creation returns the WireGuard config and QR code once. Nothing stores the config afterwards.
Admin user creation returns the temporary NAS password once and does not persist it.

## Frontend (`frontend/`)
- Served by Django from the same origin as the API (`apps/common/pages.py`). `/` redirects to the dashboard.
- Sign-in page: `GET /login` serves `frontend/login.html` to anonymous visitors (signed-in users go to the dashboard).
  The button starts SSO at the URL from `GET /api/auth/config/`. `?next=` is accepted only for same-site paths.
  SSO failures return to `/login?error=sso`. Signing out returns to `/login?signedout=1`.
- HTML pages require a signed-in user; admin pages also require `is_admin` (server-side). Assets are public.
- A user whose NAS password is temporary is redirected to `force_password_change.html`, and every API call except
  `/api/me/`, `/api/me/dsm-password`, `/api/csrf/` and `/logout` returns `403` with `code: password_change_required`
  (`ForcedPasswordMiddleware`).
- The browser keeps no business data. `store.js` loads the session state from the API, `api.js` is the only fetch wrapper.
- Vendored libraries: `lucide` 0.383.0 (UMD), FullCalendar 6.1.15 (global bundle and the Italian locale).
- Disabled screens: Calendar, Departments (employee) and the leave/onboarding blocks on the dashboard. They are
  commented out in `layout.js` (`NAV_ITEMS`, `PAGE_TO_NAV`) and `index.html`. Uncomment them to enable.
- One-time values (new device config and QR, temporary NAS password) are passed to the next page through
  `sessionStorage` and removed when displayed. A refresh after that shows "no longer available".

## Not included
- Automated test suite (planned later).
- Browser-level testing: the endpoints and page routing were verified with Django's test client and a
  static check of every API path and file reference. Run the pages in a browser before release.
- Removing the Authentik account on user delete: the API reports this; it must be done in Authentik.

## Local Authentik (identity server for testing)

`docker-compose.authentik.yml` runs Authentik next to the portal. The blueprint in
`authentik/blueprints/shesa-portal.yaml` creates the OIDC provider and the `shesa` application automatically.

**1. Map the identity server name (once, on Windows and in WSL):**

Windows: open Notepad as administrator, edit `C:\Windows\System32\drivers\etc\hosts`, add:

    127.0.0.1 sso.shesa.local

WSL/Ubuntu: `echo "127.0.0.1 sso.shesa.local" | sudo tee -a /etc/hosts`

**2. Fill in `.env`** from `.env.example`, including the generated secrets and the `AUTHENTIK_*` values.
`OIDC_SERVER_URL` must be `http://sso.shesa.local:9000/application/o/shesa` (no trailing slash). Set `USE_SSO=true` as well, otherwise the portal skips sign-in.

**3. Start the stack:**

    sudo docker compose -f docker-compose.yml -f docker-compose.authentik.yml up -d --build --force-recreate

**4. Create the first employee in Authentik:** open `http://sso.shesa.local:9000/if/admin/`,
sign in as `akadmin` with `AUTHENTIK_BOOTSTRAP_PASSWORD`. Under Directory → Users, create a user with an
email address and set a password. Check System → Blueprints: "Shesa Portal - OIDC sign-in" should show as successful.

**5. Sign in to the portal:** open `http://localhost:8000/login`, click the sign-in button, and sign in with that user.
The first user to sign in becomes the portal admin.

**Production:** run Authentik behind HTTPS with a real domain, set `AUTHENTIK_HOST`, `OIDC_SERVER_URL`,
`OIDC_REDIRECT_URI` and `PUBLIC_APP_URL` to that domain, pin `AUTHENTIK_IMAGE` to a release, and enable MFA in
Authentik's authentication flow. The blueprint's `localhost` redirect URIs must then be removed.