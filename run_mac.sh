#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ -f ".venv/bin/activate" ]; then
    . ".venv/bin/activate"
else
    echo "Virtual environment not found at .venv."
    echo "Create one with: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
fi

python manage.py migrate
python manage.py create_default_admin

echo "Local Invoice Manager: http://127.0.0.1:8000"
if command -v waitress-serve >/dev/null 2>&1; then
    waitress-serve --listen=127.0.0.1:8000 invoice_manager.wsgi:application
else
    python manage.py runserver 127.0.0.1:8000
fi
