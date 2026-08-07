from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()

CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
}


def _decimal_amount(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def _trimmed_decimal(amount):
    integer_part, decimal_part = f"{amount:.2f}".split(".")
    suffix = "" if decimal_part == "00" else f".{decimal_part}"
    return integer_part, suffix


def format_inr(value):
    amount = _decimal_amount(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    integer_part, suffix = _trimmed_decimal(amount)

    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        leading = integer_part[:-3]
        groups = []
        while len(leading) > 2:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        if leading:
            groups.insert(0, leading)
        integer_part = ",".join(groups + [last_three])

    return f"{sign}₹{integer_part}{suffix}"


def format_usd(value):
    amount = _decimal_amount(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    integer_part, suffix = _trimmed_decimal(amount)
    integer_part = f"{int(integer_part):,}"
    return f"{sign}${integer_part}{suffix}"


def format_currency(value, currency="INR"):
    if currency == "USD":
        return format_usd(value)
    return format_inr(value)


@register.filter(name="inr")
def inr(value):
    return format_inr(value)


@register.filter(name="currency_format")
def currency_format(value, currency="INR"):
    return format_currency(value, currency)


@register.filter(name="currency_symbol")
def currency_symbol(currency="INR"):
    return CURRENCY_SYMBOLS.get(currency, "₹")
