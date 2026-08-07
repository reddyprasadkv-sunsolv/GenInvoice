# Personalised Invoice Generation Application — Project Context

This document provides a comprehensive technical overview of the **Personalised Invoice Generation Application** to enable Google Antigravity AI agents and developers to quickly understand the business domain, architecture, data models, workflows, and constraints.

---

## 1. Business Purpose & Scope

The application is a local-first, standalone web/desktop application designed for managing business billing workflows, generating professional PDF invoices, tracking multi-currency project client contracts, managing vendor/developer assignments, and exporting financial reports.

### Key Functional Capabilities
- **Multi-Company Management:** Maintain company profiles, logos, authorized signatures, GSTIN, and bank account details.
- **Client Management:** Maintain client directories with soft deletion capabilities, GSTIN requirements, and billing ledgers.
- **Project Tracking:** Manage service projects (IT Consulting, Software Development, Website Development, Digital Marketing, SEO, Branding, Maintenance), approved quotes, advance payments, and completion percentages.
- **Vendor & Developer Management:** Track developers/freelancers, role assignments to projects, cost estimates, and developer payout balances.
- **Invoice Generation & PDF Rendering:** Generate itemized invoices (INR & USD) with custom invoice numbering, auto-calculated GST (18% default, GST Included, GST Extra, or Partial GST), terms & conditions, declarations, auto amount-in-words conversion, and single-click PDF downloads.
- **Recurring Invoices:** Template-based recurring invoice scheduling (Monthly, Quarterly, Yearly).
- **Reports & Data Export:** Filterable Invoice and Project financial reports with one-click Excel (`openpyxl`) and PDF (`WeasyPrint`) exports.
- **Backup & Restore System:** Automated database snapshot creation, upload-based database restoration, and backup reminders.

---

## 2. Architecture & Tech Stack

### Core Frameworks & Libraries
- **Language:** Python 3.10.x
- **Web Framework:** Django 5.2.x
- **Database:** SQLite (`db.sqlite3`)
- **PDF Generation Engine:** `WeasyPrint` (HTML/CSS to PDF renderer)
- **Excel Export Engine:** `openpyxl`
- **WSGI Server:** `waitress`
- **Packaging Utility:** `PyInstaller` (Bundles app for macOS desktop distribution)

### Django Apps Overview
- **`invoice_manager`:** Root configuration package containing `settings.py`, root `urls.py`, `wsgi.py`, and `asgi.py`.
- **`billing`:** The primary business application containing all models, views, forms, services, validators, admin bindings, and unit tests.

---

## 3. Core Data Models & Relationships

```text
+----------------+          +-------------------+          +-------------------+
|    Company     | 1      * |      Invoice      | *      1 |      Client       |
|  (Logo, Sig,   +----------+ (Num, Date, Total,+----------+  (GSTIN, Address, |
|   Bank, GSTIN) |          |  Currency, Status)|          |    Status, SoftDel)
+----------------+          +---------+---------+          +---------+---------+
                                      | 1                            | 1
                                      |                              |
                                      | *                            | *
                            +---------+---------+          +---------+---------+
                            |   InvoiceItem     |          |      Project      |
                            | (Desc, Qty, Price,|          | (Approved Quote,  |
                            |  HSN/SAC Code)    |          |  GST Type, Status)|
                            +-------------------+          +---------+---------+
                                                                     | 1
                                                                     |
                                                                     | *
                                                           +---------+---------+
                                                           | ProjectAssignment |
                                                           | (Vendor, Role,    |
                                                           |  Cost, Payments)  |
                                                           +-------------------+
```

### Key Models (`billing/models.py`)
1. `Company`: Vendor/seller company profile with file uploads (`logo`, `authorized_signature`), GSTIN validation, and bank details.
2. `Client`: Buyer profile supporting draft/active/deleted statuses, GSTIN validation, and soft deletion (`is_deleted`, `deleted_at`, `deleted_by`).
3. `Project`: Project contract linked to a `Client`. Supports currencies (INR, USD), GST calculation modes (`WITHOUT_GST`, `GST_EXTRA`, `GST_INCLUDED`, `PARTIAL_GST`), milestone advances, and status stages.
4. `DeveloperVendor` & `ProjectAssignment`: Vendor directory and project role assignment with estimated costs and payment tracking.
5. `Invoice` & `InvoiceItem`: Financial invoice document linked to `Company`, `Client`, and optionally `Project`. Tracks subtotal, GST percentage/amount, total, payment status (`PENDING`, `PARTIALLY_PAID`, `PAID`), and generated PDF path.
6. `Payment`: Payment transaction history linked to an `Invoice`.
7. `ProjectClientPayment` & `DeveloperPayment`: Individual payment logs for project milestones and developer disbursements.
8. `HsnSacCode`: System registry for tax HSN/SAC classification codes.
9. `ApplicationSetting`: Singleton setting model for default GST percentage, invoice numbering format strings, and default terms & declarations.
10. `ActivityLog`: System event audit logging.

---

## 4. Financial & Calculation Logic

### GST Calculation Modes (`Project.calculate_project_gst_fields`)
- **`GST_EXTRA`:**  
  $$\text{Base Amount} = \text{Approved Quote}$$  
  $$\text{GST Amount} = \text{Base Amount} \times \frac{\text{GST \%}}{100}$$  
  $$\text{Total Amount} = \text{Base Amount} + \text{GST Amount}$$
- **`GST_INCLUDED`:**  
  $$\text{Total Amount} = \text{Approved Quote}$$  
  $$\text{Base Amount} = \frac{\text{Total Amount}}{1 + \frac{\text{GST \%}}{100}}$$  
  $$\text{GST Amount} = \text{Total Amount} - \text{Base Amount}$$
- **`PARTIAL_GST`:**  
  $$\text{Base Amount} = \text{Approved Quote}$$  
  $$\text{GST Amount} = \text{Partial Taxable Amount} \times \frac{\text{GST \%}}{100}$$  
  $$\text{Total Amount} = \text{Base Amount} + \text{GST Amount}$$
- **`WITHOUT_GST`:**  
  $$\text{Base Amount} = \text{Approved Quote}, \quad \text{GST Amount} = 0, \quad \text{Total Amount} = \text{Approved Quote}$$

### Money Quantization
All monetary fields use standard `Decimal` representation with 2 decimal places (`Decimal("0.01")`) and `ROUND_HALF_UP` rounding (`billing/models.py:_money`).

---

## 5. File Storage & Media Structure

All runtime media files are stored under `media/` (or `INVOICEAPP_DATA_DIR/media` when running packaged):
- `media/company_logos/`: Uploaded company logo images.
- `media/company_signatures/`: Uploaded authorized signature images.
- `media/invoices/`: Dynamically rendered PDF invoice files.
- `media/reports/`: Exported report files.
- `backups/`: ZIP/SQLite snapshot archives generated by the built-in backup engine.

---

## 6. Development & Operational Constraints

1. **Non-Destructive Operations:** Never drop database tables, delete user data, or reset migrations.
2. **Financial Precision:** Never replace `Decimal` calculations with floating-point arithmetic.
3. **Soft Deletion:** Honor `is_deleted` flags on `Client` and `Invoice` models across all queries and views.
4. **Environment Isolation:** Keep `db.sqlite3`, `media/invoices/*.pdf`, and `.env` ignored from Git.
