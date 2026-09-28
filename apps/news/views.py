"""News post type: archive-news.php, single-news.php and taxonomy-news_categories.php."""
from django.shortcuts import get_object_or_404
from django.utils.safestring import mark_safe

from apps.blog import loop
from apps.blog.views import card_items, get_visible, listing_items
from apps.core.bodyclass import archive_classes, single_classes
from apps.core.views import page_number, wp_render
from apps.seo.engine import Seo

from .models import News, NewsCategory

ARCHIVE_URL = "/blog/news/"


def archive(request, page=None):
    n = page_number(request, page)
    qs = News.objects.published().select_related("featured_image").prefetch_related("categories").order_by("-published_at")
    paged = loop.Paged(qs, n, loop.per_page(), ARCHIVE_URL)
    first = paged.items[0] if paged.items else None
    seo = loop.link_crumbs(Seo(request, n, paged.max_pages).post_type_archive("news", ARCHIVE_URL, "News", first_item=first),
                           ARCHIVE_URL)
    context = {"items": listing_items(paged.items, "news"), "paged": paged,
               "archive_description": mark_safe("<p>News</p>")}
    return wp_render(request, "news/archive.html", context, seo=seo,
                     body_class=archive_classes(["post-type-archive", "post-type-archive-news"]))


def detail(request, slug):
    from apps.exampapers.shortcode import CSS_LINK, replace_shortcode

    post = get_visible(request, News, slug=slug)
    acf = post.acf or {}
    header_image = ""
    if post.featured_image:
        header_image = post.featured_image.size_url("fullWidthHeaderImage")
    body, uses_exam_papers = replace_shortcode(request, loop.ImageCounter().content(post.body_html))
    context = {
        "post": post,
        "body": body,
        "header_image_url": header_image,
        "overlay_rgba": loop.hex2rgba(acf.get("overlay_colour"), 0.7),
        "exam_papers_css": mark_safe(CSS_LINK) if uses_exam_papers else "",
    }
    s = Seo(request)
    crumbs = [(s.settings.breadcrumbs_home, "/"), ("News", ARCHIVE_URL), (post.breadcrumb_title or post.title, None)]
    seo = s.singular(post, post.get_absolute_url(), crumbs=crumbs)
    return wp_render(request, "news/single.html", context, seo=seo, body_class=single_classes(post, "news"))


def category(request, slug, page=None):
    n = page_number(request, page)
    term = get_object_or_404(NewsCategory, slug=slug)
    ids = term.get_descendants(include_self=True).values_list("pk", flat=True)
    qs = News.objects.published().filter(categories__in=ids).distinct().select_related("featured_image").order_by("-published_at")
    paged = loop.Paged(qs, n, loop.per_page(), term.get_absolute_url())
    first = paged.items[0] if paged.items else None
    seo = loop.link_crumbs(Seo(request, n, paged.max_pages).term_archive(term, first_item=first), term.get_absolute_url())
    context = {"items": card_items(paged.items), "paged": paged, "term": term,
               "header_open": loop.term_header_open(term.acf)}
    return wp_render(request, "news/category.html", context, seo=seo,
                     body_class=archive_classes(["tax-news_categories", f"term-{term.slug}", f"term-{term.wp_id or term.pk}"]))
