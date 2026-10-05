"""
Configuration Django du Hub PECS.

Tout ce qui varie d'un déploiement à l'autre vient de l'environnement
(voir .env.example à la racine du dépôt). Aucun secret en dur ici.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def env_list(name):
    """Variable d'environnement en CSV → liste (les vides sont écartés)."""
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


# --- Secrets et mode --------------------------------------------------------
SECRET_KEY = os.environ.get("HUB_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("HUB_DEBUG", "0") == "1"
ALLOWED_HOSTS = env_list("HUB_ALLOWED_HOSTS") or ["localhost", "127.0.0.1"]
# Derrière un reverse proxy HTTPS : le proxy porte le TLS, Django doit le savoir.
CSRF_TRUSTED_ORIGINS = env_list("HUB_CSRF_ORIGINS")
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Authentification maison (pas de django.contrib.auth, pas de comptes) ---
# Un mot de passe partagé pour les membres, un second pour l'admin ; le
# prénom saisi à la connexion signe tout. Voir hub/middleware.py.
HUB_SHARED_PASSWORD = os.environ.get("HUB_SHARED_PASSWORD", "")
HUB_ADMIN_PASSWORD = os.environ.get("HUB_ADMIN_PASSWORD", "")

# --- Applications -----------------------------------------------------------
# Une seule app pour tout le Hub : moins de plomberie qu'un dossier par
# fonctionnalité, et un successeur trouve tout au même endroit.
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",   # recherche plein texte (SearchVector)
    "hub",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise sert les statiques depuis gunicorn : pas de nginx à configurer.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Notre garde : tout est protégé sauf /connexion/, /static/ et /sante/.
    "hub.middleware.SharedPasswordMiddleware",
]

ROOT_URLCONF = "hub.urls"
WSGI_APPLICATION = "wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,            # trouve déjà hub/templates/
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.messages.context_processors.messages",
        "hub.middleware.hub_context",   # prenom, is_admin et pôles partout
    ]},
}]

# --- Base de données --------------------------------------------------------
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("HUB_DB_NAME", "hub"),
    "USER": os.environ.get("DB_USER", "aero"),
    "PASSWORD": os.environ.get("DB_PASSWORD", ""),
    "HOST": os.environ.get("DB_HOST", "db"),
    "PORT": os.environ.get("DB_PORT", "5432"),
}}

# --- Statiques et médias ----------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get("HUB_STATIC_ROOT", "/data/static")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
# Les médias ne sont JAMAIS servis directement : hub.views.core.protected_media
# vérifie la session avant de livrer le fichier.
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("HUB_MEDIA_ROOT", "/data/media")

# --- Divers -----------------------------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024   # photos de téléphone brutes
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90           # 90 jours : confort d'atelier
