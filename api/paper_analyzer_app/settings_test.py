"""Test-specific Django settings.

Inherits from the main settings but overrides for test isolation:
- Database connects via localhost (host-mapped port, not Docker internal)
- Celery tasks run synchronously (eager mode)
- In-memory cache and channel layer (no Redis dependency)
- pytest-django creates an isolated test_<DB_NAME> database
"""
import os

from paper_analyzer_app.settings import *  # noqa: F401,F403

# --- Database: ensure we connect via host-mapped port ---
# settings.py with RUNNING_LOCALLY=true already sets HOST='localhost'.
# Override PORT to use the externally mapped port (worktree-specific).
DATABASES["default"]["HOST"] = "localhost"  # noqa: F405
DATABASES["default"]["PORT"] = os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432"))  # noqa: F405
# gssencmode=disable: libpq defaults to gssencmode=prefer, and if the developer
# machine has ANY Kerberos state (e.g. a NASA SSO/PIV session), every test
# connection attempts GSSAPI first — KDC discovery via DNS hangs and a 20s
# suite becomes 6+ minutes (observed live; stack: pqsecure_open_gss ->
# krb5_get_init_creds -> mDNSResponder). Local test connections never need GSS.
DATABASES["default"].setdefault("OPTIONS", {})["gssencmode"] = "disable"  # noqa: F405

# --- Celery: always synchronous ---
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# --- In-memory cache (no Redis needed) ---
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# --- In-memory channel layer (no Redis needed) ---
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# --- SECRET_KEY fallback ---
if not globals().get("SECRET_KEY"):
    SECRET_KEY = "test-secret-key-not-for-production"  # noqa: F811
