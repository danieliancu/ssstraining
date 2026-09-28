"""WordPress loop helpers shared by the blog, news, course, exam paper and search views:
pagination (WP_Query max_num_pages + the theme's navigation markup), post_class(),
featured images (wp_get_attachment_image with srcset), excerpts and lazy-load bookkeeping."""
import math
import re
from urllib.parse import urlencode

from django.http import Http404
from django.utils import timezone
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

from apps.core import wp_format
from apps.core.templatetags.wp import php_date

HIDDEN_CATEGORY_SLUGS = {"uncategorized", "uncategorised"}

# add_image_size() dimensions (theme + twentyseventeen parent) used to constrain missing sizes.
IMAGE_SIZES = {
    "twentyseventeen-featured-image": (2000, 1200),
    "twentyseventeen-thumbnail-avatar": (100, 100),
    "fullWidthHeaderImage": (1600, 1600),
    "fullSizeLargeTileLandscape": (1170, 339),
}
ARCHIVE_SIZES_ATTR = "(max-width: 767px) 89vw, (max-width: 1000px) 54vw, (max-width: 1071px) 543px, 580px"
# Images before this count are printed without loading="lazy" (wp_omit_loading_attr_threshold).
EAGER_IMAGES = 2


# ---------------------------------------------------------------------------- pagination
class Paged:
    """The slice of a queryset WP_Query would return for ?paged=N."""

    def __init__(self, qs, page, per_page, base_url, query=None):
        self.page = page
        self.per_page = per_page
        self.total = qs.count() if hasattr(qs, "count") and not isinstance(qs, list) else len(qs)
        self.max_pages = max(1, math.ceil(self.total / per_page)) if per_page else 1
        # WP 404s any page past the last (page 1 of an empty archive is a normal "no posts" page).
        if page > 1 and page > self.max_pages:
            raise Http404
        start = (page - 1) * per_page
        self.items = list(qs[start:start + per_page])
        self.base_url = base_url
        self.query = query or {}

    def link(self, n):
        url = self.base_url if n <= 1 else f"{self.base_url}page/{n}/"
        if self.query:
            url += "?" + urlencode(self.query)
        return url

    def numeric_nav(self):
        """functions.php wpbeginner_numeric_posts_nav()."""
        if self.max_pages <= 1:
            return ""
        paged, mx = self.page, self.max_pages
        links = [paged]
        if paged >= 3:
            links += [paged - 1, paged - 2]
        if paged + 2 <= mx:
            links += [paged + 2, paged + 1]
        out = ['<div class="navigation"><ul>\n']
        if 1 not in links:
            cls = ' class="active"' if paged == 1 else ""
            out.append(f'<li{cls}><a href="{escape(self.link(1))}">1</a></li>\n')
            if 2 not in links:
                out.append("<li>…</li>")
        for n in sorted(links):
            cls = ' class="active"' if paged == n else ""
            out.append(f'<li{cls}><a href="{escape(self.link(n))}">{n}</a></li>\n')
        if mx not in links:
            if mx - 1 not in links:
                out.append("<li>…</li>\n")
            cls = ' class="active"' if paged == mx else ""
            out.append(f'<li{cls}><a href="{escape(self.link(mx))}">{mx}</a></li>\n')
        out.append("</ul></div>\n")
        return mark_safe("".join(out))

    def posts_pagination(self):
        """the_posts_pagination() with twentyseventeen's arguments (paginate_links, mid_size 1)."""
        if self.max_pages <= 1:
            return ""
        from apps.core.templatetags.wp import svg_icon
        cur, total = self.page, self.max_pages
        before = '<span class="meta-nav screen-reader-text">Page </span>'
        parts = []
        if cur > 1:
            parts.append(f'<a class="prev page-numbers" href="{escape(self.link(cur - 1))}">{svg_icon("arrow-left")}'
                         f'<span class="screen-reader-text">Previous page</span></a>')
        dots = False
        for n in range(1, total + 1):
            if n == cur:
                parts.append(f'<span aria-current="page" class="page-numbers current">{before}{n}</span>')
                dots = True
            elif n <= 1 or n > total - 1 or (cur - 1 <= n <= cur + 1):
                parts.append(f'<a class="page-numbers" href="{escape(self.link(n))}">{before}{n}</a>')
                dots = True
            elif dots:
                parts.append('<span class="page-numbers dots">&hellip;</span>')
                dots = False
        if cur < total:
            parts.append(f'<a class="next page-numbers" href="{escape(self.link(cur + 1))}">'
                         f'<span class="screen-reader-text">Next page</span>{svg_icon("arrow-right")}</a>')
        return mark_safe('<nav class="navigation pagination" aria-label="Posts pagination">'
                         '<h2 class="screen-reader-text">Posts pagination</h2><div class="nav-links">'
                         + "\n".join(parts) + "</div></nav>")


def per_page():
    from apps.core.models import SiteOptions
    return SiteOptions.load().posts_per_page or 16


# ---------------------------------------------------------------------------- post data
def visible_categories(post):
    """get_the_terms() with the theme's sst_filter_hidden_terms (drops Uncategorised)."""
    return [c for c in post.categories.all()
            if c.slug.lower() not in HIDDEN_CATEGORY_SLUGS and c.name.strip().lower() not in HIDDEN_CATEGORY_SLUGS]


def post_class(obj, post_type):
    classes = [f"post-{obj.wp_id or obj.pk}", post_type, f"type-{post_type}", f"status-{obj.status}", "format-standard"]
    if obj.featured_image_id:
        classes.append("has-post-thumbnail")
    classes.append("hentry")
    if post_type == "post":
        classes += [f"category-{c.slug}" for c in visible_categories(obj)]
        classes += [f"tag-{t.slug}" for t in obj.tags.all()]
    elif post_type == "news":
        classes += [f"news_categories-{c.slug}" for c in obj.categories.all()]
    elif post_type in ("nebosh_course", "safety_course"):
        tax = "nebosh_courses" if post_type == "nebosh_course" else "safety_courses"
        classes += [f"{tax}-{t.slug}" for t in obj.terms.all()]
    return " ".join(classes)


def local(dt):
    return timezone.localtime(dt) if dt and timezone.is_aware(dt) else dt


def time_link(obj):
    """twentyseventeen_time_link()."""
    pub, mod = local(obj.published_at), local(obj.modified_at)
    url = escape(obj.get_absolute_url())
    if int(pub.timestamp()) != int(mod.timestamp()):
        times = (f'<time class="entry-date published" datetime="{pub.isoformat(timespec="seconds")}">{php_date(pub, "jS F Y")}</time>'
                 f'<time class="updated" datetime="{mod.isoformat(timespec="seconds")}">{php_date(mod, "jS F Y")}</time>')
    else:
        times = f'<time class="entry-date published updated" datetime="{pub.isoformat(timespec="seconds")}">{php_date(pub, "jS F Y")}</time>'
    return mark_safe(f'<span class="screen-reader-text">Posted on</span> <a href="{url}" rel="bookmark">{times}</a>')


def short_title(title, length=60):
    """content-news.php: substr($post_title, 0, 60) . '...' (byte based, like PHP)."""
    raw = (title or "").encode("utf-8")
    out = raw[:length].decode("utf-8", errors="ignore")
    return out + ("..." if len(raw) > length else "")


def trim_words(html, num=55, more=""):
    """wp_trim_words() on already-rendered HTML."""
    text = re.sub(r"<(script|style)[^>]*?>.*?</\1>", "", html or "", flags=re.S | re.I)
    text = strip_tags(text)
    words = [w for w in re.split(r"[\n\r\t ]+", text) if w]
    if len(words) > num:
        return " ".join(words[:num]) + more
    return " ".join(words)


def the_excerpt(obj):
    """the_excerpt() with twentyseventeen's excerpt_more link."""
    if getattr(obj, "excerpt", ""):
        return mark_safe(wp_format.wpautop(wp_format.wptexturize(obj.excerpt)))
    title = wp_format.wptexturize(obj.title)
    body = obj.body_html if hasattr(obj, "body_html") else (getattr(obj, "description", "") or "")
    words = trim_words(body, 55, "")
    full = trim_words(body, 10 ** 6, "")
    if len(full) > len(words):
        more = (f'<p class="link-more"><a href="{escape(obj.get_absolute_url())}" class="more-link">'
                f'Continue reading<span class="screen-reader-text"> &#8220;{title}&#8221;</span></a></p>')
        return mark_safe(f"<p>{wp_format.wptexturize(words)} &hellip;</p>\n{more}\n")
    return mark_safe(f"<p>{wp_format.wptexturize(words)}</p>\n") if words else ""


# ---------------------------------------------------------------------------- images
class ImageCounter:
    """Tracks how many images the page printed so far, for WP's lazy-loading threshold."""

    def __init__(self, eager=EAGER_IMAGES):
        self.count = 0
        self.eager = eager

    def next_is_lazy(self):
        self.count += 1
        return self.count > self.eager

    def content(self, html):
        """Content rendered by the import bridge marks every image lazy; restore WP's in-loop output."""
        def fix(m):
            tag = m.group(0)
            if self.next_is_lazy():
                return tag
            tag = tag.replace(' loading="lazy"', "")
            return tag.replace('sizes="auto, ', 'sizes="')
        return mark_safe(re.sub(r"<img\b[^>]*>", fix, html or ""))


def _constrain(w, h, max_w, max_h=0):
    if not max_w and not max_h:
        return w, h
    wr = max_w / w if max_w and w > max_w else 1.0
    hr = max_h / h if max_h and h > max_h else 1.0
    ratio = min(wr, hr)
    if ratio == 1.0:
        return w, h
    return max(1, int(round(w * ratio))), max(1, int(round(h * ratio)))


def _matches_ratio(w1, h1, w2, h2):
    if w1 > w2:
        cw, ch = _constrain(w1, h1, w2)
        ew, eh = w2, h2
    else:
        cw, ch = _constrain(w2, h2, w1)
        ew, eh = w1, h1
    return abs(cw - ew) <= 1 and abs(ch - eh) <= 1


def attachment_image(media, size, cls, sizes_attr=None, lazy=False):
    """wp_get_attachment_image($id, $size) markup."""
    if not media:
        return ""
    from django.conf import settings
    info = media.sizes.get(size)
    if info:
        src, w, h = settings.MEDIA_URL + info["file"], info["width"], info["height"]
    else:
        src, w, h = media.url, media.width, media.height
        if size in IMAGE_SIZES and w and h:
            w, h = _constrain(w, h, *IMAGE_SIZES[size])
    attrs = []
    if w and h:
        attrs.append(f'width="{w}" height="{h}"')
    size_cls = size if isinstance(size, str) else "full"
    attrs.append(f'src="{escape(src)}" class="attachment-{size_cls} size-{size_cls}{" " + cls if cls else ""}" '
                 f'alt="{escape(media.alt)}" decoding="async"')
    if lazy:
        attrs.append('loading="lazy"')
    srcset = []
    if media.width and media.height and w and h:
        seen = {}
        candidates = list(media.sizes.values()) + [{"file": media.file.name, "width": media.width, "height": media.height}]
        for cand in candidates:
            cw, ch = cand.get("width"), cand.get("height")
            if not cw or not ch or cw > 2048:
                continue
            if not _matches_ratio(w, h, cw, ch):
                continue
            url = settings.MEDIA_URL + cand["file"]
            entry = f"{url} {cw}w"
            if url == src:
                seen = {cw: entry, **{k: v for k, v in seen.items() if k != cw}}
            else:
                seen[cw] = entry
        if len(seen) > 1:
            srcset = list(seen.values())
    if srcset:
        attrs.append(f'srcset="{escape(", ".join(srcset))}"')
        attrs.append(f'sizes="{sizes_attr or f"(max-width: {w}px) 100vw, {w}px"}"')
    return mark_safe("<img " + " ".join(attrs) + " />")


def hex2rgba(color, opacity=None):
    """functions.php hex2rgba()."""
    default = "rgb(0,0,0)"
    if not color:
        return default
    color = color[1:] if color[0] == "#" else color
    if len(color) == 6:
        parts = [color[0:2], color[2:4], color[4:6]]
    elif len(color) == 3:
        parts = [c * 2 for c in color]
    else:
        return default
    try:
        rgb = [str(int(p, 16)) for p in parts]
    except ValueError:
        return default
    if opacity:
        op = 1.0 if abs(opacity) > 1 else opacity
        return f"rgba({','.join(rgb)},{op:g})"
    return f"rgb({','.join(rgb)})"


def term_header_open(acf):
    """The opening markup archive.php / taxonomy-news_categories.php print from the term's ACF fields.
    Their closing </div></div> is printed unconditionally by the templates, as in the theme."""
    acf = acf or {}
    style = acf.get("header_style")
    if style == "full-width-image":
        from apps.core.models import Media
        media = Media.objects.filter(wp_id=acf.get("background_image") or 0).first() if str(acf.get("background_image") or "").isdigit() else None
        url = media.size_url("fullWidthHeaderImage") if media else ""
        parallax = "parralax" if acf.get("parrallax") == "yes" else ""
        overlay = f"background:{hex2rgba(acf.get('overlay_colour'), 0.7)}" if acf.get("overlay") == "yes" else ""
        return mark_safe(f'<div class="container-fluid category-header full-image {parallax} no-padding" title="" '
                         f'style="background:url({escape(url)}) {escape(acf.get("background_position") or "")} no-repeat;">'
                         f'<div class="overlay" style=" {overlay}">')
    if style == "block-background-colour":
        return mark_safe(f'<div class="container-fluid category-header block-colour no-padding" title=""  '
                         f'style="background:{escape(acf.get("background_block_colour") or "")}"><div class="overlay">')
    return ""


def link_crumbs(data, url):
    """On /page/N/ Yoast links the archive crumb before "Page N"; give link-less crumbs the archive URL."""
    crumbs = list(data.breadcrumbs or [])
    for i, (name, link) in enumerate(crumbs[:-1]):
        if link is None:
            crumbs[i] = (name, url)
    data.breadcrumbs = crumbs
    return data
