import re
from decimal import Decimal
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms import BaseFormSet, inlineformset_factory, formset_factory
from django.utils.html import strip_tags

from .models import (
    ApplicationSetting,
    Client,
    Company,
    CURRENCY_CHOICES,
    CURRENCY_INR,
    DEFAULT_DECLARATION,
    DEFAULT_TERMS_AND_CONDITIONS,
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
from .validators import normalize_gstin_value, normalize_ifsc_value, validate_gstin_value, validate_ifsc_value


CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
GSTIN_WIDGET_ATTRS = {
    "class": "form-control",
    "placeholder": "Example: 36AADC07549J1ZZ",
    "maxlength": "15",
    "autocapitalize": "characters",
    "spellcheck": "false",
    "oninput": "this.value = this.value.toUpperCase();",
}


def active_client_queryset():
    return Client.objects.filter(
        is_deleted=False,
        client_status=Client.ClientStatus.ACTIVE,
    )


def sanitize_text(value):
    if value is None:
        return value
    value = CONTROL_CHARS.sub("", str(value))
    return strip_tags(value).strip()


class SanitizedModelForm(forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if isinstance(field, (forms.CharField, forms.TypedChoiceField)):
                value = cleaned_data.get(field_name)
                if isinstance(value, str):
                    cleaned_data[field_name] = sanitize_text(value)
                    if field.required and not cleaned_data[field_name]:
                        self.add_error(field_name, "This field is required.")
        return cleaned_data


class FirstTimeAdminSetupForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": "autofocus"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    def clean_username(self):
        username = sanitize_text(self.cleaned_data.get("username", ""))
        if not username:
            raise forms.ValidationError("Username is required.")
        if get_user_model().objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already in use.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if len(password) < 8:
            raise forms.ValidationError("Password must be at least 8 characters.")
        if not re.search(r"[A-Z]", password):
            raise forms.ValidationError("Password must include at least one capital letter.")
        if not re.search(r"\d", password):
            raise forms.ValidationError("Password must include at least one number.")
        if not re.search(r"[@!#%&*]", password):
            raise forms.ValidationError("Password must include at least one symbol: @ ! # % & *.")
        return password

    def clean(self):
        cleaned_data = super().clean()
        if get_user_model().objects.exists():
            raise forms.ValidationError("First-time setup is disabled because an admin account already exists.")
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Password and confirm password must match.")
        return cleaned_data

    def save(self):
        User = get_user_model()
        return User.objects.create_superuser(
            username=self.cleaned_data["username"],
            email=self.cleaned_data.get("email", ""),
            password=self.cleaned_data["password"],
        )


class CompanyForm(SanitizedModelForm):
    gstin = forms.CharField(
        required=False,
        label="GSTIN",
        widget=forms.TextInput(attrs=GSTIN_WIDGET_ATTRS),
    )

    class Meta:
        model = Company
        fields = [
            "company_name",
            "address",
            "country",
            "state",
            "city",
            "pin_code",
            "gstin",
            "logo",
            "authorized_signature",
            "account_name",
            "bank_name",
            "bank_account_number",
            "bank_branch",
            "ifsc_code",
        ]
        labels = {
            "account_name": "Account Name",
            "bank_name": "Bank Name",
            "bank_account_number": "Bank Account Number",
            "bank_branch": "Branch Name",
            "ifsc_code": "IFSC Code",
        }
        widgets = {
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "pin_code": forms.TextInput(attrs={"class": "form-control"}),
            "account_name": forms.TextInput(attrs={"class": "form-control"}),
            "bank_name": forms.TextInput(attrs={"class": "form-control"}),
            "bank_account_number": forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric"}),
            "bank_branch": forms.TextInput(attrs={"class": "form-control"}),
            "ifsc_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Example: SBIN0001234", "maxlength": "11", "autocapitalize": "characters", "spellcheck": "false", "oninput": "this.value = this.value.toUpperCase();"}),
            "logo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".png,.jpg,.jpeg,.svg"}),
            "authorized_signature": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".png,.jpg,.jpeg,.svg"}),
        }

    def clean_gstin(self):
        gstin = normalize_gstin_value(sanitize_text(self.cleaned_data.get("gstin", "")))
        validate_gstin_value(gstin)
        return gstin

    def clean_bank_account_number(self):
        value = sanitize_text(self.cleaned_data.get("bank_account_number", ""))
        if not value:
            return value
        value = re.sub(r"\s+", "", value)
        if not re.match(r"^\d{6,30}$", value):
            raise forms.ValidationError("Enter a valid bank account number using 6 to 30 digits.")
        return value

    def clean_ifsc_code(self):
        ifsc = normalize_ifsc_value(sanitize_text(self.cleaned_data.get("ifsc_code", "")))
        validate_ifsc_value(ifsc)
        return ifsc


class ClientForm(SanitizedModelForm):
    gstin = forms.CharField(
        required=False,
        label="GSTIN",
        widget=forms.TextInput(attrs=GSTIN_WIDGET_ATTRS),
    )
    requires_gst_invoice = forms.BooleanField(
        required=False,
        initial=True,
        label="Requires GST Invoice?",
        help_text=(
            "If disabled, new invoices for this client will default to normal Invoice without GST. "
            "You can still override this while creating invoice."
        ),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    class Meta:
        model = Client
        fields = [
            "client_name",
            "address",
            "country",
            "state",
            "city",
            "pin_code",
            "gstin",
            "requires_gst_invoice",
        ]
        widgets = {
            "client_name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "pin_code": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.is_draft = kwargs.pop("is_draft", False)
        super().__init__(*args, **kwargs)
        self.fields["client_name"].label = "Client Name / Company Name"
        if self.is_draft:
            for field in self.fields.values():
                field.required = False
            self.fields["client_name"].required = True

    def clean_gstin(self):
        gstin = normalize_gstin_value(sanitize_text(self.cleaned_data.get("gstin", "")))
        validate_gstin_value(gstin)
        return gstin

    def clean(self):
        cleaned_data = super().clean()
        if self.is_draft:
            for field_name in ["address", "country", "state", "city", "pin_code"]:
                cleaned_data[field_name] = cleaned_data.get(field_name) or ""
        return cleaned_data


class InvoiceForm(SanitizedModelForm):
    invoice_number = forms.CharField(
        required=False,
        disabled=True,
        widget=forms.TextInput(attrs={"class": "form-control", "readonly": "readonly"}),
    )
    apply_gst = forms.TypedChoiceField(
        choices=[(True, "Yes"), (False, "No")],
        coerce=lambda value: value in (True, "True", "true", "1", "yes", "Yes"),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Apply GST?",
    )

    class Meta:
        model = Invoice
        fields = [
            "invoice_number",
            "company",
            "client",
            "project",
            "invoice_date",
            "currency",
            "subject",
            "apply_gst",
            "terms_and_conditions",
            "declaration",
        ]
        widgets = {
            "company": forms.Select(attrs={"class": "form-control"}),
            "client": forms.Select(attrs={"class": "form-control"}),
            "project": forms.Select(attrs={"class": "form-control"}),
            "invoice_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
            "currency": forms.Select(attrs={"class": "form-control"}),
            "subject": forms.TextInput(attrs={"class": "form-control"}),
            "terms_and_conditions": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "declaration": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        self.is_draft = kwargs.pop("is_draft", False)
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.all()
        client_filter = Q(is_deleted=False, client_status=Client.ClientStatus.ACTIVE)
        project_filter = Q(client__is_deleted=False, client__client_status=Client.ClientStatus.ACTIVE)
        if self.instance and self.instance.pk:
            client_filter |= Q(pk=self.instance.client_id)
            if self.instance.project_id:
                project_filter |= Q(pk=self.instance.project_id)
        self.fields["client"].queryset = Client.objects.filter(client_filter)
        self.fields["project"].queryset = Project.objects.select_related("client").filter(project_filter)
        self.fields["project"].required = False
        self.fields["project"].empty_label = "No project"
        self.fields["currency"].required = False
        self.fields["currency"].initial = CURRENCY_INR
        self.fields["invoice_number"].help_text = "Generated automatically from company, client, date, and sequence."
        self.fields["subject"].required = not self.is_draft
        self.fields["terms_and_conditions"].required = not self.is_draft
        self.fields["declaration"].required = not self.is_draft
        self.fields["apply_gst"].initial = True
        if not self.instance.pk and not self.is_bound:
            app_settings = ApplicationSetting.load()
            self.initial["terms_and_conditions"] = app_settings.default_terms_and_conditions
            self.initial["declaration"] = app_settings.default_declaration
        if self.instance.pk:
            self.initial["apply_gst"] = self.instance.apply_gst

    def clean_invoice_number(self):
        return self.instance.invoice_number if self.instance and self.instance.pk else ""

    def clean_apply_gst(self):
        value = self.cleaned_data.get("apply_gst")
        if value in (None, ""):
            return True
        return value

    def clean_currency(self):
        return self.cleaned_data.get("currency") or CURRENCY_INR

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        project = cleaned_data.get("project")
        if self.is_bound and "apply_gst" not in self.data and client:
            cleaned_data["apply_gst"] = bool(client.requires_gst_invoice)
        if project and client and project.client_id != client.id:
            self.add_error("project", "Selected project must belong to the selected client.")
        return cleaned_data


class InvoiceItemForm(forms.ModelForm):
    hsn_sac_code = forms.ModelChoiceField(
        queryset=HsnSacCode.objects.none(),
        required=False,
        empty_label="No HSN/SAC",
        widget=forms.Select(attrs={"class": "form-control hsn-sac-select"}),
        label="HSN/SAC Code",
    )
    item_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"class": "form-control item-price", "step": "0.01", "min": "0"}),
    )
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control item-quantity", "step": "0.01", "min": "0.01"}),
    )

    class Meta:
        model = InvoiceItem
        fields = ["description", "hsn_sac_code", "item_price", "quantity"]
        widgets = {
            "description": forms.Textarea(attrs={"class": "form-control item-description", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hsn_sac_code"].queryset = HsnSacCode.objects.all()

    def clean_description(self):
        description = sanitize_text(self.cleaned_data.get("description", ""))
        if not description:
            raise forms.ValidationError("Description is required.")
        return description


class HsnSacCodeForm(forms.ModelForm):
    class Meta:
        model = HsnSacCode
        fields = ["code", "description"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "maxlength": "20", "autocapitalize": "characters", "spellcheck": "false", "oninput": "this.value = this.value.toUpperCase();"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_code(self):
        code = sanitize_text(self.cleaned_data.get("code", "")).upper()
        if not code:
            raise forms.ValidationError("HSN/SAC Code is required.")
        return code


class BaseInvoiceItemFormSet(BaseFormSet):
    def __init__(self, *args, **kwargs):
        self.require_items = kwargs.pop("require_items", True)
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        item_count = 0
        for form in self.forms:
            cleaned_data = getattr(form, "cleaned_data", {})
            if cleaned_data.get("DELETE"):
                continue
            has_values = any(
                cleaned_data.get(field_name) not in (None, "")
                for field_name in ("description", "item_price", "quantity")
            )
            if not has_values:
                continue
            item_count += 1

        if self.require_items and item_count == 0:
            raise forms.ValidationError("At least one invoice item is required.")


InvoiceItemFormSet = formset_factory(
    InvoiceItemForm,
    formset=BaseInvoiceItemFormSet,
    extra=1,
    can_delete=True,
)


class PaymentForm(SanitizedModelForm):
    received_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )

    class Meta:
        model = Payment
        fields = ["received_amount", "payment_date", "payment_mode", "remarks"]
        widgets = {
            "payment_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
            "payment_mode": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.invoice = kwargs.pop("invoice")
        super().__init__(*args, **kwargs)

    def clean_received_amount(self):
        received_amount = self.cleaned_data["received_amount"]
        if received_amount > self.invoice.pending_amount:
            raise forms.ValidationError("Payment amount cannot exceed the invoice pending amount.")
        return received_amount


class DashboardFilterForm(forms.Form):
    PERIOD_CHOICES = [
        ("this_month", "This month"),
        ("last_month", "Last month"),
        ("custom", "Custom date range"),
    ]

    period = forms.ChoiceField(choices=PERIOD_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    client = forms.ModelChoiceField(queryset=Client.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    currency = forms.ChoiceField(choices=[("", "All currencies")] + CURRENCY_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    payment_status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = active_client_queryset()
        self.fields["payment_status"].choices = [("", "All statuses")] + list(Invoice.PaymentStatus.choices)


class InvoiceFilterForm(forms.Form):
    GST_CHOICES = [
        ("", "All invoices"),
        ("gst", "GST invoices"),
        ("non_gst", "Non-GST invoices"),
    ]
    RECORD_STATUS_CHOICES = [
        ("active", "Active Invoices"),
        ("draft", "Draft Invoices"),
        ("final", "Final Invoices"),
        ("deleted", "Deleted Invoices"),
        ("all", "All Invoices"),
    ]

    q = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Invoice, company, client, subject"}))
    month = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "type": "month"}))
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    company = forms.ModelChoiceField(queryset=Company.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    client = forms.ModelChoiceField(queryset=Client.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    currency = forms.ChoiceField(choices=[("", "All currencies")] + CURRENCY_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    payment_status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "form-control"}))
    gst_type = forms.ChoiceField(label="GST Type", choices=GST_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    record_status = forms.ChoiceField(label="Invoice View", choices=RECORD_STATUS_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.all()
        self.fields["client"].queryset = active_client_queryset()
        self.fields["project"].queryset = Project.objects.select_related("client").all()
        self.fields["payment_status"].choices = [("", "All statuses")] + list(Invoice.PaymentStatus.choices)


class ReportFilterForm(forms.Form):
    REPORT_TYPES = [
        ("date_range", "Date range invoice report"),
        ("month_wise", "Month-wise invoice report"),
        ("client_wise", "Client-wise invoice report"),
        ("paid", "Paid invoice report"),
        ("pending", "Pending invoice report"),
        ("partially_paid", "Partially paid invoice report"),
        ("gst", "GST report"),
        ("payment_received", "Payment received report"),
    ]
    GST_CHOICES = [
        ("", "All"),
        ("gst", "GST Invoices"),
        ("non_gst", "Non-GST Invoices"),
    ]

    report_type = forms.ChoiceField(choices=REPORT_TYPES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    company = forms.ModelChoiceField(queryset=Company.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    client = forms.ModelChoiceField(queryset=Client.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    currency = forms.ChoiceField(choices=[("", "All currencies")] + CURRENCY_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    payment_status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "form-control"}))
    gst_type = forms.ChoiceField(label="GST Type", choices=GST_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    include_deleted = forms.BooleanField(label="Include Deleted", required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.all()
        self.fields["client"].queryset = active_client_queryset()
        self.fields["payment_status"].choices = [("", "All statuses")] + list(Invoice.PaymentStatus.choices)


class ApplicationSettingsForm(SanitizedModelForm):
    default_gst_percentage = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("100.00"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
    )

    class Meta:
        model = ApplicationSetting
        fields = [
            "default_gst_percentage",
            "default_terms_and_conditions",
            "default_declaration",
            "default_payment_terms",
            "invoice_number_format",
            "date_separator",
            "prefix_separator",
            "running_sequence_length",
        ]
        widgets = {
            "default_terms_and_conditions": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "default_declaration": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "default_payment_terms": forms.TextInput(attrs={"class": "form-control"}),
            "invoice_number_format": forms.TextInput(attrs={"class": "form-control"}),
            "date_separator": forms.TextInput(attrs={"class": "form-control"}),
            "prefix_separator": forms.TextInput(attrs={"class": "form-control"}),
            "running_sequence_length": forms.NumberInput(attrs={"class": "form-control", "min": "1", "max": "9"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ["invoice_number_format", "date_separator", "prefix_separator", "running_sequence_length"]:
            self.fields[field_name].disabled = True
            self.fields[field_name].help_text = "Future-ready setting. Current invoice number logic keeps the default format."
        self.fields["default_gst_percentage"].help_text = "Used for new GST invoices when the selected company has a GSTIN."

    def clean_default_terms_and_conditions(self):
        value = sanitize_text(self.cleaned_data.get("default_terms_and_conditions", ""))
        if not value:
            raise forms.ValidationError("Default terms and conditions are required.")
        return value

    def clean_default_declaration(self):
        value = sanitize_text(self.cleaned_data.get("default_declaration", ""))
        if not value:
            raise forms.ValidationError("Default declaration is required.")
        return value


class BackupUploadForm(forms.Form):
    backup_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".zip"}),
        help_text="Upload a backup ZIP created by this application.",
    )

    def clean_backup_file(self):
        backup_file = self.cleaned_data["backup_file"]
        if Path(backup_file.name).suffix.lower() != ".zip":
            raise forms.ValidationError("Upload a valid .zip backup file.")
        max_size = getattr(settings, "MAX_BACKUP_UPLOAD_SIZE", 512 * 1024 * 1024)
        if backup_file.size > max_size:
            raise forms.ValidationError("Backup file is too large.")
        return backup_file


class ProjectForm(SanitizedModelForm):
    estimated_quote = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Optional, default 0.00"}),
    )
    approved_quote = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Optional, default 0.00"}),
    )
    client_next_advance_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Optional, default 0.00"}),
    )
    project_gst_percentage = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("100.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
        label="GST Percentage",
    )
    partial_gst_taxable_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
        label="GST Applicable Amount",
    )
    completion_percentage = forms.IntegerField(
        min_value=0,
        max_value=100,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "100"}),
    )

    class Meta:
        model = Project
        fields = [
            "client",
            "project_name",
            "currency",
            "project_requirement",
            "project_type",
            "billing_type",
            "custom_project_type",
            "project_description",
            "estimated_quote",
            "approved_quote",
            "client_amount_gst_type",
            "project_gst_percentage",
            "partial_gst_taxable_amount",
            "client_next_advance_amount",
            "client_next_advance_expected_date",
            "client_payment_remarks",
            "start_date",
            "expected_completion_date",
            "actual_completion_date",
            "project_status",
            "completion_percentage",
            "priority",
            "remarks",
        ]
        widgets = {
            "client": forms.Select(attrs={"class": "form-control"}),
            "project_name": forms.TextInput(attrs={"class": "form-control"}),
            "currency": forms.Select(attrs={"class": "form-control"}),
            "project_requirement": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "project_type": forms.Select(attrs={"class": "form-control"}),
            "billing_type": forms.Select(attrs={"class": "form-control"}),
            "custom_project_type": forms.TextInput(attrs={"class": "form-control", "placeholder": "Required when project type is Other"}),
            "client_amount_gst_type": forms.Select(attrs={"class": "form-control"}),
            "project_description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "client_next_advance_expected_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "client_payment_remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expected_completion_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "actual_completion_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "project_status": forms.Select(attrs={"class": "form-control"}),
            "priority": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.is_draft = kwargs.pop("is_draft", False)
        super().__init__(*args, **kwargs)
        self.fields["billing_type"].label = "Project Billing Type"
        self.fields["client_amount_gst_type"].label = "Approved Client Amount GST Type"
        self.fields["currency"].label = "Project Currency"
        self.fields["currency"].required = False
        self.fields["currency"].initial = CURRENCY_INR
        self.fields["client_amount_gst_type"].help_text = "Choose how GST should be handled for the approved client amount."
        self.fields["client_amount_gst_type"].required = False
        self.fields["client_amount_gst_type"].initial = Project.ClientAmountGstType.WITHOUT_GST
        self.fields["partial_gst_taxable_amount"].help_text = "Enter only the portion of approved client amount on which GST should be calculated."
        if not self.instance.pk and not self.is_bound:
            self.initial["project_gst_percentage"] = ApplicationSetting.load().default_gst_percentage
        client_filter = Q(is_deleted=False, client_status=Client.ClientStatus.ACTIVE)
        if self.instance and self.instance.pk:
            client_filter |= Q(pk=self.instance.client_id)
        self.fields["client"].queryset = Client.objects.filter(client_filter)
        self.fields["billing_type"].required = False
        if self.is_draft:
            for field in self.fields.values():
                field.required = False
            self.fields["client"].required = True
            self.fields["project_name"].required = True

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["client_amount_gst_type"] = cleaned_data.get("client_amount_gst_type") or Project.ClientAmountGstType.WITHOUT_GST
        if self.is_draft:
            cleaned_data["project_status"] = Project.ProjectStatus.DRAFT
            cleaned_data["project_requirement"] = cleaned_data.get("project_requirement") or ""
            cleaned_data["project_type"] = cleaned_data.get("project_type") or Project.ProjectType.OTHER
            cleaned_data["billing_type"] = cleaned_data.get("billing_type") or Project.BillingType.ONE_TIME
            cleaned_data["priority"] = cleaned_data.get("priority") or Project.Priority.MEDIUM
            cleaned_data["completion_percentage"] = cleaned_data.get("completion_percentage") or 0
            for field_name in ["estimated_quote", "approved_quote", "project_gst_percentage", "partial_gst_taxable_amount", "client_next_advance_amount"]:
                cleaned_data[field_name] = cleaned_data.get(field_name) or Decimal("0.00")
            return cleaned_data
        if cleaned_data.get("project_type") == Project.ProjectType.OTHER and not cleaned_data.get("custom_project_type"):
            self.add_error("custom_project_type", "Enter project type details when type is Other.")
        cleaned_data["billing_type"] = cleaned_data.get("billing_type") or Project.BillingType.ONE_TIME
        if cleaned_data.get("project_type") != Project.ProjectType.DIGITAL_MARKETING:
            cleaned_data["billing_type"] = Project.BillingType.ONE_TIME
        if cleaned_data.get("project_status") == Project.ProjectStatus.COMPLETED:
            cleaned_data["completion_percentage"] = 100
        start_date = cleaned_data.get("start_date")
        expected_date = cleaned_data.get("expected_completion_date")
        actual_date = cleaned_data.get("actual_completion_date")
        if start_date and expected_date and expected_date < start_date:
            self.add_error("expected_completion_date", "Expected completion date cannot be before start date.")
        if start_date and actual_date and actual_date < start_date:
            self.add_error("actual_completion_date", "Actual completion date cannot be before start date.")
        gst_type = cleaned_data.get("client_amount_gst_type")
        approved_quote = cleaned_data.get("approved_quote") or Decimal("0.00")
        gst_percentage = cleaned_data.get("project_gst_percentage") or Decimal("0.00")
        partial_taxable = cleaned_data.get("partial_gst_taxable_amount") or Decimal("0.00")
        if gst_percentage < Decimal("0.00") or gst_percentage > Decimal("100.00"):
            self.add_error("project_gst_percentage", "GST percentage must be between 0 and 100.")
        if partial_taxable < Decimal("0.00"):
            self.add_error("partial_gst_taxable_amount", "GST applicable amount cannot be negative.")
        if gst_type != Project.ClientAmountGstType.PARTIAL_GST:
            cleaned_data["partial_gst_taxable_amount"] = Decimal("0.00")
        elif partial_taxable > approved_quote:
            self.add_error("partial_gst_taxable_amount", "GST applicable amount cannot be greater than approved client amount.")
        if gst_type == Project.ClientAmountGstType.PARTIAL_GST and partial_taxable <= Decimal("0.00"):
            self.add_error("partial_gst_taxable_amount", "GST applicable amount is required for Partial GST.")
        return cleaned_data

    def clean_estimated_quote(self):
        return self.cleaned_data.get("estimated_quote") or Decimal("0.00")

    def clean_approved_quote(self):
        return self.cleaned_data.get("approved_quote") or Decimal("0.00")

    def clean_project_gst_percentage(self):
        return self.cleaned_data.get("project_gst_percentage") or Decimal("18.00")

    def clean_partial_gst_taxable_amount(self):
        return self.cleaned_data.get("partial_gst_taxable_amount") or Decimal("0.00")

    def clean_client_next_advance_amount(self):
        return self.cleaned_data.get("client_next_advance_amount") or Decimal("0.00")

    def clean_currency(self):
        return self.cleaned_data.get("currency") or CURRENCY_INR


class DeveloperVendorForm(SanitizedModelForm):
    gstin = forms.CharField(
        required=False,
        label="GSTIN",
        widget=forms.TextInput(attrs=GSTIN_WIDGET_ATTRS),
    )

    class Meta:
        model = DeveloperVendor
        fields = [
            "name",
            "vendor_type",
            "contact_person",
            "email",
            "phone_number",
            "address",
            "country",
            "state",
            "city",
            "pin_code",
            "gstin",
            "pan",
            "bank_details",
            "notes",
            "status",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "vendor_type": forms.Select(attrs={"class": "form-control"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "pin_code": forms.TextInput(attrs={"class": "form-control"}),
            "pan": forms.TextInput(attrs={"class": "form-control"}),
            "bank_details": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }

    def clean_phone_number(self):
        phone = sanitize_text(self.cleaned_data.get("phone_number", ""))
        if phone and not re.match(r"^[0-9+\-\s()]{7,20}$", phone):
            raise forms.ValidationError("Enter a valid phone number.")
        return phone

    def clean_gstin(self):
        gstin = normalize_gstin_value(sanitize_text(self.cleaned_data.get("gstin", "")))
        validate_gstin_value(gstin)
        return gstin

    def clean_pan(self):
        return sanitize_text(self.cleaned_data.get("pan", "")).upper()


class ProjectClientPaymentForm(SanitizedModelForm):
    allow_extra_payment = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Allow extra/adjustment payment above approved quote",
    )
    amount_received = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )

    class Meta:
        model = ProjectClientPayment
        fields = ["amount_received", "payment_date", "payment_mode", "payment_type", "remarks"]
        widgets = {
            "payment_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "payment_mode": forms.Select(attrs={"class": "form-control"}),
            "payment_type": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.project = kwargs.pop("project")
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount_received")
        if amount:
            quote = self.project.project_total_with_gst or self.project.approved_quote or self.project.estimated_quote or Decimal("0.00")
            original_amount = self.instance.amount_received if self.instance and self.instance.pk else Decimal("0.00")
            total_after_payment = self.project.client_total_amount_received - original_amount + amount
            if quote > 0 and total_after_payment > quote and not cleaned_data.get("allow_extra_payment"):
                self.add_error("allow_extra_payment", "Confirm extra payment because received amount exceeds the project quote.")
        return cleaned_data


class ProjectAssignmentForm(SanitizedModelForm):
    developer_cost_estimate = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Optional, default 0.00"}),
    )
    developer_final_project_cost = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Optional, default 0.00"}),
    )
    next_advance_amount_to_send = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Optional, default 0.00"}),
    )

    class Meta:
        model = ProjectAssignment
        fields = [
            "developer_vendor",
            "assigned_role",
            "work_description",
            "developer_cost_estimate",
            "developer_final_project_cost",
            "next_advance_amount_to_send",
            "next_advance_expected_date",
            "assignment_status",
            "remarks",
        ]
        widgets = {
            "developer_vendor": forms.Select(attrs={"class": "form-control"}),
            "assigned_role": forms.TextInput(attrs={"class": "form-control"}),
            "work_description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "next_advance_expected_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "assignment_status": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["developer_vendor"].queryset = DeveloperVendor.objects.filter(status=DeveloperVendor.VendorStatus.ACTIVE)

    def clean_developer_cost_estimate(self):
        return self.cleaned_data.get("developer_cost_estimate") or Decimal("0.00")

    def clean_developer_final_project_cost(self):
        return self.cleaned_data.get("developer_final_project_cost") or Decimal("0.00")

    def clean_next_advance_amount_to_send(self):
        return self.cleaned_data.get("next_advance_amount_to_send") or Decimal("0.00")


class DeveloperPaymentForm(SanitizedModelForm):
    allow_extra_payment = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Allow extra/adjustment payment above developer final cost",
    )
    amount_paid = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )

    class Meta:
        model = DeveloperPayment
        fields = ["amount_paid", "payment_date", "payment_mode", "payment_type", "remarks"]
        widgets = {
            "payment_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "payment_mode": forms.Select(attrs={"class": "form-control"}),
            "payment_type": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.assignment = kwargs.pop("assignment")
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount_paid")
        if amount:
            cost = self.assignment.developer_final_project_cost or self.assignment.developer_cost_estimate or Decimal("0.00")
            total_after_payment = self.assignment.total_amount_paid_to_developer + amount
            if cost > 0 and total_after_payment > cost and not cleaned_data.get("allow_extra_payment"):
                self.add_error("allow_extra_payment", "Confirm extra payment because paid amount exceeds developer cost.")
        return cleaned_data


class RecurringInvoiceTemplateForm(SanitizedModelForm):
    apply_gst = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Apply GST?",
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Active",
    )

    class Meta:
        model = RecurringInvoiceTemplate
        fields = ["company", "client", "project", "title", "frequency", "next_invoice_date", "apply_gst", "is_active"]
        widgets = {
            "company": forms.Select(attrs={"class": "form-control"}),
            "client": forms.Select(attrs={"class": "form-control"}),
            "project": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "frequency": forms.Select(attrs={"class": "form-control"}),
            "next_invoice_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.all()
        self.fields["client"].queryset = active_client_queryset()
        self.fields["project"].queryset = Project.objects.select_related("client").filter(client__is_deleted=False)
        self.fields["project"].required = False
        self.fields["project"].empty_label = "No project"

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        project = cleaned_data.get("project")
        if project and client and project.client_id != client.id:
            self.add_error("project", "Selected project must belong to the selected client.")
        return cleaned_data


class RecurringInvoiceTemplateItemForm(forms.ModelForm):
    hsn_sac_code = forms.ModelChoiceField(
        queryset=HsnSacCode.objects.all(),
        required=False,
        empty_label="No HSN/SAC",
        widget=forms.Select(attrs={"class": "form-control"}),
        label="HSN/SAC Code",
    )
    item_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
    )
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )

    class Meta:
        model = RecurringInvoiceTemplateItem
        fields = ["description", "hsn_sac_code", "item_price", "quantity"]
        widgets = {
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


RecurringInvoiceTemplateItemFormSet = inlineformset_factory(
    RecurringInvoiceTemplate,
    RecurringInvoiceTemplateItem,
    form=RecurringInvoiceTemplateItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class ProjectReportFilterForm(forms.Form):
    REPORT_TYPES = [
        ("project_wise", "Project-wise report"),
        ("client_wise_projects", "Client-wise project report"),
        ("developer_wise", "Developer/vendor-wise project report"),
        ("financial_summary", "Project financial summary report"),
        ("project_payment_received", "Project payment received report"),
        ("developer_payment", "Developer payment report"),
        ("project_invoice", "Invoice raised against project report"),
        ("profit", "Project profit report"),
        ("pending_receivables", "Pending receivables from clients"),
        ("pending_payables", "Pending payables to developers/vendors"),
    ]
    GST_CHOICES = [
        ("", "All"),
        ("gst", "GST Invoices"),
        ("non_gst", "Non-GST Invoices"),
    ]

    report_type = forms.ChoiceField(choices=REPORT_TYPES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    client = forms.ModelChoiceField(queryset=Client.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    project_type = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "form-control"}))
    project_status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "form-control"}))
    currency = forms.ChoiceField(choices=[("", "All currencies")] + CURRENCY_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))
    developer_vendor = forms.ModelChoiceField(queryset=DeveloperVendor.objects.none(), required=False, widget=forms.Select(attrs={"class": "form-control"}))
    min_completion = forms.IntegerField(required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "100"}))
    max_completion = forms.IntegerField(required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "100"}))
    payment_status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "form-control"}))
    gst_type = forms.ChoiceField(label="GST Type", choices=GST_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = active_client_queryset()
        self.fields["project"].queryset = Project.objects.select_related("client").all()
        self.fields["developer_vendor"].queryset = DeveloperVendor.objects.all()
        self.fields["project_type"].choices = [("", "All project types")] + list(Project.ProjectType.choices)
        self.fields["project_status"].choices = [("", "All project statuses")] + list(Project.ProjectStatus.choices)
        self.fields["payment_status"].choices = [("", "All invoice statuses")] + list(Invoice.PaymentStatus.choices)

    def clean(self):
        cleaned_data = super().clean()
        min_completion = cleaned_data.get("min_completion")
        max_completion = cleaned_data.get("max_completion")
        if min_completion is not None and max_completion is not None and min_completion > max_completion:
            self.add_error("max_completion", "Maximum completion must be greater than minimum completion.")
        return cleaned_data
