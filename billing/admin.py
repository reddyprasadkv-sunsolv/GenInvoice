from django.contrib import admin

from .models import (
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
)


class GSTINAdminLabelMixin:
    @admin.display(description="GSTIN", ordering="gstin")
    def gstin_value(self, obj):
        return obj.gstin or "-"

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "gstin":
            formfield.label = "GSTIN"
            formfield.widget.attrs.update(
                {
                    "placeholder": "Example: 36AADC07549J1ZZ",
                    "maxlength": "15",
                    "autocapitalize": "characters",
                    "spellcheck": "false",
                    "oninput": "this.value = this.value.toUpperCase();",
                }
            )
        return formfield


@admin.register(Company)
class CompanyAdmin(GSTINAdminLabelMixin, admin.ModelAdmin):
    list_display = ("company_name", "city", "state", "country", "gstin_value", "updated_at")
    search_fields = ("company_name", "city", "state", "country", "gstin")
    list_filter = ("country", "state")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Client)
class ClientAdmin(GSTINAdminLabelMixin, admin.ModelAdmin):
    list_display = ("client_name", "city", "state", "country", "gstin_value", "is_deleted", "updated_at")
    search_fields = ("client_name", "city", "state", "country", "gstin")
    list_filter = ("is_deleted", "country", "state")
    readonly_fields = ("created_at", "updated_at")


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    fields = ("serial_number", "description", "hsn_sac_code", "item_price", "quantity", "total")
    readonly_fields = ("total",)


@admin.register(HsnSacCode)
class HsnSacCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "description")
    search_fields = ("code", "description")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "invoice_date", "company", "client", "total_amount", "invoice_status", "payment_status", "apply_gst", "is_deleted")
    search_fields = ("invoice_number", "subject", "company__company_name", "client__client_name")
    list_filter = ("invoice_status", "is_deleted", "apply_gst", "payment_status", "invoice_date")
    readonly_fields = (
        "subtotal",
        "gst_percentage",
        "gst_amount",
        "total_amount",
        "amount_in_words",
        "pending_amount",
        "pdf_file",
        "created_at",
        "updated_at",
    )
    inlines = [InvoiceItemInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "received_amount", "payment_date", "payment_mode", "created_at")
    search_fields = ("invoice__invoice_number", "remarks")
    list_filter = ("payment_mode", "payment_date")
    readonly_fields = ("created_at",)


class ProjectClientPaymentInline(admin.TabularInline):
    model = ProjectClientPayment
    extra = 0
    readonly_fields = ("created_at",)


class ProjectAssignmentInline(admin.TabularInline):
    model = ProjectAssignment
    extra = 0
    readonly_fields = ("total_amount_paid_to_developer", "pending_amount_to_developer", "created_at", "updated_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("project_id", "project_name", "client", "project_type", "billing_type", "project_status", "completion_percentage", "approved_quote")
    search_fields = ("project_id", "project_name", "client__client_name")
    list_filter = ("project_type", "billing_type", "project_status", "priority")
    readonly_fields = ("project_id", "client_total_amount_received", "client_pending_amount", "created_at", "updated_at")
    inlines = [ProjectClientPaymentInline, ProjectAssignmentInline]


@admin.register(DeveloperVendor)
class DeveloperVendorAdmin(GSTINAdminLabelMixin, admin.ModelAdmin):
    list_display = ("name", "vendor_type", "contact_person", "email", "phone_number", "status")
    search_fields = ("name", "contact_person", "email", "phone_number", "gstin", "pan")
    list_filter = ("vendor_type", "status")
    readonly_fields = ("created_at", "updated_at")


class DeveloperPaymentInline(admin.TabularInline):
    model = DeveloperPayment
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(ProjectAssignment)
class ProjectAssignmentAdmin(admin.ModelAdmin):
    list_display = ("project", "developer_vendor", "assigned_role", "developer_final_project_cost", "total_amount_paid_to_developer", "pending_amount_to_developer", "assignment_status")
    search_fields = ("project__project_name", "developer_vendor__name", "assigned_role")
    list_filter = ("assignment_status",)
    readonly_fields = ("total_amount_paid_to_developer", "pending_amount_to_developer", "created_at", "updated_at")
    inlines = [DeveloperPaymentInline]


@admin.register(ProjectClientPayment)
class ProjectClientPaymentAdmin(admin.ModelAdmin):
    list_display = ("project", "amount_received", "payment_date", "payment_mode", "payment_type")
    search_fields = ("project__project_name", "remarks")
    list_filter = ("payment_mode", "payment_type", "payment_date")
    readonly_fields = ("created_at",)


@admin.register(DeveloperPayment)
class DeveloperPaymentAdmin(admin.ModelAdmin):
    list_display = ("project_assignment", "amount_paid", "payment_date", "payment_mode", "payment_type")
    search_fields = ("project_assignment__project__project_name", "project_assignment__developer_vendor__name", "remarks")
    list_filter = ("payment_mode", "payment_type", "payment_date")
    readonly_fields = ("created_at",)


@admin.register(ApplicationSetting)
class ApplicationSettingAdmin(admin.ModelAdmin):
    list_display = ("default_gst_percentage", "default_payment_terms", "updated_at")
    readonly_fields = ("updated_at",)
