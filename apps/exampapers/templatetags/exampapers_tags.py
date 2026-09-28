from django import template
from django.utils.safestring import mark_safe

from apps.exampapers import shortcode

register = template.Library()


@register.simple_tag(takes_context=True)
def exam_papers_body(context, page):
    """Page template "exam_papers": the page content plus the [exam_papers_manager] listing
    (rendered in place when the content already contains the shortcode)."""
    request = context.get("request")
    html, used = shortcode.replace_shortcode(request, page.body_html)
    if not used:
        html = mark_safe(str(html) + str(shortcode.render(request)))
    return html


@register.simple_tag(takes_context=True)
def exam_papers_shortcode(context, html):
    """Replace a literal [exam_papers_manager] in any rendered content body."""
    return shortcode.replace_shortcode(context.get("request"), html)[0]


@register.simple_tag
def exam_papers_css():
    return mark_safe(shortcode.CSS_LINK)
