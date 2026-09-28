"""Filters for the blog/news/course/search ports."""
import re

from django import template
from django.utils.safestring import mark_safe

from apps.core import wp_format

register = template.Library()

_STYLE_ATTR = re.compile(r'(\sstyle=)(["\'])(.*?)\2', re.S)
_SPACES_DASH = re.compile(r"(?<=[\s\xa0])-(?=[\s\xa0]|$)|^-(?=[\s\xa0])", re.M)


def _kses_style(html):
    """wp_kses_post() / safecss_filter_attr(): declarations re-joined with '; ', no trailing ';',
    quotes inside the attribute printed as &#039;."""
    def fix(m):
        decls = [d.strip() for d in m.group(3).split(";") if d.strip()]
        value = "; ".join(decls).replace("'", "&#039;").replace('"', "&quot;")
        return f'{m.group(1)}"{value}"'
    return _STYLE_ATTR.sub(fix, html)


def acf_format(text):
    """ACF WYSIWYG value as the_field()/the_sub_field() print it: acf_the_content filters
    (wptexturize, wpautop) and ACF's wp_kses_post escaping."""
    if not text:
        return ""
    text = str(text)
    parts = re.split(r"(<[^>]*>)", text)
    parts = [p if p.startswith("<") else _SPACES_DASH.sub("&#8211;", p) for p in parts]
    text = wp_format.wptexturize("".join(parts))
    text = wp_format.wpautop(text)
    # wp_filter_content_tags(): decoding="async" on images.
    text = re.sub(r"<img(?=[ \t\n])(?![^>]*decoding=)", "<img decoding=\"async\"", text)
    return _kses_style(text)


@register.filter
def acf_wysiwyg(text):
    return mark_safe(acf_format(text))


@register.simple_tag
def uniqid(prefix=""):
    """PHP uniqid(): 8 hex digits of seconds + 5 of microseconds."""
    import time
    t = time.time()
    return f"{prefix}{int(t):08x}{int((t % 1) * 1_000_000):05x}"
