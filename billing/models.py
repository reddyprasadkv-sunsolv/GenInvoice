from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .validators import normalize_gstin_value, normalize_ifsc_value, validate_gstin_value, validate_ifsc_value, validate_logo_file, validate_signature_file


DEFAULT_TERMS_AND_CONDITIONS = (
    "1. Payment should be made within the agreed timeline.\n"
    "2. Any delay in payment may attract additional charges.\n"
    "3. Taxes are applicable as per government regulations."
)

DEFAULT_DECLARATION = (
    "We hereby declare that the details mentioned in this invoice are true and correct "
    "to the best of our knowledge."
)

PAYMENT_MODE_CHOICES = [
    ("Cash", "Cash"),
    ("Bank Transfer", "Bank Transfer"),
    ("UPI", "UPI"),
    ("Cheque", "Cheque"),
    ("Card", "Card"),
    ("Other", "Other"),
]

CURRENCY_INR = "INR"
CURRENCY_USD = "USD"
CURRENCY_CHOICES = [
    (CURRENCY_INR, "INR - Indian Rupee"),
    (CURRENCY_USD, "USD - US Dollar"),
]

MONEY_PLACES = Decimal("0.01")


def _money(value):
    return Decimal(value or "0.00").quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _clean_gstin_field(instance):
    instance.gstin = normalize_gstin_value(instance.gstin)
    try:
        validate_gstin_value(instance.gstin)
    except ValidationError as exc:
        raise ValidationError({"gstin": exc.messages}) from exc


def _clean_ifsc_field(instance):
    instance.ifsc_code = normalize_ifsc_value(instance.ifsc_code)
    try:
        validate_ifsc_value(instance.ifsc_code)
    except ValidationError as exc:
        raise ValidationError({"ifsc_code": exc.messages}) from exc


class Company(models.Model):
    company_name = models.CharField(max_length=150)
    address = models.TextField()
    country = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    pin_code = models.CharField(max_length=12)
    gstin = models.CharField(max_length=15, blank=True)
    bank_name = models.CharField(max_length=150, blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    bank_branch = models.CharField(max_length=150, blank=True, null=True)
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    account_name = models.CharField(max_length=200, blank=True, null=True)
    logo = models.FileField(
        upload_to="company_logos/",
        blank=True,
        validators=[validate_logo_file],
    )
    authorized_signature = models.FileField(
        upload_to="company_signatures/",
        blank=True,
        validators=[validate_signature_file],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company_name"]

    def clean(self):
        _clean_gstin_field(self)
        _clean_ifsc_field(self)

    def save(self, *args, **kwargs):
        self.gstin = normalize_gstin_value(self.gstin)
        self.ifsc_code = normalize_ifsc_value(self.ifsc_code)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.company_name

    @property
    def has_bank_details(self):
        return any([self.account_name, self.bank_name, self.bank_account_number, self.bank_branch, self.ifsc_code])

    @property
    def bank_account_display_name(self):
        return self.account_name or self.company_name


class Client(models.Model):
    class ClientStatus(models.TextChoices):
        DRAFT = "Draft", "Draft"
        ACTIVE = "Active", "Active"
        DELETED = "Deleted", "Deleted"

    client_name = models.CharField(max_length=150)
    address = models.TextField()
    country = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    pin_code = models.CharField(max_length=12)
    gstin = models.CharField(max_length=15, blank=True)
    requires_gst_invoice = models.BooleanField(default=True)
    client_status = models.CharField(
        max_length=20,
        choices=ClientStatus.choices,
        default=ClientStatus.ACTIVE,
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_clients",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["client_name"]

    def clean(self):
        _clean_gstin_field(self)

    def save(self, *args, **kwargs):
        self.gstin = normalize_gstin_value(self.gstin)
        if self.is_deleted:
            self.client_status = self.ClientStatus.DELETED
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"client_status"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.client_name


class Project(models.Model):
    class ProjectType(models.TextChoices):
        IT_CONSULTING = "IT Consulting", "IT Consulting"
        WEBSITE_DEVELOPMENT = "Website Development", "Website Development"
        MOBILE_APP_DEVELOPMENT = "Mobile App Development", "Mobile App Development"
        WEB_APPLICATION = "Web Application", "Web Application"
        DIGITAL_MARKETING = "Digital Marketing", "Digital Marketing"
        SEO = "SEO", "SEO"
        BRANDING = "Branding", "Branding"
        SOFTWARE_DEVELOPMENT = "Software Development", "Software Development"
        MAINTENANCE = "Maintenance", "Maintenance"
        OTHER = "Other", "Other"

    class ProjectStatus(models.TextChoices):
        DRAFT = "Draft", "Draft"
        ENQUIRY = "Enquiry", "Enquiry"
        QUOTATION_SENT = "Quotation Sent", "Quotation Sent"
        APPROVED = "Approved", "Approved"
        IN_PROGRESS = "In Progress", "In Progress"
        ON_HOLD = "On Hold", "On Hold"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"
        URGENT = "Urgent", "Urgent"

    class BillingType(models.TextChoices):
        ONE_TIME = "One Time", "One Time"
        RECURRING = "Recurring", "Recurring"

    class ClientAmountGstType(models.TextChoices):
        WITHOUT_GST = "WITHOUT_GST", "Without GST / GST Not Applicable"
        GST_EXTRA = "GST_EXTRA", "GST Extra / Amount Before GST"
        GST_INCLUDED = "GST_INCLUDED", "GST Included in Approved Amount"
        PARTIAL_GST = "PARTIAL_GST", "Partial GST"

    project_id = models.CharField(max_length=40, unique=True, blank=True)
    project_name = models.CharField(max_length=180)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="projects")
    project_requirement = models.TextField()
    project_type = models.CharField(max_length=40, choices=ProjectType.choices)
    billing_type = models.CharField(max_length=20, choices=BillingType.choices, default=BillingType.ONE_TIME)
    custom_project_type = models.CharField(max_length=120, blank=True)
    project_description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    expected_completion_date = models.DateField(null=True, blank=True)
    actual_completion_date = models.DateField(null=True, blank=True)
    project_status = models.CharField(
        max_length=30,
        choices=ProjectStatus.choices,
        default=ProjectStatus.ENQUIRY,
    )
    completion_percentage = models.PositiveSmallIntegerField(default=0)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    estimated_quote = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    approved_quote = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default=CURRENCY_INR)
    client_amount_gst_type = models.CharField(
        "Approved Client Amount GST Type",
        max_length=30,
        choices=ClientAmountGstType.choices,
        default=ClientAmountGstType.WITHOUT_GST,
    )
    project_gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"), blank=True)
    partial_gst_taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    project_base_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    project_gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    project_total_with_gst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    client_advance_amount_received = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    client_advance_received_date = models.DateField(null=True, blank=True)
    client_next_advance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    client_next_advance_expected_date = models.DateField(null=True, blank=True)
    client_total_amount_received = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    client_pending_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    client_payment_remarks = models.TextField(blank=True)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "project_name"]

    def clean(self):
        errors = {}
        approved_quote = _money(self.approved_quote)
        gst_percentage = _money(self.project_gst_percentage or Decimal("0.00"))
        partial_taxable = _money(self.partial_gst_taxable_amount)
        if gst_percentage < Decimal("0.00") or gst_percentage > Decimal("100.00"):
            errors["project_gst_percentage"] = "GST percentage must be between 0 and 100."
        if partial_taxable < Decimal("0.00"):
            errors["partial_gst_taxable_amount"] = "GST applicable amount cannot be negative."
        if self.client_amount_gst_type == self.ClientAmountGstType.PARTIAL_GST and partial_taxable > approved_quote:
            errors["partial_gst_taxable_amount"] = "GST applicable amount cannot be greater than approved client amount."
        if (
            self.client_amount_gst_type == self.ClientAmountGstType.PARTIAL_GST
            and self.project_status != self.ProjectStatus.DRAFT
            and partial_taxable <= Decimal("0.00")
        ):
            errors["partial_gst_taxable_amount"] = "GST applicable amount is required for Partial GST."
        if errors:
            raise ValidationError(errors)

    def calculate_project_gst_fields(self):
        approved_quote = _money(self.approved_quote)
        gst_percentage = _money(self.project_gst_percentage or Decimal("0.00"))
        partial_taxable = _money(self.partial_gst_taxable_amount)
        gst_type = self.client_amount_gst_type or self.ClientAmountGstType.WITHOUT_GST
        if gst_type != self.ClientAmountGstType.PARTIAL_GST:
            partial_taxable = Decimal("0.00")
            self.partial_gst_taxable_amount = partial_taxable

        if gst_type == self.ClientAmountGstType.GST_EXTRA:
            base_amount = approved_quote
            gst_amount = _money(base_amount * gst_percentage / Decimal("100"))
            total_with_gst = _money(base_amount + gst_amount)
        elif gst_type == self.ClientAmountGstType.GST_INCLUDED:
            total_with_gst = approved_quote
            if gst_percentage > Decimal("0.00"):
                divisor = Decimal("1.00") + (gst_percentage / Decimal("100"))
                base_amount = _money(total_with_gst / divisor)
            else:
                base_amount = total_with_gst
            gst_amount = _money(total_with_gst - base_amount)
        elif gst_type == self.ClientAmountGstType.PARTIAL_GST:
            base_amount = approved_quote
            gst_amount = _money(partial_taxable * gst_percentage / Decimal("100"))
            total_with_gst = _money(base_amount + gst_amount)
        else:
            base_amount = approved_quote
            gst_amount = Decimal("0.00")
            total_with_gst = approved_quote

        client_received = _money(self.client_total_amount_received)
        client_pending = _money(total_with_gst - client_received)
        if client_pending < Decimal("0.00"):
            client_pending = Decimal("0.00")
        self.project_base_amount = base_amount
        self.project_gst_amount = gst_amount
        self.project_total_with_gst = total_with_gst
        self.client_pending_amount = client_pending

    def save(self, *args, **kwargs):
        if self.project_gst_percentage is None:
            self.project_gst_percentage = Decimal("18.00")
        for field_name in [
            "estimated_quote",
            "approved_quote",
            "partial_gst_taxable_amount",
            "project_base_amount",
            "project_gst_amount",
            "project_total_with_gst",
            "client_advance_amount_received",
            "client_next_advance_amount",
            "client_total_amount_received",
            "client_pending_amount",
        ]:
            if getattr(self, field_name) is None:
                setattr(self, field_name, Decimal("0.00"))
        if self.project_status == self.ProjectStatus.COMPLETED:
            self.completion_percentage = 100
        if not self.project_id:
            self.project_id = self._next_project_id()
        self.calculate_project_gst_fields()
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                "project_gst_percentage",
                "partial_gst_taxable_amount",
                "project_base_amount",
                "project_gst_amount",
                "project_total_with_gst",
                "client_pending_amount",
            }
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project_name} ({self.client.client_name})"

    @classmethod
    def _next_project_id(cls):
        from django.utils import timezone

        today = timezone.localdate()
        prefix = f"PRJ-{today.strftime('%Y%m%d')}"
        latest = cls.objects.filter(project_id__startswith=f"{prefix}-").order_by("-project_id").first()
        sequence = 1
        if latest:
            try:
                sequence = int(latest.project_id.rsplit("-", 1)[1]) + 1
            except (IndexError, ValueError):
                sequence = cls.objects.filter(project_id__startswith=f"{prefix}-").count() + 1
        return f"{prefix}-{sequence:03d}"


class Invoice(models.Model):
    class PaymentStatus(models.TextChoices):
        PENDING = "Pending", "Pending"
        PARTIALLY_PAID = "Partially Paid", "Partially Paid"
        PAID = "Paid", "Paid"

    class InvoiceStatus(models.TextChoices):
        DRAFT = "Draft", "Draft"
        FINAL = "Final", "Final"
        CANCELLED = "Cancelled", "Cancelled"
        DELETED = "Deleted", "Deleted"

    invoice_number = models.CharField(max_length=40, unique=True)
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="invoices")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoices")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    invoice_date = models.DateField()
    subject = models.CharField(max_length=200, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default=CURRENCY_INR)
    apply_gst = models.BooleanField(default=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_in_words = models.CharField(max_length=500, blank=True)
    terms_and_conditions = models.TextField(default=DEFAULT_TERMS_AND_CONDITIONS)
    declaration = models.TextField(default=DEFAULT_DECLARATION)
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    invoice_status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.FINAL,
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_invoices",
    )
    received_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pdf_file = models.FileField(upload_to="invoices/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-invoice_date", "-created_at"]

    def __str__(self):
        return self.invoice_number


class DeveloperVendor(models.Model):
    class VendorType(models.TextChoices):
        INDIVIDUAL_DEVELOPER = "Individual Developer", "Individual Developer"
        FREELANCER = "Freelancer", "Freelancer"
        COMPANY = "Company", "Company"
        AGENCY = "Agency", "Agency"
        CONSULTANT = "Consultant", "Consultant"
        OTHER = "Other", "Other"

    class VendorStatus(models.TextChoices):
        ACTIVE = "Active", "Active"
        INACTIVE = "Inactive", "Inactive"

    name = models.CharField("Name / Company Name", max_length=180)
    vendor_type = models.CharField(max_length=40, choices=VendorType.choices)
    contact_person = models.CharField(max_length=140, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    country = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    pin_code = models.CharField(max_length=12, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    pan = models.CharField(max_length=20, blank=True)
    bank_details = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=VendorStatus.choices, default=VendorStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        _clean_gstin_field(self)

    def save(self, *args, **kwargs):
        self.gstin = normalize_gstin_value(self.gstin)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProjectAssignment(models.Model):
    class AssignmentStatus(models.TextChoices):
        ASSIGNED = "Assigned", "Assigned"
        IN_PROGRESS = "In Progress", "In Progress"
        COMPLETED = "Completed", "Completed"
        ON_HOLD = "On Hold", "On Hold"
        CANCELLED = "Cancelled", "Cancelled"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="assignments")
    developer_vendor = models.ForeignKey(DeveloperVendor, on_delete=models.PROTECT, related_name="assignments")
    assigned_role = models.CharField(max_length=140)
    work_description = models.TextField(blank=True)
    developer_cost_estimate = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    developer_final_project_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    advance_amount_sent = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    advance_sent_date = models.DateField(null=True, blank=True)
    next_advance_amount_to_send = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    next_advance_expected_date = models.DateField(null=True, blank=True)
    total_amount_paid_to_developer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    pending_amount_to_developer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    assignment_status = models.CharField(
        max_length=30,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED,
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project", "developer_vendor"]

    def __str__(self):
        return f"{self.project.project_name} - {self.developer_vendor.name}"


class ProjectClientPayment(models.Model):
    class PaymentType(models.TextChoices):
        ADVANCE = "Advance", "Advance"
        MILESTONE = "Milestone Payment", "Milestone Payment"
        FINAL = "Final Payment", "Final Payment"
        OTHER = "Other", "Other"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="client_payments")
    amount_received = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    payment_type = models.CharField(max_length=30, choices=PaymentType.choices)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    def __str__(self):
        return f"{self.project.project_name} - {self.amount_received}"


class DeveloperPayment(models.Model):
    class PaymentType(models.TextChoices):
        ADVANCE = "Advance", "Advance"
        MILESTONE = "Milestone Payment", "Milestone Payment"
        FINAL = "Final Payment", "Final Payment"
        OTHER = "Other", "Other"

    project_assignment = models.ForeignKey(ProjectAssignment, on_delete=models.CASCADE, related_name="developer_payments")
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    payment_type = models.CharField(max_length=30, choices=PaymentType.choices)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    def __str__(self):
        return f"{self.project_assignment} - {self.amount_paid}"


class HsnSacCode(models.Model):
    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "HSN/SAC code"
        verbose_name_plural = "HSN/SAC codes"

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    serial_number = models.PositiveIntegerField()
    description = models.TextField()
    hsn_sac_code = models.ForeignKey(HsnSacCode, on_delete=models.SET_NULL, blank=True, null=True)
    item_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["serial_number", "id"]

    def __str__(self):
        return f"{self.invoice.invoice_number} - Item {self.serial_number}"


class Payment(models.Model):
    class PaymentMode(models.TextChoices):
        CASH = "Cash", "Cash"
        BANK_TRANSFER = "Bank Transfer", "Bank Transfer"
        UPI = "UPI", "UPI"
        CHEQUE = "Cheque", "Cheque"
        CARD = "Card", "Card"
        OTHER = "Other", "Other"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    received_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.received_amount}"


class ActivityLog(models.Model):
    action = models.CharField(max_length=100)
    module = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.module}: {self.action}"


class RecurringInvoiceTemplate(models.Model):
    class Frequency(models.TextChoices):
        MONTHLY = "Monthly", "Monthly"
        QUARTERLY = "Quarterly", "Quarterly"
        YEARLY = "Yearly", "Yearly"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="recurring_invoice_templates")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="recurring_invoice_templates")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="recurring_invoice_templates")
    title = models.CharField(max_length=200)
    frequency = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.MONTHLY)
    next_invoice_date = models.DateField()
    apply_gst = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_invoice_date", "title"]

    def __str__(self):
        return self.title


class RecurringInvoiceTemplateItem(models.Model):
    template = models.ForeignKey(RecurringInvoiceTemplate, related_name="items", on_delete=models.CASCADE)
    description = models.TextField()
    hsn_sac_code = models.ForeignKey(HsnSacCode, on_delete=models.SET_NULL, null=True, blank=True)
    item_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.template.title} item"


class ApplicationSetting(models.Model):
    default_gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))
    default_terms_and_conditions = models.TextField(default=DEFAULT_TERMS_AND_CONDITIONS)
    default_declaration = models.TextField(default=DEFAULT_DECLARATION)
    default_payment_terms = models.CharField(max_length=160, default="Payment should be made within the agreed timeline.")
    backup_reminder_dismissed_on = models.DateField(null=True, blank=True)
    invoice_number_format = models.CharField(
        max_length=140,
        default="{company3}{client3}-{date_ddmmyyyy}-{sequence:03d}",
    )
    date_separator = models.CharField(max_length=3, blank=True, default="")
    prefix_separator = models.CharField(max_length=3, blank=True, default="-")
    running_sequence_length = models.PositiveSmallIntegerField(default=3)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Application setting"
        verbose_name_plural = "Application settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Application settings"

    @classmethod
    def load(cls):
        settings_obj, _created = cls.objects.get_or_create(pk=1)
        return settings_obj
