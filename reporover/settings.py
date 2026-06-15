"""
Django settings for the RepoRover Phase 1.0 SaaS platform.

Configuration is driven entirely by environment variables (see .env.example) so
no secrets live in source control. A local .env file is loaded automatically.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the project root for local development.
load_dotenv(BASE_DIR / ".env")


def env(key: str, default=None, required: bool = False):
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"Required environment variable {key} is not set.")
    return value


# --- Core Django ---
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # RepoRover apps
    "tenancy",
    "webhooks",
    "engine",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "reporover.urls"

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

WSGI_APPLICATION = "reporover.wsgi.application"
ASGI_APPLICATION = "reporover.asgi.application"

# --- Database (PostgreSQL per PRD §4) ---
import dj_database_url

postgres_dsn_env = env("POSTGRES_DSN")

if postgres_dsn_env:
    # 1. Let dj-database-url handle all the complex parsing (ports, passwords, query params)
    DATABASES = {
        "default": dj_database_url.parse(
            postgres_dsn_env,
            conn_max_age=600,         # Enterprise standard connection pooling
            conn_health_checks=True,
        )
    }
    
    # Ensure sslmode prefer is set for managed cloud DBs if not explicitly in the DSN
    if "OPTIONS" not in DATABASES["default"]:
        DATABASES["default"]["OPTIONS"] = {}
    if "sslmode" not in DATABASES["default"]["OPTIONS"]:
        DATABASES["default"]["OPTIONS"]["sslmode"] = "prefer"
    
    # 2. Keep the DSN in the environment for LangGraph's psycopg_pool checkpointer
    os.environ["POSTGRES_DSN"] = postgres_dsn_env

else:
    # Fallback to individual local environment variables if DSN is missing
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "reporover"),
            "USER": env("POSTGRES_USER", "reporover"),
            "PASSWORD": env("POSTGRES_PASSWORD", "reporover"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "OPTIONS": {
                "sslmode": "prefer",
            },
        }
    }
    
    # Reconstruct the DSN strictly for LangGraph's checkpointer fallback
    POSTGRES_DSN = "postgresql://{user}:{password}@{host}:{port}/{name}".format(
        user=DATABASES["default"]["USER"],
        password=DATABASES["default"]["PASSWORD"],
        host=DATABASES["default"]["HOST"],
        port=DATABASES["default"]["PORT"],
        name=DATABASES["default"]["NAME"],
    )
    os.environ["POSTGRES_DSN"] = POSTGRES_DSN

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery / Redis (PRD §2, §5.1) ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_DEFAULT_QUEUE = "reporover"
# --- Celery / Redis Security Overrides ---
# Tells Celery to allow connection loops over cloud TLS links
CELERY_BROKER_USE_SSL = {
    'ssl_cert_reqs': None
}
CELERY_REDIS_BACKEND_USE_SSL = {
    'ssl_cert_reqs': None
}

# Upstash drops idle connections quickly to save serverless resources.
# This keeps sockets alive by actively heartbeating every 10 seconds.
CELERY_REDIS_BROKER_TRANSPORT_OPTIONS = {
    'socket_timeout': 30,
    'socket_keepalive': True,
    'retry_on_timeout': True
}

# --- BYOK encryption (PRD §3.1) ---
# Master Fernet key (AES-256) used to encrypt tenant Gemini/E2B keys at rest.
FERNET_KEY = env("FERNET_KEY")

# --- GitHub App credentials (PRD §3.3, §3.4) ---
GITHUB_APP_ID = env("GITHUB_APP_ID")
GITHUB_APP_PRIVATE_KEY = env("GITHUB_APP_PRIVATE_KEY")  # PEM contents
GITHUB_WEBHOOK_SECRET = env("GITHUB_WEBHOOK_SECRET")
GITHUB_OAUTH_CLIENT_ID = env("GITHUB_OAUTH_CLIENT_ID")
GITHUB_OAUTH_CLIENT_SECRET = env("GITHUB_OAUTH_CLIENT_SECRET")

# Login URL for the OAuth dashboard.
LOGIN_URL = "/dashboard/login/"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
