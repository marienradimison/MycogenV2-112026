"""Configuration Django — Mycogen LIMS (Institut Pasteur de Madagascar, Mycobacteria Unit)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.diagnostic",
    "apps.research",
    "apps.biobank",
    "apps.bioinfo",
    "apps.instruments",
    "apps.feed",
    "apps.quality",
    "apps.stock",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Production : WhiteNoise sert les fichiers collectés (collectstatic au démarrage de « serve »).
# Développement : Django sert directement static/, toujours à jour.
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "mycogen.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.lab",
            ],
        },
    },
]

WSGI_APPLICATION = "mycogen.wsgi.application"

# Base de données : PostgreSQL. DB_ENGINE=sqlite n'est prévu que pour des tests rapides.
# « manage.py test » utilise SQLite par défaut : le compte PostgreSQL de MYCOGEN n'a pas (et ne doit pas avoir)
# le droit de créer des bases ; DB_ENGINE=postgresql force les tests sur PostgreSQL (droit CREATEDB requis).
RUNNING_TESTS = sys.argv[1:2] == ["test"]
if os.environ.get("DB_ENGINE", "sqlite" if RUNNING_TESTS else "postgresql") == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "dev.sqlite3"}}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "mycogen"),
            "USER": os.environ.get("DB_USER", "mycogen"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
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

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Indian/Antananarivo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Fichiers téléversés (rapports, fichiers de résultats…) — servis uniquement aux utilisateurs connectés
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Session : déconnexion après 8 h et à la fermeture du navigateur (postes partagés)
SESSION_COOKIE_AGE = 8 * 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
if not DEBUG:
    SESSION_COOKIE_HTTPONLY = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "file": {"class": "logging.handlers.RotatingFileHandler", "formatter": "std",
                 "filename": BASE_DIR / "logs" / "mycogen.log", "maxBytes": 5_000_000, "backupCount": 5,
                 "encoding": "utf-8"},
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "WARNING"},
        "mycogen": {"handlers": ["console", "file"], "level": "INFO"},
    },
}
(BASE_DIR / "logs").mkdir(exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Lecture d'étuve : une ligne de formulaire par culture en étuve (plusieurs centaines) → relever la limite Django
# (1 000 champs par défaut), sinon l'enregistrement de la lecture échoue (TooManyFieldsSent, erreur 400).
DATA_UPLOAD_MAX_NUMBER_FIELDS = 30000

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "login"

# Identité du laboratoire
LAB_NAME = "MYCOGEN"
LAB_INSTITUTION = "Institut Pasteur de Madagascar"
LAB_DEPARTMENT = "Unité des Mycobactéries"

# Actualités scientifiques (tableau de bord) : récupération automatique sur Internet
NEWS_AUTO_FETCH = env_bool("NEWS_AUTO_FETCH", True) and "test" not in sys.argv[1:2]
