# Phase 5 Test Report

## Environment

- Python version: 3.10.5
- Django version: 5.2.15
- Waitress version: 3.0.2
- Database: SQLite (`db.sqlite3`)
- Operating system: macOS Darwin 25.4.0 x86_64
- Local URL: `http://127.0.0.1:8000`

## Test Results

| Test Area | Status | Remarks |
| --- | --- | --- |
| Existing Phase 1 functionality | Pass | Auth, dashboard, company, client, logo validation covered by tests. |
| Existing Phase 2 functionality | Pass | Invoice numbering, GST/non-GST totals, amount in words, invoice screens covered. |
| Existing Phase 3 functionality | Pass | Invoice PDF generation/download and missing-logo handling covered. |
| Existing Phase 4 functionality | Pass | Payments, dashboard totals, filters, month summary, Excel/PDF reports covered. |
| Backup creation | Pass | Created local ZIP backup and verified ZIP contents. |
| Backup download | Pass | Backup download returns `application/zip`. |
| Restore backup | Pass | Restored a same-state local backup successfully. |
| Restore safety backup | Pass | Restore created `invoice_backup_20260625_223453_1.zip` safety backup during smoke test. |
| Settings page | Pass | Settings save and display correctly. |
| Default GST settings | Pass | New GST invoices use saved default GST percentage. |
| Default terms/declaration | Pass | New invoice form uses saved defaults without changing existing invoices. |
| Admin-only restore access | Pass | Backup/restore routes return 403 for non-superusers and redirect anonymous users to login. |
| Security hardening | Pass | CSRF forms, safe ZIP validation, executable rejection, path traversal blocking, secure headers/cookies. |
| Waitress local run | Pass | `waitress-serve --listen=127.0.0.1:8000 invoice_manager.wsgi:application` returned `302` with `Server: waitress`. |
| Windows run script | Pass | `run_windows.bat` added with migration/default-admin/startup flow. |
| Mac/Linux run script | Pass | `run_mac.sh` added, executable, with migration/default-admin/startup flow. |
| README documentation | Pass | Final README updated with setup, commands, features, backup/restore, troubleshooting. |
| Final end-to-end testing | Pass | 32 automated tests plus manual backup/restore/Waitress smoke checks completed. |

## Commands Run

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py check
python manage.py test
waitress-serve --listen=127.0.0.1:8000 invoice_manager.wsgi:application
curl -I http://127.0.0.1:8000/
```

## Issues Found

- New invoice form settings defaults initially did not override model defaults in the rendered form.
- SQLite online backup blocked inside Django transactional tests.
- Restore would remove the `media/.gitkeep` placeholder when replacing the media folder.

## Fixes Applied

- Invoice form now sets explicit initial values for new invoice terms/declaration.
- Backup service copies file-based local SQLite databases and avoids the blocking online backup path for in-memory test databases.
- Restore recreates `media/.gitkeep` after media replacement.

## Final Confirmation

Phase 5 is complete. The Local Invoice Generation System is fully working as a standalone local Django application with backup, restore, settings, security hardening, Waitress support, run scripts, documentation, and final tests.
