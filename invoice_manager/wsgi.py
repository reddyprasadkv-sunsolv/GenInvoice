"""WSGI config for the local invoice manager project."""
import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_manager.settings")

application = get_wsgi_application()
