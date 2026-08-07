#!/usr/bin/env python3
"""macOS launcher for the packaged Local Invoice Manager app."""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
DEFAULT_PORT = 8000
APP_DIR_NAME = "InvoiceApp"
RUNTIME_DIRS = [
    "media/company_logos",
    "media/company_signatures",
    "media/invoices",
    "media/reports",
    "media/project_attachments",
    "backups",
    "logs",
]


def project_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def data_root():
    configured = os.environ.get("INVOICEAPP_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / APP_DIR_NAME


def prepare_environment():
    root = project_root()
    data_dir = data_root()
    data_dir.mkdir(parents=True, exist_ok=True)
    for folder in RUNTIME_DIRS:
        (data_dir / folder).mkdir(parents=True, exist_ok=True)

    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "invoice_manager.settings")
    os.environ.setdefault("DJANGO_DEBUG", "0")
    os.environ["INVOICEAPP_DATA_DIR"] = str(data_dir)
    os.environ["INVOICEAPP_SERVE_LOCAL_FILES"] = "1"
    return data_dir


def find_available_port(start_port=DEFAULT_PORT, max_attempts=30):
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                if probe.connect_ex((HOST, port)) == 0:
                    continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind((HOST, port))
                return port
        except OSError:
            continue
    raise RuntimeError("No available localhost port found for InvoiceApp.")


def wait_for_server_and_open(url, port):
    for _ in range(60):
        try:
            with socket.create_connection((HOST, port), timeout=1):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.5)
    webbrowser.open(url)


def bootstrap_database():
    import django
    from django.contrib.auth import get_user_model
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    return get_user_model().objects.count()


def serve_application(port):
    try:
        from waitress import serve
    except ImportError:
        from django.core.management import call_command

        call_command("runserver", f"{HOST}:{port}", use_reloader=False)
        return

    from invoice_manager.wsgi import application

    serve(application, host=HOST, port=port, threads=4)


def main():
    prepare_environment()
    user_count = bootstrap_database()
    port = find_available_port()
    target_path = "/first-time-setup/" if user_count == 0 else "/accounts/login/"
    target_url = f"http://{HOST}:{port}{target_path}"

    browser_thread = threading.Thread(
        target=wait_for_server_and_open,
        args=(target_url, port),
        daemon=True,
    )
    browser_thread.start()
    serve_application(port)


if __name__ == "__main__":
    main()
