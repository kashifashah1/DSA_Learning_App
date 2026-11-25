"""
Django settings for the DSA Learning System (B.Tech Project-1).

Secrets and database details are NOT written here. They are read from a
.env file (copy .env.example to .env and edit it).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Read the .env file (if it exists) into environment variables.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read a True/False value from the environment."""
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Core settings
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-your-env-file")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# A real deployment must not use the placeholder secret key.
if not DEBUG and SECRET_KEY == "change-me-in-your-env-file":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set a long random SECRET_KEY in your .env file when DEBUG is False.")

# ---------------------------------------------------------------------------
# HTTPS: off for local use. For a deployment with HTTPS set HTTPS_ENABLED=True in .env.
# ---------------------------------------------------------------------------
HTTPS_ENABLED = env_bool("HTTPS_ENABLED", False)
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
if HTTPS_ENABLED:
    SECURE_SSL_REDIRECT = True  # send every http:// request to https://
    SESSION_COOKIE_SECURE = True  # cookies only travel over https
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))  # raise it once HTTPS works well
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_REFERRER_POLICY = "same-origin"
    if env_bool("BEHIND_PROXY", False):  # a reverse proxy (nginx) terminates HTTPS and sets this header
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    # Our six apps (one-way dependency: web -> recommendations -> analytics
    # -> attempts -> users/problems)
    "users",
    "problems",
    "attempts",
    "analytics",
    "recommendations",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",  # CSRF protection on all forms
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page needs login, except views marked with @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dsa_learning.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # project-level templates (base.html)
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

WSGI_APPLICATION = "dsa_learning.wsgi.application"

# ---------------------------------------------------------------------------
# Database: PostgreSQL, details come from the .env file
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "dsa_learning"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# Django REST Framework: the chart endpoints are read-only, JSON only, and need a logged-in student.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# Our own User model (login by e-mail). Must be set before the first migrate.
AUTH_USER_MODEL = "users.User"

# Password hashing is done by Django's auth system (default hashers).
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Every page except login/registration needs login (the pages will use these).
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "landing"  # after logout the student sees the public landing page

# Forgot password: the reset link works once and stops working after this many seconds.
PASSWORD_RESET_TIMEOUT = 3600

# E-mail. Sending real e-mail is outside the project scope, so by default the e-mail is only
# PRINTED in the terminal window that runs the server (the reset link can be copied from there).
# To use a real mail server, set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# and the EMAIL_* values in your .env file.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "users.email_backend.ReadableConsoleEmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "DSA Path <no-reply@dsapath.local>")

# ---------------------------------------------------------------------------
# Language, time, static files
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Logging: errors go to logs/app.log (and to the console while developing)
# ---------------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 1_000_000,  # about 1 MB per file
            "backupCount": 3,
            "formatter": "standard",
            "encoding": "utf-8",
        },
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["file", "console"], "level": "INFO"},
    "loggers": {
        # Django's own errors (for example a crashing view) also go to the file.
        "django": {"handlers": ["file", "console"], "level": "INFO", "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# RuleConfig: ALL thresholds and weights live here (starting values, to be
# tuned later). Never write these numbers inside views or service classes.
# ---------------------------------------------------------------------------
MIN_ATTEMPTS_PER_TOPIC = 3      # below this, a topic has no mastery score yet
RECENT_WINDOW = 5               # "recent" means the last 5 attempts in a topic
MIN_ATTEMPTS_FOR_MODEL = 100    # below this, use rule-based recommendations only
REVISION_AFTER_DAYS = 14        # suggest revision if topic not practised this long
REVISION_ACCURACY_DROP = 0.20   # suggest revision if accuracy fell by this much
TARGET_SUCCESS_PROB = 0.6       # model: pick the problem closest to this chance
CODE_TIME_LIMIT_SEC = 5         # time limit for running submitted code
MAX_OUTPUT_BYTES = 1_000_000    # program output beyond this is cut off (protects memory)
MAX_ERROR_CHARS = 2000          # longest error message we keep (the end of it)
MAX_SOURCE_CODE_CHARS = 20_000  # longest solution a student may submit

# Rules of the recommendation engine (starting values, to be tuned later).
EXPECTED_SOLVE_SEC = {"Easy": 300, "Medium": 600, "Hard": 1200}  # a "fast" solution takes at most this long
STRONG_TOPIC_ACCURACY = 0.7     # a topic counts as "strong" if the accuracy was at least this
HARDER_MIN_CORRECT = 3          # correct AND fast attempts among the recent ones: suggest a harder problem
EASIER_MIN_FAILURES = 3         # failed attempts among the recent ones: suggest an easier problem

# Mastery score = weighted sum of four parts. Weights must add up to 1.0.
MASTERY_WEIGHTS = {
    "accuracy": 0.5,
    "recent_accuracy": 0.2,
    "speed": 0.15,
    "attempt_efficiency": 0.15,
}

# Learning levels from the mastery score (0-100):
#   Beginner     : score < 40
#   Intermediate : 40 <= score <= 70
#   Advanced     : score > 70
LEVEL_RANGES = {
    "BEGINNER_BELOW": 40,
    "ADVANCED_ABOVE": 70,
}

# Machine-learning model (starting values). Fixed random numbers make training repeatable.
MODEL_TEST_SIZE = 0.25          # share of the attempts kept back to test the model
MODEL_RANDOM_STATE = 42         # same data -> same model, every time
MODEL_MIN_CLASS_ROWS = 5        # training needs at least this many solved AND not-solved attempts
TREE_MAX_DEPTH = 4              # decision tree: small, so it does not just memorise the data
TREE_MIN_SAMPLES_LEAF = 10

# Where the trained model file is saved by `python manage.py train_model`.
MODEL_PATH = BASE_DIR / "ml_models" / "success_model.joblib"

# Only while running `python manage.py test`: use a fast password hasher so the
# tests finish quickly. Real use (runserver) keeps Django's strong default hasher.
import sys

if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

    # Tests must never read or overwrite your real trained model: they use a throw-away folder.
    import atexit
    import shutil
    import tempfile

    _test_model_dir = tempfile.mkdtemp(prefix="dsa_test_model_")
    atexit.register(shutil.rmtree, _test_model_dir, ignore_errors=True)
    MODEL_PATH = Path(_test_model_dir) / "success_model.joblib"
