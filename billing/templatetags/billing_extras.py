from django import template

from billing.services import (
    completion_bar_class,
    invoice_status_badge_class,
    project_status_badge_class,
)


register = template.Library()


@register.filter
def project_status_class(value):
    return project_status_badge_class(value)


@register.filter
def completion_class(value):
    return completion_bar_class(value)


@register.filter
def invoice_status_class(value):
    return invoice_status_badge_class(value)


@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()
