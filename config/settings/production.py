import os

from .base import *  # noqa: F401,F403
from .base import SECRET_KEY, env_bool

DEBUG = False
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
