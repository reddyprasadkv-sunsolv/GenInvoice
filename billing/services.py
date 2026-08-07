from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.db.models import Count, Max, Sum
from django.template.loader import render_to_string


GST_PERCENTAGE = Decimal("18.00")
ZERO_MONEY = Decimal("0.00")
PDF_INVOICE_DIR = "invoices"


ONES = {
    0: "",
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
    10: "Ten",
    11: "Eleven",
    12: "Twelve",
    13: "Thirteen",
    14: "Fourteen",
    15: "Fifteen",
    16: "Sixteen",
    17: "Seventeen",
    18: "Eighteen",
    19: "Nineteen",
}

TENS = {
    20: "Twenty",
    30: "Thirty",
    40: "Forty",
    50: "Fifty",
    60: "Sixty",
    70: "Seventy",
    80: "Eighty",
    90: "Ninety",
}


def to_money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def invoice_prefix(value):
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    return (cleaned[:3] or "XXX").ljust(3, "X")


def generate_invoice_number(company, client, invoice_date):
    from .models import Invoice

    base = f"{invoice_prefix(company.company_name)}{invoice_prefix(client.client_name)}-{invoice_date.strftime('%d%m%Y')}"
    latest = (
        Invoice.objects.filter(invoice_number__startswith=f"{base}-")
        .aggregate(max_number=Max("invoice_number"))
        .get("max_number")
    )
    sequence = 1
    if latest:
        try:
            sequence = int(latest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = Invoice.objects.filter(invoice_number__startswith=f"{base}-").count() + 1
    return f"{base}-{sequence:03d}"


def generate_draft_invoice_number(invoice_date):
    from .models import Invoice

    base = f"DRAFT-{invoice_date.strftime('%Y%m%d')}"
    latest = (
        Invoice.objects.filter(invoice_number__startswith=f"{base}-")
        .aggregate(max_number=Max("invoice_number"))
        .get("max_number")
    )
    sequence = 1
    if latest:
        try:
            sequence = int(latest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = Invoice.objects.filter(invoice_number__startswith=f"{base}-").count() + 1
    return f"{base}-{sequence:03d}"


def get_application_settings():
    from .models import ApplicationSetting

    try:
        return ApplicationSetting.load()
    except (OperationalError, ProgrammingError):
        return None


def get_default_gst_percentage():
    app_settings = get_application_settings()
    if not app_settings:
        return GST_PERCENTAGE
    return to_money(app_settings.default_gst_percentage)


def calculate_invoice_totals(item_rows, company, apply_gst=True, currency="INR"):
    subtotal = ZERO_MONEY
    calculated_items = []

    for index, row in enumerate(item_rows, start=1):
        price = to_money(row["item_price"])
        quantity = Decimal(row["quantity"])
        total = to_money(price * quantity)
        subtotal += total
        calculated_items.append(
            {
                "serial_number": index,
                "description": row["description"],
                "hsn_sac_code": row.get("hsn_sac_code"),
                "item_price": price,
                "quantity": quantity,
                "total": total,
            }
        )

    subtotal = to_money(subtotal)
    gst_percentage = get_default_gst_percentage() if company and company.gstin and apply_gst else ZERO_MONEY
    gst_amount = to_money(subtotal * gst_percentage / Decimal("100"))
    total_amount = to_money(subtotal + gst_amount)

    return {
        "items": calculated_items,
        "subtotal": subtotal,
        "gst_percentage": gst_percentage,
        "gst_amount": gst_amount,
        "total_amount": total_amount,
        "amount_in_words": amount_to_currency_words(total_amount, currency),
    }


def amount_to_currency_words(amount, currency="INR"):
    if currency == "USD":
        return amount_to_usd_words(amount)
    return amount_to_indian_words(amount)


def amount_to_indian_words(amount):
    amount = to_money(amount)
    rupees = int(amount)
    paise = int((amount - Decimal(rupees)) * 100)

    if rupees == 0:
        words = "Zero"
    else:
        words = _number_to_indian_words(rupees)

    result = f"Rupees {words}"
    if paise:
        result = f"{result} And Paise {_number_to_indian_words(paise)}"
    return f"{result} Only"


def amount_to_usd_words(amount):
    amount = to_money(amount)
    dollars = int(amount)
    cents = int((amount - Decimal(dollars)) * 100)

    words = "Zero" if dollars == 0 else _number_to_western_words(dollars)
    result = f"US Dollars {words}"
    if cents:
        result = f"{result} And {_number_to_western_words(cents)} Cents"
    return f"{result} Only"


def _number_to_western_words(number):
    if number < 1000:
        return _number_to_indian_words(number)
    groups = [
        (1000000000, "Billion"),
        (1000000, "Million"),
        (1000, "Thousand"),
        (1, ""),
    ]
    parts = []
    remaining = number
    for value, label in groups:
        group_number = remaining // value
        if group_number:
            part = _number_to_indian_words(group_number)
            parts.append(f"{part} {label}".strip())
            remaining %= value
    return " ".join(parts)


def _number_to_indian_words(number):
    if number < 20:
        return ONES[number]
    if number < 100:
        tens_value = number // 10 * 10
        remainder = number % 10
        return " ".join(part for part in [TENS[tens_value], ONES[remainder]] if part)
    if number < 1000:
        remainder = number % 100
        return " ".join(
            part for part in [ONES[number // 100], "Hundred", _number_to_indian_words(remainder) if remainder else ""] if part
        )

    groups = [
        (10000000, "Crore"),
        (100000, "Lakh"),
        (1000, "Thousand"),
        (1, ""),
    ]
    parts = []
    remaining = number
    for value, label in groups:
        group_number = remaining // value
        remaining %= value
        if group_number:
            words = _number_to_indian_words(group_number)
            parts.append(f"{words} {label}".strip())
    return " ".join(parts)


class PDFGenerationError(Exception):
    pass


def safe_invoice_pdf_filename(invoice_number):
    safe_number = re.sub(r"[^A-Za-z0-9._-]", "_", invoice_number or "invoice").strip("._-")
    if not safe_number:
        safe_number = "invoice"
    return f"Invoice-{safe_number}.pdf"


def invoice_pdf_relative_path(invoice_number):
    return f"{PDF_INVOICE_DIR}/{safe_invoice_pdf_filename(invoice_number)}"


def invoice_title(invoice):
    return "TAX INVOICE" if invoice.apply_gst and invoice.gst_amount > 0 else "INVOICE"


def generate_invoice_pdf(invoice, request=None):
    try:
        from weasyprint import HTML
    except Exception as exc:
        raise PDFGenerationError("WeasyPrint is not installed.") from exc

    invoice = _invoice_with_related(invoice)
    output_path = _invoice_pdf_output_path(invoice.invoice_number)
    context = {
        "invoice": invoice,
        "invoice_title": invoice_title(invoice),
        "company_logo_uri": _company_logo_uri(invoice),
        "company_signature_uri": _company_signature_uri(invoice),
    }
    html = render_to_string("invoices/invoice_pdf.html", context)
    base_url = request.build_absolute_uri("/") if request else settings.BASE_DIR.as_uri()

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=html, base_url=base_url).write_pdf(str(output_path))
    except Exception as exc:
        raise PDFGenerationError("Unable to generate invoice PDF.") from exc

    relative_path = invoice_pdf_relative_path(invoice.invoice_number)
    if invoice.pdf_file.name != relative_path:
        invoice.pdf_file.name = relative_path
        invoice.save(update_fields=["pdf_file", "updated_at"])
    return output_path


def _invoice_with_related(invoice):
    from .models import Invoice

    return (
        Invoice.objects.select_related("company", "client")
        .select_related("project")
        .prefetch_related("items__hsn_sac_code")
        .get(pk=invoice.pk)
    )


def _invoice_pdf_output_path(invoice_number):
    invoices_dir = (Path(settings.MEDIA_ROOT) / PDF_INVOICE_DIR).resolve()
    output_path = (invoices_dir / safe_invoice_pdf_filename(invoice_number)).resolve()
    if invoices_dir not in output_path.parents:
        raise PDFGenerationError("Unsafe invoice PDF path.")
    return output_path


def _company_logo_uri(invoice):
    return _file_uri(invoice.company.logo)


def _company_signature_uri(invoice):
    return _file_uri(invoice.company.authorized_signature)


def _file_uri(file_field):
    if not file_field:
        return ""
    try:
        file_path = Path(file_field.path)
    except (NotImplementedError, ValueError):
        return ""
    if not file_path.exists() or not file_path.is_file():
        return ""
    return file_path.resolve().as_uri()


def recalculate_invoice_payments(invoice):
    if invoice.invoice_status == invoice.InvoiceStatus.DRAFT or invoice.is_deleted:
        invoice.received_amount = ZERO_MONEY
        invoice.pending_amount = invoice.total_amount
        invoice.payment_status = invoice.PaymentStatus.PENDING
        invoice.save(update_fields=["received_amount", "pending_amount", "payment_status", "updated_at"])
        return invoice

    total_received = invoice.payments.aggregate(total=Sum("received_amount")).get("total") or ZERO_MONEY
    total_received = to_money(total_received)
    pending_amount = to_money(invoice.total_amount - total_received)
    if pending_amount < ZERO_MONEY:
        pending_amount = ZERO_MONEY

    invoice.received_amount = total_received
    invoice.pending_amount = pending_amount
    if total_received <= ZERO_MONEY:
        invoice.payment_status = invoice.PaymentStatus.PENDING
    elif total_received >= invoice.total_amount:
        invoice.payment_status = invoice.PaymentStatus.PAID
    else:
        invoice.payment_status = invoice.PaymentStatus.PARTIALLY_PAID
    invoice.save(update_fields=["received_amount", "pending_amount", "payment_status", "updated_at"])
    return invoice


def report_file_path(filename):
    reports_dir = (Path(settings.MEDIA_ROOT) / "reports").resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "report").strip("._-") or "report"
    output_path = (reports_dir / safe_name).resolve()
    if reports_dir not in output_path.parents:
        raise PDFGenerationError("Unsafe report path.")
    return output_path


def project_revenue_base(project):
    return to_money(project.project_base_amount or project.approved_quote or project.estimated_quote or ZERO_MONEY)


def project_client_total(project):
    return to_money(project.project_total_with_gst or project.approved_quote or project.estimated_quote or ZERO_MONEY)


def assignment_cost_base(assignment):
    return to_money(assignment.developer_final_project_cost or assignment.developer_cost_estimate or ZERO_MONEY)


def recalculate_project_client_payments(project):
    total_received = project.client_payments.aggregate(total=Sum("amount_received")).get("total") or ZERO_MONEY
    total_received = to_money(total_received)
    pending_amount = to_money(project_client_total(project) - total_received)
    if pending_amount < ZERO_MONEY:
        pending_amount = ZERO_MONEY
    project.client_total_amount_received = total_received
    project.client_pending_amount = pending_amount
    project.save(update_fields=["client_total_amount_received", "client_pending_amount", "updated_at"])
    return project


def recalculate_assignment_payments(assignment):
    total_paid = assignment.developer_payments.aggregate(total=Sum("amount_paid")).get("total") or ZERO_MONEY
    total_paid = to_money(total_paid)
    pending_amount = to_money(assignment_cost_base(assignment) - total_paid)
    assignment.total_amount_paid_to_developer = total_paid
    assignment.pending_amount_to_developer = pending_amount
    assignment.save(update_fields=["total_amount_paid_to_developer", "pending_amount_to_developer", "updated_at"])
    return assignment


def project_financial_summary(project):
    assignments = project.assignments.select_related("developer_vendor").all()
    developer_cost_estimate = ZERO_MONEY
    developer_final_cost = ZERO_MONEY
    developer_paid = ZERO_MONEY
    developer_pending = ZERO_MONEY
    developer_names = []
    for assignment in assignments:
        developer_cost_estimate += assignment.developer_cost_estimate or ZERO_MONEY
        developer_final_cost += assignment.developer_final_project_cost or ZERO_MONEY
        developer_paid += assignment.total_amount_paid_to_developer or ZERO_MONEY
        developer_pending += assignment.pending_amount_to_developer or ZERO_MONEY
        developer_names.append(assignment.developer_vendor.name)

    invoice_queryset = project.invoices.filter(invoice_status="Final", is_deleted=False)
    invoice_totals = invoice_queryset.aggregate(
        raised=Sum("total_amount"),
        received=Sum("received_amount"),
        pending=Sum("pending_amount"),
        count=Count("id"),
    )
    estimated_quote = to_money(project.estimated_quote or ZERO_MONEY)
    approved_quote = project_revenue_base(project)
    client_received = to_money(project.client_total_amount_received or ZERO_MONEY)
    client_pending = to_money(project.client_pending_amount or ZERO_MONEY)
    developer_cost_estimate = to_money(developer_cost_estimate)
    developer_final_cost = to_money(developer_final_cost)
    developer_paid = to_money(developer_paid)
    developer_pending = to_money(developer_pending)
    estimated_profit = to_money(estimated_quote - developer_cost_estimate)
    approved_profit = to_money(approved_quote - developer_final_cost)
    actual_cash_profit = to_money(client_received - developer_paid)

    return {
        "developer_names": ", ".join(developer_names) if developer_names else "-",
        "base_amount": approved_quote,
        "gst_type": getattr(project, "client_amount_gst_type", "WITHOUT_GST"),
        "gst_type_label": project.get_client_amount_gst_type_display() if hasattr(project, "get_client_amount_gst_type_display") else "Without GST / GST Not Applicable",
        "gst_percentage": to_money(project.project_gst_percentage or ZERO_MONEY),
        "partial_gst_taxable_amount": to_money(project.partial_gst_taxable_amount or ZERO_MONEY),
        "gst_amount": to_money(project.project_gst_amount or ZERO_MONEY),
        "total_with_gst": project_client_total(project),
        "developer_cost_estimate": developer_cost_estimate,
        "developer_final_cost": developer_final_cost,
        "developer_paid": developer_paid,
        "developer_pending": developer_pending,
        "invoice_raised": invoice_totals["raised"] or ZERO_MONEY,
        "invoice_received": invoice_totals["received"] or ZERO_MONEY,
        "invoice_pending": invoice_totals["pending"] or ZERO_MONEY,
        "invoice_count": invoice_totals["count"] or 0,
        "estimated_profit": estimated_profit,
        "approved_profit": approved_profit,
        "actual_cash_profit": actual_cash_profit,
        "client_received": client_received,
        "client_pending": client_pending,
    }


def project_gst_display_summary(project):
    client_received = to_money(project.client_total_amount_received or ZERO_MONEY)
    base_amount = project_revenue_base(project)
    gst_amount = to_money(project.project_gst_amount or ZERO_MONEY)
    total_with_gst = project_client_total(project)
    client_pending = to_money(total_with_gst - client_received)
    if client_pending < ZERO_MONEY:
        client_pending = ZERO_MONEY

    return {
        "base_amount": base_amount,
        "gst_type": getattr(project, "client_amount_gst_type", "WITHOUT_GST"),
        "gst_type_label": project.get_client_amount_gst_type_display() if hasattr(project, "get_client_amount_gst_type_display") else "Without GST / GST Not Applicable",
        "gst_percentage": to_money(project.project_gst_percentage or ZERO_MONEY),
        "partial_gst_taxable_amount": to_money(project.partial_gst_taxable_amount or ZERO_MONEY),
        "gst_amount": gst_amount,
        "total_with_gst": total_with_gst,
        "client_pending": client_pending,
        "gst_applicable": gst_amount > ZERO_MONEY,
    }


def project_report_rows(projects):
    rows = []
    for project in projects:
        summary = project_financial_summary(project)
        rows.append(
            {
                "project": project,
                "summary": summary,
                "client_fund_status": client_fund_status(
                    project.client_total_amount_received,
                    project.client_pending_amount,
                    project_client_total(project),
                ),
                "developer_fund_status": developer_fund_status(
                    summary["developer_paid"],
                    summary["developer_pending"],
                    summary["developer_final_cost"],
                ),
            }
        )
    return rows


def project_status_badge_class(status):
    return {
        "Draft": "badge-neutral",
        "Enquiry": "badge-neutral",
        "Quotation Sent": "badge-info",
        "Approved": "badge-success",
        "In Progress": "badge-primary",
        "On Hold": "badge-warning",
        "Completed": "badge-success-strong",
        "Cancelled": "badge-danger",
    }.get(status, "badge-neutral")


def completion_bar_class(value):
    try:
        percentage = int(value)
    except (TypeError, ValueError):
        percentage = 0
    if percentage >= 100:
        return "progress-success"
    if percentage >= 76:
        return "progress-primary"
    if percentage >= 51:
        return "progress-info"
    if percentage >= 26:
        return "progress-warning"
    return "progress-danger"


def client_fund_status(received, pending, approved_quote):
    received = to_money(received or ZERO_MONEY)
    pending = to_money(pending or ZERO_MONEY)
    approved_quote = to_money(approved_quote or ZERO_MONEY)
    if approved_quote > ZERO_MONEY and received > approved_quote:
        return {"label": "Extra Received", "class": "badge-info"}
    if pending <= ZERO_MONEY and received > ZERO_MONEY:
        return {"label": "Fully Received", "class": "badge-success"}
    if received > ZERO_MONEY and pending > ZERO_MONEY:
        return {"label": "Partially Received", "class": "badge-warning"}
    return {"label": "Not Received", "class": "badge-danger"}


def developer_fund_status(paid, pending, final_cost):
    paid = to_money(paid or ZERO_MONEY)
    pending = to_money(pending or ZERO_MONEY)
    final_cost = to_money(final_cost or ZERO_MONEY)
    if final_cost > ZERO_MONEY and paid > final_cost:
        return {"label": "Extra Paid", "class": "badge-info"}
    if pending <= ZERO_MONEY and paid > ZERO_MONEY:
        return {"label": "Fully Paid", "class": "badge-success"}
    if paid > ZERO_MONEY and pending > ZERO_MONEY:
        return {"label": "Partially Paid", "class": "badge-warning"}
    return {"label": "Not Paid", "class": "badge-danger"}


def invoice_status_badge_class(status):
    return {
        "Draft": "badge-neutral",
        "Final": "badge-success",
        "Deleted": "badge-danger",
        "Pending": "badge-danger",
        "Partially Paid": "badge-warning",
        "Paid": "badge-success",
        "Cancelled": "badge-neutral",
    }.get(status, "badge-neutral")
