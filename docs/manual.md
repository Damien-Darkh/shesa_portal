# SHESA Portal: Complete Manual

This manual covers everything needed to install, deploy, migrate, operate, modify and use the SHESA Portal.

Contents:

1. What the portal is
2. Architecture overview
3. Requirements
4. Choosing the right architecture
5. Preparing the configuration (`.env`)
6. Deployment from GitHub (Linux, Windows/WSL, macOS, Synology, QNAP)
7. Local identity server (Authentik) for testing
8. Migrating to another host
9. Operations: administration commands, backups, updates
10. Modifying the portal
11. User guide
12. Security checklist
13. Troubleshooting
14. Appendix: environment variable reference, project layout, API overview

---

## 1. What the portal is

The SHESA Portal is an internal web application for the company. It provides:

- **Sign-in** through a single sign-on provider (Authentik, OpenID Connect). Passwords are never stored in the portal.
- **Employee profiles** with job details, contact details, photo and a public profile for the company website.
- **Directory** of active colleagues, filterable by department.
- **VPN device management**: each employee can create WireGuard VPN devices (OPNsense) and receive a one-time setup file for Windows, macOS or Linux.
- **NAS accounts**: a Synology NAS user is created together with the employee account, using the same password.
- **Leave management** (optional, feature flag): leave requests, approvals, balances and a calendar.
- **Departments** with hierarchy, manager and members.
- **Notifications** and an **audit log** of administrative actions.
- **Company website synchronisation** (Sanity CMS): employee profiles published on the public website.

The portal is a Django 6.1 backend (Python 3.13) with PostgreSQL 17 as its database. The frontend is plain HTML, CSS and JavaScript served by Django from the same origin.

---

## 2. Architecture overview

```
                 +-------------------+
   Browser ----> |  web (gunicorn)   | ----> Authentik (SSO, OIDC)
                 |  Django + static  | ----> OPNsense (WireGuard API)
                 +---------+---------+ ----> Synology DSM (NAS API)
                           |           ----> Sanity (website content)
                           |           ----> SMTP (welcome e-mail)
                 +---------v---------+
                 |  postgres 17      |
                 +-------------------+
```

Containers (from `docker-compose.yml`):

| Service | Image | Purpose |
| --- | --- | --- |
| `postgres` | `postgres:17-alpine` | Application database |
| `web` | built from `Dockerfile` | Django app served by gunicorn on port 8000 |

Optional (from `docker-compose.authentik.yml`, for testing): `authentik-server`, `authentik-worker`, `authentik-postgres`, `authentik-redis`.

The `web` container:

- runs `python manage.py init_db` at start (applies migrations and creates default roles),
- then starts gunicorn with `gunicorn.conf.py` (3 workers, 4 threads, port 8000),
- runs as a non-root user (`portal`, UID 10001),
- serves the static frontend through WhiteNoise.

Ports published on the host are bound to `127.0.0.1` by default. A reverse proxy (HTTPS) is required for real use. See the security checklist.

---

## 3. Requirements

### 3.1 Software

- Docker Engine 24 or newer with the Compose plugin (`docker compose`, not the old `docker-compose`).
- Git (to obtain the project), or a copy of the project folder.
- A text editor for `.env`.
- Optional: a domain name and a reverse proxy with a valid TLS certificate (Let's Encrypt or a company certificate).

### 3.2 External services

| Service | Required | Notes |
| --- | --- | --- |
| Authentik (or any OIDC provider) | Yes (unless `USE_SSO=false` for development) | Sign-in and MFA |
| OPNsense with WireGuard API | Only for VPN features | `WIREGUARD_BACKEND=mock` runs without it |
| Synology DSM | Only for NAS accounts | Leave `DSM_URL` empty to disable |
| Sanity project | Only for website sync | `SANITY_SYNC_ENABLED=false` disables it |
| SMTP mail server | Only for welcome e-mails | Leave `SMTP_SERVER` empty to disable |

### 3.3 Hardware

- Minimum: 2 CPU cores, 2 GB RAM, 10 GB free disk for a small team.
- Recommended: 4 cores, 4 GB RAM, SSD storage.

---

## 4. Choosing the right architecture

The portal image is built for the processor of the machine running it. Find your architecture first.

### 4.1 How to find the architecture

| Operating system | Command | Result meaning |
| --- | --- | --- |
| Linux | `uname -m` | `x86_64` = 64-bit Intel/AMD; `aarch64` = 64-bit ARM; `armv7l` = 32-bit ARM; `i686` / `i386` = 32-bit x86 |
| macOS | `uname -m` | `arm64` = Apple Silicon (M1, M2, M3, M4 ...); `x86_64` = Intel Mac |
| Windows (PowerShell) | `$env:PROCESSOR_ARCHITECTURE` | `AMD64` = 64-bit Intel/AMD; `ARM64` = Windows on ARM |
| Synology / QNAP (SSH) | `uname -m` | See the table below for models |

### 4.2 Support matrix

| Architecture | Typical hardware | Status | Notes |
| --- | --- | --- | --- |
| **x86_64 (amd64)** | Intel/AMD PCs, servers, most NAS (Synology Plus/XS, QNAP Intel models) | **Fully supported** | Recommended default |
| **aarch64 (arm64)** | Apple Silicon Macs, Raspberry Pi 4/5 with 64-bit OS, Synology/QNAP ARMv8 models, Windows on ARM | **Fully supported** | Build for `linux/arm64` |
| **armv7 (32-bit ARM)** | Older Raspberry Pi (2/3 with 32-bit OS), older ARM NAS (e.g. Synology `armv7` DS models, QNAP TS-x31 ARMv7) | **Limited (best effort)** | Some Python packages (`cryptography`, `psycopg`, `Pillow`) have no prebuilt wheels for ARMv7, so builds are very slow and may fail. Use an external PostgreSQL server and expect to tune the build. Not recommended for production. |
| **32-bit x86 (i386 / i686)** | Very old PCs | **Not supported** | Docker and the current base images do not run on 32-bit x86. Install a 64-bit operating system on the machine. |
| **32-bit OS on 64-bit hardware** | Any | **Not supported** | Install a 64-bit OS on capable hardware. |

Rule of thumb: if the hardware is 64-bit capable, install a **64-bit** operating system and Docker. Only use ARMv7 when the device cannot run 64-bit.

### 4.3 Platform selection in Docker

Most images are multi-architecture, so Docker chooses the right one automatically. To build explicitly for a specific architecture:

```bash
docker buildx build --platform linux/amd64 -t shesa-portal:local .
docker buildx build --platform linux/arm64 -t shesa-portal:local .
docker buildx build --platform linux/arm/v7 -t shesa-portal:local .   # limited, see 4.2
```

Check that the base images exist for your platform:

```bash
docker manifest inspect python:3.13-slim | grep -E '"architecture"'
docker manifest inspect postgres:17-alpine | grep -E '"architecture"'
```

If `postgres:17-alpine` does not list `arm/v7` on your system, run PostgreSQL on another machine and point `DB_HOST` to it (see section 5.4).

---

## 5. Preparing the configuration

### 5.1 Create `.env`

From the project root:

```bash
cp .env.example .env
```

Never commit `.env` to version control. It contains secrets.

### 5.2 Generate secrets

Use Python (available on every platform with Docker and Python installed, or run it inside the container):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Generate separate values for each of these:

- `DJANGO_SECRET_KEY`
- `OIDC_CLIENT_SECRET`
- `AUTHENTIK_SECRET_KEY`
- `AUTHENTIK_BOOTSTRAP_PASSWORD` (a strong password)
- `AUTHENTIK_PG_PASS` and `DB_PASSWORD` (strong passwords; letters, digits and symbols)

**Important:** the `.env.example` shipped with this project contains sample values that look like real secrets. Replace every secret before any real deployment, and rotate any value that has been shared, copied or committed.

### 5.3 Core settings

| Variable | Example | Meaning |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` | Use production settings |
| `DJANGO_SECRET_KEY` | (generated) | Required in production |
| `DJANGO_DEBUG` | `false` | Never `true` in production |
| `ALLOWED_HOSTS` | `portal.company.it,localhost` | Hostnames the site answers to |
| `PUBLIC_APP_URL` | `https://portal.company.it` | Public address; used in links and e-mails |
| `SECURE_SSL_REDIRECT` | `true` behind HTTPS, `false` for local HTTP | Redirects HTTP to HTTPS |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### 5.4 Database settings

| Variable | Example | Meaning |
| --- | --- | --- |
| `DB_NAME` | `shesa_portal` | Database name |
| `DB_USER` | `shesa` | Database user |
| `DB_PASSWORD` | (strong password) | Database password |
| `DB_HOST` | `postgres` (Docker) or `192.168.1.20` (external) | Compose overrides this to `postgres` automatically |
| `DB_PORT` | `5432` | Database port |

### 5.5 Sign-in settings

| Variable | Example | Meaning |
| --- | --- | --- |
| `USE_SSO` | `true` | `false` only for local development (auto-login as `DEV_USER_EMAIL`) |
| `OIDC_PROVIDER_ID` | `authentik` | Provider identifier |
| `OIDC_PROVIDER_NAME` | `SHESA SSO` | Name shown on the sign-in button |
| `OIDC_CLIENT_ID` | `shesa-portal-client` | Must match the provider |
| `OIDC_CLIENT_SECRET` | (generated) | Must match the provider |
| `OIDC_SERVER_URL` | `https://sso.company.it/application/o/shesa/` | Authentik application URL (trailing slash) |
| `OIDC_REDIRECT_URI` | `https://portal.company.it/accounts/oidc/authentik/login/callback/` | Must match the provider exactly |
| `LOGIN_REDIRECT_URL` | `/index.html` | Page after sign-in |

### 5.6 Identity provider (Authentik) settings

Used only when running the Authentik overlay (section 11) or when the portal creates Authentik accounts.

| Variable | Meaning |
| --- | --- |
| `AUTHENTIK_SECRET_KEY` | Authentik secret (generated) |
| `AUTHENTIK_PG_PASS` | Authentik database password |
| `AUTHENTIK_BOOTSTRAP_PASSWORD` | Initial password of the `akadmin` account |
| `AUTHENTIK_BOOTSTRAP_EMAIL` | E-mail of the initial admin |
| `AUTHENTIK_IMAGE` | Pinned Authentik release, e.g. `ghcr.io/goauthentik/server:2024.12.5` |
| `AUTHENTIK_API_URL` | Address the portal uses to reach Authentik's API |
| `AUTHENTIK_API_TOKEN` | API token created in Authentik for the portal |
| `AUTHENTIK_DEFAULT_GROUP` / `AUTHENTIK_ADMIN_GROUP` | Groups assigned to new staff and admin accounts |

### 5.7 VPN settings (OPNsense WireGuard)

| Variable | Example | Meaning |
| --- | --- | --- |
| `WIREGUARD_BACKEND` | `opnsense` (production) or `mock` (testing) | `mock` simulates peers without a firewall |
| `OPNSENSE_URL` | `https://fw.company.it` | OPNsense address |
| `OPNSENSE_API_KEY` / `OPNSENSE_API_SECRET` | (from OPNsense user) | API credentials |
| `WG_INSTANCE_UUID` | (UUID of the WireGuard server) | Found in OPNsense WireGuard settings |
| `WG_ENDPOINT` / `WG_PORT` | `vpn.company.it` / `51820` | Public endpoint clients connect to |
| `WG_SUBNET` | `10.10.10.0/24` | Address pool for devices |
| `WG_DNS` | `192.168.11.254` | DNS pushed to clients |
| `ALLOWED_IPS_CLIENT` | `192.168.11.0/24,10.10.10.0/24` | Networks routed through the VPN |
| `VERIFY_SSL` | `true` | Verify the OPNsense certificate in production |
| `LAUNCHER_TOKEN_TTL_MINUTES` | `60` | How long a one-time setup file stays downloadable |

### 5.8 NAS settings (Synology DSM)

| Variable | Example | Meaning |
| --- | --- | --- |
| `DSM_URL` | `https://nas.company.it:5001` | DSM address (empty disables NAS features) |
| `DSM_ADMIN_USER` / `DSM_ADMIN_PASS` | (admin account) | Account that manages users |
| `DSM_SHARE_GROUP` | `staff` | Group for staff |
| `DSM_ADMIN_GROUP` | `staff` | Group for administrators |
| `NAS_IP` | `192.168.11.20` | NAS address used in setup files |
| `NAS_SHARE_NAME` | `shared` | Share name (set both NAS settings to enable setup files) |

### 5.9 E-mail settings

| Variable | Example | Meaning |
| --- | --- | --- |
| `SMTP_SERVER` | `smtp.company.it` | Leave empty to disable welcome e-mails |
| `SMTP_PORT` | `465` (SSL) or `587` (STARTTLS) | Port |
| `SMTP_USER` / `SMTP_PASSWORD` | (mail account) | Credentials |
| `SENDER_EMAIL` | `it@company.it` | From address |
| `COMPANY_NAME` | `SHESA S.r.l.` | Used in e-mails and PDFs |

### 5.10 Website synchronisation (Sanity)

| Variable | Example | Meaning |
| --- | --- | --- |
| `SANITY_SYNC_ENABLED` | `true` / `false` | Turns website sync on or off |
| `SANITY_PROJECT_ID` | (Sanity project id) | Project |
| `SANITY_DATASET` | `production` | Dataset |
| `SANITY_API_VERSION` | `2026-01-01` | API version |
| `SANITY_WRITE_TOKEN` | (write-scoped token) | Token with write rights; keep secret |
| `SANITY_SYNC_TIME` | `03:00` | Daily synchronisation time |
| `SANITY_RETRY_INTERVAL_MINUTES` | `5` | Retry cadence for failed pushes |
| `SANITY_MAX_ATTEMPTS` | `20` | Attempts before HR is alerted |

### 5.11 Feature flags and leave defaults

| Variable | Example | Meaning |
| --- | --- | --- |
| `LEAVE_MANAGEMENT_ENABLED` | `true` / `false` | Shows leave pages, calendar, approvals and API |
| `LEAVE_DEFAULT_VACATION_DAYS` | `26` | Initial yearly allowance |
| `LEAVE_DEFAULT_SICK_DAYS` | `10` | Initial sick allowance |
| `LEAVE_DEFAULT_PERSONAL_DAYS` | `4` | Initial personal allowance |

### 5.12 Example for a local test (no SSO, mock VPN)

```env
DJANGO_SETTINGS_MODULE=config.settings.development
DJANGO_DEBUG=true
DJANGO_SECRET_KEY=change-me-local-only
ALLOWED_HOSTS=localhost,127.0.0.1
PUBLIC_APP_URL=http://localhost:8000
SECURE_SSL_REDIRECT=false
DB_NAME=shesa_portal
DB_USER=shesa
DB_PASSWORD=local-db-password
USE_SSO=false
DEV_USER_EMAIL=developer@localhost
WIREGUARD_BACKEND=mock
SANITY_SYNC_ENABLED=false
LEAVE_MANAGEMENT_ENABLED=true
```

---

## 6. Deployment from GitHub (Linux, Windows/WSL, macOS, Synology, QNAP)

Images are built by GitHub Actions and pushed to GitHub Container Registry (GHCR). Servers only pull them. No source build happens on the server.

### 6.1 One-time setup in GitHub

- Settings → Environments → create `production`. Add required reviewers if you want an approval step before deploy.
- Settings → Secrets and variables → Actions, add:
  - `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT` (optional), `DEPLOY_PATH` (the folder on the server that contains `docker-compose.yml` and `.env`)
  - `DEPLOY_SSH_KEY`: a private key whose public key is in `~/.ssh/authorized_keys` on the server
  - `GHCR_TOKEN`: a personal access token with `read:packages` (lets the server pull private images)
- Packages → make `shesa-portal` private (recommended), or public if the code allows it.

### 6.2 Server prerequisites

Docker Engine and the Compose plugin (see sections 6.1 to 10 for each platform), SSH access for the deploy user, and a `.env` file in `DEPLOY_PATH` (copied once, never committed).

### 6.3 First deploy

```bash
cd /opt/shesa-portal            # DEPLOY_PATH
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d postgres
docker compose -f docker-compose.yml -f docker-compose.deploy.yml pull web
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d web
```

### 6.4 Ongoing deploys

Push to `main` (deploys the latest build) or push a tag `v1.2.3` (deploys that release). The workflow builds for `linux/amd64` and `linux/arm64`, so Intel/AMD servers, Raspberry Pi 4/5, Apple Silicon hosts, and ARM64 NAS models all work. ARMv7 is not built; see section 4.2.

### 6.5 Rollback

Edit the image tag in the deploy command to a previous `sha-xxxxxxx` or `v1.x.y` tag and run `up -d web` again. Database migrations are not reversed automatically; restore a backup if a release changed the schema (section 13.2).

---

## 11. Local identity server (Authentik) for testing

Use this to test SSO on a single machine. For production, deploy Authentik behind HTTPS with its own domain (section 11.5).

### 11.1 Hosts entry

The blueprint uses the name `sso.shesa.local`.

- Windows (Notepad as Administrator), edit `C:\Windows\System32\drivers\etc\hosts`, add: `127.0.0.1 sso.shesa.local`
- Linux/macOS/WSL: `echo "127.0.0.1 sso.shesa.local" | sudo tee -a /etc/hosts`

### 11.2 Configure and start

In `.env` set:

```env
USE_SSO=true
OIDC_SERVER_URL=http://sso.shesa.local:9000/application/o/shesa/
OIDC_REDIRECT_URI=http://localhost:8000/accounts/oidc/authentik/login/callback/
AUTHENTIK_HOST=http://sso.shesa.local:9000
AUTHENTIK_SECRET_KEY=(generated)
AUTHENTIK_PG_PASS=(strong)
AUTHENTIK_BOOTSTRAP_PASSWORD=(strong)
AUTHENTIK_API_URL=http://sso.shesa.local:9000
```

Start the full stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.authentik.yml up -d --build --force-recreate
```

### 11.3 Create the first user

1. Open [http://sso.shesa.local:9000/if/admin/](http://sso.shesa.local:9000/if/admin/) and sign in as `akadmin` with `AUTHENTIK_BOOTSTRAP_PASSWORD`.
2. **Directory > Users > Create**: fill in an e-mail and set a password.
3. **System > Blueprints**: check that "Shesa Portal - OIDC sign-in" shows as successful.
4. Open http://localhost:8000/login and sign in with the user. **The first user who signs in becomes the portal administrator.**

### 11.4 Create an API token for the portal

In Authentik: **Directory > Tokens and App passwords > Create**, type "API", user `akadmin` (or a service account). Copy the key into `AUTHENTIK_API_TOKEN` in `.env`, then restart `web`.

### 11.5 Production Authentik

- Run Authentik behind HTTPS on its own domain, for example `sso.company.it`.
- Set `AUTHENTIK_HOST`, `OIDC_SERVER_URL`, `OIDC_REDIRECT_URI` and `PUBLIC_APP_URL` to the real domains.
- Pin `AUTHENTIK_IMAGE` to a specific release and upgrade deliberately.
- Enable MFA in Authentik's authentication flow (the portal does not enforce MFA itself).
- Remove the `localhost` and `127.0.0.1` redirect URIs from the blueprint `authentik/blueprints/shesa-portal.yaml`.
- The blueprint's `authentik-server` port bindings (`127.0.0.1:9000`) must be replaced by your reverse proxy setup.

---

## 12. Migrating to another host

Migration moves four things: the portal database, the Authentik database and media, the `.env` file, and the Docker volumes that hold uploads. Do it in this order. Plan a maintenance window; the old host must stop writing before the dump is taken.

### 12.1 Prepare the new host

Install Docker and the Compose plugin, create the same folder layout, and copy the repository (or let the first GitHub deploy create the images). Do not start the new stack yet.

### 12.2 Freeze the old host

```bash
cd /opt/shesa-portal
docker compose stop web
```

### 12.3 Dump the portal database

```bash
docker compose exec -T postgres pg_dump -U shesa -d shesa_portal -Fc > shesa_portal.dump
```

### 12.4 Dump the Authentik database

```bash
docker compose -f docker-compose.yml -f docker-compose.authentik.yml exec -T authentik-postgres \
  pg_dump -U authentik -d authentik -Fc > authentik.dump
```

### 12.5 Copy Authentik media and certificates

Authentik stores uploaded files and generated certificates in Docker volumes. Export them:

```bash
for v in authentik_media authentik_certs; do
  docker run --rm -v "${v}:/data" -v "$PWD:/backup" alpine \
    tar czf "/backup/${v}.tgz" -C /data .
done
```

### 12.6 Copy the secrets and the dumps

Copy `.env`, `shesa_portal.dump`, `authentik.dump`, and the two `.tgz` files to the new host with `scp` over the internal network. Keep `.env` secret; delete the dumps from both hosts when migration is verified.

### 12.7 Restore on the new host

```bash
cd /opt/shesa-portal
docker compose -f docker-compose.yml -f docker-compose.authentik.yml up -d postgres authentik-postgres
docker compose exec -T postgres pg_restore -U shesa -d shesa_portal --clean --if-exists < shesa_portal.dump
docker compose -f docker-compose.yml -f docker-compose.authentik.yml exec -T authentik-postgres \
  pg_restore -U authentik -d authentik --clean --if-exists < authentik.dump
for v in authentik_media authentik_certs; do
  docker volume create "$v"
  docker run --rm -v "${v}:/data" -v "$PWD:/backup" alpine \
    sh -c "cd /data && tar xzf /backup/${v}.tgz"
done
```

If the restored Authentik database is from a different Authentik release, pin the same `AUTHENTIK_IMAGE` as the old host before starting it.

### 12.8 Start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d web
docker compose -f docker-compose.yml -f docker-compose.authentik.yml up -d authentik-server authentik-worker
```

### 12.9 Cut over

- Point DNS for the portal and the SSO host at the new host (or change the reverse proxy target).
- If the hostnames or URLs changed, update `PUBLIC_APP_URL`, `OIDC_SERVER_URL`, `OIDC_REDIRECT_URI`, and the redirect URIs in the Authentik provider, then restart `web`.
- Sign in with an administrator account and check: employees, devices, leave balances, departments, and one sign-in through Authentik.
- Re-register scheduled jobs on the new host (for example `sanity_retry_pending`, every 5 minutes).

### 12.10 Retire the old host

Keep the old host stopped (not deleted) for a week as a fallback. After that, remove the dumps, revoke the old host's SSH key in GitHub secrets, and delete `.env` copies that are no longer needed.

### 12.11 Verify the restore

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py shell -c "from apps.accounts.models import User; print(User.objects.count())"
```

Compare the user count with the old host before the freeze.

---

## 13. Operations

### 13.1 Administration commands

Run inside the web container:

```bash
docker compose exec web python manage.py <command>
```

| Command | Purpose |
| --- | --- |
| `init_db` | Applies migrations and seeds roles/permissions. Runs automatically at each start. Safe to repeat. |
| `migrate` | Applies migrations only. |
| `seed_rbac` | Creates default roles and permissions (safe to repeat). |
| `seed_data` | Seeds roles and sets the Sites domain from `PUBLIC_APP_URL`. |
| `sanity_backfill [--dry-run] [--refresh] [--limit N]` | Publishes employees to the website (Sanity). `--refresh` updates everyone. |
| `sanity_retry_pending` | Retries failed website pushes. Run every few minutes from cron. |
| `sample_credentials` | Writes a test credential PDF to the working directory (layout checks only). |
| `createsuperuser` | Django admin account for `/admin/` (rarely needed; the SSO admin is the normal route). |
| `shell` | Django shell for inspection. |

Cron example for the retry job (Linux host, every 5 minutes):

```cron
*/5 * * * * cd /opt/shesa-portal && docker compose exec -T web python manage.py sanity_retry_pending >> /var/log/shesa-sanity.log 2>&1
```

On Synology and QNAP, use **Task Scheduler** (DSM) or **Qcenter/Scheduled task** (QTS) to run the same command.

The daily website synchronisation is specified in `docs/sanity-portal-integration.md`. Check that your release provides the `sanity_daily_sync` command (`python manage.py help`) before scheduling it.

Admin pages: `/admin/` (Django admin) is available to Django superusers. The portal's own admin panel is `admin.html` for portal administrators.

### 13.2 Backups

Two things must be backed up: the **database** and the **`.env` file** (secrets).

Database backup:

```bash
mkdir -p /opt/backups
docker compose exec -T postgres pg_dump -U shesa -d shesa_portal -Fc > /opt/backups/shesa_portal_$(date +%F).dump
```

Keep at least 14 daily copies, and one copy off-site. Store `.env` in a password manager or encrypted vault, not beside the dump.

Restore into an empty database:

```bash
docker compose exec -T postgres pg_restore -U shesa -d shesa_portal --clean --if-exists < /opt/backups/shesa_portal_2026-11-01.dump
```

Back up the same four items as in section 12, on a schedule, and test a restore on a spare machine every quarter.

### 13.3 Restore on a new server

1. Install Docker and copy the project.
2. Restore `.env`.
3. Start only PostgreSQL: `docker compose up -d postgres`.
4. Restore the dump (above).
5. Start the portal: `docker compose up -d web`.

### 13.4 Logs

```bash
docker compose logs -f web          # application and gunicorn logs
docker compose logs -f postgres     # database
```

Error references shown to users on error pages (for example `Reference: 3F9A1C2B`) appear in the web log as `Server error <reference>`. Search for that reference to find the traceback.

Audit trail: administrators can read it at `/api/admin/audit-logs/` and in the Django admin (read-only).

### 13.5 Updating the containers

- Base images (`postgres`, `python`): `docker compose pull && docker compose up -d --build`.
- Authentik: change `AUTHENTIK_IMAGE` to the new release, run `docker compose -f docker-compose.yml -f docker-compose.authentik.yml up -d`, and read the Authentik upgrade notes first.

### 13.6 Stopping and starting

```bash
docker compose stop          # stop, keep data
docker compose start         # start again
docker compose down          # remove containers, keep volumes (data is safe)
docker compose down -v       # remove containers AND data (destructive)
```

### 13.7 Health checks

- `curl -I http://127.0.0.1:8000/login` returns `302` or `200`.
- `docker compose ps` shows `postgres` as `healthy`.
- The web log shows no repeated `Server error` lines.

---

## 14. Modifying the portal

This section explains how to change the portal. Keep the changes in a Git branch, test locally (section 5.12), then deploy (section 12.4).

### 14.1 Project layout

```
apps/
  accounts/   users, roles, audit model; login/logout; admin API (admin_views.py, admin_urls.py)
  core/       departments, profiles, notifications, search, dashboard/people API
  devices/    VPN devices (model, services, views); OPNsense/WireGuard integration
  pto/        leave: models, services (rules), views (API)
  common/     utilities, middleware, error pages, rbac.py (permissions), integrations/
    integrations/  OPNsense (wg_manager), Synology (synology_manager), Authentik,
                   Sanity, mailer, PDF, Windows/Linux/macOS setup generators
config/
  settings/   base.py (shared), production.py, development.py, testing.py
  urls.py     URL routing and frontend page guard
frontend/
  *.html      pages
  pages/*.js  page scripts (one per page)
  layout.js   header, navigation, dialogs (shared)
  store.js    in-memory state loaded from the API
  api.js      the only fetch wrapper
  i18n.js     Italian/English translations
  style.css, components.css
docs/         integration design notes
```

### 14.2 Change a text or label

- Visible text is in the HTML page and in the page script.
- For Italian translation, add an exact-match entry to the `IT` object in `frontend/i18n.js`. The key is the English text as written in the HTML. Strings without an entry stay in English.
- Refresh the browser after each change (the static files are cached by WhiteNoise only after `collectstatic`, which the image runs at build; rebuild with `docker compose up -d --build web`).

### 14.3 Change the navigation menu

Edit `frontend/layout.js`:

- `NAV_ITEMS`: the main menu entries (key, label, href, icon from Lucide).
- `CALENDAR_ITEM`, `ADMIN_ITEM`: optional items.
- `PAGE_TO_NAV`: which menu item is highlighted for each page file.

Icons: any name from [https://lucide.dev](https://lucide.dev) (version 0.383.0 is vendored in `frontend/vendor/`).

### 14.4 Add a new page

1. Create `frontend/my_page.html` based on an existing page (for example `directory.html`). Keep the header mount `<header id="site-header"></header>`, the CSS links, the Lucide script, and `<script type="module" src="./pages/my_page.js"></script>`.
2. Create `frontend/pages/my_page.js`:

   ```javascript
   import { ready, dbData, refreshIcons } from '../layout.js';
   import { api } from '../api.js';

   (async () => {
     if (!await ready) return;          // session missing: already redirected to /login
     // your code here
     refreshIcons();
   })();
   ```
3. Add the page to `PAGE_TO_NAV` and, if it needs a menu item, to `NAV_ITEMS` in `layout.js`.
4. Protect admin-only pages: add the file name to `ADMIN_HTML` in `apps/common/pages.py`. Employee pages need no change (any signed-in user).

### 14.5 Add or change an API endpoint

1. Add a view in the relevant app's `views.py` (for example `apps/core/views.py`). Use the helpers from `apps/common/http.py`:
   - `@api_login_required` or `@api_admin_required`,
   - `ok(data)`, `error(status, message)`, `read_json(request)`.
2. Register the route in the app's `urls.py` (or `apps/accounts/admin_urls.py` for `/api/admin/`).
3. Record important actions: `record(request, "ACTION", "resource_type", resource_id, details={...})`.
4. From the frontend, call it with `api('/api/path/', { method: 'POST', body: {...} })` from `frontend/api.js`. Never call `fetch` directly.

Writes (POST, PATCH, DELETE) need the CSRF token; `api.js` sends it automatically.

### 14.6 Add a permission or role

Permissions are defined in `apps/common/rbac.py`:

1. Add a tuple to `PERMISSIONS`: `(name, resource, action, description)`.
2. Add the permission name to the roles in `ROLES`.
3. Run `python manage.py seed_rbac` (or restart `web`, since `init_db` runs it).
4. Check it in a view with `has_permission(request.user, "name")` from `apps/common/http.py`.

Note: `is_admin` users pass every permission check. Role assignment is done per user in the admin panel or through `roles` in the user API.

### 14.7 Change the database (models)

1. Edit the model in `apps/<app>/models.py`. Keep `db_table` names stable.
2. Create a migration:

   ```bash
   docker compose exec web python manage.py makemigrations <app>
   ```

   Review the generated file in `apps/<app>/migrations/`.
3. Apply it: `docker compose up -d --build web` (or `docker compose exec web python manage.py migrate`).
4. Add the new fields to the serializers in the views (the dictionaries returned by the API) and to the frontend page that shows them.
5. Commit the migration file with the model change. Never edit an applied migration; add a new one.

### 14.8 Turn a feature on or off

- **Leave management**: `LEAVE_MANAGEMENT_ENABLED=true|false` in `.env`, then `docker compose up -d web`. The flag controls the API routes, pages and dashboard widgets.
- **Departments page for employees**: the link is not shown in `NAV_ITEMS`; uncomment the entries in `layout.js` and the page routes described in `frontend/departments.html`.
- **Website synchronisation**: `SANITY_SYNC_ENABLED=true|false`.
- **NAS accounts**: leave `DSM_URL` empty to disable NAS creation and password changes.
- **Welcome e-mail**: leave `SMTP_SERVER` empty.
- **VPN**: `WIREGUARD_BACKEND=mock` for testing; `opnsense` for production.

### 14.9 Change the sign-in flow

- Provider settings: `OIDC_*` in `.env` and `SOCIALACCOUNT_PROVIDERS` in `config/settings/base.py`.
- How accounts are created and matched: `apps/accounts/adapters.py` (`SocialAccountAdapter`). The first ever user becomes admin there.
- Disabled accounts are sent to `account_disabled.html` from the same adapter.

### 14.10 Change the NAS, VPN or website integrations

Each integration is a single module in `apps/common/integrations/`:

- `wg_manager.py`: OPNsense WireGuard peers (create, enable, disable, delete).
- `synology_manager.py`: DSM users, groups and passwords. Password policy: `_validate_password_policy`.
- `authentik_manager.py`: Authentik accounts via its REST API.
- `sanity_client.py` (HTTP), `sanity_sync.py` (field mapping, push, retry), `sanity_photo.py` (photos), `sanity_projects.py` (project list cache).
- `mailer.py`: welcome e-mail. `credential_pdf.py`: encrypted PDF.
- `windows_launcher.py`, `unix_launcher.py`: generated setup scripts.

To change a Sanity field, edit `FIELD_MAP` in `sanity_sync.py` and the schema in the Sanity Studio project.

### 14.11 Change the look

- Colours and spacing: CSS variables at the top of `frontend/style.css` (`--primary`, `--accent-light`, etc.).
- Reusable components: `frontend/components.css`.
- Header and flash styles: `LAYOUT_CSS` in `frontend/layout.js`.

### 14.12 Testing a change

- Run the Django checks: `docker compose exec web python manage.py check`.
- Check that migrations are complete: `docker compose exec web python manage.py makemigrations --check --dry-run`.
- Test the pages in a browser (desktop and phone width) for the role you changed (employee and admin).
- Test API errors: the frontend shows the `error` text returned by the API.

Automated tests are not yet part of the project; add tests under `apps/<app>/tests.py` when you add important business rules.

### 14.13 Coding conventions observed in the project

- Python: Django views return JSON through helpers; services hold business rules and run in transactions; integrations never touch views directly.
- JavaScript: one page script per page; shared logic in `layout.js`, `store.js`, `api.js`; no `innerHTML` with unescaped user input (use `esc()`).
- Sensitive values (passwords, WireGuard private keys) are never stored in the database or logged; one-time values pass through `sessionStorage` and are removed on display.

---

## 15. User guide

This section is for employees and administrators.

### 15.1 Signing in

1. Open the portal address (for example `https://portal.company.it`).
2. Click **Sign in with company account**.
3. Enter your company e-mail and password, and complete the second factor if prompted (managed by the sign-in service).
4. You arrive at the **Dashboard**.

If your NAS password is temporary (you were just created or reset by an administrator), the portal first asks you to **set your NAS password**. This is required; the other pages stay locked until you do. The new password must be at least 8 characters, contain upper and lower case letters and a number, and must not contain your name or username. The same password works for the portal (via the sign-in service) and for the NAS.

To sign out, click **Log out** in the header.

### 15.2 Navigation

The header shows: Dashboard, Directory, Calendar (if leave is enabled), Profile, Admin Panel (administrators only), notifications (bell with unread count), your e-mail, and Log out. On phones, the menu opens with the menu button at the top right.

### 15.3 Dashboard

- **Profile card**: your name, job title, identity ID and role.
- **Personal details**: e-mail, phone, office, start date and "About".
- **Notifications**: messages such as leave decisions. Items are marked as read after you have looked at them for two seconds.
- **VPN Devices** (if you have VPN access): see section 15.6.
- **Leave** widgets (if enabled).

### 15.4 Profile

The profile page has these sections:

- **Job details** (read-only): managed by HR. Contact an administrator to change them.
- **Photo**: upload a JPEG, PNG or WebP image of at least 200 × 200 pixels, up to 5 MB. It appears on the company website.
- **Projects**: choose the projects you worked on and press **Save projects**. Only projects published on the website appear in the list.
- **Contact details**: phone, LinkedIn link (must be an https link on linkedin.com), and other e-mail addresses (one per line). Saved immediately and sent to the website.
- **Company website**: tick **Show my profile on the company website** and, the first time, confirm consent. Write a short bio and a full profile (the editor has bold, italic, headings, lists, quotes and links; pasted Markdown is converted). Press **Save website profile**.
- **Interface language**: Italiano or English. Italian is the default.
- **NAS password**: link to change the NAS password at any time.

Your changes are saved in the portal immediately. If the website cannot be updated at that moment, the portal shows "Your changes are saved... will retry automatically" and retries in the background.

To hide your profile from the website, untick the box and save. Only you can publish it again.

### 15.5 Directory

- Lists active colleagues. Type in the search field to filter by name, e-mail or job title.
- Use the department filter to narrow the list.
- Click a person to open their profile.
- Administrators also see disabled accounts in the admin panel.

### 15.6 VPN devices (WireGuard)

**Add a device**

1. Go to **Dashboard > VPN Devices > Add Device** (visible when VPN access is enabled for your account; administrators always have it).
2. Enter a name you will recognise, for example "Work Laptop" or "iPhone", and press **Create VPN Access**.
3. The setup page shows the device configuration **once**:
   - **Step 1**: download the setup file for your operating system (Windows `.cmd`, macOS `.command`, or Linux `.sh`). The file installs WireGuard if needed, imports the tunnel, adds a desktop shortcut to the company NAS, and asks whether to connect now. Files are valid for one hour (configurable) and for one use.
   - **Step 2**: scan the QR code in the WireGuard app ("Add Tunnel" > "Scan QR Code"), for phones or computers.
   - **Step 3**: copy the configuration text for manual setup.

Important: the configuration contains a private key. Do not share it. After you leave the page, the configuration cannot be shown again; if you lost it, disconnect the device and create a new one.

**Windows note**: Windows may show a security prompt. Choose "More info", then "Run anyway". The setup runs as administrator.

**macOS note**: if the `.command` file is blocked, right-click it and choose **Open**. The setup needs Homebrew to install WireGuard tools; if Homebrew is missing, install it from [https://brew.sh](https://brew.sh) and run the file again.

**Linux note**: run the `.sh` file as your normal user (`bash install-nas-signout-cleanup.sh`); it asks for your password when root rights are needed.

**Disconnect and reconnect**

- **Disconnect** removes the device's VPN access immediately. You can **Reconnect** it later.
- Devices disconnected because an administrator disabled the account are restored only when the account is re-enabled and VPN access is granted again.

**Sign-out behaviour of the setup**: the setup installs a small background task that removes NAS sessions and saved NAS passwords when you sign out or shut down, so shared network access does not stay open on a shared computer.

### 15.7 Calendar and leave (when enabled)

**Request leave**

1. Open **Calendar**.
2. Click **Request Leave** (or select dates on the calendar).
3. Choose the type (Vacation, Sick, Personal), start and end dates, and an optional note. Press **Submit request**.

Rules checked by the portal:

- Both dates are required; the end date cannot be before the start date.
- Weekends alone cannot be requested.
- You cannot overlap another of your own pending or approved requests.
- The request cannot exceed your available balance for that type.

**Track requests**: the table **My requests** shows each request's status (Pending, Approved, Denied, Cancelled). Press **Cancel request** on a pending request to withdraw it. Approved requests that have not started can be cancelled by an administrator.

**Calendar colours**: your leave is shown in a colour per type; colleagues' approved leave shows as "Away" (their name only). Pending requests are dashed.

**Decisions**: when a request is approved or denied, you receive a notification on the dashboard.

### 15.8 Departments

Departments group employees and can have a parent department, a manager and sub-departments. The Departments page shows members and the manager; the page is hidden from the menu by default (section 14.8).

### 15.9 Administration (administrators only)

Open **Admin Panel** in the header. It has four tabs: **Employees**, **Leave approvals** and **Leave calendar** (when leave is enabled), and **Departments**. The tab you are on is kept in the address (for example `admin.html#departments`).

**Add an employee**

1. **Add Employee** (top right).
2. Fill in the e-mail (required), first and last name, job title, department, phone (required). Office location, avatar photo and bio are optional. Tick **Administrator** only for people who must manage the portal.
3. Press **Add Employee**. The portal:
   - creates the portal record and an identity ID (from the name and mobile number),
   - creates the Authentik sign-in account and the NAS account (if configured), using one shared temporary password,
   - sends a welcome e-mail with the credentials in an encrypted PDF (if SMTP is configured).
4. The **Employee Created** page shows the temporary password **once**. Copy it, or rely on the e-mail. The status rows show each step (Created / Not sent). Warnings are listed when something needs attention.

The employee must change the password at first sign-in.

**Edit an employee**

Open the employee from the list and press **Edit**. You can change:

- personal and job details, photo, bio,
- administrator status (you cannot change your own),
- VPN access (turning it off disconnects the employee's devices; they are restored when it is turned on again),
- leave balances per type (allowance and carryover; see below),
- devices: create one for the employee, disconnect, reconnect, or delete,
- website visibility: you can **hide** a profile, but only the employee can publish it,
- NAS password reset (creates a new temporary password).

**Disable and enable**

- **Disable** removes the employee's VPN devices (on the VPN server and in the portal), removes administrator rights and VPN access, and blocks sign-in. The account and history are kept.
- **Enable** makes the account active again; administrator and VPN access must be granted again.

**Delete**

**Delete employee** permanently removes the account, its devices and its NAS account, and asks the sign-in provider to remove the Authentik account. Use **Disable** for temporary suspension. Deleting your own account is not allowed.

**Reset a password**

From the employee page, **Reset NAS password** (or the Authentik reset on the person page) sets a new temporary password for all of the employee's accounts at once. It is shown once. The employee must set their own password at next sign-in.

**Leave balances**

On the employee page, the **Leave balances** table shows the current year. **Edit** lets you change the yearly allowance and carryover (in steps of 0.5 days). The remaining days are recalculated automatically.

**Leave approvals**

- Filter: **Pending** or **All requests**.
- **Approve** accepts the request and deducts the days from the balance.
- **Deny** asks for an optional reason shown to the employee.
- You cannot approve your own request; another administrator must.
- An approved request can be edited from the employee's page (dates, days, reason); the balance is corrected.

**Leave calendar**

Shows everyone's leave. Filter by employee, show or hide pending requests. Click an event to see details.

**Departments**

- **Add department**: name (required), description, parent department and manager.
- A manager must be a member of the department or one of its sub-departments.
- A department with members or sub-departments cannot be deleted; move them first.

**Audit log**

Administrators can review actions in the audit log (API `/api/admin/audit-logs/`, or Django admin). Entries record who did what, when and from which IP address. Audit entries cannot be edited or deleted from the interface.

### 15.10 Notifications

The bell in the header shows the unread count. The dashboard lists notifications; each new one is marked "New" until you have seen it for a moment.

### 15.11 Website profile (what visitors see)

Once you publish your profile, the company website shows your photo, job title, department, short bio and, if you wrote it, your full profile and projects. Your e-mail and phone appear on the website only if the website is configured to show them. Your data on the website is updated shortly after each change; if that fails, the portal retries automatically.

---

## 16. Security checklist

Before go-live, confirm each item:

- [ ] All secrets in `.env` are generated and unique. Sample values from `.env.example` are gone.
- [ ] `.env` is not in version control and has restricted permissions (`chmod 600 .env`).
- [ ] `DJANGO_DEBUG=false`.
- [ ] `ALLOWED_HOSTS` lists only your real hostnames.
- [ ] HTTPS is in front of the portal (reverse proxy with a valid certificate); `SECURE_SSL_REDIRECT=true`.
- [ ] Ports 8000 and 5432 are not exposed on the public network (default bindings are `127.0.0.1`).
- [ ] Authentik (or your provider) has MFA enabled for all users.
- [ ] The `akadmin` bootstrap password was changed, and the bootstrap account is secured.
- [ ] `VERIFY_SSL=true` with trusted certificates for OPNsense and DSM. If DSM uses a self-signed certificate, install it in the trust store used by the container, or accept the risk consciously.
- [ ] The database is backed up and a restore has been tested (section 13.2).
- [ ] Backups are stored off the server, encrypted.
- [ ] SSH on the NAS or server is disabled when not in use, and key-based login is used.
- [ ] The Sanity write token and SMTP password are restricted to the minimum needed.
- [ ] The first portal administrator is a named person, and at least two administrators exist.
- [ ] Only the minimum number of employees have administrator rights.

---

## 17. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `web` restarts repeatedly | Missing or wrong `.env` value (for example `DJANGO_SECRET_KEY` empty in production) | `docker compose logs web`; fix the variable; `docker compose up -d web` |
| `DJANGO_SECRET_KEY must be set in production` | Empty secret | Generate one (section 5.2) |
| `Bad Request (400)` in the browser | Hostname not in `ALLOWED_HOSTS` | Add the hostname; restart `web` |
| Sign-in page says "Sign-in failed" | OIDC settings do not match Authentik | Compare `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` and `OIDC_SERVER_URL` with the Authentik provider |
| Sign-in page shows "temporarily unavailable" (503) | Authentik unreachable from the `web` container | Check `OIDC_SERVER_URL` is reachable from inside the container: `docker compose exec web python -c "import requests;print(requests.get('<url>').status_code)"` |
| Infinite redirect to `/login` | Cookies blocked or the site is served on HTTP while cookies are `Secure` | Use HTTPS in production; for local use `USE_SSO=false` or `SECURE_SSL_REDIRECT=false` |
| Every API call returns 403 with `password_change_required` | The user's NAS password is temporary | The user must set a new password on the forced page |
| Employee cannot see VPN section | VPN access not granted | Edit the employee > VPN access |
| "Could not create VPN access" | OPNsense unreachable or API keys wrong | Check `OPNSENSE_URL`, keys, `VERIFY_SSL`; or use `WIREGUARD_BACKEND=mock` for testing |
| Setup file says "expired or already used" | The one-time link was used or is older than the TTL | Create a new device; download once |
| NAS account not created | `DSM_URL`/credentials wrong, or password policy rejected | Check the warning on the Employee Created page; check DSM admin rights |
| Welcome e-mail not sent | SMTP settings wrong | Test with `docker compose exec web python -c "import smtplib;..."`; check port 465 vs 587 |
| Website shows old data | Sanity push pending | Check the profile warning; run `sanity_retry_pending`; check `SANITY_WRITE_TOKEN` |
| Migration fails on start | Database not reachable or previous failed migration | `docker compose logs postgres web`; restore backup if needed |
| Build is very slow or fails on ARMv7 | No prebuilt wheels for some packages | Use an ARM64 or x86_64 machine, or see section 4.2 |
| `exec format error` when starting a container | Image built for another CPU | Rebuild with `docker compose build --no-cache web` on the target machine |
| Port already allocated | Another program uses 8000 or 5432 | Change the host port in `docker-compose.yml` |
| Pages look unstyled | Static files not collected or browser cache | Rebuild the image; hard-refresh (Ctrl+F5) |
| Italian text missing for a new label | No translation entry | Add it to `frontend/i18n.js` (section 14.2) |
| Desktop shortcut or NAS not reachable after VPN connects | NAS firewall or routing | Check OPNsense rules for the peer network, and NAS SMB service |

Diagnostic commands:

```bash
docker compose ps
docker compose logs --tail=200 web
docker compose exec web python manage.py check
docker compose exec web python manage.py showmigrations | tail -n 30
docker compose exec postgres psql -U shesa -d shesa_portal -c "select count(*) from users;"
```

---

## 18. Appendix

### 18.1 Environment variable reference (summary)

| Group | Variables |
| --- | --- |
| Django | `DJANGO_SETTINGS_MODULE`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS`, `PUBLIC_APP_URL`, `SECURE_SSL_REDIRECT`, `LOG_LEVEL` |
| Database | `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_CONN_MAX_AGE` |
| Sign-in | `USE_SSO`, `OIDC_PROVIDER_ID`, `OIDC_PROVIDER_NAME`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SERVER_URL`, `OIDC_REDIRECT_URI`, `LOGIN_REDIRECT_URL`, `DEV_USER_EMAIL` |
| Authentik | `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_PG_PASS`, `AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_EMAIL`, `AUTHENTIK_IMAGE`, `AUTHENTIK_API_URL`, `AUTHENTIK_API_TOKEN`, `AUTHENTIK_DEFAULT_GROUP`, `AUTHENTIK_ADMIN_GROUP` |
| VPN | `WIREGUARD_BACKEND`, `OPNSENSE_URL`, `OPNSENSE_API_KEY`, `OPNSENSE_API_SECRET`, `WG_INSTANCE_UUID`, `WG_ENDPOINT`, `WG_PORT`, `WG_SUBNET`, `WG_DNS`, `ALLOWED_IPS_CLIENT`, `VERIFY_SSL`, `LAUNCHER_TOKEN_TTL_MINUTES` |
| NAS | `DSM_URL`, `DSM_ADMIN_USER`, `DSM_ADMIN_PASS`, `DSM_SHARE_GROUP`, `DSM_ADMIN_GROUP`, `NAS_IP`, `NAS_SHARE_NAME` |
| E-mail | `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SENDER_EMAIL`, `COMPANY_NAME` |
| Website | `SANITY_SYNC_ENABLED`, `SANITY_PROJECT_ID`, `SANITY_DATASET`, `SANITY_API_VERSION`, `SANITY_WRITE_TOKEN`, `SANITY_SYNC_TIME`, `SANITY_RETRY_INTERVAL_MINUTES`, `SANITY_MAX_ATTEMPTS` |
| Features | `LEAVE_MANAGEMENT_ENABLED`, `LEAVE_DEFAULT_VACATION_DAYS`, `LEAVE_DEFAULT_SICK_DAYS`, `LEAVE_DEFAULT_PERSONAL_DAYS` |

### 18.2 Docker commands cheat sheet

```bash
docker compose up -d --build postgres web      # start / rebuild
docker compose ps                              # status
docker compose logs -f web                     # logs
docker compose exec web sh                     # shell in the app container
docker compose exec web python manage.py <cmd> # management commands
docker compose exec -T postgres pg_dump -U shesa -d shesa_portal -Fc > backup.dump
docker compose restart web                     # apply .env changes
docker compose down                            # stop and remove containers (keeps data)
```

Note: changing `.env` requires `docker compose up -d web` (the container reads the file at creation). Code changes require `docker compose up -d --build web`.

### 18.3 API overview

All endpoints return JSON and use the signed-in session. Writes need the CSRF token (handled by the frontend).

| Area | Endpoints |
| --- | --- |
| Auth | `GET /login`, `GET /logout`, `GET /api/auth/config/`, `GET /api/me/`, `PATCH /api/me/`, `POST /api/me/dsm-password`, `GET /api/me/projects/`, \`POST |
| Core | `GET /api/dashboard/`, `GET /api/people/`, `GET /api/departments/`, `POST /api/departments/create`, \`PATCH |
| Devices | `GET /api/devices/`, `POST /api/devices/create`, \`POST /api/devices//revoke |
| Leave (when enabled) | `GET /api/pto/balances/`, `GET /api/pto/calendar/`, \`GET |
| Admin | \`GET |

### 18.4 Glossary

- **Authentik**: open-source identity provider used for sign-in and MFA.
- **OIDC**: OpenID Connect, the sign-in protocol between the portal and Authentik.
- **WireGuard**: modern VPN protocol; the OPNsense firewall hosts the VPN server.
- **DSM**: Synology DiskStation Manager, the NAS operating system.
- **QTS / QuTS hero**: QNAP NAS operating systems.
- **Container Manager / Container Station**: Docker front-ends on Synology and QNAP.
- **Identity ID**: employee identifier of the form `XXY-XXXXXX`, created from the name and mobile number.
- **Feature flag**: a setting in `.env` that turns a module on or off without code changes.
- **Migration (database)**: a versioned change to the database schema, applied by `manage.py migrate`.
- **Sanity**: headless content platform that stores the company website content.

---

*End of manual. For release-specific changes, read the release notes and compare `.env.example` with your `.env` before upgrading.*