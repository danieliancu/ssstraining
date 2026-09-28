"""Template helpers that reproduce WordPress/WooCommerce/Yoast output. Loaded as a builtin."""
import base64
import json
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from apps.contact.forms import FORMS
from apps.core import wp_format

register = template.Library()

ASSET_DIR = Path(settings.BASE_DIR) / "templates" / "wp_assets"
MANIFEST = Path(settings.BASE_DIR) / "apps" / "core" / "wp_assets.json"


@lru_cache(maxsize=None)
def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _asset(name):
    path = ASSET_DIR / f"{name}.html"
    return path.read_text(encoding="utf-8").rstrip("\n") if path.exists() else ""


@register.simple_tag
def wp_assets(profile, position, only=None, exclude=None):
    """Print the enqueued styles/scripts of a page profile ('head' or 'footer'), in WP order."""
    names = _manifest().get(profile, _manifest()["default"])[position]
    only = set(only.split(",")) if only else None
    exclude = set(exclude.split(",")) if exclude else set()
    out = []
    for name in names:
        handle = name.split(".")[0]
        if (only and handle not in only) or handle in exclude:
            continue
        out.append(_asset(name))
    return mark_safe("".join(out))


@register.simple_tag
def inline_script(code, script_id=""):
    """A deferred inline script as Autoptimize prints it (data: URI keeps execution order)."""
    src = "data:text/javascript;base64," + base64.b64encode(code.encode("utf-8")).decode("ascii")
    id_attr = f' id="{script_id}"' if script_id else ""
    return mark_safe(f'<script defer{id_attr} src="{src}"></script>')


class InlineScriptNode(template.Node):
    def __init__(self, nodelist, script_id):
        self.nodelist = nodelist
        self.script_id = script_id

    def render(self, context):
        return inline_script(self.nodelist.render(context), self.script_id)


@register.tag("deferscript")
def do_deferscript(parser, token):
    bits = token.split_contents()
    script_id = bits[1].strip("\"'") if len(bits) > 1 else ""
    nodelist = parser.parse(("enddeferscript",))
    parser.delete_first_token()
    return InlineScriptNode(nodelist, script_id)


@register.simple_tag(takes_context=True)
def nav_menu(context, menu_name, menu_id, menu_class="menu", container="div", depth=0, item_ids=True):
    from apps.navigation.render import render_menu
    request = context.get("request")
    path = request.path if request else "/"
    current = context.get("menu_current_path") or path
    return mark_safe(render_menu(menu_name, current, menu_id=menu_id, menu_class=menu_class,
                                 container=container or None, depth=int(depth), item_ids=item_ids,
                                 parent_term_urls=context.get("menu_parent_term_urls") or ()))


# ---------------------------------------------------------------------------- prices
def _money(value):
    value = Decimal(value or 0).quantize(Decimal("0.01"))
    return f"{value:,.2f}"


@register.filter
def wc_price(value, bdi=True):
    """WooCommerce wc_price() markup."""
    if value is None or value == "":
        return ""
    negative = Decimal(value) < 0
    amount = _money(abs(Decimal(value)))
    if bdi:
        # WooCommerce 11 wraps the amount in <bdi> and marks the symbol translate="no".
        inner = f'<bdi><span class="woocommerce-Price-currencySymbol" translate="no">&pound;</span>{amount}</bdi>'
    else:
        inner = f'<span class="woocommerce-Price-currencySymbol">&pound;</span>{amount}'
    sign = "-" if negative else ""
    return mark_safe(f'<span class="woocommerce-Price-amount amount">{sign}{inner}</span>')


@register.filter
def price_html(product, show_vat=True):
    """WC_Product::get_price_html() with the theme's filters (NVQ prefix, '+ VAT')."""
    if product is None or product.price is None:
        return ""
    if product.on_sale:
        html = (f'<del aria-hidden="true">{wc_price(product.regular_price)}</del> '
                f'<span class="screen-reader-text">Original price was: &pound;{_money(product.regular_price)}.</span>'
                f'<ins aria-hidden="true">{wc_price(product.price)}</ins>'
                f'<span class="screen-reader-text">Current price is: &pound;{_money(product.price)}.</span>')
    else:
        html = str(wc_price(product.price))
    if product.is_nvq:
        html = f'<span class="nvq-price-prefix">PAY 50% UPFRONT</span> {html}'
    if show_vat and "VAT" not in html:
        html += ' <span class="price-vat-note">+ VAT</span>'
    return mark_safe(html)


@register.filter
def money_plain(value):
    """£ amount without markup, trailing zeros trimmed (search modal style)."""
    if value is None:
        return ""
    text = _money(value).rstrip("0").rstrip(".")
    return f"£{text}"


# ---------------------------------------------------------------------------- text
@register.filter
def wpautop(text):
    return mark_safe(wp_format.wpautop(text or ""))


@register.filter
def texturize(text):
    """the_title() output: wptexturize applied."""
    return mark_safe(wp_format.wptexturize(str(text or "")))


@register.filter
def acf_textarea(text):
    """ACF textarea with 'new_lines = br' (the theme's option textareas)."""
    return mark_safe(wp_format.nl2br(text or ""))


@register.filter
def wp_date(value, fmt="l jS F Y"):
    """PHP date() formats used by the theme, e.g. 'l jS F Y' → 'Saturday 3rd October 2026'."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return value
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)
    return php_date(value, fmt)


def php_date(value, fmt):
    out = []
    for ch in fmt:
        if ch == "l":
            out.append(value.strftime("%A"))
        elif ch == "D":
            out.append(value.strftime("%a"))
        elif ch == "j":
            out.append(str(value.day))
        elif ch == "d":
            out.append(f"{value.day:02d}")
        elif ch == "S":
            d = value.day
            out.append("th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th"))
        elif ch == "F":
            out.append(value.strftime("%B"))
        elif ch == "M":
            out.append(value.strftime("%b"))
        elif ch == "m":
            out.append(f"{value.month:02d}")
        elif ch == "n":
            out.append(str(value.month))
        elif ch == "Y":
            out.append(str(value.year))
        elif ch == "y":
            out.append(value.strftime("%y"))
        elif ch == "G" and isinstance(value, datetime):
            out.append(str(value.hour))
        elif ch == "H" and isinstance(value, datetime):
            out.append(f"{value.hour:02d}")
        elif ch == "i" and isinstance(value, datetime):
            out.append(f"{value.minute:02d}")
        elif ch == "g" and isinstance(value, datetime):
            out.append(str(value.hour % 12 or 12))
        elif ch == "a" and isinstance(value, datetime):
            out.append("am" if value.hour < 12 else "pm")
        else:
            out.append(ch)
    return "".join(out)


@register.filter
def media_url(media, size="full"):
    return media.size_url(size) if media else ""


# ---------------------------------------------------------------------------- SEO
@register.simple_tag(takes_context=True)
def seo_head(context):
    seo = context.get("seo")
    if seo is None:
        return ""
    return mark_safe(render_to_string("partials/seo_head.html", {"seo": seo, "graph_json": _graph_json(seo.graph)}))


def _graph_json(graph):
    if not graph:
        return ""
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=4, ensure_ascii=False)
    return text.replace("/", "\\/").replace("</", "<\\/")


@register.simple_tag(takes_context=True)
def breadcrumbs(context):
    """Yoast breadcrumb markup: <p id="breadcrumbs"><span><span><a>Home</a></span> / ...</span></p>"""
    seo = context.get("seo")
    crumbs = seo.breadcrumbs if seo else []
    if not crumbs:
        return ""
    from apps.seo.models import SeoSettings
    sep = SeoSettings.load().breadcrumbs_sep
    parts = []
    for i, (name, url) in enumerate(crumbs):
        last = i == len(crumbs) - 1
        if last:
            parts.append(f'<span class="breadcrumb_last" aria-current="page"><strong>{name}</strong></span>')
        else:
            parts.append(f'<span><a href="{escape(url)}">{name}</a></span>')
    return mark_safe(f'<p id="breadcrumbs"><span>{f" {sep} ".join(parts)}</span></p>')


# ---------------------------------------------------------------------------- forms
@register.simple_tag(takes_context=True)
def contact_form(context, form_id):
    """Contact Form 7 shortcode output."""
    request = context.get("request")
    counter = context.render_context.setdefault("cf7_counter", [0])
    counter[0] += 1
    ak_counter = context.render_context.setdefault("ak_counter", [0])
    ak_counter[0] += 1
    code = f'\ndocument.getElementById( "ak_js_{ak_counter[0]}" ).setAttribute( "value", ( new Date() ).getTime() );\n'
    return mark_safe(render_to_string("contact/cf7_form.html", {
        "form": FORMS[form_id](),
        # cf7_in_loop: post id when the shortcode runs inside The Loop (WP adds "-p<id>" to the unit tag).
        "unit_tag": f"wpcf7-f{form_id}-" + (f"p{context['cf7_in_loop']}-" if context.get("cf7_in_loop") else "") + f"o{counter[0]}",
        "action_path": request.path if request else "/",
        "container_post": context.get("cf7_container_post", 0),
        "ak_index": ak_counter[0],
        "ak_value": 99,
        "ak_script": "data:text/javascript;base64," + base64.b64encode(code.encode()).decode(),
    }))


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


@register.simple_tag
def svg_icon(icon):
    return mark_safe(f'<svg class="icon icon-{icon}" aria-hidden="true" role="img"> <use href="#icon-{icon}" '
                     f'xlink:href="#icon-{icon}"></use> </svg>')
