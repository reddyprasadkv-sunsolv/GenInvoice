# Local Invoice Generation and Management System

A standalone, local-only Django application for company/client management, invoice generation, invoice PDFs, payment tracking, reports, backups, restore, and default invoice settings. The system is designed to run on the user machine with SQLite and local folders. No AWS, Azure, Google Cloud, Firebase, Supabase, or external hosting is required.

## Technology Stack

- Python Django
- SQLite
- Django templates with Bootstrap-compatible local styling
- WeasyPrint for invoice/report PDF generation
- OpenPyXL for Excel report exports
- Waitress for stable local serving
- Local filesystem storage for uploads, PDFs, reports, and backups

## Agent Onboarding & Documentation

This repository includes specialized documentation for developer and AI agent onboarding:

- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) — Comprehensive technical context, business domain rules, model relationships, and financial formulas.
- [`AGENTS.md`](AGENTS.md) — Mandatory operating guidelines, change control workflow, and strict prohibitions for AI agents.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — System request flow, middleware sequence, data model hierarchy, and export pipeline architecture.
- [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) — Cataloged baseline issues and edge cases reserved for future targeted development.


## Installation

These commands are for local development and testing:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py create_default_admin
python manage.py runserver 127.0.0.1:8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Default local test login:

- Username: `admin`
- Password: `Admin@12345`

This default credential is only for local development/testing through `create_default_admin`. It is not auto-created by the final macOS DMG launcher and is not included in the packaged app database.

## macOS DMG Packaging

Build packaging dependencies:

```bash
python -m pip install -r requirements-packaging.txt
```

macOS packaging also requires Apple Command Line Tools:

```bash
xcode-select --install
```

Create the clean macOS package:

```bash
./build_dmg.sh
```

The packaging script builds `InvoiceApp.app`, validates that no runtime data is bundled, stages a clean README, and creates `InvoiceApp.dmg`. The script fails if it finds a bundled SQLite database, media upload, generated invoice PDF, report export, backup file, log file, default development password string, or developer-only default admin command.

The packaged launcher is `start_app.py`. It creates runtime data under `~/Documents/InvoiceApp/`, runs migrations, and opens either first-time setup or login. It does not call `create_default_admin`, reset passwords, overwrite users, or insert sample business data.

## Final DMG Data Policy

- The final `.dmg` does not include dummy data.
- The final `.dmg` does not include real company, client, invoice, project, payment, media, report, backup, or log data.
- The app creates an empty database on first launch.
- The user creates the first admin account during first-time setup.
- Existing passwords are not changed during app updates.
- User data is stored outside the app at `~/Documents/InvoiceApp/`.

## Password Policy

- The final installed app asks the user to create a password on first launch.
- App updates do not change existing passwords.
- If a password is forgotten, use Django password reset/change or administrator recovery for the local database.

## Waitress Local Server

Development server:

```bash
python manage.py runserver 127.0.0.1:8000
```

Waitress server:

```bash
waitress-serve --listen=127.0.0.1:8000 invoice_manager.wsgi:application
```

## Local Run Scripts

macOS/Linux:

```bash
./run_mac.sh
```

Windows:

```bat
run_windows.bat
```

The scripts activate `.venv` when present, run migrations, ensure the default local admin exists, and start Waitress when available. If Waitress is not installed, they fall back to Django `runserver`.

## Useful Commands

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
python manage.py test
python manage.py create_default_admin
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

## Features

- Login/logout with Django authentication
- Login protection for internal pages
- Company management with validated logo upload
- Client management with optional GSTIN validation
- GST and non-GST invoice creation
- Auto invoice numbering in the default `SUNMSU-25062026-001` style
- Multiple invoice items with backend recalculation
- Amount in Indian currency words
- Invoice preview, print, and PDF download
- Local PDF storage under `media/invoices/`
- Partial/full payment tracking and overpayment blocking
- Payment history
- Dashboard totals and filters
- Dashboard project summary cards
- Invoice search and filters
- Month-wise invoice summary
- Reports with Excel and PDF export
- Company authorized signature upload and invoice signature display
- Project management with client financial tracking
- Developers/vendors module with project assignment and payment tracking
- Project-wise, developer-wise, invoice-against-project, and profit reports
- Local backup ZIP creation and download
- Admin-only restore with ZIP validation and safety backup
- Settings page for default GST, terms, declaration, and payment terms

## Folder Structure

```text
invoice_manager/          Django project settings, URLs, WSGI, ASGI
billing/                  Main app for dashboard, company, client, invoices, reports, backup, settings
templates/                Django templates
static/                   Local CSS assets
media/company_logos/      Uploaded company logos
media/company_signatures/ Uploaded authorized company signatures
media/invoices/           Generated invoice PDFs
media/reports/            Generated Excel/PDF reports
backups/                  Local backup ZIP files
requirements.txt          Python dependencies
requirements-packaging.txt macOS packaging dependency list
run_mac.sh                macOS/Linux local start script
run_windows.bat           Windows local start script
start_app.py              macOS packaged app launcher
build_dmg.sh              Clean DMG build and validation script
packaging/README_DMG.md   README copied into the final DMG
```

Generated `media/` and `backups/` contents are local data and are ignored by git.

## Backup and Restore

Backup:

1. Log in as a superuser.
2. Open `Backup`.
3. Click `Create Backup`.
4. Download the generated `invoice_backup_YYYYMMDD_HHMMSS.zip` from the backup list.

Backup ZIP files include the SQLite database, local media files, generated invoice PDFs, generated report files, and application settings metadata.
Project data, developer/vendor data, project payments, assignments, and authorized signatures are included automatically because backups include the SQLite database and local media folder.

Restore:

1. Log in as a superuser.
2. Open `Backup`.
3. Upload a backup ZIP created by this application.
4. Review the confirmation screen.
5. Confirm restore.

Restore validates ZIP structure, blocks path traversal, rejects executable files, checks for a SQLite database, creates an automatic safety backup, then replaces the local database and media folder.

## Settings

The `Settings` page stores defaults in SQLite:

- Default GST percentage, initially `18`
- Default terms and conditions
- Default declaration
- Default payment terms
- Future-ready invoice number format placeholders
- Local URL and backup location display
- Company logo guidance

New invoices use the saved default terms/declaration and the saved GST percentage. Existing invoices are not overwritten when settings change.

## Authorized Signatures

Company records can store an optional authorized signature under `media/company_signatures/`.

- Allowed formats: PNG, JPG, JPEG, SVG
- Maximum file size: 2 MB
- Minimum dimensions: 300px by 100px
- Recommended dimensions: 600px by 200px

When uploaded, the signature appears by default in invoice preview and invoice PDF output.

## Projects and Developers / Vendors

Projects are linked to clients. A client can have multiple projects, and invoices can optionally be linked to a project. Existing invoices without a project continue to work.

Project tracking includes:

- Project type, status, priority, start/expected/actual completion dates
- Completion percentage from 0 to 100
- Estimated quote and approved quote
- Multiple client project payments
- Pending receivable calculation
- Developer/vendor assignment
- Multiple developer/vendor payments
- Pending payable calculation
- Estimated profit, approved profit, and actual cash profit

Project reports are available from `Project Reports` with Excel and PDF export.

Project and vendor safety/analytics enhancements:

- Projects and Developers/Vendors have delete confirmation pages.
- Unlinked records can be permanently deleted after confirmation.
- Linked projects are protected and marked `Cancelled` instead of being deleted.
- Linked developers/vendors are protected and marked `Inactive` instead of being deleted.
- Project status badges, completion progress bars, client fund badges, developer fund badges, and invoice payment badges are color-coded.
- Dashboard analytics include offline-friendly charts for project status, invoice payment status, receivable/payable totals, monthly invoice totals, and profit summary.

## Security Notes

- `DEBUG` defaults to local development mode through `DJANGO_DEBUG=1`.
- `DJANGO_SECRET_KEY` can be set through the environment; see `.env.example`.
- CSRF middleware is enabled for forms.
- Uploaded logos and restore ZIPs are validated.
- Backup/restore actions require a superuser.
- The SQLite database is not served through static or media URLs.
- This is a local system; do not expose it directly to the public internet.

## Troubleshooting

Migration errors:

```bash
python manage.py makemigrations
python manage.py migrate
```

WeasyPrint native dependency errors on macOS:

```bash
brew install pango
```

Static/media files not loading:

- Confirm `DEBUG=1` for local development.
- Confirm files are under the local `static/` or `media/` folders.

Developer login issue:

```bash
python manage.py create_default_admin
```

For the final DMG, use the first-time setup screen to create the admin account instead of running the development helper command.

Port already in use:

- Stop the process using port `8000`, or run with another local port:

```bash
python manage.py runserver 127.0.0.1:8001
```

Waitress not found:

```bash
pip install -r requirements.txt
```
