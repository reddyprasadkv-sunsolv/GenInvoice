@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo Virtual environment not found at .venv.
    echo Create one with: py -m venv .venv ^& .venv\Scripts\activate ^& pip install -r requirements.txt
)

python manage.py migrate
python manage.py create_default_admin

echo Local Invoice Manager: http://127.0.0.1:8000
where waitress-serve >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    waitress-serve --listen=127.0.0.1:8000 invoice_manager.wsgi:application
) else (
    python manage.py runserver 127.0.0.1:8000
)
