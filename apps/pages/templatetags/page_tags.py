from django import template

register = template.Library()


@register.filter
def add_after_first(classes, extra):
    """'product type-product …' → 'product <extra> type-product …' (wc_product_class() with extra classes)."""
    first, _, rest = str(classes).partition(" ")
    return f"{first} {extra} {rest}".strip()
