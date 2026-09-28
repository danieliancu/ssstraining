"""WooCommerce product markup used by the catalog templates ({% load catalog_tags %})."""
import re
from decimal import Decimal

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.catalog import services
from apps.core.templatetags.wp import _money, price_html

register = template.Library()


def _amount(value):
    return (f'<span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol" '
            f'translate="no">&pound;</span>{_money(value)}</bdi></span>')


def _incl(product, value):
    if value is None:
        return None
    value = Decimal(value)
    return (value * Decimal("1.2")).quantize(Decimal("0.01")) if product.taxable else value


@register.filter
def wc_price_html(product):
    """get_price_html() as WooCommerce prints it on product pages and loops: the shop displays
    prices including VAT (woocommerce_tax_display_shop = incl), then the theme adds '+ VAT'."""
    if product is None or product.price is None:
        return ""
    if product.on_sale:
        reg, cur = _incl(product, product.regular_price), _incl(product, product.price)
        html = (f'<del aria-hidden="true">{_amount(reg)}</del> '
                f'<span class="screen-reader-text">Original price was: &pound;{_money(reg)}.</span>'
                f'<ins aria-hidden="true">{_amount(cur)}</ins>'
                f'<span class="screen-reader-text">Current price is: &pound;{_money(cur)}.</span>')
    else:
        html = _amount(_incl(product, product.price))
    if product.is_nvq:
        html = f'<span class="nvq-price-prefix">PAY 50% UPFRONT</span> {html}'
    if "VAT" not in html:
        html += ' <span class="price-vat-note">+ VAT</span>'
    return mark_safe(html)


@register.filter
def shop_card_price(product):
    """Shop card price (inc/custom-shop.php:806 through wp_kses_post, which drops <bdi>).
    Deliberate change: ex-VAT amount via the shared price_html filter."""
    html = str(price_html(product))
    html = html.replace("<bdi>", "").replace("</bdi>", "").replace(' translate="no"', "")
    return mark_safe(html)


@register.filter
def wc_raw_price(value):
    """WC_Product::get_price() string as stored in _price (wc_format_decimal trims zeros)."""
    if value is None or value == "":
        return ""
    text = format(Decimal(value).normalize(), "f")
    return text


@register.filter
def display_date(value):
    return services.format_display_date(value)


@register.filter
def same_day(start, end):
    return services.dates_are_same_day(start, end)


@register.simple_tag
def product_classes(product, index=None, columns=4, extra=""):
    """wc_get_product_class() for loops (index given) and the single product (first)."""
    classes = ["product", "type-product", f"post-{product.wp_id or product.pk}", "status-publish"]
    if index is not None:
        if index % columns == 0:
            classes.append("first")
        elif index % columns == columns - 1:
            classes.append("last")
    classes.append(product.stock_status)
    for c in sorted(product.categories.all(), key=lambda c: c.name.lower()):
        if c.slug.lower() in ("uncategorized", "uncategorised"):
            continue
        classes.append(f"product_cat-{c.slug}")
    for t in sorted(product.tags.all(), key=lambda t: t.name.lower()):
        classes.append(f"product_tag-{t.slug}")
    if product.on_sale:
        classes.append("sale")
    if product.virtual:
        classes.append("virtual")
    if product.taxable:
        classes.append("taxable")
        if not product.virtual:
            classes.append("shipping-taxable")
    if product.is_purchasable:
        classes.append("purchasable")
    classes.append("product-type-simple")
    return " ".join(classes)


@register.simple_tag
def add_to_cart_url(request, product):
    """add_query_arg('add-to-cart', id) on the current request URI (relative, as WP prints it)."""
    params = request.GET.copy()
    params["add-to-cart"] = str(product.pk)
    return f"{request.path}?{params.urlencode(safe='/')}"


@register.filter
def json_script_raw(value):
    return mark_safe(services.wp_json_encode(value))


@register.filter
def strip_bdi(html):
    return mark_safe(re.sub(r"</?bdi>", "", str(html)))


@register.filter
def esc_quotes(text):
    return mark_safe(escape(text))
