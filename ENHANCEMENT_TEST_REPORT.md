# Enhancement Test Report

## Environment

- Python version: 3.10.5
- Django version: 5.2.15
- Database: SQLite (`db.sqlite3`)
- Operating system: macOS Darwin 25.4.0 x86_64
- Local URL: `http://127.0.0.1:8000`

## Test Results

| Test Area | Status | Remarks |
| --- | --- | --- |
| Digital Marketing recurring project | Pass | Recurring billing type saves for Digital Marketing projects. |
| Project date fields optional for recurring | Pass | Recurring Digital Marketing projects save without start/expected/actual dates. |
| Project save draft | Pass | Draft projects save with only client and project name. |
| Client soft delete | Pass | Clients are soft deleted through login-protected POST confirmation. |
| Client restore | Pass | Deleted clients restore through POST and return to normal dropdowns. |
| Invoice save draft | Pass | Draft invoices save with company, client, and invoice date only. |
| Draft invoice edit | Pass | Draft invoices reopen in edit mode and accept added details/items. |
| Draft to final invoice | Pass | Draft conversion generates the normal invoice number and recalculates totals. |
| Invoice soft delete | Pass | Invoices are soft deleted and hidden from default invoice list/dashboard/report totals. |
| Invoice restore | Pass | Deleted invoices restore and return to the active invoice list. |
| GST optional invoice | Pass | GST can be disabled even when the company has a GSTIN. |
| GST blocked without company GSTIN | Pass | Backend forces GST off when company GSTIN is empty. |
| GST report filter | Pass | View, Excel export, and PDF export respect GST invoice filter. |
| Non-GST report filter | Pass | View and PDF export respect non-GST invoice filter. |
| Dashboard totals | Pass | Dashboard totals use final, non-deleted invoices and show draft/project counters. |
| Existing functionality | Pass | Existing company, client, invoice, payment, PDF, project, report, backup/restore, and settings flows remain covered by regression tests. |

## Commands Run

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver
```

## Manual Smoke Checks

- Logged in successfully with `admin` / `Admin@12345`.
- Browser-rendered pages returned HTTP 200 for Dashboard, Clients, Invoices, Invoice Add, Projects, Project Add, Reports, and Project Reports.
- Verified new visible controls: Active/Deleted client filter, invoice view filter, GST Type filters, Include Deleted report option, Save Draft buttons, Apply GST selector, and soft-delete buttons.
- Verified dev server is running at `http://127.0.0.1:8000`.

## Issues Found

- Existing templates initially needed one custom tag load for the new invoice status badge. Fixed immediately.
- Auto-generated labels for GST Type were normalized to exact UI text.

## Fixes Applied

- Added safe migrations for project billing type, project Draft status, client soft delete fields, invoice draft/deleted fields, and invoice `apply_gst`.
- Added data migration to set `apply_gst` from historical `gst_amount`.
- Added backend draft/final invoice save paths, draft invoice numbering, final conversion numbering, and GST enforcement.
- Added client/invoice soft delete and restore actions with POST side effects and CSRF-protected forms.
- Updated dashboard, invoice reports, payment reports, project reports, and monthly summaries to exclude draft/deleted invoices by default.
- Added focused regression tests for the new enhancement scope.

## Final Confirmation

The enhancement is working correctly without breaking existing functionality. The full suite passes with 50 tests, and the local server is running.
