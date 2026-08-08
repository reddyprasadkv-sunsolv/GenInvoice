"""Django settings for the local invoice manager project."""
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("INVOICEAPP_DATA_DIR", BASE_DIR)).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_CACHE_DIR = DATA_DIR / ".cache"
LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
(LOCAL_CACHE_DIR / "fontconfig").mkdir(exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(LOCAL_CACHE_DIR))
os.environ.setdefault("FC_CACHEDIR", str(LOCAL_CACHE_DIR / "fontconfig"))

def parse_bool(value, default=False):
    """Safely parse boolean environment variable values.

    Recognizes:
    - Truthy: "1", "true", "yes", "on" (case-insensitive)
    - Falsy: "0", "false", "no", "off" (case-insensitive)
    Returns default if value is None, empty, or unrecognised.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    val = str(value).strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


DEBUG = parse_bool(os.environ.get("DJANGO_DEBUG"), default=True)

INSECURE_DEV_SECRET = "django-insecure-local-only-phase-1-change-before-shared-use"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = INSECURE_DEV_SECRET
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY environment variable must be set when DJANGO_DEBUG is False."
        )

_allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS")
if _allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]
else:
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

_csrf_trusted_env = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS") or os.environ.get("CSRF_TRUSTED_ORIGINS")
if _csrf_trusted_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_trusted_env.split(",") if o.strip()]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "billing.middleware.AuthenticatedNoCacheMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "invoice_manager.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "invoice_manager.wsgi.application"


try:
    _conn_max_age_env = os.environ.get("DJANGO_DB_CONN_MAX_AGE") or os.environ.get("CONN_MAX_AGE")
    _conn_max_age = int(_conn_max_age_env) if _conn_max_age_env is not None else (60 if not DEBUG else 0)
except ValueError:
    _conn_max_age = 0

_db_sslmode = os.environ.get("DJANGO_DB_SSLMODE") or os.environ.get("DB_SSLMODE")

_db_url_raw = os.environ.get("DATABASE_URL", "").strip()

if _db_url_raw:
    import urllib.parse
    from django.core.exceptions import ImproperlyConfigured

    _db_url = urllib.parse.urlparse(_db_url_raw)
    _scheme = _db_url.scheme.lower()
    if _scheme in ("postgres", "postgresql", "postgres+psycopg", "postgresql+psycopg"):
        _query_params = urllib.parse.parse_qs(_db_url.query)

        _pg_options = {}
        _ssl_val = _db_sslmode or (_query_params.get("sslmode", [None])[0])
        if _ssl_val:
            _pg_options["sslmode"] = _ssl_val

        _db_config = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": urllib.parse.unquote(_db_url.path.lstrip("/")),
            "USER": urllib.parse.unquote(_db_url.username or ""),
            "PASSWORD": urllib.parse.unquote(_db_url.password or ""),
            "HOST": _db_url.hostname or "localhost",
            "PORT": str(_db_url.port or 5432),
            "CONN_MAX_AGE": _conn_max_age,
        }
        if _pg_options:
            _db_config["OPTIONS"] = _pg_options

        DATABASES = {"default": _db_config}
    else:
        if _scheme:
            raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {_scheme}")
        else:
            raise ImproperlyConfigured("Invalid or malformed DATABASE_URL specified")

elif os.environ.get("DJANGO_DB_ENGINE") == "postgresql":
    _pg_options = {}
    if _db_sslmode:
        _pg_options["sslmode"] = _db_sslmode

    _db_config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DJANGO_DB_NAME", "invoiceapp"),
        "USER": os.environ.get("DJANGO_DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", "localhost"),
        "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
        "CONN_MAX_AGE": _conn_max_age,
    }
    if _pg_options:
        _db_config["OPTIONS"] = _pg_options

    DATABASES = {"default": _db_config}

else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(os.environ.get("INVOICEAPP_DB_PATH", DATA_DIR / "db.sqlite3")).expanduser(),
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
BACKUP_ROOT = DATA_DIR / "backups"
LOG_ROOT = DATA_DIR / "logs"
MAX_BACKUP_UPLOAD_SIZE = 512 * 1024 * 1024
INVOICEAPP_SERVE_LOCAL_FILES = os.environ.get("INVOICEAPP_SERVE_LOCAL_FILES", "0") == "1"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
_cookie_secure_env = os.environ.get("SESSION_COOKIE_SECURE") or os.environ.get("SECURE_COOKIE_SECURITY")
SESSION_COOKIE_SECURE = parse_bool(_cookie_secure_env, default=not DEBUG)

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
_csrf_cookie_secure_env = os.environ.get("CSRF_COOKIE_SECURE") or os.environ.get("SECURE_COOKIE_SECURITY")
CSRF_COOKIE_SECURE = parse_bool(_csrf_cookie_secure_env, default=not DEBUG)

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = parse_bool(os.environ.get("SECURE_CONTENT_TYPE_NOSNIFF"), default=True)
SECURE_SSL_REDIRECT = parse_bool(os.environ.get("SECURE_SSL_REDIRECT"), default=not DEBUG)
SECURE_REFERRER_POLICY = os.environ.get("SECURE_REFERRER_POLICY", "same-origin")

if parse_bool(os.environ.get("SECURE_PROXY_SSL_HEADER"), default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
else:
    SECURE_PROXY_SSL_HEADER = None

try:
    _hsts_seconds_raw = os.environ.get("DJANGO_SECURE_HSTS_SECONDS") or os.environ.get("SECURE_HSTS_SECONDS", "0")
    SECURE_HSTS_SECONDS = int(_hsts_seconds_raw)
except ValueError:
    SECURE_HSTS_SECONDS = 0

SECURE_HSTS_INCLUDE_SUBDOMAINS = parse_bool(
    os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS") or os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS"),
    default=False,
)
SECURE_HSTS_PRELOAD = parse_bool(
    os.environ.get("DJANGO_SECURE_HSTS_PRELOAD") or os.environ.get("SECURE_HSTS_PRELOAD"),
    default=False,
)
