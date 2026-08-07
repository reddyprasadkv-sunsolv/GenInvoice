"""ASGI config for the local invoice manager project."""
import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_manager.settings")

application = get_asgi_application()
