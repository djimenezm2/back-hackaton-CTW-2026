import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "insecure-dev-key-change-me")

DEBUG = os.environ.get("DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "corsheaders",
    # Registers the `unaccent` and trigram lookups; the extensions themselves are migrated
    "django.contrib.postgres",
    "ayudagente.radar",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

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

WSGI_APPLICATION = "backend.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("DB_NAME", "hackaton"),
        "USER": os.environ.get("DB_USER", "hackaton"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "hackaton"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Harvested images live on disk, not in Postgres: hundreds of MB of bytes would bloat
# every backup for something a filesystem does better.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "media/"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Frontend runs on its own origin during the hackathon; open CORS only in DEBUG.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    origin for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if origin
]

# Some hosts carry a second GDAL build (e.g. /usr/gdal312) that ctypes picks up but that
# is linked against an incompatible GEOS. These let each dev pin the working libraries.
if os.environ.get("GDAL_LIBRARY_PATH"):
    GDAL_LIBRARY_PATH = os.environ["GDAL_LIBRARY_PATH"]
if os.environ.get("GEOS_LIBRARY_PATH"):
    GEOS_LIBRARY_PATH = os.environ["GEOS_LIBRARY_PATH"]

# OpenAI. A model per role, mapped onto the GPT-5.6 tiers: Sol for frontier judgment,
# Luna for cheap image triage. Extraction shares Sol until the volume justifies splitting.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODELS = {
    "reasoning": os.environ.get("OPENAI_MODEL_REASONING", "gpt-5.6-sol"),
    "extraction": os.environ.get("OPENAI_MODEL_EXTRACTION", "gpt-5.6-sol"),
    "triage": os.environ.get("OPENAI_MODEL_TRIAGE", "gpt-5.6-luna"),
    "embedding": os.environ.get("OPENAI_MODEL_EMBEDDING", "text-embedding-3-small"),
}

GOOGLE_GEOCODING_API_KEY = os.environ.get("GOOGLE_GEOCODING_API_KEY", "")
