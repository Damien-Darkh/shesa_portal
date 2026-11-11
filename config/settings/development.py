from .base import *  # noqa: F401,F403
from .base import DEBUG, SECRET_KEY, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-change-me"

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
