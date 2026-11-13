"""Settings shared by every environment. Environment files override/extend this."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    fallback = "true" if default else "false"
    return os.environ.get(name, fallback).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str) -> list[str]:
    return [h.strip() for h in os.environ.get(name, default).split(",") if h.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = env_bool("DJANGO_DEBUG", False)

PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
if PUBLIC_APP_URL:
    _public_host = PUBLIC_APP_URL.split("://", 1)[-1].split("/")[0]
    if _public_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_public_host)
CSRF_TRUSTED_ORIGINS = [PUBLIC_APP_URL] if PUBLIC_APP_URL else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Third party
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    # Local apps (order matters only for AppConfig.ready signal wiring)
    "apps.common",
    "apps.accounts",
    "apps.core",
    "apps.devices",
    "apps.pto",
]

MIDDLEWARE = [
    "apps.common.middleware.MovedPermanentlyPageMiddleware",
    "apps.common.middleware.SignInProviderUnavailableMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.common.middleware.DevAuthMiddleware",
    "apps.common.middleware.ForcedPasswordMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---- PostgreSQL (latest). Connection comes from DB_* variables. ----
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "shesa_portal"),
        "USER": os.environ.get("DB_USER", "shesa"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
    }
}

CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SITE_ID = 1

# ---- Identity: no passwords. Users come from the OIDC provider (Authentik). ----
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = []
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Development bypass (was USE_WORKOS in the Flask/Django-WorkOS versions).
USE_SSO = env_bool("USE_SSO", True)
DEV_USER_EMAIL = os.environ.get("DEV_USER_EMAIL", "developer@localhost")

# ---- django-allauth ----
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "none"  # the IdP owns email verification
ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"  # no local sign-up
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True  # match pre-created accounts by email
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_STORE_TOKENS = False
OIDC_PROVIDER_ID = os.environ.get("OIDC_PROVIDER_ID", "authentik")
OIDC_SERVER_URL = os.environ.get("OIDC_SERVER_URL", "")  # e.g. http://sso.shesa.local:9000/application/o/shesa/
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_PROVIDER_NAME = os.environ.get("OIDC_PROVIDER_NAME", "Shesa SSO")
SOCIALACCOUNT_PROVIDERS = {
    "openid_connect": {
        "OAUTH_PKCE_ENABLED": True,
        "APPS": [
            {
                "provider_id": OIDC_PROVIDER_ID,
                "name": OIDC_PROVIDER_NAME,
                "client_id": os.environ.get("OIDC_CLIENT_ID", ""),
                "secret": os.environ.get("OIDC_CLIENT_SECRET", ""),
                "settings": {
                    # Authentik: https://<host>/application/o/<slug>/
                    "server_url": os.environ.get("OIDC_SERVER_URL", ""),
                    "token_auth_method": "client_secret_basic",
                },
            }
        ],
    }
}
LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = os.environ.get("LOGIN_REDIRECT_URL", "/index.html")
LOGOUT_REDIRECT_URL = "/logout.html"

# ---- Portal integrations (same env var names as before) ----
DSM_URL = os.environ.get("DSM_URL", "")
# Reachable from the web container (Docker network alias), not necessarily
# the public-facing host the browser uses for sign-in.
AUTHENTIK_API_URL = os.environ.get("AUTHENTIK_API_URL", "")
NAS_IP = os.environ.get("NAS_IP", "")
NAS_SHARE_NAME = os.environ.get("NAS_SHARE_NAME", "")
LAUNCHER_TOKEN_TTL_MINUTES = int(os.environ.get("LAUNCHER_TOKEN_TTL_MINUTES", "60"))

# ---- Sanity (company website content store) ----
SANITY_PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "")
SANITY_DATASET = os.environ.get("SANITY_DATASET", "production")
SANITY_API_VERSION = os.environ.get("SANITY_API_VERSION", "2026-01-01")
SANITY_WRITE_TOKEN = os.environ.get("SANITY_WRITE_TOKEN", "")
SANITY_SYNC_TIME = os.environ.get("SANITY_SYNC_TIME", "03:00")
SANITY_SYNC_ENABLED = env_bool("SANITY_SYNC_ENABLED", False)
SANITY_RETRY_INTERVAL_MINUTES = int(os.environ.get("SANITY_RETRY_INTERVAL_MINUTES", "5"))
SANITY_MAX_ATTEMPTS = int(os.environ.get("SANITY_MAX_ATTEMPTS", "20"))

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # processes run in UTC; datetimes are stored naive UTC
USE_I18N = True
USE_TZ = False

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Behind a reverse proxy (TLS terminated upstream).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "verbose"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}