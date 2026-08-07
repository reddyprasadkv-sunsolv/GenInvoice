# Personalised Invoice Generation Application — Architecture Documentation

This document describes the architectural design, request flow, component interactions, and data model hierarchy discovered from inspecting the **Personalised Invoice Generation Application**.

---

## 1. High-Level Architectural Flow

```text
+-------------------------------------------------------------------------+
|                              Desktop User                               |
|                  (Browser UI @ http://127.0.0.1:8000)                   |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
+-------------------------------------------------------------------------+
|                  Launcher Script / WSGI Web Server                      |
|           (start_app.py / run_mac.sh -> Waitress WSGI Server)           |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
+-------------------------------------------------------------------------+
|                         Django Security Layer                           |
|        (CsrfViewMiddleware, SessionMiddleware, AuthenticatedNoCache)    |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
+-------------------------------------------------------------------------+
|                           URL Router (urls.py)                          |
|             (invoice_manager/urls.py -> billing/urls.py)                |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
+-------------------------------------------------------------------------+
|                     Views & Form Handlers (views.py)                    |
|           (Company, Client, Invoice, Project, Vendor, Reports)          |
+-------------------------------------------------------------------------+
             │                                              │
             ▼                                              ▼
+--------------------------+                   +--------------------------+
|  Services & Utilities    |                   |    Domain Models & DB    |
|       (services.py)      |                   |    (billing/models.py    |
| ───► WeasyPrint (PDF)    | ◄───────────────► |           │              |
| ───► openpyxl (Excel)    |                   |           ▼              |
| ───► Backup Engine       |                   |     SQLite Database      |
+--------------------------+                   |       (db.sqlite3)       |
             │                                 +--------------------------+
             ▼                                              │
+--------------------------+                                │
|   Media Storage System   |                                │
| (company_logos, sigs,    | ◄──────────────────────────────┘
|  invoices PDF, backups)  |
+--------------------------+
```

---

## 2. Request Handling Pipeline

1. **Launcher & Startup (`start_app.py` / `run_mac.sh`):**
   - Prepares data directory (`~/Documents/InvoiceApp` or configured `INVOICEAPP_DATA_DIR`).
   - Ensures local runtime directories exist (`media/*`, `backups/`, `logs/`).
   - Executes non-interactive database migrations (`python manage.py migrate`).
   - Probes local network ports starting from `8000` to find an available port.
   - Automatically opens default browser to setup (`/first-time-setup/`) or login (`/accounts/login/`).
   - Launches Waitress WSGI server.

2. **Middleware & Authentication:**
   - Security headers enforced via `SecurityMiddleware` and `XFrameOptionsMiddleware`.
   - `AuthenticatedNoCacheMiddleware` (`billing/middleware.py`) prevents browser caching of sensitive financial records on logout.
   - User authentication powered by Django Auth system with custom `FirstTimeAwareLoginView`.

3. **View Logic (`billing/views.py`):**
   - Class-based views (`CompanyListView`, `ClientListView`, `InvoiceListView`, `ProjectListView`) handle listing, filtering, and detail renders.
   - Function-based views handle complex workflows (`invoice_create`, `invoice_edit`, `invoice_clone`, `project_assign_developer`, `backup_create`, `restore_confirm`).

4. **Service Layer & Rendering (`billing/services.py`):**
   - **PDF Generation:** Invoices rendered from HTML templates (`invoice_pdf.html`) to PDF via `WeasyPrint` and saved to `media/invoices/`.
   - **Excel Generation:** Reports built dynamically using `openpyxl` with custom styling, borders, and column formatting.
   - **Backup Service (`billing/backup.py`):** Creates timestamped ZIP archives containing `db.sqlite3` and `media/` assets.

---

## 3. Data Model Hierarchy & Relationships

```text
Company (1) ────< (N) Invoice (N) >──── (1) Client (1) ────< (N) Project
   │                     │                                        │
   ├── Logo              ├── InvoiceItem (N)                      ├── ProjectAssignment (N)
   └── Signature         ├── Payment (N)                          │      └── DeveloperVendor (1)
                         └── PDF File                             └── ProjectClientPayment (N)
```

- **Company to Invoice:** One company can issue multiple invoices (`PROTECT`).
- **Client to Invoice:** One client can receive multiple invoices (`PROTECT`).
- **Client to Project:** One client can have multiple projects (`PROTECT`).
- **Project to Invoice:** Invoices can optionally link to a specific project (`SET_NULL`).
- **Invoice to InvoiceItem:** One invoice has 1 or more line items (`CASCADE`).
- **Project to ProjectAssignment:** One project can have multiple assigned developers/vendors (`CASCADE`).

---

## 4. Environment & Storage Strategy

- **Database:** Local SQLite database file (`db.sqlite3`).
- **User Files:** Company logos, signatures, generated PDF invoices, and backups are saved in `media/` subdirectories.
- **Local Isolation:** Desktop execution isolates runtime data in user home documents, ensuring full portability.
