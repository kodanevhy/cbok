"""Isolated SQLite settings; never read production credentials or run gates."""

SECRET_KEY = "alert-tests-only"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "cbok.bbx",
    "cbok.user",
    "cbok.alert",
    "cbok.notification",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
AUTH_USER_MODEL = "user.UserProfile"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_FROM = "alert-tests@example.invalid"
DEFAULT_FROM_EMAIL = EMAIL_FROM
MIGRATION_MODULES = {"alert": None, "user": None, "notification": None, "bbx": None}
