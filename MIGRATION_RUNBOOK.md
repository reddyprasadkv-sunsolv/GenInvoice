# Production SQLite → PostgreSQL Migration Runbook & Rollback Plan

This runbook outlines the operational cutover procedure and rollback strategy for migrating the Local Invoice Manager application from SQLite to PostgreSQL.

---

## Technical Specifications & Safety Mandates

- **Target Engine:** PostgreSQL 16 (Durable Managed Database, e.g. Render Managed PostgreSQL or AWS RDS).
- **Tooling:** Django management command `python manage.py migrate_operational_data`.
- **Zero Data Loss Guarantee:** Primary key and foreign key preservation with strict sequence reset and transaction rollback on error.
- **No Hardcoded Credentials:** All credentials and connection parameters passed via `DATABASE_URL` environment variable.

> [!CAUTION]
> **CRITICAL MANDATE:** DO NOT perform final production cutover into temporary or free-tier PostgreSQL databases. Production cutover requires provisioned, durable production infrastructure with automated point-in-time backups.

---

## Operational Cutover Runbook (19 Steps)

1. **Announce Maintenance Window**
   - Notify users of scheduled maintenance and application downtime.

2. **Stop Application Writes**
   - Scale down live application web services or set application to read-only mode to prevent new transactions during migration.

3. **Final SQLite Backup**
   - Create a complete, timestamped copy of `db.sqlite3` and the `media/` folder in a secure baseline backup location:
     `/Users/reddyprasadkv/Documents/invoice_app_baseline_backup/pre_postgres_migration_<timestamp>/`

4. **SHA-256 Checksum Verification**
   - Compute SHA-256 checksum of source `db.sqlite3` and backup copy.
   - Verify checksums match exactly (`Source SHA-256 == Backup SHA-256`).

5. **SQLite Integrity & Foreign Key Check**
   - Run integrity checks against the backup copy:
     ```sql
     PRAGMA integrity_check;
     PRAGMA foreign_key_check;
     ```
   - Ensure `integrity_check` returns `ok` and 0 foreign key violations exist.

6. **Provision Empty Durable PostgreSQL Database**
   - Provision a fresh, dedicated PostgreSQL 16 instance.
   - Verify the database contains 0 tables/relations.

7. **Apply Current Django Schema**
   - Execute migrations against target PostgreSQL:
     ```bash
     DATABASE_URL="postgres://user:pass@host:5432/dbname" python manage.py migrate --noinput
     ```
   - Verify all migrations are applied cleanly and system check reports 0 issues (`python manage.py check`).

8. **Import Data via Migration Tooling**
   - Execute data migration from backup SQLite copy to target PostgreSQL with PK/FK preservation:
     ```bash
     DATABASE_URL="postgres://user:pass@host:5432/dbname" python manage.py migrate_operational_data --source-sqlite /path/to/backup/db.sqlite3 --confirm
     ```

9. **Reset PostgreSQL Primary Key Sequences**
   - Sequence reset is automatically performed by `migrate_operational_data` using `setval(pg_get_serial_sequence(table, 'id'), MAX(id))`.
   - Verify for every sequence: `nextval > MAX(migrated_id)`.

10. **Reconcile Row Counts**
    - Compare model row counts between source SQLite backup and target PostgreSQL across all models:
      - Users, Companies, Clients, Projects, Developers/Vendors, ProjectAssignments, Invoices, InvoiceItems, Payments, ProjectClientPayments, DeveloperPayments, ActivityLogs, HsnSacCodes, RecurringInvoiceTemplates, RecurringInvoiceTemplateItems, ApplicationSettings.
    - Confirm zero differences for all models.

11. **Reconcile Financial Totals**
    - Calculate and verify currency-wise financial aggregates:
      - INR invoice subtotals, GST totals, and grand totals.
      - USD invoice subtotals, GST totals, and grand totals.
      - Invoice payment totals by currency.
      - Approved project quotes by currency.
      - Developer payment totals.
    - Guarantee zero decimal discrepancies (`0.00` difference).

12. **Invoice Number & Sequence Audit**
    - Verify distinct invoice numbers count matches baseline.
    - Ensure zero duplicate invoice numbers.
    - Verify standard and draft sequence counters continue correctly.

13. **Validate User Authentication Structure**
    - Confirm user account password hashes (`pbkdf2_sha256$...`) were transferred intact.
    - Test login functionality on staging/target environment.

14. **Validate Document & Report Generation (PDF & Excel)**
    - Generate sample invoice PDF on PostgreSQL environment and verify total, currency, and GST calculations match.
    - Export sample date range Excel report and verify row counts and totals.

15. **Update Production Environment Variables (`DATABASE_URL`)**
    - Set the `DATABASE_URL` config var in Render / deployment environment to point to the migrated PostgreSQL database.

16. **Deploy Updated Web Application Service**
    - Trigger production deployment and verify service status reports `LIVE`.

17. **Perform Post-Cutover Smoke Tests**
    - Verify HTTPS response, login page, static asset serving, dashboard loading, and read-only views.

18. **Retain Original SQLite Rollback Copy**
    - Do NOT delete or modify the original `db.sqlite3` or backup archives.
    - Keep source SQLite archived securely as a rollback baseline.

19. **Monitor Production Logs & Metrics**
    - Monitor application logs, database connection pools, response times, and error rates for 24-48 hours post-migration.

---

## Rollback Plan

If critical unexpected failures occur during cutover before final sign-off:

1. **Immediate Safety Freeze:**
   - Stop cutover operations and do not commit database changes.

2. **Revert Configuration:**
   - Update deployment `DATABASE_URL` or database settings to point back to the preserved SQLite database or previous backend configuration.

3. **Re-deploy Previous Application State:**
   - Deploy stable pre-migration application build to production.

4. **Verify Baseline Integrity:**
   - Verify original `db.sqlite3` remains completely untouched and intact.
   - Run `.venv/bin/python manage.py check` and run test suite against source SQLite baseline to confirm operational readiness.

5. **Post-Mortem & Incident Analysis:**
   - Review PostgreSQL logs, migration errors, and diff reports to isolate root cause before scheduling subsequent attempt.
