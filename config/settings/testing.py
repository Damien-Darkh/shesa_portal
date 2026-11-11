from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "testing-only"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
