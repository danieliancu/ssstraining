"""Yoast-equivalent SEO data: titles from templates, meta description, canonical, OpenGraph,
Twitter and the schema.org @graph. Views build a SeoData and the {% seo_head %} tag prints it.

The behaviour mirrors Yoast SEO's presentations (wordpress-seo/src/presentations/*) and schema
pieces (src/generators/schema/*):

    Seo(request, page_number, total_pages).singular(obj, url)        # pages, posts, CPTs, products
    Seo(...).singular(blog_page, url)                                 # static posts page (auto)
    Seo(...).archive(kind=..., url=..., name=..., term=term)          # taxonomy term archive
    Seo(...).post_type_archive(post_type, url, name, first_item=...)  # /blog/news/ etc.
    Seo(...).author(user, url, first_item=...)                        # /blog/author/x/
    Seo(...).date_archive(label, url)                                 # /blog/2026/06/
    Seo(...).search(phrase, first_item=...)
    Seo(...).not_found()

``first_item`` is the first object listed on the archive; Yoast uses its featured image as the
page's primary image in the schema graph.
"""
import hashlib
import html
import json
import math
import re
from dataclasses import dataclass, field
from html.entities import codepoint2name, name2codepoint
from urllib.parse import quote

from django.conf import settings
from django.utils.text import Truncator

from .models import SeoMeta, SeoSettings

ROBOTS_INDEX = "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
ROBOTS_NOINDEX = "noindex, follow"
LANGUAGE = "en-GB"

DEFAULT_TITLES = {
    "home": "%%sitename%% %%page%% %%sep%% %%sitedesc%%",
    "singular": "%%title%% %%page%% %%sep%% %%sitename%%",
    "archive": "%%pt_plural%% Archive %%page%% %%sep%% %%sitename%%",
    "term": "%%term_title%% Archives %%page%% %%sep%% %%sitename%%",
    "author": "%%name%%, Author at %%sitename%% %%page%%",
    "date": "%%date%% %%page%% %%sep%% %%sitename%%",
    "search": "You searched for %%searchphrase%% %%page%% %%sep%% %%sitename%%",
    "404": "Page not found %%sep%% %%sitename%%",
}

# WooCommerce marks these pages noindex (wc_page_noindex); Yoast prints the result.
WC_NOINDEX_SLUGS = {"basket", "cart", "checkout", "checkout-2", "my-account"}
# Post types with Yoast's Article + Person pieces (is_author_supported / schema-article-type).
ARTICLE_TYPES = {"post"}
UNCATEGORISED = {"Uncategorized", "Uncategorised"}


def absolute(url):
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return settings.SITE_URL + (url if url.startswith("/") else "/" + url)


# ----------------------------------------------------------------------------- escaping
_ENTITY_RE = re.compile(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")


def esc_attr(text):
    """WordPress esc_attr()/esc_html(): escape &<>"' without double-encoding valid entities."""
    text = "" if text is None else str(text)
    out, pos = [], 0
    for m in _ENTITY_RE.finditer(text):
        out.append(_esc_plain(text[pos:m.start()]))
        ent = m.group(0)
        name = ent[1:-1]
        out.append(ent if name.startswith("#") or name in name2codepoint else "&amp;" + ent[1:])
        pos = m.end()
    out.append(_esc_plain(text[pos:]))
    return "".join(out)


def _esc_plain(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#039;"))


def strip_all_tags(text):
    """wp_strip_all_tags() without line-break removal."""
    text = re.sub(r"<(script|style)[^>]*?>.*?</\1>", "", text or "", flags=re.S | re.I)
    return re.sub(r"<[^>]*>", "", text).strip()


def smart_strip_tags(text):
    """Yoast HTML_Helper::smart_strip_tags (schema text values)."""
    if not text:
        return ""
    text = re.sub(r"(\r|\n)", " ", str(text))
    text = re.sub(r"<br(\s*)?/?>", " ", text, flags=re.I)
    text = re.sub(r"</(p|div|h\d)>", r"</\1> ", text, flags=re.I)
    text = re.sub(r"(<li[^>]*>)", "\\1\u2022 ", text, flags=re.I)
    text = strip_all_tags(text)
    return re.sub(r"\s+", " ", text).strip()


def php_str_word_count(text):
    """PHP str_word_count(): ASCII letters plus ' and - (not leading)."""
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text or ""))


def php_round(x):
    return int(math.floor(x + 0.5))


def strip_shortcodes(text):
    return re.sub(r"\[(\[?)(/?)[A-Za-z][\w-]*(?:\s[^\]]*)?(\]?)\]", "", text or "")


def yoast_word_count(content, title=""):
    """Yoast Article::word_count()."""
    text = f"{title} {content or ''}"
    text = re.sub(r"<(pre|code)[^>]*?>.*?</\1>", "", text, flags=re.S | re.I)
    text = text.replace("><", "> <")
    text = strip_all_tags(text)
    enc = []
    for ch in text:
        cp = ord(ch)
        if ch == "&":
            enc.append("&amp;")
        elif ch == '"':
            enc.append("&quot;")
        elif ch == "'":
            enc.append("&#039;")
        elif ch == "<":
            enc.append("&lt;")
        elif ch == ">":
            enc.append("&gt;")
        elif cp > 127 and cp in codepoint2name:
            enc.append(f"&{codepoint2name[cp]};")
        else:
            enc.append(ch)
    text = re.sub(r"&[a-z0-9]+;", " ", "".join(enc), flags=re.I)
    return php_str_word_count(text)


def texturize_title(text):
    """get_the_title(): wptexturize incl. its bare-ampersand -> &#038; step."""
    from apps.core.wp_format import wptexturize
    text = wptexturize(text or "")
    return re.sub(r"&(?!#(?:\d+|x[a-f0-9]+);|[a-z1-4]{1,8};)", "&#038;", text, flags=re.I)


def gravatar_url(email, size=96):
    digest = hashlib.sha256((email or "").strip().lower().encode()).hexdigest()
    return f"https://secure.gravatar.com/avatar/{digest}?s={size}&d=mm&r=g"


def _date(value):
    return value.isoformat(timespec="seconds") if value else ""


# ----------------------------------------------------------------------------- data
@dataclass
class SeoData:
    title: str = ""
    description: str = ""
    canonical: str = ""
    robots: str = ROBOTS_INDEX
    og_type: str = "article"
    og_title: str = ""
    og_description: str = ""
    og_image: dict | None = None
    og_url: str = ""
    published: str = ""
    modified: str = ""
    author: str = ""
    twitter: list = field(default_factory=list)
    twitter_title: str = ""
    prev: str = ""
    next: str = ""
    graph: list = field(default_factory=list)
    breadcrumbs: list = field(default_factory=list)  # [(name, url or None)] - visible breadcrumbs
    site_name: str = ""
    is_error: bool = False  # 404: only locale/title/site_name OG tags, no twitter card
    # Yoast drops canonical/prev/next when its own robots value is noindex (not for WooCommerce's
    # wc_page_noindex, which basket/checkout get).
    hide_canonical: bool = False
    canonical_on_noindex: bool = False

    @property
    def head_html(self):
        """The Yoast <head> block (without robots, which base.html prints first)."""
        e = esc_attr
        lines = [f"<title>{e(self.title)}</title>"]
        if self.description:
            lines.append(f'<meta name="description" content="{e(self.description)}" />')
        hide = self.hide_canonical or (self.robots.startswith("noindex") and not self.canonical_on_noindex)
        if self.canonical and not hide:
            lines.append(f'<link rel="canonical" href="{e(self.canonical)}" />')
        if self.prev and not hide:
            lines.append(f'<link rel="prev" href="{e(self.prev)}" />')
        if self.next and not hide:
            lines.append(f'<link rel="next" href="{e(self.next)}" />')
        lines.append('<meta property="og:locale" content="en_GB" />')
        if self.is_error:
            lines.append(f'<meta property="og:title" content="{e(self.og_title)}" />')
            lines.append(f'<meta property="og:site_name" content="{e(self.site_name)}" />')
        else:
            lines.append(f'<meta property="og:type" content="{e(self.og_type)}" />')
            if self.og_title:
                lines.append(f'<meta property="og:title" content="{e(self.og_title)}" />')
            if self.og_description:
                lines.append(f'<meta property="og:description" content="{e(self.og_description)}" />')
            og_url = self.og_url if self.og_url is not None else self.canonical
            if og_url:
                lines.append(f'<meta property="og:url" content="{e(og_url)}" />')
            lines.append(f'<meta property="og:site_name" content="{e(self.site_name)}" />')
            if self.published:
                lines.append(f'<meta property="article:published_time" content="{self.published}" />')
            if self.modified:
                lines.append(f'<meta property="article:modified_time" content="{self.modified}" />')
            if self.og_image:
                img = self.og_image
                lines.append(f'<meta property="og:image" content="{img["url"].replace(chr(34), "%22")}" />')
                if img.get("width") and img.get("height"):
                    lines.append(f'<meta property="og:image:width" content="{img["width"]}" />')
                    lines.append(f'<meta property="og:image:height" content="{img["height"]}" />')
                if img.get("type"):
                    lines.append(f'<meta property="og:image:type" content="{e(img["type"])}" />')
            if self.author:
                lines.append(f'<meta name="author" content="{e(self.author)}" />')
            lines.append('<meta name="twitter:card" content="summary_large_image" />')
            if self.twitter_title:
                lines.append(f'<meta name="twitter:title" content="{e(self.twitter_title)}" />')
            for i, (label, value) in enumerate(self.twitter, start=1):
                lines.append(f'<meta name="twitter:label{i}" content="{e(label)}" />')
                lines.append(f'<meta name="twitter:data{i}" content="{e(value)}" />')
        if self.graph:
            lines.append(f'<script type="application/ld+json" class="yoast-schema-graph">{self.schema_json}</script>')
        return "\n".join(lines) + "\n"

    @property
    def schema_json(self):
        return schema_json(self.graph)


def schema_json(graph):
    """PHP wp_json_encode(JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE) + Yoast's "\\n" -> "\\n\\t"."""
    if not graph:
        return ""
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=4, ensure_ascii=False)
    text = text.replace("/", "\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return text.replace("\n", "\n\t")


# ----------------------------------------------------------------------------- engine
class Seo:
    def __init__(self, request, page_number=1, total_pages=1):
        from apps.core.models import SiteOptions
        self.request = request
        self.settings = SeoSettings.load()
        self.options = SiteOptions.load()
        self.page_number = int(page_number or 1)
        self.total_pages = int(total_pages or 1)

    # --- variables ------------------------------------------------------------------
    def replace_vars(self, template, **values):
        sep = self.settings.separator
        page = ""
        if self.total_pages > 1 and self.page_number > 1:
            page = f"{sep} Page {self.page_number} of {self.total_pages}"
        mapping = {
            "sitename": self.options.site_name,
            "sitedesc": self.options.tagline,
            "sep": sep,
            "page": page,
            "pagenumber": str(self.page_number) if self.page_number > 1 else "",
            "pagetotal": str(self.total_pages) if self.total_pages > 1 else "",
            "currentyear": _now().strftime("%Y"),
            "currentmonth": _now().strftime("%B"),
            "currentday": str(_now().day),
            **{k: ("" if v is None else str(v)) for k, v in values.items()},
        }
        out = re.sub(r"%%([a-z_]+)%%", lambda m: mapping.get(m.group(1), ""), template or "")
        return re.sub(r"\s+", " ", out).strip()

    def template(self, key, fallback):
        return self.settings.title_templates.get(key) or DEFAULT_TITLES[fallback]

    def _data(self, **kwargs):
        return SeoData(site_name=self.options.site_name, **kwargs)

    def _paged(self, url, n=None):
        n = self.page_number if n is None else n
        return url if n <= 1 else f"{url.rstrip('/')}/page/{n}/"

    # --- singular -------------------------------------------------------------------
    def singular(self, obj, url, *, is_front=False, crumbs=None, posts_page=None):
        """A post of any type: page, post, news, course, product, the static front page and the
        static posts page (Page.is_posts_page)."""
        kind = obj.seo_type
        if posts_page is None:
            posts_page = bool(getattr(obj, "is_posts_page", False))
        title_text = obj.title
        values = self._post_values(obj)
        if getattr(obj, "seo_title", ""):
            title = self.replace_vars(obj.seo_title, **values)
        else:
            title = self.replace_vars(self.template(f"title-{kind}", "singular"), **values)
        desc_tpl = getattr(obj, "seo_description", "") or self.settings.title_templates.get(f"metadesc-{kind}", "")
        desc = strip_all_tags(self.replace_vars(desc_tpl, **values))
        permalink = absolute(getattr(obj, "canonical_url", "") or url)
        canonical = permalink
        if self.page_number > 1 and not getattr(obj, "canonical_url", ""):
            canonical = absolute(self._paged(url))
        data = self._data(title=title, description=desc, canonical=canonical, og_url=permalink)
        noindex = getattr(obj, "noindex", False) or getattr(obj, "status", "publish") == "private"
        if kind == "page" and getattr(obj, "slug", "") in WC_NOINDEX_SLUGS:
            noindex = True
            data.canonical_on_noindex = True
        data.robots = ROBOTS_NOINDEX if noindex else ROBOTS_INDEX
        data.og_type = "website" if is_front else "article"
        data.og_title = self.replace_vars(getattr(obj, "og_title", ""), **values) or title
        data.og_description = (self.replace_vars(getattr(obj, "og_description", ""), **values)
                               or desc or self._auto_excerpt(obj))

        # Open Graph image (indexable: user-set OG image > featured image > first content image)
        og_media = getattr(obj, "og_image", None) or _featured(obj)
        content_img = None
        if og_media:
            data.og_image = _og_image_from_media(og_media)  # None for types OG doesn't allow
        else:
            content_img = self._first_content_image(obj)
            if content_img and content_img[0].rsplit("?", 1)[0].rsplit(".", 1)[-1].lower() in OG_IMAGE_EXTENSIONS:
                data.og_image = {"url": content_img[0]}

        published = _published(obj)
        modified = effective_modified(obj)
        singular_tags = not posts_page  # Yoast strips singular presenters from the posts page
        if singular_tags:
            if kind == "post" and published:
                data.published = _date(published)
            if published and modified and modified > published:
                data.modified = _date(modified)
            author = getattr(obj, "author", None) if kind in ARTICLE_TYPES else None
            if author is not None:
                data.author = _author_name(author)
            if not is_front:
                if author is not None:
                    data.twitter.append(("Written by", _author_name(author)))
                minutes = self.reading_time(obj)
                if minutes:
                    data.twitter.append(("Estimated reading time", f"{minutes} minute" + ("s" if minutes != 1 else "")))

        # Pagination (static posts page behaves as an archive)
        if posts_page:
            if self.page_number > 1:
                data.prev = absolute(self._paged(url, self.page_number - 1))
            if self.page_number < self.total_pages:
                data.next = absolute(self._paged(url, self.page_number + 1))
        elif kind == "page" and getattr(obj, "slug", "") == "shop" and self.page_number > 1:
            data.prev = absolute(self._paged(url, self.page_number - 1))
        if kind == "page" and getattr(obj, "slug", "") == "shop" and self.page_number < self.total_pages:
            data.next = absolute(self._paged(url, self.page_number + 1))

        data.breadcrumbs = crumbs if crumbs is not None else self.crumbs_for(obj, is_front)

        # Schema
        if is_front:
            page_type = "WebPage"
        elif posts_page:
            page_type = ["WebPage", "CollectionPage"]
        else:
            page_type = "WebPage"
        main_image = None
        if _featured(obj):
            main_image = self._image_from_media(_featured(obj), permalink)
        elif content_img:
            main_image = self._image_from_url(content_img[0], permalink, content_img[1])
        schema_crumbs = self._schema_crumbs(data.breadcrumbs, is_front=is_front, posts_page=posts_page,
                                            simple_page=True)
        data.graph = self._graph(
            page_type=page_type, main_id=permalink, url=permalink, canonical=permalink, name=title,
            description=desc, main_image=main_image, crumbs=schema_crumbs, obj=obj,
            published=published, modified=modified, is_front=is_front,
        )
        return data

    def _post_values(self, obj):
        return {
            "title": obj.title,
            "excerpt": self._excerpt_var(obj),
            "excerpt_only": _plain(getattr(obj, "excerpt", "") or getattr(obj, "short_description", "")),
            "date": _wp_date(_published(obj)),
            "modified": _wp_date(getattr(obj, "modified_at", None)),
            "name": _author_name(obj.author) if getattr(obj, "author", None) else "",
            "pt_single": getattr(obj._meta, "verbose_name", "").title(),
            "pt_plural": getattr(obj._meta, "verbose_name_plural", "").title(),
            "id": str(getattr(obj, "wp_id", None) or obj.pk),
        }

    def _excerpt_var(self, obj):
        raw = getattr(obj, "excerpt", "") or getattr(obj, "short_description", "")
        if raw:
            return _plain(raw)
        text = _plain(strip_shortcodes(_content(obj)))
        return Truncator(text).words(55, truncate="")

    def reading_time(self, obj):
        """Yoast estimated reading time: the stored editor value while the object is unchanged
        since import, else round(words / 200)."""
        meta = SeoMeta.for_object(obj)
        modified = getattr(obj, "modified_at", None)
        if meta and meta.estimated_reading_time is not None and (
                meta.source_modified is None or modified is None or meta.source_modified == modified):
            return meta.estimated_reading_time
        return php_round(php_str_word_count(strip_all_tags(_content(obj))) / 200)

    def _auto_excerpt(self, obj):
        """get_the_excerpt() stripped of tags, as Yoast's og:description fallback."""
        manual = getattr(obj, "excerpt", None)
        if manual is None:
            manual = getattr(obj, "short_description", "")
        if manual:
            return strip_all_tags(strip_shortcodes(manual))
        raw = _content(obj)
        if not raw:
            return ""
        from apps.core.wp_format import wpautop, wptexturize
        if "[" not in raw and getattr(obj, "content_rendered", ""):
            rendered = obj.content_rendered
        else:
            rendered = wptexturize(wpautop(strip_shortcodes(raw)))
        text = strip_all_tags(rendered)
        words = [w for w in re.split(r"[\n\r\t ]+", text) if w]
        if len(words) > 55:
            from apps.core.wp_format import wptexturize
            title = texturize_title(obj.title)
            return " ".join(words[:55]) + f' &hellip; Continue reading "{title}"'
        return " ".join(words)

    def _first_content_image(self, obj):
        """(absolute src, Media or None) of the first <img> in the content."""
        m = re.search(r"<img\s[^>]*?src\s*=\s*[\"']([^\"']+)[\"']", _content(obj), re.I)
        if not m:
            return None
        src = absolute(html.unescape(m.group(1)))
        return src, _media_for_url(src)

    # --- archives -------------------------------------------------------------------
    def archive(self, *, kind, url, name, term=None, template_key=None, fallback="term",
                page_type="CollectionPage", crumbs=None, noindex=False, extra_values=None,
                first_item=None, og_type=None):
        """Generic archive. With ``term`` (or fallback="term") this is Yoast's term archive;
        fallback="archive" / a title-ptarchive-* key is a post type archive; fallback="author"
        and fallback="date" map to author()/date_archive()-style output."""
        if fallback == "author" or page_type == "ProfilePage":
            user = _user_for_author_url(url)
            if user is not None:
                return self.author(user, url, first_item=first_item)
        values = {"term_title": name, "pt_plural": name, "name": name, "date": name, **(extra_values or {})}
        is_pt_archive = fallback == "archive" or (template_key or "").startswith("title-ptarchive-")
        if term is not None and getattr(term, "seo_title", ""):
            title = self.replace_vars(term.seo_title, **values)
        else:
            key = template_key or (f"title-ptarchive-{kind}" if is_pt_archive else f"title-tax-{kind}")
            title = self.replace_vars(self.template(key, fallback if fallback in DEFAULT_TITLES else "term"), **values)
        if term is not None and getattr(term, "seo_description", ""):
            desc_tpl = term.seo_description
        elif template_key:
            desc_tpl = self.settings.title_templates.get(template_key.replace("title-", "metadesc-"), "")
        elif is_pt_archive:
            desc_tpl = self.settings.title_templates.get(f"metadesc-ptarchive-{kind}", "")
        else:
            desc_tpl = self.settings.title_templates.get(f"metadesc-tax-{kind}", "")
        desc = strip_all_tags(self.replace_vars(desc_tpl, **values))
        base = absolute((term.canonical_url if term is not None and getattr(term, "canonical_url", "") else "") or url)
        data = self._data(title=title, description=desc, canonical=absolute(self._paged(base)), og_url=base)
        term_noindex = term is not None and getattr(term, "noindex", False)
        data.robots = ROBOTS_NOINDEX if (noindex or term_noindex) else ROBOTS_INDEX
        if og_type:
            data.og_type = og_type
        elif fallback == "author":
            data.og_type = "profile"
        elif is_pt_archive or fallback == "date":
            data.og_type = "website"
        else:
            data.og_type = "article"
        data.og_title = title
        if term is not None and getattr(term, "og_title", ""):
            data.og_title = self.replace_vars(term.og_title, **values)
        data.og_description = desc
        if term is not None and getattr(term, "og_description", ""):
            data.og_description = self.replace_vars(term.og_description, **values)
        if not data.og_description and term is not None and not is_pt_archive:
            data.og_description = strip_all_tags(getattr(term, "description", "") or "")
        if term is not None and getattr(term, "og_image", None):
            data.og_image = _og_image_from_media(term.og_image)
        self._adjacent(data, base)
        data.breadcrumbs = crumbs or [(self.settings.breadcrumbs_home, "/"), (name, None)]
        if self.page_number > 1:
            data.breadcrumbs = [*data.breadcrumbs, (f"Page {self.page_number}", None)]
        if first_item is None:
            first_item = self._guess_first_item(kind, term, is_pt_archive)
        data.graph = self._collection_graph(data, page_type, base, first_item)
        return data

    def _guess_first_item(self, kind, term, is_pt_archive):
        """The first post WordPress's main query lists (date DESC), when the view didn't say."""
        from django.apps import apps as django_apps
        models = {"post": "blog.Post", "news": "news.News", "nebosh_course": "courses.NeboshCourse",
                  "safety_course": "courses.SafetyCourse"}
        qs = None
        try:
            if is_pt_archive and kind in models:
                qs = django_apps.get_model(models[kind]).objects.published()
            elif term is not None:
                for rel in ("posts", "news", "courses"):
                    if hasattr(term, rel):
                        qs = getattr(term, rel).published()
                        break
        except LookupError:
            return None
        if qs is None:
            return None
        per_page = self.options.posts_per_page or 10
        offset = (self.page_number - 1) * per_page
        return qs.select_related("featured_image").order_by("-published_at")[offset:offset + 1].first()

    def post_type_archive(self, post_type, url, name, *, first_item=None, crumbs=None):
        return self.archive(kind=post_type, url=url, name=name, fallback="archive",
                            template_key=f"title-ptarchive-{post_type}", first_item=first_item, crumbs=crumbs)

    def term_archive(self, term, url=None, *, first_item=None, crumbs=None):
        return self.archive(kind=term.seo_type, url=url or term.get_absolute_url(), name=term.name,
                            term=term, first_item=first_item, crumbs=crumbs)

    def date_archive(self, label, url, *, first_item=None):
        noindex = self.settings.noindex_date_archives
        return self.archive(kind="date", url=url, name=label, template_key="title-archive-wpseo",
                            fallback="date", noindex=noindex, og_type="website", first_item=first_item,
                            extra_values={"date": label},
                            crumbs=[(self.settings.breadcrumbs_home, "/"), (f"Archives for {label}", None)])

    def author(self, user, url, *, first_item=None, has_posts=None):
        from apps.blog.models import Post
        posts = Post.objects.published().filter(author=user)
        if has_posts is None:
            has_posts = posts.exists()
        if first_item is None:
            per_page = self.options.posts_per_page or 10
            offset = (self.page_number - 1) * per_page
            first_item = posts.select_related("featured_image").order_by("-published_at")[offset:offset + 1].first()
        name = _author_name(user)
        values = {"name": name}
        title = self.replace_vars(self.template("title-author-wpseo", "author"), **values)
        desc = strip_all_tags(self.replace_vars(self.settings.title_templates.get("metadesc-author-wpseo", ""), **values))
        base = absolute(url)
        data = self._data(title=title, description=desc, canonical=absolute(self._paged(base)), og_url=base)
        noindex = self.settings.noindex_empty_authors and not has_posts
        data.robots = ROBOTS_NOINDEX if noindex else ROBOTS_INDEX
        data.og_type = "profile"
        data.og_title = title
        data.og_description = desc
        if getattr(user, "email", ""):
            data.og_image = {"url": gravatar_url(user.email, 500)}
        self._adjacent(data, base)
        data.breadcrumbs = [(self.settings.breadcrumbs_home, "/"), (f"Archives for {name}", None)]
        if self.page_number > 1:
            data.breadcrumbs.append((f"Page {self.page_number}", None))
        data.graph = self._collection_graph(data, "ProfilePage", base, first_item, person=user)
        return data

    def search(self, phrase, *, first_item=None):
        title = self.replace_vars(self.template("title-search-wpseo", "search"), searchphrase=phrase)
        data = self._data(title=title, robots=ROBOTS_NOINDEX, og_title=title, twitter_title=title)
        data.canonical = ""
        data.og_type = "article"
        data.og_url = absolute(f"/search/{quote(phrase, safe='')}/") if phrase else ""
        data.breadcrumbs = [(self.settings.breadcrumbs_home, "/"), (f"You searched for {phrase}", None)]
        if self.page_number > 1:
            data.breadcrumbs.append((f"Page {self.page_number}", None))
        main_id = absolute("/") + "?s=" + quote(phrase, safe="")
        data.graph = self._collection_graph(data, ["CollectionPage", "SearchResultsPage"], main_id, first_item,
                                            url=main_id)
        return data

    def not_found(self):
        title = self.replace_vars(self.template("title-404-wpseo", "404"))
        data = self._data(title=title, robots=ROBOTS_NOINDEX, og_title=title, is_error=True, og_url="")
        data.breadcrumbs = [(self.settings.breadcrumbs_home, "/"), ("Error 404: Page not found", None)]
        data.graph = [self._website()]
        return data

    # --- helpers --------------------------------------------------------------------
    def _adjacent(self, data, base):
        if self.page_number > 1:
            data.prev = absolute(self._paged(base, self.page_number - 1))
        if self.page_number < self.total_pages:
            data.next = absolute(self._paged(base, self.page_number + 1))

    def crumbs_for(self, obj, is_front=False):
        home = (self.settings.breadcrumbs_home, "/")
        if is_front:
            return [(self.settings.breadcrumbs_home, None)]
        chain = []
        kind = obj.seo_type
        if kind == "product":
            chain.append(("Shop", "/shop/"))
        elif kind in ("news", "nebosh_course", "safety_course", "testimonials"):
            label = {"news": "News", "nebosh_course": "NEBOSH Courses", "safety_course": "Safety Courses",
                     "testimonials": "Testimonials"}[kind]
            chain.append((label, f"/blog/{kind}/"))
        parent = getattr(obj, "parent", None)
        parents = []
        while parent is not None:
            parents.insert(0, (parent.breadcrumb_title or parent.title, parent.get_absolute_url()))
            parent = parent.parent
        chain.extend(parents)
        return [home, *chain, (getattr(obj, "breadcrumb_title", "") or obj.title, None)]

    def _schema_crumbs(self, crumbs, *, is_front=False, posts_page=False, simple_page=False):
        crumbs = list(crumbs)
        if self.page_number > 1 and not posts_page and len(crumbs) > 1:
            crumbs.pop()
        if not crumbs:
            return []
        crumbs[-1] = (crumbs[-1][0], None)
        if is_front and len(crumbs) > 1:
            crumbs = [(crumbs[0][0], None)]
        return crumbs

    def _website(self):
        data = {
            "@type": "WebSite",
            "@id": absolute("/") + "#website",
            "url": absolute("/"),
            "name": self.options.site_name,
            "description": self.options.tagline,
        }
        if self.settings.company_name:
            data["publisher"] = {"@id": absolute("/") + "#organization"}
        data["potentialAction"] = [{
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": absolute("/") + "?s={search_term_string}"},
            "query-input": {"@type": "PropertyValueSpecification", "valueRequired": True,
                            "valueName": "search_term_string"},
        }]
        data["inLanguage"] = LANGUAGE
        return data

    def _organization(self):
        s = self.settings
        if not s.company_name:
            return None
        org = {"@type": "Organization", "@id": absolute("/") + "#organization", "name": s.company_name,
               "url": absolute("/")}
        if s.company_logo:
            logo = self._image_from_media(s.company_logo, absolute("/") + "#/schema/logo/image/", suffix="")
            logo["caption"] = s.company_name
            org["logo"] = logo
            org["image"] = {"@id": absolute("/") + "#/schema/logo/image/"}
        if s.social_profiles:
            org["sameAs"] = list(s.social_profiles)
        return org

    def _breadcrumb_list(self, canonical, crumbs):
        items = []
        for i, (name, link) in enumerate(crumbs, start=1):
            item = {"@type": "ListItem", "position": i, "name": smart_strip_tags(texturize_title(name))}
            if link:
                item["item"] = absolute(link)
            items.append(item)
        return {"@type": "BreadcrumbList", "@id": canonical + "#breadcrumb", "itemListElement": items}

    def _image_from_media(self, media, page_url, suffix="#primaryimage"):
        url = absolute(media.url)
        data = {"@type": "ImageObject", "inLanguage": LANGUAGE, "@id": page_url + suffix, "url": url,
                "contentUrl": url}
        w, h = media.width, media.height
        if w and h:
            data["width"] = w
            data["height"] = h
        caption = getattr(media, "caption", "") or getattr(media, "alt", "")
        if caption:
            data["caption"] = smart_strip_tags(caption)
        return data

    def _image_from_url(self, url, page_url, media=None):
        if media is not None:
            return self._image_from_media(media, page_url)
        return {"@type": "ImageObject", "inLanguage": LANGUAGE, "@id": page_url + "#primaryimage", "url": url,
                "contentUrl": url}

    def person_id(self, user):
        meta = SeoMeta.for_object(user)
        digest = meta.person_schema_id if meta and meta.person_schema_id else hashlib.md5(
            f"{user.get_username()}{getattr(getattr(user, 'author_profile', None), 'wp_id', None) or user.pk}".encode()
        ).hexdigest()
        return absolute("/") + "#/schema/person/" + digest

    def _person(self, user, *, main_entity=None, with_url=False):
        name = _author_name(user)
        data = {"@type": "Person", "@id": self.person_id(user), "name": smart_strip_tags(name)}
        if getattr(user, "email", ""):
            avatar = gravatar_url(user.email, 96)
            data["image"] = {"@type": "ImageObject", "inLanguage": LANGUAGE, "@id": avatar, "url": avatar,
                             "contentUrl": avatar, "caption": name}
        profile = getattr(user, "author_profile", None)
        if profile is not None and profile.bio:
            data["description"] = smart_strip_tags(profile.bio)
        if main_entity:
            data["mainEntityOfPage"] = {"@id": main_entity}
        if with_url and profile is not None:
            data["url"] = absolute(profile.get_absolute_url())
        return data

    def _graph(self, *, page_type, main_id, url, canonical, name, description, main_image, crumbs, obj,
               published, modified, is_front=False):
        graph = []
        kind = obj.seo_type
        author = getattr(obj, "author", None) if kind in ARTICLE_TYPES else None
        is_article = kind in ARTICLE_TYPES and author is not None
        if is_article:
            article = {
                "@type": "Article",
                "@id": canonical + "#article",
                "isPartOf": {"@id": main_id},
                "author": {"name": smart_strip_tags(_author_name(author)), "@id": self.person_id(author)},
                "headline": smart_strip_tags(obj.title or "No title"),
                "datePublished": _date(published),
            }
            if published and modified and modified > published:
                article["dateModified"] = _date(modified)
            article["mainEntityOfPage"] = {"@id": main_id}
            article["wordCount"] = yoast_word_count(getattr(obj, "content", ""), obj.title)
            comments_open = getattr(obj, "comment_status", "open") == "open"
            if comments_open:
                article["commentCount"] = int(getattr(obj, "comment_count", 0) or 0)
            if self.settings.company_name:
                article["publisher"] = {"@id": absolute("/") + "#organization"}
            if main_image:
                article["image"] = {"@id": canonical + "#primaryimage"}
                article["thumbnailUrl"] = main_image["url"]
            tags = [t.name for t in obj.tags.all()] if hasattr(obj, "tags") else []
            if tags:
                article["keywords"] = tags
            cats = [c.name for c in obj.categories.all() if c.name not in UNCATEGORISED] if hasattr(obj, "categories") else []
            if cats:
                article["articleSection"] = cats
            article["inLanguage"] = LANGUAGE
            if comments_open:
                article["potentialAction"] = [{"@type": "CommentAction", "name": "Comment",
                                               "target": [canonical + "#respond"]}]
            graph.append(article)
        page = {"@type": page_type, "@id": main_id, "url": url, "name": smart_strip_tags(name),
                "isPartOf": {"@id": absolute("/") + "#website"}}
        if is_front and self.settings.company_name:
            page["about"] = {"@id": absolute("/") + "#organization"}
        if main_image:
            page["primaryImageOfPage"] = {"@id": canonical + "#primaryimage"}
            page["image"] = {"@id": canonical + "#primaryimage"}
            page["thumbnailUrl"] = main_image.get("_thumb", main_image["url"])
        if published:
            page["datePublished"] = _date(published)
            if modified and modified > published:
                page["dateModified"] = _date(modified)
        if is_article and not self.settings.company_name:
            page["author"] = {"@id": self.person_id(author)}
        if description:
            page["description"] = smart_strip_tags(description)
        page["breadcrumb"] = {"@id": canonical + "#breadcrumb"}
        page["inLanguage"] = LANGUAGE
        is_collection = page_type == "CollectionPage" or (isinstance(page_type, list) and "CollectionPage" in page_type)
        if not is_collection:
            page["potentialAction"] = [{"@type": "ReadAction", "target": [canonical]}]
        graph.append(page)
        if main_image:
            graph.append({k: v for k, v in main_image.items() if k != "_thumb"})
        if crumbs:
            graph.append(self._breadcrumb_list(canonical, crumbs))
        graph.append(self._website())
        org = self._organization()
        if org:
            graph.append(org)
        if is_article:
            graph.append(self._person(author, with_url=True))
        return self._finalize(graph, page, allow_single=is_front)

    def _collection_graph(self, data, page_type, main_id, first_item, url=None, person=None):
        canonical = data.canonical
        url = url or canonical
        crumbs = self._schema_crumbs(data.breadcrumbs)
        main_image = None
        featured = _featured(first_item) if first_item is not None else None
        if featured:
            main_image = self._image_from_media(featured, canonical)
        page = {"@type": page_type, "@id": main_id, "url": url, "name": smart_strip_tags(data.title),
                "isPartOf": {"@id": absolute("/") + "#website"}}
        if main_image:
            page["primaryImageOfPage"] = {"@id": canonical + "#primaryimage"}
            page["image"] = {"@id": canonical + "#primaryimage"}
            page["thumbnailUrl"] = main_image["url"]
        if data.description:
            page["description"] = smart_strip_tags(data.description)
        page["breadcrumb"] = {"@id": canonical + "#breadcrumb"}
        page["inLanguage"] = LANGUAGE
        is_collection = page_type == "CollectionPage" or (isinstance(page_type, list) and "CollectionPage" in page_type)
        if not is_collection:
            page["potentialAction"] = [{"@type": "ReadAction", "target": [canonical]}]
        graph = [page]
        if main_image:
            graph.append(main_image)
        if crumbs:
            graph.append(self._breadcrumb_list(canonical, crumbs))
        graph.append(self._website())
        org = self._organization()
        if org:
            graph.append(org)
        if person is not None:
            graph.append(self._person(person, main_entity=main_id))
        return self._finalize(graph, page)

    def _finalize(self, graph, page, allow_single=False):
        """Schema_Generator::remove_empty_breadcrumb (not on the static front page)."""
        if allow_single:
            return graph
        for i, piece in enumerate(graph):
            if piece.get("@type") == "BreadcrumbList" and len(piece["itemListElement"]) == 1 and i != 0:
                del graph[i]
                page.pop("breadcrumb", None)
                break
        return graph


# ----------------------------------------------------------------------------- helpers
def _now():
    from django.utils import timezone
    return timezone.localtime()


def _plain(text):
    return re.sub(r"\s+", " ", strip_all_tags(text or "")).strip()


def _content(obj):
    if obj is None:
        return ""
    return getattr(obj, "content", None) if getattr(obj, "content", None) is not None else getattr(obj, "description", "") or ""


def _featured(obj):
    if obj is None:
        return None
    return getattr(obj, "featured_image", None) or getattr(obj, "image", None)


def effective_modified(obj, meta=None):
    """post_modified_gmt. Products' modified_at is auto_now (touched by every MMC sync), so use
    WordPress's imported date unless the product was synced since (synced_at)."""
    modified = getattr(obj, "modified_at", None)
    if not any(f.name == "published_at" for f in obj._meta.get_fields()):
        meta = meta or SeoMeta.for_object(obj)
        if meta and meta.source_modified:
            synced = getattr(obj, "synced_at", None)
            modified = max(meta.source_modified, synced) if synced else meta.source_modified
    return modified


def _published(obj):
    return getattr(obj, "published_at", None) or getattr(obj, "created_at", None)


def _wp_date(value):
    if not value:
        return ""
    from django.utils import timezone
    value = timezone.localtime(value)
    return f"{value.day} {value:%B %Y}"


OG_IMAGE_TYPES = {"image/jpeg", "image/gif", "image/png", "image/webp"}
OG_IMAGE_EXTENSIONS = {"jpeg", "jpg", "gif", "png", "webp"}


def _og_image_from_media(media):
    """Yoast only accepts jpeg/gif/png/webp as Open Graph images."""
    mime = media.mime_type or ""
    ext = (media.file.name.rsplit(".", 1)[-1] if media.file else "").lower()
    if (mime and mime not in OG_IMAGE_TYPES) or (not mime and ext not in OG_IMAGE_EXTENSIONS):
        return None
    w, h = media.width, media.height
    return {"url": absolute(media.url), "width": w, "height": h, "type": media.mime_type}


def _media_for_url(url):
    from apps.core.models import Media
    path = re.sub(r"^https?://[^/]+", "", url)
    prefix = settings.MEDIA_URL
    if not path.startswith(prefix):
        return None
    name = path[len(prefix):]
    media = Media.objects.filter(file=name).first()
    if media is None:
        stripped = re.sub(r"-\d+x\d+\.(jpeg|jpg|png|gif)$", r".\1", name)
        if stripped != name:
            media = Media.objects.filter(file=stripped).first()
    return media


def _user_for_author_url(url):
    from apps.blog.models import AuthorProfile
    m = re.search(r"/author/([^/]+)/", url or "")
    profile = AuthorProfile.objects.select_related("user").filter(nicename=m.group(1)).first() if m else None
    return profile.user if profile else None


def _author_name(user):
    profile = getattr(user, "author_profile", None)
    return profile.display_name if profile else (user.get_full_name() or user.get_username())


def truncate_words(text, n):
    return Truncator(text).words(n)
