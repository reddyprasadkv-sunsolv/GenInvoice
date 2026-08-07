import io
import os
import struct
import shutil
import tempfile
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import Client as TestClient, TestCase, override_settings
from django.urls import reverse

from .forms import ClientForm, CompanyForm, DeveloperVendorForm, InvoiceForm, ProjectForm
from .models import (
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
from .services import (
    amount_to_indian_words,
    client_fund_status,
    completion_bar_class,
    developer_fund_status,
    generate_invoice_number,
    invoice_title,
    invoice_status_badge_class,
    amount_to_currency_words,
    project_financial_summary,
    project_status_badge_class,
    recalculate_project_client_payments,
)
from .templatetags.currency_filters import format_currency, format_inr


def png_bytes(width=300, height=150):
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00" * 24
    )


def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


VALID_GSTIN = "36AADC07549J1ZZ"
LOWERCASE_GSTIN = "36aadc07549j1zz"
INVALID_GSTIN = "36AADC07549J1Z"
SPECIAL_CHAR_GSTIN = "36AADC07549J1Z@"


class FirstTimeAdminSetupTests(TestCase):
    def test_login_redirects_to_setup_when_no_users_exist(self):
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("first_time_setup"))

    def test_first_time_setup_creates_superuser_and_redirects_to_login(self):
        response = self.client.post(
            reverse("first_time_setup"),
            {
                "username": "owner",
                "email": "owner@example.com",
                "password": "Strong@123",
                "confirm_password": "Strong@123",
            },
        )
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        user = get_user_model().objects.get(username="owner")
        self.assertEqual(user.email, "owner@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("Strong@123"))

    def test_first_time_setup_rejects_weak_password(self):
        response = self.client.post(
            reverse("first_time_setup"),
            {
                "username": "owner",
                "email": "",
                "password": "weakpass",
                "confirm_password": "weakpass",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password must include at least one capital letter.")
        self.assertFalse(get_user_model().objects.exists())

    def test_first_time_setup_is_disabled_after_user_exists(self):
        get_user_model().objects.create_user(username="owner", password="Strong@123")
        response = self.client.get(reverse("first_time_setup"))
        self.assertRedirects(response, reverse("login"))


class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_dashboard_opens_after_login(self):
        self.client.login(username="owner", password="secure-test-password-123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Raised invoice amount")
        self.assertContains(response, "Received Amount")
        self.assertContains(response, "₹0")
        self.assertEqual(response.context["received_amount"], Decimal("0.00"))
        self.assertContains(response, 'class="user-menu-button"', html=False)
        self.assertContains(response, "Signed in as: owner")
        self.assertContains(response, "backLogoutForm")
        self.assertNotContains(response, "sidebar-logout")
        self.assertIn("no-cache", response.headers.get("Cache-Control", ""))

    def test_logout_redirects_to_login(self):
        self.client.login(username="owner", password="secure-test-password-123")
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))


class CurrencyFilterTests(TestCase):
    def test_inr_formats_indian_number_groups_and_decimals(self):
        self.assertEqual(format_inr(Decimal("523000.00")), "₹5,23,000")
        self.assertEqual(format_inr(Decimal("523000.50")), "₹5,23,000.50")
        self.assertEqual(format_inr(1000000), "₹10,00,000")
        self.assertEqual(format_inr(None), "₹0")
        self.assertEqual(format_inr(Decimal("-1234567.10")), "-₹12,34,567.10")

    def test_currency_format_supports_usd(self):
        self.assertEqual(format_currency(Decimal("5230.00"), "USD"), "$5,230")
        self.assertEqual(format_currency(Decimal("85132.66"), "USD"), "$85,132.66")
        self.assertEqual(format_currency(None, "USD"), "$0")
        self.assertEqual(format_currency(Decimal("-42.30"), "USD"), "-$42.30")

    def test_create_default_admin_command_is_idempotent(self):
        call_command("create_default_admin", verbosity=0)
        call_command("create_default_admin", verbosity=0)
        User = get_user_model()
        self.assertEqual(User.objects.filter(username="admin").count(), 1)
        admin = User.objects.get(username="admin")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("Admin@12345"))

    def test_create_default_admin_does_not_reset_existing_password(self):
        User = get_user_model()
        User.objects.create_user(
            username="admin",
            password="CustomAdminPassword123",
            is_staff=True,
            is_superuser=True,
        )
        call_command("create_default_admin", verbosity=0)
        admin = User.objects.get(username="admin")
        self.assertTrue(admin.check_password("CustomAdminPassword123"))


class CompanyFormTests(TestCase):
    def test_gstin_is_optional(self):
        form = CompanyForm(
            data={
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_gstin_validates_when_entered(self):
        form = CompanyForm(
            data={
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "INVALID",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("gstin", form.errors)
        self.assertIn("Example: 36AADC07549J1ZZ", form.errors["gstin"][0])

    def test_company_gstin_accepts_alphanumeric_and_normalizes_uppercase(self):
        form = CompanyForm(
            data={
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": LOWERCASE_GSTIN,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["gstin"], VALID_GSTIN)
        self.assertEqual(form.fields["gstin"].label, "GSTIN")
        self.assertEqual(form.fields["gstin"].widget.attrs["maxlength"], "15")
        self.assertEqual(form.fields["gstin"].widget.attrs["placeholder"], "Example: 36AADC07549J1ZZ")

    def test_company_bank_details_and_ifsc_normalize(self):
        form = CompanyForm(
            data={
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
                "bank_name": "State Bank of India",
                "bank_account_number": "123456789012",
                "bank_branch": "MG Road",
                "ifsc_code": "sbin0001234",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["ifsc_code"], "SBIN0001234")

    def test_company_invalid_ifsc_is_blocked(self):
        form = CompanyForm(
            data={
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
                "ifsc_code": "INVALID",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Enter a valid IFSC code. Example: SBIN0001234", form.errors["ifsc_code"][0])

    def test_logo_rejects_small_image(self):
        form = CompanyForm(
            data={
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
            },
            files={"logo": SimpleUploadedFile("logo.png", png_bytes(200, 100), content_type="image/png")},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)


class GSTINValidationTests(TestCase):
    def test_client_gstin_accepts_alphanumeric_and_normalizes_uppercase(self):
        form = ClientForm(
            data={
                "client_name": "Northwind Services",
                "address": "45 Lake View",
                "country": "India",
                "state": "Maharashtra",
                "city": "Mumbai",
                "pin_code": "400001",
                "gstin": LOWERCASE_GSTIN,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["gstin"], VALID_GSTIN)
        self.assertEqual(form.fields["gstin"].label, "GSTIN")

    def test_client_gstin_with_less_than_15_characters_is_blocked(self):
        form = ClientForm(
            data={
                "client_name": "Northwind Services",
                "address": "45 Lake View",
                "country": "India",
                "state": "Maharashtra",
                "city": "Mumbai",
                "pin_code": "400001",
                "gstin": INVALID_GSTIN,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Enter a valid 15-character GSTIN using only letters and numbers.", form.errors["gstin"][0])

    def test_client_gstin_blocks_special_characters(self):
        form = ClientForm(
            data={
                "client_name": "Northwind Services",
                "address": "45 Lake View",
                "country": "India",
                "state": "Maharashtra",
                "city": "Mumbai",
                "pin_code": "400001",
                "gstin": SPECIAL_CHAR_GSTIN,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("gstin", form.errors)

    def test_developer_vendor_gstin_accepts_alphanumeric_and_normalizes_uppercase(self):
        form = DeveloperVendorForm(
            data={
                "name": "Build Partner",
                "vendor_type": DeveloperVendor.VendorType.COMPANY,
                "contact_person": "",
                "email": "",
                "phone_number": "",
                "address": "",
                "country": "",
                "state": "",
                "city": "",
                "pin_code": "",
                "gstin": LOWERCASE_GSTIN,
                "pan": "",
                "bank_details": "",
                "notes": "",
                "status": DeveloperVendor.VendorStatus.ACTIVE,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["gstin"], VALID_GSTIN)
        self.assertEqual(form.fields["gstin"].label, "GSTIN")

    def test_model_save_normalizes_gstin_and_full_clean_validates(self):
        company = Company.objects.create(
            company_name="Acme Traders",
            address="12 Market Road",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin=LOWERCASE_GSTIN,
        )
        self.assertEqual(company.gstin, VALID_GSTIN)
        company.gstin = SPECIAL_CHAR_GSTIN
        with self.assertRaises(ValidationError):
            company.full_clean()


class GSTINLabelRenderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")

    def test_add_forms_show_gstin_label(self):
        for url_name in ["company_add", "client_add", "developer_vendor_add"]:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, ">GSTIN</label>", html=False)
                self.assertNotContains(response, ">Gstin</label>", html=False)


class ClientCrudTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")

    def client_payload(self, **overrides):
        data = {
            "client_name": "Northwind Services",
            "address": "45 Lake View",
            "country": "India",
            "state": "Maharashtra",
            "city": "Mumbai",
            "pin_code": "400001",
            "gstin": "",
        }
        data.update(overrides)
        return data

    def test_user_can_create_client_without_gstin(self):
        response = self.client.post(
            reverse("client_add"),
            self.client_payload(),
        )
        self.assertEqual(response.status_code, 302)
        client_record = Client.objects.get(client_name="Northwind Services")
        self.assertEqual(client_record.client_status, Client.ClientStatus.ACTIVE)

    def test_user_can_create_client_with_lowercase_gstin_saved_uppercase(self):
        response = self.client.post(
            reverse("client_add"),
            self.client_payload(gstin=LOWERCASE_GSTIN),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Client.objects.get(client_name="Northwind Services").gstin, VALID_GSTIN)

    def test_user_sees_error_for_invalid_client_gstin(self):
        response = self.client.post(
            reverse("client_add"),
            self.client_payload(gstin=INVALID_GSTIN),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Example: 36AADC07549J1ZZ")

    def test_save_draft_client_with_only_name(self):
        response = self.client.post(
            reverse("client_add"),
            {"client_name": "Draft Client", "client_action": "draft"},
        )
        self.assertEqual(response.status_code, 302)
        client_record = Client.objects.get(client_name="Draft Client")
        self.assertEqual(client_record.client_status, Client.ClientStatus.DRAFT)
        self.assertFalse(client_record.is_deleted)
        self.assertEqual(client_record.address, "")

        draft_list = self.client.get(reverse("client_list"), {"status": "draft"})
        self.assertContains(draft_list, "Draft Client")
        active_list = self.client.get(reverse("client_list"), {"status": "active"})
        self.assertNotIn(client_record, active_list.context["clients"])

    def test_draft_client_can_be_edited_and_converted_to_active(self):
        self.client.post(
            reverse("client_add"),
            {"client_name": "Draft Client", "client_action": "draft"},
        )
        client_record = Client.objects.get(client_name="Draft Client")

        edit_page = self.client.get(reverse("client_edit", kwargs={"pk": client_record.pk}))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, "Save Draft")
        self.assertContains(edit_page, "Convert to Active")

        invalid_active = self.client.post(
            reverse("client_edit", kwargs={"pk": client_record.pk}),
            {"client_name": "Draft Client", "client_action": "active"},
        )
        self.assertEqual(invalid_active.status_code, 200)
        self.assertContains(invalid_active, "This field is required")
        client_record.refresh_from_db()
        self.assertEqual(client_record.client_status, Client.ClientStatus.DRAFT)

        valid_active = self.client.post(
            reverse("client_edit", kwargs={"pk": client_record.pk}),
            self.client_payload(client_name="Draft Client", client_action="active"),
        )
        self.assertEqual(valid_active.status_code, 302)
        client_record.refresh_from_db()
        self.assertEqual(client_record.client_status, Client.ClientStatus.ACTIVE)

    def test_draft_clients_are_excluded_from_invoice_and_project_dropdowns(self):
        draft_client = Client.objects.create(
            client_name="Draft Client",
            address="",
            country="",
            state="",
            city="",
            pin_code="",
            client_status=Client.ClientStatus.DRAFT,
        )
        active_client = Client.objects.create(
            client_name="Active Client",
            address="45 Lake View",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            client_status=Client.ClientStatus.ACTIVE,
        )

        invoice_clients = InvoiceForm().fields["client"].queryset
        project_clients = ProjectForm().fields["client"].queryset
        self.assertIn(active_client, invoice_clients)
        self.assertNotIn(draft_client, invoice_clients)
        self.assertIn(active_client, project_clients)
        self.assertNotIn(draft_client, project_clients)

    def test_soft_delete_sets_deleted_status_and_restore_sets_active(self):
        client_record = Client.objects.create(**self.client_payload())
        response = self.client.post(reverse("client_soft_delete", kwargs={"pk": client_record.pk}))
        self.assertEqual(response.status_code, 302)
        client_record.refresh_from_db()
        self.assertTrue(client_record.is_deleted)
        self.assertEqual(client_record.client_status, Client.ClientStatus.DELETED)

        response = self.client.post(reverse("client_restore", kwargs={"pk": client_record.pk}))
        self.assertEqual(response.status_code, 302)
        client_record.refresh_from_db()
        self.assertFalse(client_record.is_deleted)
        self.assertEqual(client_record.client_status, Client.ClientStatus.ACTIVE)


class CompanyCrudTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")

    def test_user_can_create_company_with_valid_logo(self):
        response = self.client.post(
            reverse("company_add"),
            {
                "company_name": "Acme Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
            },
            files={"logo": SimpleUploadedFile("logo.png", png_bytes(), content_type="image/png")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Company.objects.filter(company_name="Acme Traders").exists())

    def test_user_can_save_company_bank_details(self):
        response = self.client.post(
            reverse("company_add"),
            {
                "company_name": "Banked Traders",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
                "bank_name": "State Bank of India",
                "bank_account_number": "123456789012",
                "bank_branch": "MG Road",
                "ifsc_code": "sbin0001234",
            },
        )
        self.assertEqual(response.status_code, 302)
        company = Company.objects.get(company_name="Banked Traders")
        self.assertEqual(company.ifsc_code, "SBIN0001234")
        self.assertTrue(company.has_bank_details)


class InvoicePhaseTwoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")
        self.gst_company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.no_gst_company = Company.objects.create(
            company_name="Local Services",
            address="34 Market Street",
            country="India",
            state="Karnataka",
            city="Mysuru",
            pin_code="570001",
            gstin="",
        )
        self.client_with_gstin = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )
        self.client_without_gstin = Client.objects.create(
            client_name="Northwind Services",
            address="78 Lake View",
            country="India",
            state="Tamil Nadu",
            city="Chennai",
            pin_code="600001",
            gstin="",
        )

    def invoice_post_data(self, company, client, item_price="10000.00", quantity="1.00"):
        return {
            "company": company.pk,
            "client": client.pk,
            "invoice_date": "2026-06-25",
            "subject": "Website development services",
            "terms_and_conditions": "Payment should be made within the agreed timeline.",
            "declaration": "Invoice details are true and correct.",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-description": "Development work",
            "items-0-item_price": item_price,
            "items-0-quantity": quantity,
        }

    def test_invoice_pages_require_login(self):
        self.client.logout()
        for url in [
            reverse("invoice_list"),
            reverse("invoice_add"),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])

    def test_invoice_number_generation_sequence(self):
        invoice_date = date(2026, 6, 25)
        first_number = generate_invoice_number(self.gst_company, self.client_with_gstin, invoice_date)
        self.assertEqual(first_number, "SUNMSU-25062026-001")
        Invoice.objects.create(
            invoice_number=first_number,
            company=self.gst_company,
            client=self.client_with_gstin,
            invoice_date=invoice_date,
            subject="First invoice",
            subtotal=Decimal("100.00"),
            gst_percentage=Decimal("18.00"),
            gst_amount=Decimal("18.00"),
            total_amount=Decimal("118.00"),
            amount_in_words="Rupees One Hundred Eighteen Only",
            pending_amount=Decimal("118.00"),
        )
        second_number = generate_invoice_number(self.gst_company, self.client_with_gstin, invoice_date)
        self.assertEqual(second_number, "SUNMSU-25062026-002")

    def test_amount_in_words_uses_indian_currency_words(self):
        self.assertEqual(amount_to_indian_words(Decimal("11800.00")), "Rupees Eleven Thousand Eight Hundred Only")
        self.assertEqual(amount_to_currency_words(Decimal("5900.50"), "USD"), "US Dollars Five Thousand Nine Hundred And Fifty Cents Only")

    def test_create_invoice_with_gst_calculates_totals(self):
        response = self.client.post(
            reverse("invoice_add"),
            self.invoice_post_data(self.gst_company, self.client_with_gstin),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(subject="Website development services")
        self.assertEqual(invoice.invoice_number, "SUNMSU-25062026-001")
        self.assertEqual(invoice.subtotal, Decimal("10000.00"))
        self.assertEqual(invoice.gst_percentage, Decimal("18.00"))
        self.assertEqual(invoice.gst_amount, Decimal("1800.00"))
        self.assertEqual(invoice.total_amount, Decimal("11800.00"))
        self.assertEqual(invoice.pending_amount, Decimal("11800.00"))
        self.assertEqual(invoice.amount_in_words, "Rupees Eleven Thousand Eight Hundred Only")
        self.assertEqual(invoice.items.count(), 1)
        self.assertContains(response, invoice.invoice_number)

    def test_create_usd_invoice_formats_preview_and_pdf_with_dollars(self):
        data = self.invoice_post_data(self.gst_company, self.client_with_gstin, item_price="5000.00")
        data["currency"] = "USD"
        response = self.client.post(reverse("invoice_add"), data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(subject="Website development services")
        self.assertEqual(invoice.currency, "USD")
        self.assertEqual(invoice.amount_in_words, "US Dollars Five Thousand Nine Hundred Only")

        preview = self.client.get(reverse("invoice_preview", kwargs={"pk": invoice.pk}))
        self.assertContains(preview, "$5,900")
        self.assertContains(preview, "US Dollars Five Thousand Nine Hundred Only")

        payment_page = self.client.get(reverse("invoice_add_payment", kwargs={"pk": invoice.pk}))
        self.assertContains(payment_page, "Invoice Currency")
        self.assertContains(payment_page, "USD")
        self.assertContains(payment_page, "$5,900")

        pdf_html = render_to_string(
            "invoices/invoice_pdf.html",
            {
                "invoice": invoice,
                "invoice_title": invoice_title(invoice),
                "company_logo_uri": "",
                "company_signature_uri": "",
            },
        )
        self.assertIn("$5,900", pdf_html)
        self.assertIn("Currency</span>USD", pdf_html)

        report = self.client.get(reverse("reports"), {"currency": "USD"})
        self.assertContains(report, "Currency")
        self.assertContains(report, "$5,900")

    def test_create_invoice_without_company_gstin_skips_gst(self):
        response = self.client.post(
            reverse("invoice_add"),
            self.invoice_post_data(self.no_gst_company, self.client_without_gstin),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(company=self.no_gst_company)
        self.assertEqual(invoice.gst_percentage, Decimal("0.00"))
        self.assertEqual(invoice.gst_amount, Decimal("0.00"))
        self.assertEqual(invoice.total_amount, Decimal("10000.00"))

    def test_multiple_items_and_invoice_screens(self):
        data = self.invoice_post_data(self.gst_company, self.client_with_gstin)
        data.update(
            {
                "items-TOTAL_FORMS": "2",
                "items-0-description": "Development work",
                "items-0-item_price": "5000.00",
                "items-0-quantity": "2.00",
                "items-1-description": "Support work",
                "items-1-item_price": "1000.00",
                "items-1-quantity": "1.00",
            }
        )
        response = self.client.post(reverse("invoice_add"), data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(subject="Website development services")
        self.assertEqual(invoice.subtotal, Decimal("11000.00"))
        self.assertEqual(invoice.gst_amount, Decimal("1980.00"))
        self.assertEqual(invoice.total_amount, Decimal("12980.00"))
        self.assertEqual(invoice.items.count(), 2)

        list_response = self.client.get(reverse("invoice_list"))
        detail_response = self.client.get(reverse("invoice_detail", kwargs={"pk": invoice.pk}))
        preview_response = self.client.get(reverse("invoice_preview", kwargs={"pk": invoice.pk}))
        self.assertContains(list_response, invoice.invoice_number)
        self.assertContains(list_response, "Payment Status")
        self.assertContains(list_response, invoice.payment_status)
        self.assertContains(detail_response, "Development work")
        self.assertContains(detail_response, 'title="Invoice Number"', html=False)
        self.assertContains(detail_response, 'title="Client Name"', html=False)
        self.assertContains(detail_response, 'title="Payment Status"', html=False)
        self.assertContains(detail_response, 'title="Download PDF"', html=False)
        self.assertContains(detail_response, 'title="Print Invoice"', html=False)
        self.assertContains(preview_response, "Authorized Signature")
        self.assertContains(preview_response, "MSU Enterprises")
        self.assertNotContains(preview_response, "Status:")
        self.assertNotContains(preview_response, "Payment Status")
        self.assertNotContains(preview_response, "Invoice Status")

    def test_edit_invoice_recalculates_backend_totals(self):
        self.client.post(reverse("invoice_add"), self.invoice_post_data(self.gst_company, self.client_with_gstin))
        invoice = Invoice.objects.get()
        data = self.invoice_post_data(self.gst_company, self.client_with_gstin, item_price="2000.00", quantity="2.00")
        data["subject"] = "Updated services"
        response = self.client.post(reverse("invoice_edit", kwargs={"pk": invoice.pk}), data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.subject, "Updated services")
        self.assertEqual(invoice.subtotal, Decimal("4000.00"))
        self.assertEqual(invoice.gst_amount, Decimal("720.00"))
        self.assertEqual(invoice.total_amount, Decimal("4720.00"))

    def test_edit_invoice_delete_item_row_recalculates_totals(self):
        data = self.invoice_post_data(self.gst_company, self.client_with_gstin)
        data.update(
            {
                "items-TOTAL_FORMS": "2",
                "items-0-description": "Development work",
                "items-0-item_price": "5000.00",
                "items-0-quantity": "2.00",
                "items-1-description": "Support work",
                "items-1-item_price": "1000.00",
                "items-1-quantity": "1.00",
            }
        )
        self.client.post(reverse("invoice_add"), data, follow=True)
        invoice = Invoice.objects.get(subject="Website development services")
        self.assertEqual(invoice.items.count(), 2)

        edit_data = self.invoice_post_data(self.gst_company, self.client_with_gstin)
        edit_data.update(
            {
                "subject": "Removed item invoice",
                "items-TOTAL_FORMS": "2",
                "items-INITIAL_FORMS": "2",
                "items-0-description": "Development work",
                "items-0-item_price": "5000.00",
                "items-0-quantity": "2.00",
                "items-0-DELETE": "on",
                "items-1-description": "Support work",
                "items-1-item_price": "1000.00",
                "items-1-quantity": "1.00",
            }
        )
        response = self.client.post(reverse("invoice_edit", kwargs={"pk": invoice.pk}), edit_data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.items.count(), 1)
        self.assertEqual(invoice.items.get().description, "Support work")
        self.assertEqual(invoice.subtotal, Decimal("1000.00"))
        self.assertEqual(invoice.gst_amount, Decimal("180.00"))
        self.assertEqual(invoice.total_amount, Decimal("1180.00"))

    def test_final_invoice_cannot_save_when_all_item_rows_deleted(self):
        self.client.post(reverse("invoice_add"), self.invoice_post_data(self.gst_company, self.client_with_gstin))
        invoice = Invoice.objects.get()
        edit_data = self.invoice_post_data(self.gst_company, self.client_with_gstin)
        edit_data.update(
            {
                "items-INITIAL_FORMS": "1",
                "items-0-DELETE": "on",
            }
        )
        response = self.client.post(reverse("invoice_edit", kwargs={"pk": invoice.pk}), edit_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "At least one invoice item is required.")
        invoice.refresh_from_db()
        self.assertEqual(invoice.items.count(), 1)


class InvoicePDFTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")
        self.company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.no_gst_company = Company.objects.create(
            company_name="Local Services",
            address="34 Market Street",
            country="India",
            state="Karnataka",
            city="Mysuru",
            pin_code="570001",
            gstin="",
        )
        self.client_record = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def create_invoice(self, company, invoice_number):
        invoice = Invoice.objects.create(
            invoice_number=invoice_number,
            company=company,
            client=self.client_record,
            invoice_date=date(2026, 6, 25),
            subject="PDF invoice services",
            subtotal=Decimal("10000.00"),
            gst_percentage=Decimal("18.00") if company.gstin else Decimal("0.00"),
            gst_amount=Decimal("1800.00") if company.gstin else Decimal("0.00"),
            total_amount=Decimal("11800.00") if company.gstin else Decimal("10000.00"),
            amount_in_words=amount_to_indian_words(Decimal("11800.00") if company.gstin else Decimal("10000.00")),
            terms_and_conditions="Payment should be made within the agreed timeline.",
            declaration="Invoice details are true and correct.",
            pending_amount=Decimal("11800.00") if company.gstin else Decimal("10000.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            serial_number=1,
            description="PDF generation work",
            item_price=Decimal("10000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("10000.00"),
        )
        return invoice

    def test_pdf_download_requires_login(self):
        invoice = self.create_invoice(self.company, "SUNMSU-25062026-901")
        self.client.logout()
        response = self.client.get(reverse("invoice_pdf_download", kwargs={"pk": invoice.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_pdf_generation_works_for_gst_invoice(self):
        invoice = self.create_invoice(self.company, "SUNMSU-25062026-902")
        response = self.client.get(reverse("invoice_pdf_download", kwargs={"pk": invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("Invoice-SUNMSU-25062026-902.pdf", response["Content-Disposition"])
        pdf_bytes = b"".join(response.streaming_content)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.pdf_file.name, "invoices/Invoice-SUNMSU-25062026-902.pdf")
        self.assertTrue(os.path.exists(invoice.pdf_file.path))

    def test_pdf_generation_works_for_non_gst_invoice(self):
        invoice = self.create_invoice(self.no_gst_company, "LOCMSU-25062026-901")
        response = self.client.get(reverse("invoice_pdf_download", kwargs={"pk": invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("Invoice-LOCMSU-25062026-901.pdf", response["Content-Disposition"])
        invoice.refresh_from_db()
        self.assertTrue(os.path.exists(invoice.pdf_file.path))

    def test_missing_logo_does_not_break_pdf_generation(self):
        self.company.logo.name = "company_logos/missing-logo.svg"
        self.company.save(update_fields=["logo"])
        invoice = self.create_invoice(self.company, "SUNMSU-25062026-903")
        response = self.client.get(reverse("invoice_pdf_download", kwargs={"pk": invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")


class PhaseFourTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")
        self.company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.client_record = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )
        self.invoice = self.create_invoice("SUNMSU-25062026-501", Decimal("11800.00"))

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def create_invoice(self, invoice_number, total_amount, invoice_date=date(2026, 6, 25), currency="INR", project=None):
        invoice = Invoice.objects.create(
            invoice_number=invoice_number,
            company=self.company,
            client=self.client_record,
            project=project,
            invoice_date=invoice_date,
            subject="Phase 4 services",
            currency=currency,
            subtotal=Decimal("10000.00"),
            gst_percentage=Decimal("18.00"),
            gst_amount=Decimal("1800.00"),
            total_amount=total_amount,
            amount_in_words=amount_to_indian_words(total_amount),
            pending_amount=total_amount,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            serial_number=1,
            description="Phase 4 work",
            item_price=Decimal("10000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("10000.00"),
        )
        return invoice

    def create_project(self, name, approved_quote=Decimal("5000.00"), currency="INR", status=Project.ProjectStatus.IN_PROGRESS):
        return Project.objects.create(
            project_name=name,
            client=self.client_record,
            project_requirement="Dashboard project receipt",
            project_type=Project.ProjectType.WEB_APPLICATION,
            estimated_quote=approved_quote,
            approved_quote=approved_quote,
            currency=currency,
            project_status=status,
            completion_percentage=40,
        )

    def add_payment(self, invoice, amount):
        return self.client.post(
            reverse("invoice_add_payment", kwargs={"pk": invoice.pk}),
            {
                "received_amount": str(amount),
                "payment_date": "2026-06-25",
                "payment_mode": "UPI",
                "remarks": "QA payment",
            },
            follow=True,
        )

    def test_payment_creation_partial_full_and_overpayment_blocking(self):
        response = self.add_payment(self.invoice, Decimal("5000.00"))
        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)
        self.assertEqual(self.invoice.received_amount, Decimal("5000.00"))
        self.assertEqual(self.invoice.pending_amount, Decimal("6800.00"))
        self.assertEqual(self.invoice.payment_status, Invoice.PaymentStatus.PARTIALLY_PAID)

        overpay = self.add_payment(self.invoice, Decimal("7000.00"))
        self.assertEqual(overpay.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertContains(overpay, "Payment amount cannot exceed")
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)
        self.assertEqual(self.invoice.pending_amount, Decimal("6800.00"))

        response = self.add_payment(self.invoice, Decimal("6800.00"))
        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.received_amount, Decimal("11800.00"))
        self.assertEqual(self.invoice.pending_amount, Decimal("0.00"))
        self.assertEqual(self.invoice.payment_status, Invoice.PaymentStatus.PAID)

    def test_payment_history_is_visible(self):
        self.add_payment(self.invoice, Decimal("1000.00"))
        response = self.client.get(reverse("invoice_payment_history", kwargs={"pk": self.invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QA payment")

    def test_dashboard_current_month_totals_and_filters(self):
        self.add_payment(self.invoice, Decimal("3000.00"))
        june_filter = {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"}
        response = self.client.get(reverse("dashboard"), june_filter)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Received Amount")
        self.assertContains(response, "₹11,800")
        self.assertContains(response, "₹3,000")
        self.assertContains(response, "₹8,800")
        self.assertContains(response, "Invoice Pending Amount")
        self.assertEqual(response.context["received_amount"], Decimal("3000.00"))
        self.assertEqual(response.context["invoice_received_amount"], Decimal("3000.00"))
        self.assertEqual(response.context["client_project_received_amount"], Decimal("0.00"))
        self.assertEqual(response.context["total_received_amount"], Decimal("3000.00"))
        self.assertEqual(response.context["pending_amount"], Decimal("8800.00"))
        self.assertEqual(response.context["invoice_pending_amount"], Decimal("8800.00"))
        filtered = self.client.get(reverse("dashboard"), {**june_filter, "payment_status": Invoice.PaymentStatus.PARTIALLY_PAID})
        self.assertContains(filtered, self.invoice.invoice_number)

    def test_dashboard_received_amount_uses_filtered_invoices_not_unfiltered_payments(self):
        may_invoice = self.create_invoice("SUNMSU-25052026-701", Decimal("5000.00"), invoice_date=date(2026, 5, 25))
        self.add_payment(may_invoice, Decimal("2000.00"))

        response = self.client.get(
            reverse("dashboard"),
            {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["received_amount"], Decimal("0.00"))
        self.assertEqual(response.context["pending_amount"], Decimal("11800.00"))
        self.assertContains(response, "Received Amount")
        self.assertNotContains(response, "₹2,000")
        monthly_chart = response.context["dashboard_chart_data"]["monthlyInvoice"]
        received_series = next(series for series in monthly_chart["series"] if series["label"] == "Received")
        self.assertIn("Jun 2026", monthly_chart["labels"])
        june_index = monthly_chart["labels"].index("Jun 2026")
        self.assertEqual(received_series["values"][june_index], 0.0)

    def test_dashboard_pending_amount_is_total_invoice_value_minus_received_amount(self):
        self.invoice.is_deleted = True
        self.invoice.save(update_fields=["is_deleted", "updated_at"])
        invoice = self.create_invoice("SUNMSU-25062026-901", Decimal("85132.66"))
        self.add_payment(invoice, Decimal("41578.00"))

        response = self.client.get(
            reverse("dashboard"),
            {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_invoice_amount"], Decimal("85132.66"))
        self.assertEqual(response.context["invoice_received_amount"], Decimal("41578.00"))
        self.assertEqual(response.context["client_project_received_amount"], Decimal("0.00"))
        self.assertEqual(response.context["total_received_amount"], Decimal("41578.00"))
        self.assertEqual(response.context["received_amount"], Decimal("41578.00"))
        self.assertEqual(response.context["pending_amount"], Decimal("43554.66"))
        self.assertEqual(response.context["invoice_pending_amount"], Decimal("43554.66"))
        self.assertContains(response, "₹85,132.66")
        self.assertContains(response, "₹41,578")
        self.assertContains(response, "₹43,554.66")
        chart = response.context["invoice_payment_status_data"]
        partial_index = chart["labels"].index(Invoice.PaymentStatus.PARTIALLY_PAID)
        self.assertGreaterEqual(chart["values"][partial_index], 1)

    def test_dashboard_invoice_payment_status_chart_counts_payment_states(self):
        paid_invoice = self.create_invoice("SUNMSU-25062026-801", Decimal("1000.00"))
        partial_invoice = self.create_invoice("SUNMSU-25062026-802", Decimal("2000.00"))
        pending_invoice = self.create_invoice("SUNMSU-25062026-803", Decimal("3000.00"))
        Invoice.objects.create(
            invoice_number="DRAFT-20260625-801",
            company=self.company,
            client=self.client_record,
            invoice_date=date(2026, 6, 25),
            subject="Draft dashboard invoice",
            subtotal=Decimal("1000.00"),
            gst_percentage=Decimal("0.00"),
            gst_amount=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
            amount_in_words=amount_to_indian_words(Decimal("1000.00")),
            invoice_status=Invoice.InvoiceStatus.DRAFT,
            pending_amount=Decimal("1000.00"),
        )
        deleted_invoice = self.create_invoice("DELMSU-25062026-801", Decimal("4000.00"))
        deleted_invoice.is_deleted = True
        deleted_invoice.save(update_fields=["is_deleted", "updated_at"])
        self.add_payment(paid_invoice, Decimal("1000.00"))
        self.add_payment(partial_invoice, Decimal("500.00"))
        partial_invoice.received_amount = Decimal("0.00")
        partial_invoice.pending_amount = partial_invoice.total_amount
        partial_invoice.payment_status = Invoice.PaymentStatus.PENDING
        partial_invoice.save()

        response = self.client.get(
            reverse("dashboard"),
            {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
        )

        chart = response.context["dashboard_chart_data"]["invoicePaymentStatus"]
        self.assertEqual(chart["labels"], [Invoice.PaymentStatus.PAID, Invoice.PaymentStatus.PENDING, Invoice.PaymentStatus.PARTIALLY_PAID, "Draft"])
        self.assertEqual(chart["values"], [1, 2, 1, 1])
        self.assertNotContains(response, deleted_invoice.invoice_number)

    def test_dashboard_separates_inr_and_usd_invoice_totals(self):
        usd_invoice = self.create_invoice("SUNMSU-25062026-902", Decimal("5900.00"), currency="USD")
        self.add_payment(self.invoice, Decimal("1000.00"))
        self.add_payment(usd_invoice, Decimal("900.00"))

        response = self.client.get(
            reverse("dashboard"),
            {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total Invoice Value - INR")
        self.assertContains(response, "Total Invoice Value - USD")
        self.assertContains(response, "₹11,800")
        self.assertContains(response, "$5,900")
        self.assertContains(response, "$900")

    def test_dashboard_usd_total_received_uses_only_valid_usd_income_once(self):
        usd_project = self.create_project("USD Project Receipt", Decimal("50000.00"), currency="USD")
        usd_invoiced_project = self.create_project("USD Invoiced Project", Decimal("10000.00"), currency="USD")
        inr_project = self.create_project("INR Project Receipt", Decimal("10000.00"), currency="INR")
        cancelled_usd_project = self.create_project(
            "Cancelled USD Project",
            Decimal("8000.00"),
            currency="USD",
            status=Project.ProjectStatus.CANCELLED,
        )
        usd_invoice = self.create_invoice(
            "SUNMSU-25062026-903",
            Decimal("5900.00"),
            currency="USD",
            project=usd_invoiced_project,
        )
        self.add_payment(usd_invoice, Decimal("900.00"))
        self.add_payment(self.invoice, Decimal("1000.00"))
        ProjectClientPayment.objects.create(
            project=usd_project,
            amount_received=Decimal("42294.30"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.MILESTONE,
        )
        ProjectClientPayment.objects.create(
            project=usd_invoiced_project,
            amount_received=Decimal("900.00"),
            payment_date=date(2026, 6, 25),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.MILESTONE,
        )
        ProjectClientPayment.objects.create(
            project=inr_project,
            amount_received=Decimal("5000.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.MILESTONE,
        )
        ProjectClientPayment.objects.create(
            project=cancelled_usd_project,
            amount_received=Decimal("8000.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.MILESTONE,
        )
        vendor = DeveloperVendor.objects.create(
            name="USD Vendor",
            vendor_type=DeveloperVendor.VendorType.FREELANCER,
        )
        assignment = ProjectAssignment.objects.create(
            project=usd_project,
            developer_vendor=vendor,
            assigned_role="Backend",
            developer_final_project_cost=Decimal("10000.00"),
        )
        DeveloperPayment.objects.create(
            project_assignment=assignment,
            amount_paid=Decimal("10000.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=DeveloperPayment.PaymentType.MILESTONE,
        )

        response = self.client.get(
            reverse("dashboard"),
            {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
        )

        cards = {card["label"]: card["value"] for card in response.context["summary_cards"]}
        self.assertEqual(response.context["invoice_currency_summaries"]["USD"]["received"], Decimal("900.00"))
        self.assertEqual(response.context["project_currency_summaries"]["USD"]["client_received"], Decimal("42294.30"))
        self.assertEqual(cards["Invoice Received Amount - USD"], "$900")
        self.assertEqual(cards["Client / Project Received Amount - USD"], "$42,294.30")
        self.assertEqual(cards["Total Received Amount - USD"], "$43,194.30")
        self.assertEqual(cards["Invoice Pending Amount - USD"], "$5,000")

        usd_filter = self.client.get(
            reverse("dashboard"),
            {
                "period": "custom",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "currency": "USD",
            },
        )
        usd_cards = {card["label"]: card["value"] for card in usd_filter.context["summary_cards"]}
        self.assertEqual(usd_cards["Total Received Amount - USD"], "$43,194.30")
        self.assertEqual(usd_cards["Total Received Amount - INR"], "₹0")

    def test_invoice_search_and_filters(self):
        other = self.create_invoice("SUNMSU-25052026-501", Decimal("11800.00"), invoice_date=date(2026, 5, 25))
        search_response = self.client.get(reverse("invoice_list"), {"q": "25062026"})
        self.assertContains(search_response, self.invoice.invoice_number)
        self.assertNotContains(search_response, other.invoice_number)
        month_response = self.client.get(reverse("invoice_list"), {"month": "2026-05"})
        self.assertContains(month_response, other.invoice_number)
        self.assertNotContains(month_response, self.invoice.invoice_number)

    def test_month_summary_totals(self):
        self.add_payment(self.invoice, Decimal("11800.00"))
        response = self.client.get(reverse("month_summary"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "June 2026")
        self.assertContains(response, "₹11,800")

    def test_reports_and_exports(self):
        self.add_payment(self.invoice, Decimal("11800.00"))
        report_response = self.client.get(reverse("reports"), {"report_type": "paid"})
        self.assertEqual(report_response.status_code, 200)
        self.assertContains(report_response, self.invoice.invoice_number)

        excel_response = self.client.get(reverse("report_export_excel"), {"report_type": "paid"})
        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(
            excel_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        excel_bytes = b"".join(excel_response.streaming_content)
        self.assertTrue(excel_bytes.startswith(b"PK"))

        pdf_response = self.client.get(reverse("report_export_pdf"), {"report_type": "paid"})
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        pdf_bytes = b"".join(pdf_response.streaming_content)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        payment_report = self.client.get(reverse("reports"), {"report_type": "payment_received"})
        self.assertContains(payment_report, "QA payment")

    def test_payment_and_report_pages_require_login(self):
        self.client.logout()
        urls = [
            reverse("invoice_add_payment", kwargs={"pk": self.invoice.pk}),
            reverse("invoice_payment_history", kwargs={"pk": self.invoice.pk}),
            reverse("reports"),
            reverse("report_export_excel"),
            reverse("report_export_pdf"),
            reverse("month_summary"),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])


class PhaseFiveTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.backup_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root, BACKUP_ROOT=self.backup_root)
        self.settings_override.enable()
        self.admin = get_user_model().objects.create_superuser(
            username="admin-owner",
            password="secure-test-password-123",
        )
        self.normal_user = get_user_model().objects.create_user(
            username="regular-owner",
            password="secure-test-password-123",
        )
        self.client.login(username="admin-owner", password="secure-test-password-123")
        self.company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.client_record = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        shutil.rmtree(self.backup_root, ignore_errors=True)

    def invoice_post_data(self):
        return {
            "company": self.company.pk,
            "client": self.client_record.pk,
            "invoice_date": "2026-06-25",
            "subject": "Settings backed invoice",
            "terms_and_conditions": "Settings terms",
            "declaration": "Settings declaration",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-description": "Consulting work",
            "items-0-item_price": "1000.00",
            "items-0-quantity": "1.00",
        }

    def test_backup_and_restore_pages_require_superuser(self):
        self.client.logout()
        response = self.client.get(reverse("backup"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

        self.client.force_login(self.normal_user)
        response = self.client.get(reverse("backup"))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse("backup_create"))
        self.assertEqual(response.status_code, 403)

    def test_backup_creation_and_download(self):
        logo_dir = os.path.join(self.media_root, "company_logos")
        os.makedirs(logo_dir, exist_ok=True)
        with open(os.path.join(logo_dir, "logo.png"), "wb") as logo_file:
            logo_file.write(png_bytes())

        response = self.client.post(reverse("backup_create"), follow=True)
        self.assertEqual(response.status_code, 200)
        backups = [name for name in os.listdir(self.backup_root) if name.endswith(".zip")]
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].startswith("invoice_backup_"))

        backup_path = os.path.join(self.backup_root, backups[0])
        with zipfile.ZipFile(backup_path) as archive:
            self.assertIn("database/db.sqlite3", archive.namelist())
            self.assertIn("backup_manifest.json", archive.namelist())
            self.assertIn("settings/app_settings.json", archive.namelist())
            self.assertIn("media/company_logos/logo.png", archive.namelist())

        download = self.client.get(reverse("backup_download", kwargs={"filename": backups[0]}))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "application/zip")
        downloaded_bytes = b"".join(download.streaming_content)
        self.assertTrue(downloaded_bytes.startswith(b"PK"))

    def test_restore_upload_rejects_path_traversal_zip(self):
        payload = zip_bytes(
            {
                "backup_manifest.json": "{}",
                "database/db.sqlite3": b"not-a-real-db",
                "../evil.txt": b"bad",
            }
        )
        response = self.client.post(
            reverse("restore_upload"),
            {"backup_file": SimpleUploadedFile("bad.zip", payload, content_type="application/zip")},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unsafe file path")

    def test_restore_upload_rejects_executable_files(self):
        payload = zip_bytes(
            {
                "backup_manifest.json": "{}",
                "database/db.sqlite3": b"not-a-real-db",
                "media/invoices/run.sh": b"echo unsafe",
            }
        )
        response = self.client.post(
            reverse("restore_upload"),
            {"backup_file": SimpleUploadedFile("bad.zip", payload, content_type="application/zip")},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "executable files")

    def test_settings_update_and_invoice_defaults(self):
        response = self.client.post(
            reverse("settings"),
            {
                "default_gst_percentage": "12.50",
                "default_terms_and_conditions": "Updated default terms",
                "default_declaration": "Updated default declaration",
                "default_payment_terms": "Due within 15 days",
                "invoice_number_format": "{company3}{client3}-{date_ddmmyyyy}-{sequence:03d}",
                "date_separator": "",
                "prefix_separator": "-",
                "running_sequence_length": "3",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        app_settings = ApplicationSetting.load()
        self.assertEqual(app_settings.default_gst_percentage, Decimal("12.50"))
        self.assertEqual(app_settings.default_terms_and_conditions, "Updated default terms")

        create_page = self.client.get(reverse("invoice_add"))
        self.assertContains(create_page, "Updated default terms")
        self.assertContains(create_page, "Updated default declaration")

        data = self.invoice_post_data()
        data["terms_and_conditions"] = "Updated default terms"
        data["declaration"] = "Updated default declaration"
        response = self.client.post(reverse("invoice_add"), data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(subject="Settings backed invoice")
        self.assertEqual(invoice.gst_percentage, Decimal("12.50"))
        self.assertEqual(invoice.gst_amount, Decimal("125.00"))
        self.assertEqual(invoice.total_amount, Decimal("1125.00"))
        self.assertEqual(invoice.terms_and_conditions, "Updated default terms")
        self.assertEqual(invoice.declaration, "Updated default declaration")


class PhaseSixTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")
        self.company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.client_record = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def invoice_post_data(self, project=""):
        return {
            "company": self.company.pk,
            "client": self.client_record.pk,
            "project": project,
            "invoice_date": "2026-06-26",
            "subject": "Project invoice services",
            "terms_and_conditions": "Payment should be made within the agreed timeline.",
            "declaration": "Invoice details are true and correct.",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-description": "Project work",
            "items-0-item_price": "1000.00",
            "items-0-quantity": "1.00",
        }

    def create_project(self, name="Website Build", approved_quote=Decimal("5000.00")):
        project = Project.objects.create(
            project_name=name,
            client=self.client_record,
            project_requirement="Build client website",
            project_type=Project.ProjectType.WEBSITE_DEVELOPMENT,
            estimated_quote=Decimal("6000.00"),
            approved_quote=approved_quote,
            project_status=Project.ProjectStatus.IN_PROGRESS,
            completion_percentage=40,
        )
        return project

    def test_company_signature_upload_validation_and_preview_template(self):
        form = CompanyForm(
            data={
                "company_name": "Signature Co",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
            },
            files={"authorized_signature": SimpleUploadedFile("signature.png", png_bytes(600, 200), content_type="image/png")},
        )
        self.assertTrue(form.is_valid(), form.errors)

        bad_form = CompanyForm(
            data={
                "company_name": "Signature Co",
                "address": "12 Market Road",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pin_code": "560001",
                "gstin": "",
            },
            files={"authorized_signature": SimpleUploadedFile("signature.png", png_bytes(200, 80), content_type="image/png")},
        )
        self.assertFalse(bad_form.is_valid())
        self.assertIn("authorized_signature", bad_form.errors)

    def test_invoice_preview_and_pdf_template_include_signature(self):
        signature_dir = os.path.join(self.media_root, "company_signatures")
        os.makedirs(signature_dir, exist_ok=True)
        with open(os.path.join(signature_dir, "signature.png"), "wb") as signature_file:
            signature_file.write(png_bytes(600, 200))
        self.company.authorized_signature.name = "company_signatures/signature.png"
        self.company.save(update_fields=["authorized_signature"])

        invoice = Invoice.objects.create(
            invoice_number="SUNMSU-26062026-901",
            company=self.company,
            client=self.client_record,
            invoice_date=date(2026, 6, 26),
            subject="Signature invoice",
            subtotal=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            amount_in_words=amount_to_indian_words(Decimal("1180.00")),
            pending_amount=Decimal("1180.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            serial_number=1,
            description="Signed project work",
            item_price=Decimal("1000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("1000.00"),
        )

        preview = self.client.get(reverse("invoice_preview", kwargs={"pk": invoice.pk}))
        self.assertContains(preview, "company-signature")
        pdf_html = render_to_string(
            "invoices/invoice_pdf.html",
            {
                "invoice": invoice,
                "company_logo_uri": "",
                "company_signature_uri": self.company.authorized_signature.path,
            },
        )
        self.assertIn("company-signature", pdf_html)

    def test_project_creation_multiple_projects_and_completion_rule(self):
        first = self.create_project("Website Build")
        second = self.create_project("SEO Retainer", approved_quote=Decimal("3000.00"))
        self.assertEqual(Project.objects.filter(client=self.client_record).count(), 2)
        self.assertTrue(first.project_id.startswith("PRJ-"))
        self.assertNotEqual(first.project_id, second.project_id)

        response = self.client.post(
            reverse("project_add"),
            {
                "client": self.client_record.pk,
                "project_name": "Completed App",
                "project_requirement": "Build app",
                "project_type": Project.ProjectType.MOBILE_APP_DEVELOPMENT,
                "custom_project_type": "",
                "project_description": "",
                "estimated_quote": "10000.00",
                "approved_quote": "9000.00",
                "client_next_advance_amount": "0.00",
                "client_next_advance_expected_date": "",
                "client_payment_remarks": "",
                "start_date": "2026-06-26",
                "expected_completion_date": "2026-07-26",
                "actual_completion_date": "",
                "project_status": Project.ProjectStatus.COMPLETED,
                "completion_percentage": "40",
                "priority": Project.Priority.HIGH,
                "remarks": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        completed = Project.objects.get(project_name="Completed App")
        self.assertEqual(completed.completion_percentage, 100)

    def test_project_create_blank_amount_fields_save_as_zero(self):
        response = self.client.post(
            reverse("project_add"),
            {
                "client": self.client_record.pk,
                "project_name": "Blank Amount Project",
                "project_requirement": "Build project with optional amount fields",
                "project_type": Project.ProjectType.WEB_APPLICATION,
                "billing_type": Project.BillingType.ONE_TIME,
                "custom_project_type": "",
                "project_description": "",
                "estimated_quote": "",
                "approved_quote": "",
                "client_next_advance_amount": "",
                "client_next_advance_expected_date": "",
                "client_payment_remarks": "",
                "start_date": "",
                "expected_completion_date": "",
                "actual_completion_date": "",
                "project_status": Project.ProjectStatus.IN_PROGRESS,
                "completion_percentage": "25",
                "priority": Project.Priority.MEDIUM,
                "remarks": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        project = Project.objects.get(project_name="Blank Amount Project")
        self.assertEqual(project.estimated_quote, Decimal("0.00"))
        self.assertEqual(project.approved_quote, Decimal("0.00"))
        self.assertEqual(project.client_next_advance_amount, Decimal("0.00"))
        self.assertEqual(project.client_total_amount_received, Decimal("0.00"))
        self.assertEqual(project.client_pending_amount, Decimal("0.00"))
        self.assertContains(response, project.project_name)
        report_response = self.client.get(reverse("project_reports"), {"report_type": "project_wise"})
        self.assertContains(report_response, project.project_name)

    def test_project_list_uses_accessible_icon_actions(self):
        project = self.create_project()
        response = self.client.get(reverse("project_list"))
        self.assertContains(response, project.project_name)
        for label in [
            "View Project",
            "Edit Project",
            "Delete Project",
            "Client Payment",
            "Assign Developer",
            "View Invoices",
        ]:
            self.assertContains(response, f'aria-label="{label}"')
            self.assertContains(response, f'title="{label}"')
        self.assertNotContains(response, ">Client Payment</a>")
        self.assertNotContains(response, ">Assign Developer</a>")
        self.assertNotContains(response, ">Invoices</a>")

    def test_invoice_can_be_linked_to_project_and_still_saved_without_project(self):
        project = self.create_project()
        response = self.client.post(reverse("invoice_add"), self.invoice_post_data(project=project.pk), follow=True)
        self.assertEqual(response.status_code, 200)
        linked_invoice = Invoice.objects.get(subject="Project invoice services")
        self.assertEqual(linked_invoice.project, project)

        response = self.client.post(reverse("invoice_add"), self.invoice_post_data(project=""), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Invoice.objects.filter(project__isnull=True).exists())

        project_response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))
        self.assertContains(project_response, linked_invoice.invoice_number)

        preview_response = self.client.get(reverse("invoice_preview", kwargs={"pk": linked_invoice.pk}))
        self.assertContains(preview_response, linked_invoice.invoice_number)
        self.assertNotContains(preview_response, project.project_name)
        self.assertNotContains(preview_response, "Project:")

        pdf_html = render_to_string(
            "invoices/invoice_pdf.html",
            {
                "invoice": linked_invoice,
                "invoice_title": invoice_title(linked_invoice),
                "company_logo_uri": "",
                "company_signature_uri": "",
            },
        )
        self.assertIn(linked_invoice.invoice_number, pdf_html)
        self.assertNotIn(project.project_name, pdf_html)
        self.assertNotIn("Project:", pdf_html)

        edit_response = self.client.get(reverse("invoice_edit", kwargs={"pk": linked_invoice.pk}))
        self.assertContains(edit_response, project.project_name)

        project_report = self.client.get(reverse("project_reports"), {"report_type": "project_invoice"})
        self.assertContains(project_report, project.project_name)

    def test_project_gst_extra_calculation_and_invoice_gst_unchanged(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))
        project.client_amount_gst_type = Project.ClientAmountGstType.GST_EXTRA
        project.project_gst_percentage = Decimal("18.00")
        project.client_total_amount_received = Decimal("400.00")
        project.save()
        invoice = Invoice.objects.create(
            invoice_number="PRJGST-26062026-001",
            company=self.company,
            client=self.client_record,
            project=project,
            invoice_date=date(2026, 6, 26),
            subject="Project GST invoice",
            apply_gst=True,
            subtotal=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            amount_in_words=amount_to_indian_words(Decimal("1180.00")),
            received_amount=Decimal("400.00"),
            pending_amount=Decimal("780.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            serial_number=1,
            description="GST project work",
            item_price=Decimal("1000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("1000.00"),
        )

        response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))

        self.assertContains(response, "GST Amount")
        self.assertContains(response, "Total With GST")
        self.assertEqual(response.context["project_base_amount"], Decimal("5000.00"))
        self.assertEqual(response.context["project_gst_amount"], Decimal("900.00"))
        self.assertEqual(response.context["project_total_with_gst"], Decimal("5900.00"))
        self.assertEqual(response.context["project_client_pending_amount"], Decimal("5500.00"))
        self.assertContains(response, "GST Extra / Amount Before GST")
        self.assertContains(response, "₹900")
        self.assertContains(response, "₹5,900")
        invoice.refresh_from_db()
        self.assertEqual(invoice.gst_amount, Decimal("180.00"))
        self.assertEqual(invoice.total_amount, Decimal("1180.00"))

    def test_dashboard_received_amount_includes_project_client_payments(self):
        project = self.create_project(name="Client Receipt Project", approved_quote=Decimal("100000.00"))
        ProjectClientPayment.objects.create(
            project=project,
            amount_received=Decimal("42294.30"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.MILESTONE,
            remarks="Client project receipt",
        )

        response = self.client.get(
            reverse("dashboard"),
            {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["invoice_received_amount"], Decimal("0.00"))
        self.assertEqual(response.context["client_project_received_amount"], Decimal("42294.30"))
        self.assertEqual(response.context["total_received_amount"], Decimal("42294.30"))
        self.assertEqual(response.context["received_amount"], Decimal("42294.30"))
        self.assertEqual(response.context["invoice_pending_amount"], Decimal("0.00"))
        self.assertEqual(response.context["client_project_pending_amount"], Decimal("57705.70"))
        self.assertContains(response, "Invoice Received Amount")
        self.assertContains(response, "Client / Project Received Amount")
        self.assertContains(response, "Total Received Amount")
        self.assertContains(response, "Invoice Pending Amount")
        self.assertContains(response, "Client / Project Pending Amount")
        self.assertContains(response, "₹42,294.30")
        self.assertContains(response, "₹57,705.70")
        project_cards = {card["label"]: card["value"] for card in response.context["project_summary_cards"]}
        self.assertEqual(project_cards["Client amount received"], "₹42,294.30")

    def test_project_client_payment_can_be_edited_from_history(self):
        project = self.create_project(name="Editable Client Receipt", approved_quote=Decimal("5000.00"))
        payment = ProjectClientPayment.objects.create(
            project=project,
            amount_received=Decimal("4800.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.MILESTONE,
            remarks="Initial receipt",
        )
        recalculate_project_client_payments(project)

        detail = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))
        self.assertContains(detail, 'aria-label="Edit Client Payment"', html=False)

        edit = self.client.get(reverse("project_edit_client_payment", kwargs={"project_pk": project.pk, "payment_pk": payment.pk}))
        self.assertEqual(edit.status_code, 200)
        self.assertContains(edit, "Edit Client Project Payment")
        self.assertContains(edit, "Update Payment")

        response = self.client.post(
            reverse("project_edit_client_payment", kwargs={"project_pk": project.pk, "payment_pk": payment.pk}),
            {
                "amount_received": "4900.00",
                "payment_date": "2026-06-27",
                "payment_mode": "Bank Transfer",
                "payment_type": ProjectClientPayment.PaymentType.FINAL,
                "remarks": "Updated receipt",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        project.refresh_from_db()
        self.assertEqual(payment.amount_received, Decimal("4900.00"))
        self.assertEqual(payment.payment_date, date(2026, 6, 27))
        self.assertEqual(payment.payment_mode, "Bank Transfer")
        self.assertEqual(payment.payment_type, ProjectClientPayment.PaymentType.FINAL)
        self.assertEqual(payment.remarks, "Updated receipt")
        self.assertEqual(project.client_total_amount_received, Decimal("4900.00"))
        self.assertEqual(project.client_pending_amount, Decimal("100.00"))
        self.assertContains(response, "₹4,900")
        self.assertContains(response, "₹100")

    def test_project_without_gst_calculation(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))

        response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))

        self.assertEqual(project.client_amount_gst_type, Project.ClientAmountGstType.WITHOUT_GST)
        self.assertEqual(response.context["project_base_amount"], Decimal("5000.00"))
        self.assertEqual(response.context["project_gst_amount"], Decimal("0.00"))
        self.assertEqual(response.context["project_total_with_gst"], Decimal("5000.00"))

    def test_project_can_use_usd_currency(self):
        project = self.create_project(name="USD Project", approved_quote=Decimal("5000.00"))
        project.currency = "USD"
        project.client_amount_gst_type = Project.ClientAmountGstType.GST_EXTRA
        project.project_gst_percentage = Decimal("18.00")
        project.save()

        response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(project.currency, "USD")
        self.assertContains(response, "Project Currency")
        self.assertContains(response, "$5,900")

    def test_project_gst_included_calculation_excludes_gst_from_profit(self):
        project = self.create_project(approved_quote=Decimal("5900.00"))
        project.client_amount_gst_type = Project.ClientAmountGstType.GST_INCLUDED
        project.project_gst_percentage = Decimal("18.00")
        project.client_total_amount_received = Decimal("1000.00")
        project.save()
        vendor = DeveloperVendor.objects.create(name="GST Included Dev", vendor_type=DeveloperVendor.VendorType.FREELANCER)
        ProjectAssignment.objects.create(
            project=project,
            developer_vendor=vendor,
            assigned_role="Backend",
            developer_final_project_cost=Decimal("3000.00"),
        )

        response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))

        self.assertEqual(response.context["project_base_amount"], Decimal("5000.00"))
        self.assertEqual(response.context["project_gst_amount"], Decimal("900.00"))
        self.assertEqual(response.context["project_total_with_gst"], Decimal("5900.00"))
        self.assertEqual(response.context["project_client_pending_amount"], Decimal("4900.00"))
        self.assertEqual(response.context["summary"]["approved_profit"], Decimal("2000.00"))
        self.assertEqual(response.context["summary"]["actual_cash_profit"], Decimal("1000.00"))

    def test_project_partial_gst_calculation_and_validation(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))
        project.client_amount_gst_type = Project.ClientAmountGstType.PARTIAL_GST
        project.project_gst_percentage = Decimal("18.00")
        project.partial_gst_taxable_amount = Decimal("2000.00")
        project.client_total_amount_received = Decimal("1000.00")
        project.save()

        response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))

        self.assertEqual(response.context["project_base_amount"], Decimal("5000.00"))
        self.assertEqual(response.context["project_gst_amount"], Decimal("360.00"))
        self.assertEqual(response.context["project_total_with_gst"], Decimal("5360.00"))
        self.assertEqual(response.context["project_client_pending_amount"], Decimal("4360.00"))

        invalid_form = ProjectForm(
            data={
                "client": self.client_record.pk,
                "project_name": "Invalid Partial GST",
                "project_requirement": "Partial GST validation",
                "project_type": Project.ProjectType.WEB_APPLICATION,
                "billing_type": Project.BillingType.ONE_TIME,
                "custom_project_type": "",
                "project_description": "",
                "estimated_quote": "0.00",
                "approved_quote": "5000.00",
                "client_amount_gst_type": Project.ClientAmountGstType.PARTIAL_GST,
                "project_gst_percentage": "18.00",
                "partial_gst_taxable_amount": "6000.00",
                "client_next_advance_amount": "0.00",
                "client_next_advance_expected_date": "",
                "client_payment_remarks": "",
                "start_date": "",
                "expected_completion_date": "",
                "actual_completion_date": "",
                "project_status": Project.ProjectStatus.IN_PROGRESS,
                "completion_percentage": "25",
                "priority": Project.Priority.MEDIUM,
                "remarks": "",
            }
        )
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("partial_gst_taxable_amount", invalid_form.errors)

    def test_project_detail_handles_zero_non_gst_project_without_invoice(self):
        self.client_record.requires_gst_invoice = False
        self.client_record.save(update_fields=["requires_gst_invoice"])
        project = Project.objects.create(
            project_name="Zero Non-GST Project",
            client=self.client_record,
            project_requirement="Zero value project",
            project_type=Project.ProjectType.WEB_APPLICATION,
            estimated_quote=Decimal("0.00"),
            approved_quote=Decimal("0.00"),
            project_status=Project.ProjectStatus.IN_PROGRESS,
        )

        response = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["project_base_amount"], Decimal("0.00"))
        self.assertEqual(response.context["project_gst_amount"], Decimal("0.00"))
        self.assertEqual(response.context["project_total_with_gst"], Decimal("0.00"))
        self.assertEqual(response.context["project_client_pending_amount"], Decimal("0.00"))

    def test_invoice_rejects_project_for_different_client(self):
        other_client = Client.objects.create(
            client_name="Other Client",
            address="1 Road",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560002",
        )
        other_project = Project.objects.create(
            project_name="Other Project",
            client=other_client,
            project_requirement="Other",
            project_type=Project.ProjectType.OTHER,
            custom_project_type="Research",
            estimated_quote=Decimal("1000.00"),
            approved_quote=Decimal("1000.00"),
        )
        response = self.client.post(reverse("invoice_add"), self.invoice_post_data(project=other_project.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selected project must belong")
        self.assertFalse(Invoice.objects.filter(subject="Project invoice services").exists())

    def test_developer_assignment_payments_pending_and_profit(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))
        vendor = DeveloperVendor.objects.create(
            name="North Devs",
            vendor_type=DeveloperVendor.VendorType.COMPANY,
            contact_person="N Dev",
            email="dev@example.com",
            phone_number="+91 9999999999",
        )
        assignment = ProjectAssignment.objects.create(
            project=project,
            developer_vendor=vendor,
            assigned_role="Frontend",
            developer_cost_estimate=Decimal("2000.00"),
            developer_final_project_cost=Decimal("2500.00"),
        )
        ProjectClientPayment.objects.create(
            project=project,
            amount_received=Decimal("3000.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="UPI",
            payment_type=ProjectClientPayment.PaymentType.ADVANCE,
        )
        DeveloperPayment.objects.create(
            project_assignment=assignment,
            amount_paid=Decimal("1000.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="Bank Transfer",
            payment_type=DeveloperPayment.PaymentType.ADVANCE,
        )

        from .services import recalculate_assignment_payments, recalculate_project_client_payments

        recalculate_project_client_payments(project)
        recalculate_assignment_payments(assignment)
        project.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(project.client_total_amount_received, Decimal("3000.00"))
        self.assertEqual(project.client_pending_amount, Decimal("2000.00"))
        self.assertEqual(assignment.total_amount_paid_to_developer, Decimal("1000.00"))
        self.assertEqual(assignment.pending_amount_to_developer, Decimal("1500.00"))
        summary = project_financial_summary(project)
        self.assertEqual(summary["approved_profit"], Decimal("2500.00"))
        self.assertEqual(summary["actual_cash_profit"], Decimal("2000.00"))

    def test_project_assignment_delete_button_renders_and_post_deletes_without_payments(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))
        vendor = DeveloperVendor.objects.create(name="Delete Assignment Dev", vendor_type=DeveloperVendor.VendorType.FREELANCER)
        assignment = ProjectAssignment.objects.create(
            project=project,
            developer_vendor=vendor,
            assigned_role="Frontend",
            developer_final_project_cost=Decimal("1200.00"),
        )
        detail = self.client.get(reverse("project_detail", kwargs={"pk": project.pk}))
        self.assertContains(detail, 'title="Delete Assignment"', html=False)
        self.assertContains(detail, 'aria-label="Delete Assignment"', html=False)
        self.assertContains(detail, "Are you sure you want to delete this developer/vendor assignment?")

        response = self.client.post(
            reverse("project_assignment_delete", kwargs={"project_id": project.pk, "assignment_id": assignment.pk}),
            follow=True,
        )

        self.assertContains(response, "Developer/Vendor assignment deleted successfully.")
        self.assertFalse(ProjectAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(DeveloperVendor.objects.filter(pk=vendor.pk).exists())
        self.assertEqual(response.context["summary"]["developer_final_cost"], Decimal("0.00"))

    def test_project_assignment_delete_rejects_get_and_requires_csrf(self):
        project = self.create_project()
        vendor = DeveloperVendor.objects.create(name="Secure Delete Dev", vendor_type=DeveloperVendor.VendorType.FREELANCER)
        assignment = ProjectAssignment.objects.create(project=project, developer_vendor=vendor, assigned_role="Backend")
        delete_url = reverse("project_assignment_delete", kwargs={"project_id": project.pk, "assignment_id": assignment.pk})

        get_response = self.client.get(delete_url)
        self.assertEqual(get_response.status_code, 405)

        csrf_client = TestClient(enforce_csrf_checks=True)
        csrf_client.login(username="owner", password="secure-test-password-123")
        csrf_response = csrf_client.post(delete_url)
        self.assertEqual(csrf_response.status_code, 403)
        self.assertTrue(ProjectAssignment.objects.filter(pk=assignment.pk).exists())

    def test_project_assignment_with_payments_is_protected_from_delete(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))
        vendor = DeveloperVendor.objects.create(name="Protected Assignment Dev", vendor_type=DeveloperVendor.VendorType.FREELANCER)
        assignment = ProjectAssignment.objects.create(
            project=project,
            developer_vendor=vendor,
            assigned_role="Backend",
            developer_final_project_cost=Decimal("2000.00"),
        )
        DeveloperPayment.objects.create(
            project_assignment=assignment,
            amount_paid=Decimal("500.00"),
            payment_date=date(2026, 6, 26),
            payment_mode="Bank Transfer",
            payment_type=DeveloperPayment.PaymentType.ADVANCE,
        )

        response = self.client.post(
            reverse("project_assignment_delete", kwargs={"project_id": project.pk, "assignment_id": assignment.pk}),
            follow=True,
        )

        self.assertContains(response, "This assignment has payment records and cannot be deleted.")
        self.assertTrue(ProjectAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(DeveloperPayment.objects.filter(project_assignment=assignment).exists())
        self.assertTrue(DeveloperVendor.objects.filter(pk=vendor.pk).exists())

    def test_project_assignment_blank_optional_amounts_save_as_zero(self):
        project = self.create_project(approved_quote=Decimal("5000.00"))
        vendor = DeveloperVendor.objects.create(
            name="Optional Amount Dev",
            vendor_type=DeveloperVendor.VendorType.FREELANCER,
        )
        response = self.client.post(
            reverse("project_assign_developer", kwargs={"pk": project.pk}),
            {
                "developer_vendor": vendor.pk,
                "assigned_role": "Backend",
                "work_description": "",
                "developer_cost_estimate": "",
                "developer_final_project_cost": "",
                "next_advance_amount_to_send": "",
                "next_advance_expected_date": "",
                "assignment_status": ProjectAssignment.AssignmentStatus.ASSIGNED,
                "remarks": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        assignment = ProjectAssignment.objects.get(project=project, developer_vendor=vendor)
        self.assertEqual(assignment.developer_cost_estimate, Decimal("0.00"))
        self.assertEqual(assignment.developer_final_project_cost, Decimal("0.00"))
        self.assertEqual(assignment.next_advance_amount_to_send, Decimal("0.00"))
        self.assertEqual(assignment.pending_amount_to_developer, Decimal("0.00"))

    def test_project_reports_exports_and_login_protection(self):
        project = self.create_project()
        project.client_amount_gst_type = Project.ClientAmountGstType.GST_EXTRA
        project.project_gst_percentage = Decimal("18.00")
        project.save()
        vendor = DeveloperVendor.objects.create(name="Report Dev", vendor_type=DeveloperVendor.VendorType.FREELANCER)
        ProjectAssignment.objects.create(
            project=project,
            developer_vendor=vendor,
            assigned_role="Backend",
            developer_cost_estimate=Decimal("1000.00"),
            developer_final_project_cost=Decimal("1200.00"),
        )
        response = self.client.get(reverse("project_reports"), {"report_type": "developer_wise"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, project.project_name)
        self.assertContains(response, "GST Amount")
        self.assertContains(response, "Total With GST")
        self.assertContains(response, "GST Extra / Amount Before GST")
        self.assertContains(response, "₹900")

        excel_response = self.client.get(reverse("project_report_export_excel"), {"report_type": "project_wise"})
        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(
            excel_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        excel_bytes = b"".join(excel_response.streaming_content)
        self.assertTrue(excel_bytes.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(excel_bytes)) as workbook_zip:
            workbook_xml = "\n".join(
                workbook_zip.read(name).decode("utf-8", errors="ignore")
                for name in workbook_zip.namelist()
                if name.startswith("xl/worksheets/") or name == "xl/sharedStrings.xml"
            )
        self.assertIn("GST Amount", workbook_xml)
        self.assertIn("Total With GST", workbook_xml)

        pdf_response = self.client.get(reverse("project_report_export_pdf"), {"report_type": "project_wise"})
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        pdf_bytes = b"".join(pdf_response.streaming_content)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        self.client.logout()
        for url in [reverse("project_list"), reverse("developer_vendor_list"), reverse("project_reports")]:
            protected = self.client.get(url)
            self.assertEqual(protected.status_code, 302)
            self.assertIn(reverse("login"), protected["Location"])


class EnhancementSafetyAndAnalyticsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="secure-test-password-123",
        )
        self.client.login(username="owner", password="secure-test-password-123")
        self.company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.client_record = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )

    def create_project(self, name="Delete Test Project"):
        return Project.objects.create(
            project_name=name,
            client=self.client_record,
            project_requirement="Project requirement",
            project_type=Project.ProjectType.WEB_APPLICATION,
            estimated_quote=Decimal("5000.00"),
            approved_quote=Decimal("5000.00"),
            project_status=Project.ProjectStatus.IN_PROGRESS,
            completion_percentage=50,
        )

    def create_invoice(self, project=None):
        invoice = Invoice.objects.create(
            invoice_number=generate_invoice_number(self.company, self.client_record, date(2026, 6, 26)),
            company=self.company,
            client=self.client_record,
            project=project,
            invoice_date=date(2026, 6, 26),
            subject="Enhancement invoice",
            subtotal=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            amount_in_words=amount_to_indian_words(Decimal("1180.00")),
            pending_amount=Decimal("1180.00"),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            serial_number=1,
            description="Enhancement work",
            item_price=Decimal("1000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("1000.00"),
        )
        return invoice

    def test_developer_vendor_delete_without_linked_projects(self):
        vendor = DeveloperVendor.objects.create(name="Unlinked Vendor", vendor_type=DeveloperVendor.VendorType.FREELANCER)
        confirm = self.client.get(reverse("developer_vendor_delete", kwargs={"pk": vendor.pk}))
        self.assertEqual(confirm.status_code, 200)
        self.assertContains(confirm, "Confirm Delete")

        response = self.client.post(reverse("developer_vendor_delete", kwargs={"pk": vendor.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DeveloperVendor.objects.filter(pk=vendor.pk).exists())

    def test_developer_vendor_delete_is_blocked_when_linked(self):
        project = self.create_project()
        vendor = DeveloperVendor.objects.create(name="Linked Vendor", vendor_type=DeveloperVendor.VendorType.COMPANY)
        ProjectAssignment.objects.create(
            project=project,
            developer_vendor=vendor,
            assigned_role="Backend",
            developer_cost_estimate=Decimal("1000.00"),
            developer_final_project_cost=Decimal("1000.00"),
        )
        confirm = self.client.get(reverse("developer_vendor_delete", kwargs={"pk": vendor.pk}))
        self.assertContains(confirm, "Mark Inactive")
        response = self.client.post(reverse("developer_vendor_delete", kwargs={"pk": vendor.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        vendor.refresh_from_db()
        self.assertEqual(vendor.status, DeveloperVendor.VendorStatus.INACTIVE)

    def test_project_delete_without_linked_records(self):
        project = self.create_project()
        confirm = self.client.get(reverse("project_delete", kwargs={"pk": project.pk}))
        self.assertContains(confirm, "Confirm Delete")
        response = self.client.post(reverse("project_delete", kwargs={"pk": project.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())

    def test_project_delete_is_blocked_when_linked(self):
        project = self.create_project()
        invoice = self.create_invoice(project=project)
        response = self.client.post(reverse("project_delete", kwargs={"pk": project.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.project_status, Project.ProjectStatus.CANCELLED)

    def test_status_and_fund_helpers(self):
        self.assertEqual(project_status_badge_class(Project.ProjectStatus.IN_PROGRESS), "badge-primary")
        self.assertEqual(project_status_badge_class(Project.ProjectStatus.CANCELLED), "badge-danger")
        self.assertEqual(completion_bar_class(10), "progress-danger")
        self.assertEqual(completion_bar_class(40), "progress-warning")
        self.assertEqual(completion_bar_class(65), "progress-info")
        self.assertEqual(completion_bar_class(85), "progress-primary")
        self.assertEqual(completion_bar_class(100), "progress-success")
        self.assertEqual(client_fund_status(Decimal("0.00"), Decimal("100.00"), Decimal("100.00"))["label"], "Not Received")
        self.assertEqual(client_fund_status(Decimal("50.00"), Decimal("50.00"), Decimal("100.00"))["label"], "Partially Received")
        self.assertEqual(client_fund_status(Decimal("100.00"), Decimal("0.00"), Decimal("100.00"))["label"], "Fully Received")
        self.assertEqual(client_fund_status(Decimal("120.00"), Decimal("-20.00"), Decimal("100.00"))["label"], "Extra Received")
        self.assertEqual(developer_fund_status(Decimal("0.00"), Decimal("100.00"), Decimal("100.00"))["label"], "Not Paid")
        self.assertEqual(developer_fund_status(Decimal("50.00"), Decimal("50.00"), Decimal("100.00"))["label"], "Partially Paid")
        self.assertEqual(developer_fund_status(Decimal("100.00"), Decimal("0.00"), Decimal("100.00"))["label"], "Fully Paid")
        self.assertEqual(developer_fund_status(Decimal("120.00"), Decimal("-20.00"), Decimal("100.00"))["label"], "Extra Paid")
        self.assertEqual(invoice_status_badge_class(Invoice.PaymentStatus.PENDING), "badge-danger")

    def test_dashboard_chart_data_and_existing_invoice_flow(self):
        project = self.create_project()
        invoice = self.create_invoice(project=project)
        response = self.client.get(reverse("dashboard"), {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dashboard-chart-data")
        self.assertContains(response, "Project Status")
        self.assertContains(response, "Monthly Invoice Raised vs Received")

        invoice_response = self.client.get(reverse("invoice_list"))
        self.assertContains(invoice_response, invoice.invoice_number)


class DraftSoftDeleteGstEnhancementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", password="secure-test-password-123")
        self.client.login(username="owner", password="secure-test-password-123")
        self.gst_company = Company.objects.create(
            company_name="Sunsolv Technologies",
            address="12 Tech Park",
            country="India",
            state="Karnataka",
            city="Bengaluru",
            pin_code="560001",
            gstin="29ABCDE1234F1Z5",
        )
        self.no_gst_company = Company.objects.create(
            company_name="Local Services",
            address="34 Market Street",
            country="India",
            state="Karnataka",
            city="Mysuru",
            pin_code="570001",
            gstin="",
        )
        self.client_record = Client.objects.create(
            client_name="MSU Enterprises",
            address="45 Commerce Road",
            country="India",
            state="Maharashtra",
            city="Mumbai",
            pin_code="400001",
            gstin="27ABCDE1234F1Z5",
        )

    def invoice_data(self, company=None, client_record=None, apply_gst="True", action="final", subject="Enhancement invoice"):
        return {
            "company": (company or self.gst_company).pk,
            "client": (client_record or self.client_record).pk,
            "invoice_date": "2026-06-26",
            "subject": subject,
            "apply_gst": apply_gst,
            "terms_and_conditions": "Payment should be made within the agreed timeline.",
            "declaration": "Invoice details are true and correct.",
            "invoice_action": action,
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-description": "Enhancement work",
            "items-0-item_price": "1000.00",
            "items-0-quantity": "1.00",
        }

    def create_final_invoice(self, invoice_number="SUNMSU-26062026-901", apply_gst=True):
        gst_amount = Decimal("180.00") if apply_gst else Decimal("0.00")
        total = Decimal("1180.00") if apply_gst else Decimal("1000.00")
        invoice = Invoice.objects.create(
            invoice_number=invoice_number,
            company=self.gst_company,
            client=self.client_record,
            invoice_date=date(2026, 6, 26),
            subject="Final enhancement invoice",
            apply_gst=apply_gst,
            subtotal=Decimal("1000.00"),
            gst_percentage=Decimal("18.00") if apply_gst else Decimal("0.00"),
            gst_amount=gst_amount,
            total_amount=total,
            amount_in_words=amount_to_indian_words(total),
            pending_amount=total,
            invoice_status=Invoice.InvoiceStatus.FINAL,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            serial_number=1,
            description="Enhancement work",
            item_price=Decimal("1000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("1000.00"),
        )
        return invoice

    def test_client_soft_delete_restore_and_dropdown_exclusion(self):
        response = self.client.post(reverse("client_soft_delete", kwargs={"pk": self.client_record.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.client_record.refresh_from_db()
        self.assertTrue(self.client_record.is_deleted)
        self.assertIsNotNone(self.client_record.deleted_at)

        add_invoice = self.client.get(reverse("invoice_add"))
        self.assertNotContains(add_invoice, self.client_record.client_name)
        add_project = self.client.get(reverse("project_add"))
        self.assertNotContains(add_project, self.client_record.client_name)

        response = self.client.post(reverse("client_restore", kwargs={"pk": self.client_record.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.client_record.refresh_from_db()
        self.assertFalse(self.client_record.is_deleted)
        self.assertContains(self.client.get(reverse("invoice_add")), self.client_record.client_name)

    def test_invoice_draft_edit_convert_to_final_and_soft_delete_restore(self):
        draft_data = {
            "company": self.gst_company.pk,
            "client": self.client_record.pk,
            "invoice_date": "2026-06-26",
            "invoice_action": "draft",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("invoice_add"), draft_data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.invoice_status, Invoice.InvoiceStatus.DRAFT)
        self.assertTrue(invoice.invoice_number.startswith("DRAFT-20260626-"))
        self.assertEqual(invoice.items.count(), 0)

        final_data = self.invoice_data(action="final", subject="Converted draft invoice")
        response = self.client.post(reverse("invoice_edit", kwargs={"pk": invoice.pk}), final_data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.invoice_status, Invoice.InvoiceStatus.FINAL)
        self.assertEqual(invoice.invoice_number, "SUNMSU-26062026-001")
        self.assertEqual(invoice.gst_amount, Decimal("180.00"))
        self.assertEqual(invoice.pending_amount, Decimal("1180.00"))
        self.assertEqual(invoice.items.count(), 1)

        self.client.post(reverse("invoice_soft_delete", kwargs={"pk": invoice.pk}), follow=True)
        invoice.refresh_from_db()
        self.assertTrue(invoice.is_deleted)
        self.assertEqual(invoice.invoice_status, Invoice.InvoiceStatus.DELETED)
        self.assertNotContains(self.client.get(reverse("invoice_list")), invoice.invoice_number)

        self.client.post(reverse("invoice_restore", kwargs={"pk": invoice.pk}), follow=True)
        invoice.refresh_from_db()
        self.assertFalse(invoice.is_deleted)
        self.assertEqual(invoice.invoice_status, Invoice.InvoiceStatus.FINAL)
        self.assertContains(self.client.get(reverse("invoice_list")), invoice.invoice_number)

    def test_gst_optional_and_blocked_without_company_gstin(self):
        response = self.client.post(reverse("invoice_add"), self.invoice_data(apply_gst="False"), follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get()
        self.assertFalse(invoice.apply_gst)
        self.assertEqual(invoice.gst_amount, Decimal("0.00"))
        self.assertEqual(invoice.total_amount, Decimal("1000.00"))
        self.assertEqual(invoice_title(invoice), "INVOICE")
        preview = self.client.get(reverse("invoice_preview", kwargs={"pk": invoice.pk}))
        self.assertContains(preview, "INVOICE")
        self.assertNotContains(preview, "TAX INVOICE")

        no_gst_client = Client.objects.create(
            client_name="Local Client",
            address="1 Local Road",
            country="India",
            state="Karnataka",
            city="Mysuru",
            pin_code="570002",
        )
        response = self.client.post(
            reverse("invoice_add"),
            self.invoice_data(company=self.no_gst_company, client_record=no_gst_client, apply_gst="True", subject="No GST company invoice"),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        no_gst_invoice = Invoice.objects.get(company=self.no_gst_company)
        self.assertFalse(no_gst_invoice.apply_gst)
        self.assertEqual(no_gst_invoice.gst_amount, Decimal("0.00"))
        self.assertEqual(invoice_title(no_gst_invoice), "INVOICE")

    def test_client_gst_preference_defaults_invoice_to_non_gst(self):
        client_no_gst = Client.objects.create(
            client_name="No GST Preference Client",
            address="1 Local Road",
            country="India",
            state="Karnataka",
            city="Mysuru",
            pin_code="570002",
            requires_gst_invoice=False,
        )
        data = self.invoice_data(client_record=client_no_gst, subject="Client preference invoice")
        data.pop("apply_gst")
        response = self.client.post(reverse("invoice_add"), data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(subject="Client preference invoice")
        self.assertFalse(invoice.apply_gst)
        self.assertEqual(invoice.gst_amount, Decimal("0.00"))
        self.assertEqual(invoice.total_amount, Decimal("1000.00"))

    def test_hsn_sac_code_master_crud_uppercase_and_unique_constraint(self):
        code = HsnSacCode.objects.create(code="svc001", description="Software services")
        self.assertEqual(code.code, "SVC001")

        list_response = self.client.get(reverse("hsn_sac_code_list"))
        self.assertContains(list_response, "SVC001")

        create_response = self.client.post(
            reverse("hsn_sac_code_add"),
            {"code": "998314", "description": "IT consulting"},
            follow=True,
        )
        self.assertEqual(create_response.status_code, 200)
        created_code = HsnSacCode.objects.get(code="998314")

        edit_response = self.client.post(
            reverse("hsn_sac_code_edit", kwargs={"pk": created_code.pk}),
            {"code": "998315", "description": "Updated consulting"},
            follow=True,
        )
        self.assertEqual(edit_response.status_code, 200)
        created_code.refresh_from_db()
        self.assertEqual(created_code.code, "998315")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HsnSacCode.objects.create(code="svc001", description="Duplicate")

    def test_invoice_item_hsn_sac_selection_optional_and_existing_compatibility(self):
        code = HsnSacCode.objects.create(code="998314", description="IT consulting")
        data = self.invoice_data(subject="HSN selected invoice")
        data["items-0-hsn_sac_code"] = str(code.pk)
        response = self.client.post(reverse("invoice_add"), data, follow=True)
        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(subject="HSN selected invoice")
        item = invoice.items.get()
        self.assertEqual(item.hsn_sac_code, code)

        detail = self.client.get(reverse("invoice_detail", kwargs={"pk": invoice.pk}))
        preview = self.client.get(reverse("invoice_preview", kwargs={"pk": invoice.pk}))
        edit = self.client.get(reverse("invoice_edit", kwargs={"pk": invoice.pk}))
        self.assertContains(detail, "998314")
        self.assertContains(preview, "998314")
        self.assertContains(edit, "998314")

        no_code_response = self.client.post(reverse("invoice_add"), self.invoice_data(subject="No HSN invoice"), follow=True)
        self.assertEqual(no_code_response.status_code, 200)
        no_code_invoice = Invoice.objects.get(subject="No HSN invoice")
        self.assertIsNone(no_code_invoice.items.get().hsn_sac_code)
        no_code_preview = self.client.get(reverse("invoice_preview", kwargs={"pk": no_code_invoice.pk}))
        self.assertContains(no_code_preview, "<td>-</td>", html=True)

    def test_invoice_title_and_bank_details_render_in_preview_and_pdf_template(self):
        self.gst_company.bank_name = "State Bank of India"
        self.gst_company.bank_account_number = "123456789012"
        self.gst_company.bank_branch = "MG Road"
        self.gst_company.ifsc_code = "SBIN0001234"
        self.gst_company.save()
        invoice = self.create_final_invoice("GSTMSU-26062026-777", apply_gst=True)
        self.assertEqual(invoice_title(invoice), "TAX INVOICE")

        preview = self.client.get(reverse("invoice_preview", kwargs={"pk": invoice.pk}))
        self.assertContains(preview, "TAX INVOICE")
        self.assertContains(preview, "Bank Details")
        self.assertContains(preview, "Account Name")
        self.assertContains(preview, "Sunsolv Technologies")
        self.assertContains(preview, "State Bank of India")
        self.assertContains(preview, "SBIN0001234")
        self.assertContains(preview, "This is a computer generated invoice.")
        self.assertNotContains(preview, "Status:")
        self.assertNotContains(preview, "Payment Status")
        self.assertNotContains(preview, "Invoice Status")

        hsn_code = HsnSacCode.objects.create(code="998314", description="IT consulting")
        item = invoice.items.get()
        item.hsn_sac_code = hsn_code
        item.save(update_fields=["hsn_sac_code"])

        pdf_html = render_to_string(
            "invoices/invoice_pdf.html",
            {
                "invoice": invoice,
                "invoice_title": invoice_title(invoice),
                "company_logo_uri": "",
                "company_signature_uri": "",
            },
        )
        self.assertIn("TAX INVOICE", pdf_html)
        self.assertIn("Bank Details", pdf_html)
        self.assertIn("Account Name", pdf_html)
        self.assertIn("State Bank of India", pdf_html)
        self.assertIn("998314", pdf_html)
        self.assertIn("This is a computer generated invoice.", pdf_html)
        self.assertNotIn("Status", pdf_html)
        self.assertNotIn("Payment Status", pdf_html)
        self.assertNotIn("Invoice Status", pdf_html)

    def test_report_gst_and_non_gst_filters_and_dashboard_excludes_deleted(self):
        gst_invoice = self.create_final_invoice("GSTMSU-26062026-001", apply_gst=True)
        non_gst_invoice = self.create_final_invoice("NGTMSU-26062026-001", apply_gst=False)
        deleted_invoice = self.create_final_invoice("DELMSU-26062026-001", apply_gst=True)
        self.client.post(reverse("invoice_soft_delete", kwargs={"pk": deleted_invoice.pk}), follow=True)

        dashboard = self.client.get(reverse("dashboard"), {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"})
        self.assertContains(dashboard, "GSTMSU-26062026-001")
        self.assertNotContains(dashboard, "DELMSU-26062026-001")

        gst_report = self.client.get(reverse("reports"), {"gst_type": "gst"})
        self.assertContains(gst_report, gst_invoice.invoice_number)
        self.assertNotContains(gst_report, non_gst_invoice.invoice_number)
        self.assertNotContains(gst_report, deleted_invoice.invoice_number)

        non_gst_report = self.client.get(reverse("reports"), {"gst_type": "non_gst"})
        self.assertContains(non_gst_report, non_gst_invoice.invoice_number)
        self.assertNotContains(non_gst_report, gst_invoice.invoice_number)

        excel_response = self.client.get(reverse("report_export_excel"), {"gst_type": "gst"})
        self.assertEqual(excel_response.status_code, 200)
        pdf_response = self.client.get(reverse("report_export_pdf"), {"gst_type": "non_gst"})
        self.assertEqual(pdf_response.status_code, 200)

    def test_digital_marketing_recurring_one_time_and_project_draft(self):
        recurring_data = {
            "client": self.client_record.pk,
            "project_name": "Recurring marketing",
            "project_requirement": "Monthly marketing support",
            "project_type": Project.ProjectType.DIGITAL_MARKETING,
            "billing_type": Project.BillingType.RECURRING,
            "estimated_quote": "5000.00",
            "approved_quote": "5000.00",
            "completion_percentage": "0",
            "project_status": Project.ProjectStatus.IN_PROGRESS,
            "priority": Project.Priority.MEDIUM,
            "project_action": "final",
        }
        response = self.client.post(reverse("project_add"), recurring_data, follow=True)
        self.assertEqual(response.status_code, 200)
        recurring = Project.objects.get(project_name="Recurring marketing")
        self.assertEqual(recurring.billing_type, Project.BillingType.RECURRING)
        self.assertIsNone(recurring.start_date)
        self.assertIsNone(recurring.expected_completion_date)

        one_time_data = recurring_data | {
            "project_name": "One-time marketing",
            "billing_type": Project.BillingType.ONE_TIME,
            "start_date": "2026-06-26",
            "expected_completion_date": "2026-07-26",
        }
        response = self.client.post(reverse("project_add"), one_time_data, follow=True)
        self.assertEqual(response.status_code, 200)
        one_time = Project.objects.get(project_name="One-time marketing")
        self.assertEqual(one_time.billing_type, Project.BillingType.ONE_TIME)
        self.assertEqual(one_time.start_date, date(2026, 6, 26))

        draft_response = self.client.post(
            reverse("project_add"),
            {"client": self.client_record.pk, "project_name": "Draft project", "project_action": "draft"},
            follow=True,
        )
        self.assertEqual(draft_response.status_code, 200)
        draft = Project.objects.get(project_name="Draft project")
        self.assertEqual(draft.project_status, Project.ProjectStatus.DRAFT)
        self.assertContains(self.client.get(reverse("dashboard")), "Draft projects")


class PhaseEightTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="phase8", password="secure-test-password-123", is_superuser=True)
        self.client.login(username="phase8", password="secure-test-password-123")
        self.company = Company.objects.create(
            company_name="Phase Eight Company",
            address="Company address",
            country="India",
            state="Telangana",
            city="Hyderabad",
            pin_code="500001",
        )
        self.client_record = Client.objects.create(
            client_name="Phase Eight Client",
            address="Client address",
            country="India",
            state="Telangana",
            city="Hyderabad",
            pin_code="500002",
        )
        self.invoice = Invoice.objects.create(
            invoice_number="PHECLI-27062026-001",
            company=self.company,
            client=self.client_record,
            invoice_date=date(2026, 6, 27),
            subject="Phase Eight Services",
            apply_gst=False,
            subtotal=Decimal("1000.00"),
            gst_percentage=Decimal("0.00"),
            gst_amount=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
            amount_in_words="Rupees One Thousand Only",
            payment_status=Invoice.PaymentStatus.PARTIALLY_PAID,
            invoice_status=Invoice.InvoiceStatus.FINAL,
            received_amount=Decimal("400.00"),
            pending_amount=Decimal("600.00"),
        )
        InvoiceItem.objects.create(
            invoice=self.invoice,
            serial_number=1,
            description="Phase 8 work",
            item_price=Decimal("1000.00"),
            quantity=Decimal("1.00"),
            total=Decimal("1000.00"),
        )
        Payment.objects.create(
            invoice=self.invoice,
            received_amount=Decimal("400.00"),
            payment_date=date(2026, 6, 27),
            payment_mode=Payment.PaymentMode.UPI,
            remarks="Phase 8 payment",
        )
        self.project = Project.objects.create(
            project_name="Phase Eight Project",
            client=self.client_record,
            project_requirement="Track Phase 8",
            project_type=Project.ProjectType.WEB_APPLICATION,
            approved_quote=Decimal("1500.00"),
            client_total_amount_received=Decimal("400.00"),
            client_pending_amount=Decimal("1100.00"),
            project_status=Project.ProjectStatus.IN_PROGRESS,
            priority=Project.Priority.MEDIUM,
        )

    def test_major_lists_are_paginated(self):
        for index in range(12):
            Client.objects.create(
                client_name=f"Paged Client {index:02d}",
                address="Address",
                country="India",
                state="Telangana",
                city="Hyderabad",
                pin_code="500001",
            )
        response = self.client.get(reverse("client_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(len(response.context["clients"]), 10)

    def test_global_search_finds_active_records_and_excludes_deleted_clients(self):
        Client.objects.create(
            client_name="Hidden Search Client",
            address="Address",
            country="India",
            state="Telangana",
            city="Hyderabad",
            pin_code="500001",
            is_deleted=True,
            client_status=Client.ClientStatus.DELETED,
        )
        response = self.client.get(reverse("global_search"), {"q": "Phase Eight"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.invoice.invoice_number)
        self.assertContains(response, self.client_record.client_name)
        self.assertContains(response, self.company.company_name)
        self.assertNotContains(response, "Hidden Search Client")

    def test_dashboard_backup_reminder_and_activity_sections_render(self):
        backup_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, backup_root, True)
        with override_settings(BACKUP_ROOT=backup_root):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Backup Reminder")
        self.assertContains(response, "Total Invoice Value")
        self.assertContains(response, "Recent Activity")

    def test_client_and_project_ledgers_show_financial_totals(self):
        client_response = self.client.get(reverse("client_ledger", kwargs={"pk": self.client_record.pk}))
        self.assertEqual(client_response.status_code, 200)
        self.assertContains(client_response, "Total invoices raised")
        self.assertContains(client_response, "₹1,000")
        self.assertContains(client_response, "Phase 8 payment")

        project_response = self.client.get(reverse("project_ledger", kwargs={"pk": self.project.pk}))
        self.assertEqual(project_response.status_code, 200)
        self.assertContains(project_response, "Client pending")
        self.assertContains(project_response, "₹1,100")

    def test_invoice_clone_creates_draft_without_payments_or_pdf(self):
        response = self.client.post(reverse("invoice_clone", kwargs={"pk": self.invoice.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        clone = Invoice.objects.exclude(pk=self.invoice.pk).get(subject=self.invoice.subject)
        self.assertEqual(clone.invoice_status, Invoice.InvoiceStatus.DRAFT)
        self.assertTrue(clone.invoice_number.startswith("DRAFT-"))
        self.assertEqual(clone.items.count(), 1)
        self.assertEqual(clone.payments.count(), 0)
        self.assertFalse(bool(clone.pdf_file))
        self.assertTrue(ActivityLog.objects.filter(module="Invoice", action="cloned").exists())

    def test_recurring_template_creation_and_manual_draft_generation(self):
        response = self.client.post(
            reverse("recurring_invoice_add"),
            {
                "company": self.company.pk,
                "client": self.client_record.pk,
                "project": "",
                "title": "Monthly Maintenance",
                "frequency": RecurringInvoiceTemplate.Frequency.MONTHLY,
                "next_invoice_date": "2026-06-27",
                "apply_gst": "on",
                "is_active": "on",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-description": "Maintenance service",
                "items-0-hsn_sac_code": "",
                "items-0-item_price": "1200.00",
                "items-0-quantity": "1.00",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        recurring = RecurringInvoiceTemplate.objects.get(title="Monthly Maintenance")
        self.assertEqual(recurring.items.count(), 1)

        response = self.client.post(reverse("recurring_invoice_generate", kwargs={"pk": recurring.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        draft = Invoice.objects.get(subject="Monthly Maintenance")
        self.assertEqual(draft.invoice_status, Invoice.InvoiceStatus.DRAFT)
        self.assertEqual(draft.payments.count(), 0)
        recurring.refresh_from_db()
        self.assertEqual(recurring.next_invoice_date, date(2026, 7, 27))

    def test_empty_invoice_list_message_is_helpful(self):
        Invoice.objects.all().delete()
        response = self.client.get(reverse("invoice_list"))
        self.assertContains(response, "No invoices found. Create your first invoice to get started.")
