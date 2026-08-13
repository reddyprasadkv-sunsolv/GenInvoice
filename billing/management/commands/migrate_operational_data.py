import os
import sqlite3
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from billing.models import (
    ActivityLog,
    ApplicationSetting,
    Client,
    Company,
    DeveloperPayment,
    DeveloperVendor,
    HsnSacCode,
    Invoice,
    InvoiceItem,
    Payment,
    Project,
    ProjectAssignment,
    ProjectClientPayment,
    RecurringInvoiceTemplate,
    RecurringInvoiceTemplateItem,
)


class Command(BaseCommand):
    help = "Migrate operational SQLite business data to PostgreSQL with PK preservation and validation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-sqlite",
            type=str,
            required=True,
            help="Absolute path to the source db.sqlite3 file (must be a verified backup copy).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Explicit confirmation required to execute migration.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform all validation and transactional import, then roll back.",
        )

    def handle(self, *args, **options):
        source_path = Path(options["source_sqlite"]).resolve()
        confirm = options["confirm"]
        dry_run = options["dry_run"]

        self.stdout.write(self.style.MIGRATE_HEADING("=== OPERATIONAL DATA MIGRATION ==="))
        self.stdout.write(f"Source SQLite: {source_path}")
        self.stdout.write(f"Target Vendor: {connection.vendor}")

        if not source_path.exists():
            raise CommandError(f"Source SQLite file does not exist at {source_path}")

        # Guard: Check connection vendor
        if connection.vendor != "postgresql":
            raise CommandError(f"Target database engine must be PostgreSQL, but got '{connection.vendor}'.")

        # Guard: Check host to prevent accidental production overwrite
        db_host = connection.settings_dict.get("HOST", "")
        if "onrender.com" in db_host:
            raise CommandError("SAFETY BLOCK: Target database host is Render production. Migration to live Render DB is disabled.")

        # Guard: Check SQLite integrity
        source_conn = sqlite3.connect(source_path)
        source_conn.row_factory = sqlite3.Row
        cursor = source_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        integrity = cursor.fetchone()[0]
        if integrity != "ok":
            raise CommandError(f"Source SQLite integrity check failed: {integrity}")

        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()
        if fk_violations:
            raise CommandError(f"Source SQLite has {len(fk_violations)} foreign key violations.")

        # Guard: Check empty target
        if (
            Company.objects.exists()
            or Client.objects.exists()
            or Invoice.objects.exists()
            or Project.objects.exists()
        ):
            raise CommandError("SAFETY BLOCK: Target PostgreSQL database already contains business records. Aborting migration.")

        if not confirm and not dry_run:
            raise CommandError("Pass --confirm to execute migration or --dry-run to simulate transactional import.")

        self.stdout.write(self.style.SUCCESS("All pre-migration safety checks PASSED."))

        try:
            with transaction.atomic():
                self._migrate_users(cursor)
                self._migrate_companies(cursor)
                self._migrate_clients(cursor)
                self._migrate_projects(cursor)
                self._migrate_vendors(cursor)
                self._migrate_assignments(cursor)
                self._migrate_invoices(cursor)
                self._migrate_hsn_codes(cursor)
                self._migrate_invoice_items(cursor)
                self._migrate_payments(cursor)
                self._migrate_project_client_payments(cursor)
                self._migrate_developer_payments(cursor)
                self._migrate_activity_logs(cursor)
                self._migrate_recurring_templates(cursor)
                self._migrate_recurring_template_items(cursor)
                self._migrate_app_settings(cursor)

                self._reset_sequences()

                # Reconcile counts
                self._reconcile_counts(cursor)

                if dry_run:
                    self.stdout.write(self.style.WARNING("DRY RUN MODE: Rolling back transaction..."))
                    transaction.set_rollback(True)
                else:
                    self.stdout.write(self.style.SUCCESS("MIGRATION COMMITTED SUCCESSFULLY."))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Migration failed with error: {exc}"))
            raise CommandError(f"Migration aborted and transaction rolled back: {exc}") from exc

    def _migrate_users(self, cursor):
        User = get_user_model()
        cursor.execute("SELECT * FROM auth_user")
        count = 0
        for row in cursor.fetchall():
            d = dict(row)
            if not User.objects.filter(pk=d["id"]).exists():
                User.objects.create(
                    id=d["id"],
                    password=d["password"],
                    last_login=d["last_login"],
                    is_superuser=bool(d["is_superuser"]),
                    username=d["username"],
                    first_name=d["first_name"],
                    last_name=d["last_name"],
                    email=d["email"],
                    is_staff=bool(d["is_staff"]),
                    is_active=bool(d["is_active"]),
                    date_joined=d["date_joined"],
                )
                count += 1
        self.stdout.write(f"Migrated Users: {count}")

    def _migrate_companies(self, cursor):
        cursor.execute("SELECT * FROM billing_company")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(Company(
                id=d["id"],
                company_name=d["company_name"],
                address=d["address"],
                country=d["country"],
                state=d["state"],
                city=d["city"],
                pin_code=d["pin_code"],
                gstin=d["gstin"] or "",
                bank_name=d["bank_name"],
                bank_account_number=d["bank_account_number"],
                bank_branch=d["bank_branch"],
                ifsc_code=d["ifsc_code"],
                account_name=d["account_name"],
                logo=d["logo"] or "",
                authorized_signature=d["authorized_signature"] or "",
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        Company.objects.bulk_create(items)
        self.stdout.write(f"Migrated Companies: {len(items)}")

    def _migrate_clients(self, cursor):
        cursor.execute("SELECT * FROM billing_client")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(Client(
                id=d["id"],
                client_name=d["client_name"],
                address=d["address"],
                country=d["country"],
                state=d["state"],
                city=d["city"],
                pin_code=d["pin_code"],
                gstin=d["gstin"] or "",
                requires_gst_invoice=bool(d["requires_gst_invoice"]),
                client_status=d["client_status"],
                is_deleted=bool(d["is_deleted"]),
                deleted_at=d["deleted_at"],
                deleted_by_id=d["deleted_by_id"],
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        Client.objects.bulk_create(items)
        self.stdout.write(f"Migrated Clients: {len(items)}")

    def _migrate_projects(self, cursor):
        cursor.execute("SELECT * FROM billing_project")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(Project(
                id=d["id"],
                project_id=d["project_id"] or "",
                project_name=d["project_name"],
                client_id=d["client_id"],
                project_requirement=d["project_requirement"],
                project_type=d["project_type"],
                billing_type=d["billing_type"],
                custom_project_type=d["custom_project_type"] or "",
                project_description=d["project_description"] or "",
                start_date=d["start_date"],
                expected_completion_date=d["expected_completion_date"],
                actual_completion_date=d["actual_completion_date"],
                project_status=d["project_status"],
                completion_percentage=d["completion_percentage"],
                priority=d["priority"],
                estimated_quote=Decimal(str(d["estimated_quote"] or "0.00")),
                approved_quote=Decimal(str(d["approved_quote"] or "0.00")),
                currency=d["currency"] or "INR",
                client_amount_gst_type=d["client_amount_gst_type"] or "WITHOUT_GST",
                project_gst_percentage=Decimal(str(d["project_gst_percentage"] or "18.00")),
                partial_gst_taxable_amount=Decimal(str(d["partial_gst_taxable_amount"] or "0.00")),
                project_base_amount=Decimal(str(d["project_base_amount"] or "0.00")),
                project_gst_amount=Decimal(str(d["project_gst_amount"] or "0.00")),
                project_total_with_gst=Decimal(str(d["project_total_with_gst"] or "0.00")),
                client_advance_amount_received=Decimal(str(d["client_advance_amount_received"] or "0.00")),
                client_advance_received_date=d["client_advance_received_date"],
                client_next_advance_amount=Decimal(str(d["client_next_advance_amount"] or "0.00")),
                client_next_advance_expected_date=d["client_next_advance_expected_date"],
                client_total_amount_received=Decimal(str(d["client_total_amount_received"] or "0.00")),
                client_pending_amount=Decimal(str(d["client_pending_amount"] or "0.00")),
                client_payment_remarks=d["client_payment_remarks"] or "",
                remarks=d["remarks"] or "",
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        Project.objects.bulk_create(items)
        self.stdout.write(f"Migrated Projects: {len(items)}")

    def _migrate_vendors(self, cursor):
        cursor.execute("SELECT * FROM billing_developervendor")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(DeveloperVendor(
                id=d["id"],
                name=d["name"],
                vendor_type=d["vendor_type"],
                contact_person=d["contact_person"] or "",
                email=d["email"] or "",
                phone_number=d["phone_number"] or "",
                address=d["address"] or "",
                country=d["country"] or "",
                state=d["state"] or "",
                city=d["city"] or "",
                pin_code=d["pin_code"] or "",
                gstin=d["gstin"] or "",
                pan=d["pan"] or "",
                bank_details=d["bank_details"] or "",
                notes=d["notes"] or "",
                status=d["status"],
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        DeveloperVendor.objects.bulk_create(items)
        self.stdout.write(f"Migrated Developers/Vendors: {len(items)}")

    def _migrate_assignments(self, cursor):
        cursor.execute("SELECT * FROM billing_projectassignment")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(ProjectAssignment(
                id=d["id"],
                project_id=d["project_id"],
                developer_vendor_id=d["developer_vendor_id"],
                assigned_role=d["assigned_role"],
                work_description=d["work_description"] or "",
                developer_cost_estimate=Decimal(str(d["developer_cost_estimate"] or "0.00")),
                developer_final_project_cost=Decimal(str(d["developer_final_project_cost"] or "0.00")),
                advance_amount_sent=Decimal(str(d["advance_amount_sent"] or "0.00")),
                advance_sent_date=d["advance_sent_date"],
                next_advance_amount_to_send=Decimal(str(d["next_advance_amount_to_send"] or "0.00")),
                next_advance_expected_date=d["next_advance_expected_date"],
                total_amount_paid_to_developer=Decimal(str(d["total_amount_paid_to_developer"] or "0.00")),
                pending_amount_to_developer=Decimal(str(d["pending_amount_to_developer"] or "0.00")),
                assignment_status=d["assignment_status"],
                remarks=d["remarks"] or "",
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        ProjectAssignment.objects.bulk_create(items)
        self.stdout.write(f"Migrated ProjectAssignments: {len(items)}")

    def _migrate_invoices(self, cursor):
        cursor.execute("SELECT * FROM billing_invoice")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(Invoice(
                id=d["id"],
                invoice_number=d["invoice_number"],
                company_id=d["company_id"],
                client_id=d["client_id"],
                project_id=d["project_id"],
                invoice_date=d["invoice_date"],
                subject=d["subject"] or "",
                currency=d["currency"] or "INR",
                apply_gst=bool(d["apply_gst"]),
                subtotal=Decimal(str(d["subtotal"] or "0.00")),
                gst_percentage=Decimal(str(d["gst_percentage"] or "0.00")),
                gst_amount=Decimal(str(d["gst_amount"] or "0.00")),
                total_amount=Decimal(str(d["total_amount"] or "0.00")),
                amount_in_words=d["amount_in_words"] or "",
                terms_and_conditions=d["terms_and_conditions"],
                declaration=d["declaration"],
                payment_status=d["payment_status"],
                invoice_status=d["invoice_status"],
                is_deleted=bool(d["is_deleted"]),
                deleted_at=d["deleted_at"],
                deleted_by_id=d["deleted_by_id"],
                received_amount=Decimal(str(d["received_amount"] or "0.00")),
                pending_amount=Decimal(str(d["pending_amount"] or "0.00")),
                pdf_file=d["pdf_file"] or "",
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        Invoice.objects.bulk_create(items)
        self.stdout.write(f"Migrated Invoices: {len(items)}")

    def _migrate_hsn_codes(self, cursor):
        cursor.execute("SELECT * FROM billing_hsnsaccode")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(HsnSacCode(
                id=d["id"],
                code=d["code"],
                description=d["description"],
            ))
        HsnSacCode.objects.bulk_create(items)
        self.stdout.write(f"Migrated HSN/SAC Codes: {len(items)}")

    def _migrate_invoice_items(self, cursor):
        cursor.execute("SELECT * FROM billing_invoiceitem")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(InvoiceItem(
                id=d["id"],
                invoice_id=d["invoice_id"],
                serial_number=d["serial_number"],
                description=d["description"],
                hsn_sac_code_id=d["hsn_sac_code_id"],
                item_price=Decimal(str(d["item_price"] or "0.00")),
                quantity=Decimal(str(d["quantity"] or "1.00")),
                total=Decimal(str(d["total"] or "0.00")),
            ))
        InvoiceItem.objects.bulk_create(items)
        self.stdout.write(f"Migrated InvoiceItems: {len(items)}")

    def _migrate_payments(self, cursor):
        cursor.execute("SELECT * FROM billing_payment")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(Payment(
                id=d["id"],
                invoice_id=d["invoice_id"],
                received_amount=Decimal(str(d["received_amount"] or "0.00")),
                payment_date=d["payment_date"],
                payment_mode=d["payment_mode"],
                remarks=d["remarks"] or "",
                created_at=d["created_at"],
            ))
        Payment.objects.bulk_create(items)
        self.stdout.write(f"Migrated Invoice Payments: {len(items)}")

    def _migrate_project_client_payments(self, cursor):
        cursor.execute("SELECT * FROM billing_projectclientpayment")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(ProjectClientPayment(
                id=d["id"],
                project_id=d["project_id"],
                amount_received=Decimal(str(d["amount_received"] or "0.00")),
                payment_date=d["payment_date"],
                payment_mode=d["payment_mode"],
                payment_type=d["payment_type"],
                remarks=d["remarks"] or "",
                created_at=d["created_at"],
            ))
        ProjectClientPayment.objects.bulk_create(items)
        self.stdout.write(f"Migrated Project Client Payments: {len(items)}")

    def _migrate_developer_payments(self, cursor):
        cursor.execute("SELECT * FROM billing_developerpayment")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(DeveloperPayment(
                id=d["id"],
                project_assignment_id=d["project_assignment_id"],
                amount_paid=Decimal(str(d["amount_paid"] or "0.00")),
                payment_date=d["payment_date"],
                payment_mode=d["payment_mode"],
                payment_type=d["payment_type"],
                remarks=d["remarks"] or "",
                created_at=d["created_at"],
            ))
        DeveloperPayment.objects.bulk_create(items)
        self.stdout.write(f"Migrated Developer Payments: {len(items)}")

    def _migrate_activity_logs(self, cursor):
        cursor.execute("SELECT * FROM billing_activitylog")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(ActivityLog(
                id=d["id"],
                action=d["action"],
                module=d["module"],
                description=d["description"],
                object_id=d["object_id"],
                created_by_id=d["created_by_id"],
                created_at=d["created_at"],
            ))
        ActivityLog.objects.bulk_create(items)
        self.stdout.write(f"Migrated ActivityLogs: {len(items)}")

    def _migrate_recurring_templates(self, cursor):
        cursor.execute("SELECT * FROM billing_recurringinvoicetemplate")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(RecurringInvoiceTemplate(
                id=d["id"],
                company_id=d["company_id"],
                client_id=d["client_id"],
                project_id=d["project_id"],
                title=d["title"],
                frequency=d["frequency"],
                next_invoice_date=d["next_invoice_date"],
                apply_gst=bool(d["apply_gst"]),
                is_active=bool(d["is_active"]),
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            ))
        RecurringInvoiceTemplate.objects.bulk_create(items)
        self.stdout.write(f"Migrated Recurring Templates: {len(items)}")

    def _migrate_recurring_template_items(self, cursor):
        cursor.execute("SELECT * FROM billing_recurringinvoicetemplateitem")
        items = []
        for row in cursor.fetchall():
            d = dict(row)
            items.append(RecurringInvoiceTemplateItem(
                id=d["id"],
                template_id=d["template_id"],
                description=d["description"],
                hsn_sac_code_id=d["hsn_sac_code_id"],
                item_price=Decimal(str(d["item_price"] or "0.00")),
                quantity=Decimal(str(d["quantity"] or "1.00")),
            ))
        RecurringInvoiceTemplateItem.objects.bulk_create(items)
        self.stdout.write(f"Migrated Recurring Template Items: {len(items)}")

    def _migrate_app_settings(self, cursor):
        cursor.execute("SELECT * FROM billing_applicationsetting")
        for row in cursor.fetchall():
            d = dict(row)
            ApplicationSetting.objects.update_or_create(
                id=d["id"],
                defaults={
                    "default_gst_percentage": Decimal(str(d["default_gst_percentage"] or "18.00")),
                    "default_terms_and_conditions": d["default_terms_and_conditions"],
                    "default_declaration": d["default_declaration"],
                    "default_payment_terms": d["default_payment_terms"],
                    "backup_reminder_dismissed_on": d["backup_reminder_dismissed_on"],
                    "invoice_number_format": d["invoice_number_format"],
                    "date_separator": d["date_separator"] or "",
                    "prefix_separator": d["prefix_separator"] or "-",
                    "running_sequence_length": d["running_sequence_length"],
                },
            )
        self.stdout.write("Migrated ApplicationSettings")

    def _reset_sequences(self):
        with connection.cursor() as pg_cursor:
            models = [
                get_user_model(),
                Company,
                Client,
                Project,
                DeveloperVendor,
                ProjectAssignment,
                Invoice,
                HsnSacCode,
                InvoiceItem,
                Payment,
                ProjectClientPayment,
                DeveloperPayment,
                ActivityLog,
                RecurringInvoiceTemplate,
                RecurringInvoiceTemplateItem,
                ApplicationSetting,
            ]
            for m in models:
                table = m._meta.db_table
                sql = f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table};"
                try:
                    pg_cursor.execute(sql)
                except Exception as exc:
                    self.stdout.write(f"Sequence reset warning for {table}: {exc}")

    def _reconcile_counts(self, cursor):
        models_tables = [
            (get_user_model(), "auth_user"),
            (Company, "billing_company"),
            (Client, "billing_client"),
            (Project, "billing_project"),
            (DeveloperVendor, "billing_developervendor"),
            (ProjectAssignment, "billing_projectassignment"),
            (Invoice, "billing_invoice"),
            (InvoiceItem, "billing_invoiceitem"),
            (Payment, "billing_payment"),
            (ProjectClientPayment, "billing_projectclientpayment"),
            (DeveloperPayment, "billing_developerpayment"),
            (ActivityLog, "billing_activitylog"),
            (HsnSacCode, "billing_hsnsaccode"),
            (RecurringInvoiceTemplate, "billing_recurringinvoicetemplate"),
            (RecurringInvoiceTemplateItem, "billing_recurringinvoicetemplateitem"),
            (ApplicationSetting, "billing_applicationsetting"),
        ]
        self.stdout.write(self.style.MIGRATE_HEADING("=== RECONCILIATION AUDIT ==="))
        all_matched = True
        for model, table in models_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            sq_count = cursor.fetchone()[0]
            pg_count = model.objects.count()
            diff = pg_count - sq_count
            status = "OK" if diff == 0 else "MISMATCH"
            if diff != 0:
                all_matched = False
            self.stdout.write(f"Model {model.__name__:<30} SQLite: {sq_count:<4} PG: {pg_count:<4} Diff: {diff:<2} [{status}]")

        if not all_matched:
            raise CommandError("Reconciliation failed: row count mismatch detected.")
