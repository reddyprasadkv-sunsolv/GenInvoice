from django.conf import settings
from django.db import connection


def environment_context(request):
    return {
        "DJANGO_ENVIRONMENT": getattr(settings, "DJANGO_ENVIRONMENT", "local"),
        "IS_POSTGRESQL": connection.vendor == "postgresql",
    }
