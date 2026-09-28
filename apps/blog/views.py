"""Blog views: the posts page (index.php), single posts (single.php) and the archive.php family
(author, tag, date and root-level category archives)."""
import calendar
import re
from datetime import date, datetime, time, timedelta

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.safestring import mark_safe

from apps.core.bodyclass import archive_classes, blog_classes, single_classes
from apps.core.models import Status
from apps.core.templatetags.wp import php_date
from apps.core.views import page_number, wp_render
from apps.seo.engine import ROBOTS_NOINDEX, Seo

from . import loop
from .models import AuthorProfile, Category, Post, Tag


def _published(qs, request=None):
    return qs.published()


def listing_items(objs, post_type, images=None):
    """Loop items for template-parts/post/content.php."""
    images = images or loop.ImageCounter()
    items = []
    for obj in objs:
        thumb = ""
        if obj.featured_image_id:
            thumb = loop.attachment_image(obj.featured_image, "twentyseventeen-featured-image", "wp-post-image",
                                          sizes_attr=loop.ARCHIVE_SIZES_ATTR, lazy=images.next_is_lazy())
        items.append({
            "obj": obj,
            "post_type": post_type,
            "classes": loop.post_class(obj, post_type),
            "time_link": loop.time_link(obj) if post_type == "post" else "",
            "thumb": thumb,
            "content": images.content(obj.body_html),
        })
    return items


def card_items(objs):
    """Loop items for content-news.php / content-nebosh-course.php cards."""
    return [{"obj": o, "short_title": loop.short_title(o.title),
             "trimmed": mark_safe(loop.trim_words(o.content, 30, "&hellip;"))} for o in objs]


def seo_home(seo):
    return (seo.settings.breadcrumbs_home, "/")


# ---------------------------------------------------------------------------- posts page
def index(request, page=None):
    from apps.pages.models import Page

    n = page_number(request, page)
    blog_page = Page.objects.filter(wp_id=4651).first() or Page.objects.filter(is_posts_page=True).first()
    posts = Post.objects.published().select_related("featured_image").order_by("-published_at")
    paged = loop.Paged(posts, n, loop.per_page(), "/blog/")
    seo = Seo(request, n, paged.max_pages)
    if blog_page:
        data = seo.singular(blog_page, "/blog/", posts_page=True)
        title = blog_page.title
    else:
        title = "Blog"
        data = seo.archive(kind="post", url="/blog/", name=title, fallback="archive")
    context = {"items": listing_items(paged.items, "post"), "paged": paged, "page_title": title}
    return wp_render(request, "blog/index.html", context, seo=data, body_class=blog_classes())


# ---------------------------------------------------------------------------- singles
def render_single(request, obj, post_type, crumbs=None):
    """single.php for posts, NEBOSH/safety courses and exam papers."""
    body = loop.ImageCounter().content(obj.body_html)
    from apps.exampapers.shortcode import CSS_LINK, replace_shortcode
    body, uses_exam_papers = replace_shortcode(request, body)
    context = {
        "post": obj,
        "body": body,
        "is_course_single": post_type in ("nebosh_course", "safety_course"),
        "cf7_container_post": obj.wp_id or obj.pk,
        "exam_papers_css": mark_safe(CSS_LINK) if uses_exam_papers else "",
    }
    seo = Seo(request).singular(obj, obj.get_absolute_url(), crumbs=crumbs)
    return wp_render(request, "blog/single.html", context, seo=seo, body_class=single_classes(obj, post_type))


def get_visible(request, model, **lookup):
    obj = get_object_or_404(model.objects.select_related("featured_image"), **lookup)
    if obj.status != Status.PUBLISH and not request.user.is_staff:
        raise Http404
    if obj.published_at > timezone.now() and not request.user.is_staff:
        raise Http404
    return obj


def post_detail(request, slug):
    post = get_visible(request, Post, slug=slug)
    return render_single(request, post, "post")


# ---------------------------------------------------------------------------- archive.php
def render_archive(request, *, posts, n, url, title_html, seo_fn, body_extra, header_acf=None,
                   template="blog/archive.html", extra=None):
    """archive.php. seo_fn(Seo, first_item) returns the SeoData."""
    paged = loop.Paged(posts, n, loop.per_page(), url)
    first = paged.items[0] if paged.items else None
    data = loop.link_crumbs(seo_fn(Seo(request, n, paged.max_pages), first), url)
    context = {
        "items": card_items(paged.items),
        "paged": paged,
        "archive_title": mark_safe(title_html),
        "header_open": loop.term_header_open(header_acf),
        **(extra or {}),
    }
    return wp_render(request, template, context, seo=data, body_class=archive_classes(body_extra))


def author(request, nicename, page=None):
    from django.utils.html import escape

    n = page_number(request, page)
    profile = get_object_or_404(AuthorProfile, nicename=nicename)
    posts = Post.objects.published().filter(author=profile.user).select_related("featured_image").order_by("-published_at")
    url = profile.get_absolute_url()
    return render_archive(
        request, posts=posts, n=n, url=url,
        title_html=f"Author: <span>{escape(profile.display_name)}</span>",
        seo_fn=lambda seo, first: seo.author(profile.user, url, first_item=first, has_posts=posts.exists()),
        body_extra=["author", f"author-{profile.nicename}", f"author-{profile.wp_id or profile.user_id}"],
    )


def tag(request, slug, page=None):
    from django.utils.html import escape

    n = page_number(request, page)
    term = get_object_or_404(Tag, slug=slug)
    posts = Post.objects.published().filter(tags=term).select_related("featured_image").order_by("-published_at")
    return render_archive(
        request, posts=posts, n=n, url=term.get_absolute_url(),
        title_html=f"Tag: <span>{escape(term.name)}</span>",
        seo_fn=lambda seo, first: seo.term_archive(term, first_item=first),
        body_extra=["tag", f"tag-{term.slug}", f"tag-{term.wp_id or term.pk}"],
        header_acf=getattr(term, "acf", None),
    )


def date_archive(request, year, month=None, day=None, page=None):
    n = page_number(request, page)
    y = int(year)
    try:
        if day:
            start = date(y, int(month), int(day))
            end = start + timedelta(days=1)
            # get_the_archive_title() uses en_GB's "j F Y"; Yoast's %%date%% and crumb use date_format "jS F Y".
            label, prefix, url = f"{start.day} {start.strftime('%B')} {y}", "Day", f"/blog/{year}/{month}/{day}/"
            seo_label = php_date(start, "jS F Y")
        elif month:
            m = int(month)
            start = date(y, m, 1)
            end = date(y + (m == 12), m % 12 + 1, 1)
            label, prefix, url = f"{start.strftime('%B')} {y}", "Month", f"/blog/{year}/{month}/"
        else:
            start, end = date(y, 1, 1), date(y + 1, 1, 1)
            label, prefix, url = str(y), "Year", f"/blog/{year}/"
        if not day:
            seo_label = label
    except ValueError:
        raise Http404
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz)
    hi = timezone.make_aware(datetime.combine(end, time.min), tz)
    posts = Post.objects.published().filter(published_at__gte=lo, published_at__lt=hi)         .select_related("featured_image").order_by("-published_at")
    if not posts.exists():
        raise Http404

    def seo_fn(seo, first):
        data = seo.date_archive(seo_label, url, first_item=first)
        data.robots = ROBOTS_NOINDEX  # WP output for date archives is noindex
        return data

    return render_archive(
        request, posts=posts, n=n, url=url,
        title_html=f"{prefix}: <span>{label}</span>",
        seo_fn=seo_fn,
        body_extra=["date"],
    )


def category_archive(request, path, page=None):
    """Root-level blog categories (category base "."). WordPress 404s on hidden (Uncategorised) ones."""
    from django.utils.html import escape

    # /page/N/?s=term: WordPress's paginated search links.
    m = re.fullmatch(r"page/(\d+)", path.strip("/"))
    if m and "s" in request.GET:
        from apps.search.views import search_results
        return search_results(request, page=m.group(1))

    slugs = [s for s in path.strip("/").split("/") if s]
    term = None
    for slug in slugs:
        term = Category.objects.filter(slug=slug, parent=term).first()
        if term is None:
            raise Http404
    if term is None or term.slug.lower() in loop.HIDDEN_CATEGORY_SLUGS or term.name.strip().lower() in loop.HIDDEN_CATEGORY_SLUGS:
        raise Http404
    n = page_number(request, page)
    ids = term.get_descendants(include_self=True).values_list("pk", flat=True)
    posts = Post.objects.published().filter(categories__in=ids).distinct() \
        .select_related("featured_image").order_by("-published_at")
    return render_archive(
        request, posts=posts, n=n, url=term.get_absolute_url(),
        title_html=f"Category: <span>{escape(term.name)}</span>",
        seo_fn=lambda seo, first: seo.term_archive(term, first_item=first),
        body_extra=["category", f"category-{term.slug}", f"category-{term.wp_id or term.pk}"],
        header_acf=getattr(term, "acf", None),
    )
