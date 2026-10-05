"""Point d'entrée WSGI pour gunicorn (voir entrypoint.sh)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
application = get_wsgi_application()
