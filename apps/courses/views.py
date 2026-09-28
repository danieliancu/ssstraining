"""NEBOSH and safety course post types: archive-nebosh_course.php, archive-safety_course.php,
single.php (course branch) and archive.php for their taxonomies."""
from django.shortcuts import get_object_or_404
from django.utils.html import escape

from apps.blog import loop
from apps.blog.views import card_items, get_visible, render_archive, render_single
from apps.core.bodyclass import archive_classes
from apps.core.models import SiteOptions
from apps.core.views import page_number, wp_render
from apps.seo.engine import Seo

from .models import NeboshCourse, NeboshCourseTerm, SafetyCourse, SafetyCourseTerm

TYPES = {
    "nebosh": {
        "model": NeboshCourse, "term_model": NeboshCourseTerm, "post_type": "nebosh_course",
        "taxonomy": "nebosh_courses", "name": "NEBOSH Courses", "tax_label": "NEBOSH Courses Category",
        "url": "/blog/nebosh_course/",
    },
    "safety": {
        "model": SafetyCourse, "term_model": SafetyCourseTerm, "post_type": "safety_course",
        "taxonomy": "safety_courses", "name": "Safety Courses", "tax_label": "Safety Courses Category",
        "url": "/blog/safety_course/",
    },
}


def _archive(request, kind, page):
    t = TYPES[kind]
    n = page_number(request, page)
    qs = t["model"].objects.published().select_related("featured_image").order_by("-published_at")
    paged = loop.Paged(qs, n, loop.per_page(), t["url"])
    first = paged.items[0] if paged.items else None
    seo = loop.link_crumbs(Seo(request, n, paged.max_pages).post_type_archive(t["post_type"], t["url"], t["name"],
                                                                              first_item=first), t["url"])
    options = SiteOptions.load()
    context = {
        "kind": kind,
        "items": card_items(paged.items),
        "paged": paged,
        "archive_name": t["name"],
        "options": options,
        "about": options.nebosh_about if kind == "nebosh" else options.safety_about,
    }
    return wp_render(request, "courses/archive.html", context, seo=seo,
                     body_class=archive_classes(["post-type-archive", f"post-type-archive-{t['post_type']}"]))


def _detail(request, kind, slug):
    t = TYPES[kind]
    course = get_visible(request, t["model"], slug=slug)
    return render_single(request, course, t["post_type"])


def _term(request, kind, slug, page):
    t = TYPES[kind]
    n = page_number(request, page)
    term = get_object_or_404(t["term_model"], slug=slug)
    ids = term.get_descendants(include_self=True).values_list("pk", flat=True)
    qs = t["model"].objects.published().filter(terms__in=ids).distinct().select_related("featured_image").order_by("-published_at")
    return render_archive(
        request, posts=qs, n=n, url=term.get_absolute_url(),
        title_html=f"{t['tax_label']}: <span>{escape(term.name)}</span>",
        seo_fn=lambda seo, first: seo.term_archive(term, first_item=first),
        body_extra=[f"tax-{t['taxonomy']}", f"term-{term.slug}", f"term-{term.wp_id or term.pk}"],
        header_acf=term.acf,
    )


def nebosh_archive(request, page=None):
    return _archive(request, "nebosh", page)


def safety_archive(request, page=None):
    return _archive(request, "safety", page)


def nebosh_detail(request, slug):
    return _detail(request, "nebosh", slug)


def safety_detail(request, slug):
    return _detail(request, "safety", slug)


def nebosh_term(request, slug, page=None):
    return _term(request, "nebosh", slug, page)


def safety_term(request, slug, page=None):
    return _term(request, "safety", slug, page)
