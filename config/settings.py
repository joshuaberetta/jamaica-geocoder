"""
Django settings for the Humanitarian Geocoder backend.

Replaces the Flask app in web_app.py. Geospatial access uses GeoDjango
(django.contrib.gis) against the existing PostGIS database; API auth uses DRF
token authentication with per-scope rate throttling.
"""

import glob
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# GeoDjango native library discovery
# ---------------------------------------------------------------------------
# On hosts without a system GDAL/GEOS (e.g. local macOS dev), fall back to the
# libraries bundled inside the fiona/pyogrio/shapely wheels. The Docker image
# ships a system GDAL, so these env vars are only set when discovery succeeds
# and nothing is already configured.

def _find_lib(*site_globs):
    for pattern in site_globs:
        for site in __import__("site").getsitepackages() + [__import__("site").getusersitepackages()]:
            matches = sorted(glob.glob(os.path.join(site, pattern)))
            if matches:
                return matches[-1]
    return None


if not os.getenv("GDAL_LIBRARY_PATH"):
    _gdal = _find_lib("fiona/.dylibs/libgdal*.dylib", "pyogrio/.dylibs/libgdal*.dylib",
                      "fiona*.so", "*/libgdal.so*")
    if _gdal:
        GDAL_LIBRARY_PATH = _gdal

if not os.getenv("GEOS_LIBRARY_PATH"):
    _geos = _find_lib("shapely/.dylibs/libgeos_c*.dylib", "shapely*/libgeos_c*",
                      "Shapely.libs/libgeos_c*.so*", "shapely/.libs/libgeos_c*.so*")
    if _geos:
        GEOS_LIBRARY_PATH = _geos


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "corsheaders",
    "apps.geo",
    "apps.geocoding",
    "apps.accounts",
    "apps.core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database (PostGIS) — parsed from the existing DATABASE_URL env var
# ---------------------------------------------------------------------------

_db_url = os.getenv("DATABASE_URL", "")
if _db_url:
    _p = urlparse(_db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": _p.path.lstrip("/"),
            "USER": _p.username or "",
            "PASSWORD": _p.password or "",
            "HOST": _p.hostname or "",
            "PORT": str(_p.port or ""),
        }
    }
else:
    # No DATABASE_URL (e.g. unit tests that mock the DB) — use a sqlite stub so
    # Django can still start. Spatial queries require the real PostGIS DB.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dev.sqlite3",
        }
    }


# ---------------------------------------------------------------------------
# Caching — replaces the in-memory dicts in the old Flask app
# ---------------------------------------------------------------------------
# LocMemCache matches the old per-process behaviour. Switch to Redis once
# running more than one gunicorn worker so cache-clear-on-ingest reaches all
# workers (see plans/django-migration-plan.md, Phase 4).

_redis_url = os.getenv("REDIS_URL")
if _redis_url:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                          "LOCATION": _redis_url}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                          "LOCATION": "geocoder"}}


# ---------------------------------------------------------------------------
# DRF: token auth + throttling
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_ANON", "120/min"),
        "user": os.getenv("THROTTLE_USER", "600/min"),
        "geocode": os.getenv("THROTTLE_GEOCODE", "30/min"),
        "batch": os.getenv("THROTTLE_BATCH", "5/min"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Humanitarian Geocoder API",
    "DESCRIPTION": "Resolve coordinates/addresses to OCHA admin P-codes and "
                   "secondary boundaries; download per-country KoboCollect XLSForms.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# The SPA is served same-origin in production, so CORS is only needed for the
# Vite dev server. Mirrors the old `CORS(app)` (open) but configurable.

CORS_ALLOWED_ORIGINS = [
    o for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o
]
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Auth / i18n / static
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# The compiled React SPA lives in static/ (output of `vite build`).
FRONTEND_DIST = BASE_DIR / "static"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_ROOT = FRONTEND_DIST  # serve SPA assets (index.html, assets/) at the root

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Match the old Flask 16 MB upload cap for batch geocoding.
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
