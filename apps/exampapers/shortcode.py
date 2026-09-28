"""Port of the exam-papers-manager plugin's [exam_papers_manager] shortcode (render_shortcode)."""
import re

from django.template.loader import render_to_string
from django.utils.safestring import SafeString, mark_safe

SHORTCODE_RE = re.compile(r"(?:<p>\s*)?\[exam_papers_manager(?:\s[^\]]*)?\](?:\s*</p>)?")
CSS_LINK = ('<link rel="stylesheet" id="sst-epm-frontend-css" '
            'href="/static/wp/wp-content/plugins/exam-papers-manager/assets/frontend.css?ver=1.0.0" media="all" />')


def _key(value):
    """sanitize_key(): lowercase, only a-z 0-9 _ -."""
    return re.sub(r"[^a-z0-9_\-]", "", (value or "").lower())


def render(request):
    from apps.blog.loop import the_excerpt
    from .models import DropdownOption, ExamPaper

    groups = DropdownOption.Group
    dropdowns = []
    filters = {}
    for group in groups:
        value = _key(request.GET.get(f"epm_{group.value}", "")) if request else ""
        filters[group.value] = value
        dropdowns.append({
            "key": group.value,
            "label": group.label,
            "items": list(DropdownOption.objects.filter(group=group.value)),
            "selected": value,
        })
    papers = ExamPaper.objects.published().select_related("course", "level", "year", "paper_type").order_by("title")
    for key, value in filters.items():
        if value:
            papers = papers.filter(**{f"{key}__key": value})
    cards = []
    for paper in papers:
        meta = []
        for group in groups:
            option = getattr(paper, group.value)
            if option and option.label:
                meta.append((group.label, option.label))
        cards.append({"paper": paper, "meta": meta, "excerpt": the_excerpt(paper), "url": paper.download_url})
    return mark_safe(render_to_string("exampapers/shortcode.html", {"dropdowns": dropdowns, "cards": cards}))


def replace_shortcode(request, html):
    """Replace a literal [exam_papers_manager] in rendered content. Returns (html, used)."""
    html = str(html or "")
    if "[exam_papers_manager" not in html:
        return mark_safe(html), False
    out = SHORTCODE_RE.sub(lambda m: str(render(request)), html)
    return mark_safe(out), True
