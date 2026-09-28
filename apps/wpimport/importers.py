"""Import functions: WordPress database → Django models. All idempotent (upsert on wp_id)."""
import json
import re
import shutil
import subprocess
import ipaddress
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from apps.blog.models import AuthorProfile, Category, Post, Tag
from apps.catalog.models import Product, ProductCategory, ProductTag
from apps.contact.forms import FORMS
from apps.contact.models import ContactForm, Submission
from apps.core.models import AccreditationLogo, Media, Redirect, SiteOptions, SocialLink
from apps.courses.models import NeboshCourse, NeboshCourseTerm, SafetyCourse, SafetyCourseTerm
from apps.exampapers.models import DropdownOption, ExamPaper
from apps.mmc.models import MMCSettings
from apps.navigation.models import Menu, MenuItem
from apps.news.models import News, NewsCategory
from apps.orders.models import Delegate, MMCBooking, Order, OrderFee, OrderItem, OrderNote
from apps.pages.models import Page
from apps.seo.models import SeoSettings

from .wp import WordPress, gmt_datetime, unserialize

# Lorem-ipsum placeholders and drafts that are not carried over.
SKIP_NEWS_IDS = {49, 52, 68, 70, 72, 495, 496}
UPLOAD_EXCLUDES = {"wc-logs", "mmc-logs", "ao_ccss", "woocommerce_uploads", "wpcf7_uploads", "_notes", "fonts", "cache"}

PAGE_TEMPLATES = {
    "page-templates/front-page.php": Page.Template.FRONT,
    "page-only.php": Page.Template.PAGE_ONLY,
    "page-api.php": Page.Template.API,
    "page-templates/nvq-level-page.php": Page.Template.NVQ_LEVEL,
    "page-templates/nebosh-distance-learning.php": Page.Template.NEBOSH_DL,
    "page-templates/category-page.php": Page.Template.CATEGORY,
}
# functions.php template_include forces page-only.php for this page.
FORCED_PAGE_TEMPLATES = {"certificate-in-fire-safety": Page.Template.PAGE_ONLY}


def log(msg):
    print(msg, flush=True)


def rewrite_urls(html):
    """Make links to the old site relative."""
    if not html:
        return html or ""
    for base in settings.WP_OLD_URLS:
        base = base.rstrip("/")
        html = html.replace(base + "/", "/").replace(base.replace("/", "\\/") + "\\/", "\\/")
        if html.endswith(base):
            html = html[: -len(base)] + "/"
    return html.replace('href="http://localhost/sst"', 'href="/"')


def to_decimal(value):
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def to_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def yoast_fields(meta):
    """Map Yoast postmeta/termmeta to SeoFields kwargs."""
    return {
        "seo_title": meta.get("_yoast_wpseo_title") or "",
        "seo_description": meta.get("_yoast_wpseo_metadesc") or "",
        "focus_keyword": meta.get("_yoast_wpseo_focuskw") or "",
        "canonical_url": meta.get("_yoast_wpseo_canonical") or "",
        "noindex": meta.get("_yoast_wpseo_meta-robots-noindex") == "1",
        "og_title": meta.get("_yoast_wpseo_opengraph-title") or "",
        "og_description": meta.get("_yoast_wpseo_opengraph-description") or "",
        "og_image": media_by_wp_id(meta.get("_yoast_wpseo_opengraph-image-id")),
        "breadcrumb_title": meta.get("_yoast_wpseo_bctitle") or "",
    }


def yoast_term_fields(meta):
    return {
        "seo_title": meta.get("wpseo_title") or "",
        "seo_description": meta.get("wpseo_desc") or "",
        "focus_keyword": meta.get("wpseo_focuskw") or "",
        "canonical_url": meta.get("wpseo_canonical") or "",
        "noindex": meta.get("wpseo_noindex") == "noindex",
        "og_title": meta.get("wpseo_opengraph-title") or "",
        "og_description": meta.get("wpseo_opengraph-description") or "",
        "breadcrumb_title": meta.get("wpseo_bctitle") or "",
    }


_media_cache = {}


def media_by_wp_id(wp_id):
    try:
        wp_id = int(wp_id)
    except (TypeError, ValueError):
        return None
    if wp_id not in _media_cache:
        _media_cache[wp_id] = Media.objects.filter(wp_id=wp_id).first()
    return _media_cache[wp_id]


def resolve_images(value):
    """Replace ACF image ids (strings of digits) inside nested ACF data with media URLs+ids."""
    if isinstance(value, list):
        return [resolve_images(v) for v in value]
    if isinstance(value, dict):
        return {k: resolve_images(v) for k, v in value.items()}
    if isinstance(value, str):
        return rewrite_urls(value)
    return value


# ------------------------------------------------------------------------------------ media
def import_media(wp: WordPress, copy_files=True):
    uploads = Path(settings.WP_ROOT) / "wp-content" / "uploads"
    dest = Path(settings.MEDIA_ROOT)
    if copy_files:
        dest.mkdir(parents=True, exist_ok=True)
        for item in uploads.iterdir():
            if item.name in UPLOAD_EXCLUDES or item.suffix in (".log", ".php"):
                continue
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True,
                                ignore=lambda d, n: [x for x in n if x in UPLOAD_EXCLUDES or x.endswith((".log", ".php"))])
            else:
                shutil.copy2(item, target)
        log(f"Copied uploads to {dest}")

    rows = wp.posts("attachment", statuses=("inherit", "publish", "private"))
    meta = wp.postmeta([r["ID"] for r in rows])
    count = 0
    for r in rows:
        m = meta.get(r["ID"], {})
        path = m.get("_wp_attached_file")
        if not path:
            continue
        info = unserialize(m.get("_wp_attachment_metadata")) or {}
        folder = str(Path(path).parent).replace("\\", "/")
        sizes = {}
        for name, s in (info.get("sizes") or {}).items() if isinstance(info, dict) else []:
            sizes[name] = {"file": f"{folder}/{s['file']}" if folder != "." else s["file"],
                           "width": s.get("width"), "height": s.get("height")}
        Media.objects.update_or_create(wp_id=r["ID"], defaults={
            "file": path,
            "title": r["post_title"],
            "alt": m.get("_wp_attachment_image_alt") or "",
            "caption": r["post_excerpt"] or "",
            "width": info.get("width") if isinstance(info, dict) else None,
            "height": info.get("height") if isinstance(info, dict) else None,
            "mime_type": r["post_mime_type"] or "",
            "sizes": sizes,
            "uploaded_at": gmt_datetime(r["post_date_gmt"]) or gmt_datetime(r["post_date"]),
        })
        count += 1
    _media_cache.clear()
    log(f"Media: {count}")


# ---------------------------------------------------------------------------------- options
def import_options(wp: WordPress):
    raw = wp.options_like("%options_%")
    acf = wp.acf_values({k: v for k, v in raw.items()}, "options_")
    opts = SiteOptions.load()
    opts.site_name = wp.option("blogname") or opts.site_name
    opts.tagline = wp.option("blogdescription") or opts.tagline
    opts.company_name = acf.get("company_name") or ""
    opts.main_logo = media_by_wp_id(acf.get("main_logo"))
    opts.address = acf.get("address") or ""
    opts.google_map_link = acf.get("google_map_link") or ""
    opts.main_email_address = acf.get("main_email_address") or ""
    opts.main_telephone_number = acf.get("main_telephone_number") or ""
    opts.banner_message = acf.get("banner_message") or ""
    opts.about_us = acf.get("about_us_textarea") or ""
    opts.nebosh_about = acf.get("nebosh_about") or ""
    opts.safety_about = acf.get("safety_about") or ""
    opts.special_offer = acf.get("special_offer") or ""
    opts.page_404_image = media_by_wp_id(acf.get("404_page_image"))
    opts.page_404_message = acf.get("404_page_message") or ""
    opts.enable_sidebar_on_posts = acf.get("enable_sidebar_on_posts") == "yes"
    opts.enable_sidebar_on_pages = acf.get("enable_sidebar_on_pages") == "yes"
    opts.posts_per_page = int(wp.option("posts_per_page") or 16)
    opts.save()
    opts.social_links.all().delete()
    for i, s in enumerate(acf.get("social_media") or []):
        SocialLink.objects.create(options=opts, type=s.get("social_media_type") or "", handle=s.get("social_media_handle") or "",
                                  link=s.get("social_media_link") or "", order=i)
    opts.accreditation_logos.all().delete()
    for i, a in enumerate(acf.get("accreditations__associated_logos") or []):
        AccreditationLogo.objects.create(options=opts, image=media_by_wp_id(a.get("image")),
                                         link=a.get("link_if_applicable") or "", order=i)

    # Yoast
    titles = wp.option("wpseo_titles") or {}
    social = wp.option("wpseo_social") or {}
    seo = SeoSettings.load()
    seo.separator = {"sc-dash": "-", "sc-ndash": "–", "sc-mdash": "—", "sc-pipe": "|", "sc-middot": "·",
                     "sc-bull": "•", "sc-star": "*", "sc-tilde": "~", "sc-laquo": "«", "sc-raquo": "»",
                     "sc-lt": "<", "sc-gt": ">"}.get(titles.get("separator"), "-")
    seo.title_templates = {k: v for k, v in titles.items()
                           if isinstance(v, str) and k.startswith(("title-", "metadesc-", "social-title-", "social-description-"))}
    seo.breadcrumbs_home = titles.get("breadcrumbs-home") or "Home"
    seo.breadcrumbs_sep = titles.get("breadcrumbs-sep") or "/"
    seo.breadcrumbs_bold_last = bool(titles.get("breadcrumbs-boldlast", True))
    seo.noindex_date_archives = bool(titles.get("noindex-archive-wpseo", True))
    seo.noindex_empty_authors = bool(titles.get("noindex-author-noposts-wpseo", True))
    seo.company_name = titles.get("company_name") or ""
    seo.company_logo = media_by_wp_id(titles.get("company_logo_id"))
    seo.social_profiles = [u for u in [social.get("facebook_site"), *(social.get("other_social_urls") or [])] if u]
    seo.og_default_image = media_by_wp_id(social.get("og_default_image_id"))
    seo.twitter_card = social.get("twitter_card_type") or "summary_large_image"
    seo.save()

    # MMC (secrets are never imported)
    s = wp.option("tz_mmc_wc_settings") or {}
    mmc = MMCSettings.load()
    mmc.title_format = s.get("title_format") or mmc.title_format
    mmc.sku_format = s.get("sku_format") or mmc.sku_format
    mmc.future_only = bool(int(s.get("future_only", 1) or 0))
    mmc.auto_delete_past = bool(int(s.get("auto_delete_past", 1) or 0))
    mmc.closed_session_behaviour = s.get("closed_session_behaviour") or "draft"
    mmc.price_sync_mode = s.get("price_sync_mode") or "auto"
    mmc.error_notification_email = s.get("error_notification_email") or ""
    mmc.allowed_venues = wp.option("tz_mmc_wc_allowed_venues") or []
    mmc.allowed_course_types = wp.option("tz_mmc_wc_allowed_course_types") or []
    mmc.allowed_course_refs = wp.option("tz_mmc_wc_allowed_course_refs") or []
    mmc.venue_list = wp.option("tz_mmc_wc_venue_list") or []
    mmc.course_ref_list = wp.option("tz_mmc_wc_course_ref_list") or []
    nvq = wp.option("tz_mmc_wc_nvq_settings") or {}
    mmc.nvq_settings = {k: {"enabled": str(v.get("enabled")) == "1", "price_mode": v.get("price_mode") or "full"}
                        for k, v in nvq.items()} if isinstance(nvq, dict) else {}
    mapping = wp.option("tz_mmc_wc_attribute_mapping") or {}
    mmc.attribute_mapping = [{"field": f, "label": v.get("label") or f, "enabled": bool(v.get("enabled")),
                              "visible": bool(v.get("visible"))} for f, v in mapping.items()]
    ds = wp.option("tz_mmc_wc_delegate_settings") or {}
    mmc.delegate_settings = {
        "enable_capture": bool(ds.get("enable_capture", 1)),
        "enforce_quantity": bool(ds.get("enforce_quantity", 1)),
        "position": ds.get("position") or "after_order_notes",
        "fields": {k: {"label": v.get("label"), "enabled": bool(v.get("enabled")), "required": bool(v.get("required"))}
                   for k, v in (ds.get("fields") or {}).items()},
    }
    mmc.save()

    # Exam papers dropdowns
    epm = wp.option("sst_epm_dropdown_options") or {}
    for group, conf in (epm.items() if isinstance(epm, dict) else []):
        for i, (key, label) in enumerate((conf.get("items") or {}).items()):
            DropdownOption.objects.update_or_create(group=group, key=key, defaults={"label": label, "order": i})
    log("Options, SEO, MMC settings imported")


# ------------------------------------------------------------------------------------ terms
def _import_tree(wp, taxonomy, model, extra=None, yoast=None):
    rows = wp.terms(taxonomy)
    meta = wp.termmeta([r["term_id"] for r in rows])
    yoast = yoast or {}
    by_wp = {}
    # parents first
    pending = list(rows)
    while pending:
        progressed = False
        for r in list(pending):
            if r["parent"] and r["parent"] not in by_wp:
                continue
            defaults = {"name": r["name"], "slug": r["slug"], "description": rewrite_urls(r["description"] or "")}
            if hasattr(model, "parent"):
                defaults["parent"] = by_wp.get(r["parent"])
            defaults.update(yoast_term_fields(yoast.get(r["term_id"], {})))
            if extra:
                defaults.update(extra(r, meta.get(r["term_id"], {})))
            obj, _ = model.objects.update_or_create(wp_id=r["term_id"], defaults=defaults)
            by_wp[r["term_id"]] = obj
            pending.remove(r)
            progressed = True
        if not progressed:
            break
    if hasattr(model, "_tree_manager"):
        model._tree_manager.rebuild()
    log(f"{taxonomy}: {len(by_wp)}")
    return by_wp


def import_terms(wp: WordPress):
    tax_meta = wp.option("wpseo_taxonomy_meta") or {}

    def yoast_for(tax):
        return {int(k): v for k, v in (tax_meta.get(tax) or {}).items()} if isinstance(tax_meta, dict) else {}

    def acf_term(r, m):
        return {"acf": resolve_images(wp.acf_values(m))}

    _import_tree(wp, "category", Category, yoast=yoast_for("category"))
    tags = wp.terms("post_tag")
    for r in tags:
        Tag.objects.update_or_create(wp_id=r["term_id"], defaults={
            "name": r["name"], "slug": r["slug"], "description": r["description"] or "",
            **yoast_term_fields(yoast_for("post_tag").get(r["term_id"], {}))})
    _import_tree(wp, "news_categories", NewsCategory, extra=acf_term, yoast=yoast_for("news_categories"))
    _import_tree(wp, "nebosh_courses", NeboshCourseTerm, extra=acf_term, yoast=yoast_for("nebosh_courses"))
    _import_tree(wp, "safety_courses", SafetyCourseTerm, extra=acf_term, yoast=yoast_for("safety_courses"))

    def product_cat(r, m):
        return {"thumbnail": media_by_wp_id(m.get("thumbnail_id")), "menu_order": int(m.get("order") or 0)}

    _import_tree(wp, "product_cat", ProductCategory, extra=product_cat, yoast=yoast_for("product_cat"))
    for r in wp.terms("product_tag"):
        ProductTag.objects.update_or_create(wp_id=r["term_id"], defaults={
            "name": r["name"], "slug": r["slug"], "description": r["description"] or "",
            **yoast_term_fields(yoast_for("product_tag").get(r["term_id"], {}))})


# ---------------------------------------------------------------------------------- authors
def import_users(wp: WordPress):
    User = get_user_model()
    users = {}
    for r in wp.query("SELECT ID, user_login, user_email, user_nicename, display_name FROM {p}users"):
        meta = {m["meta_key"]: m["meta_value"] for m in wp.query(
            "SELECT meta_key, meta_value FROM {p}usermeta WHERE user_id=%s AND meta_key IN ('first_name','last_name','description')",
            [r["ID"]])}
        user, created = User.objects.get_or_create(username=r["user_login"], defaults={"email": r["user_email"]})
        if created:
            user.set_unusable_password()
        user.first_name = meta.get("first_name") or ""
        user.last_name = meta.get("last_name") or ""
        user.save()
        AuthorProfile.objects.update_or_create(user=user, defaults={
            "wp_id": r["ID"], "nicename": r["user_nicename"], "display_name": r["display_name"],
            "bio": meta.get("description") or ""})
        users[r["ID"]] = user
    log(f"Users: {len(users)}")
    return users


# ---------------------------------------------------------------------------------- content
def upsert_content(model, wp_id, defaults):
    """update_or_create that keeps the imported modified date (Content.save stamps now otherwise)."""
    obj = model.objects.filter(wp_id=wp_id).first() or model(wp_id=wp_id)
    for key, value in defaults.items():
        setattr(obj, key, value)
    obj.save(keep_modified=True)
    return obj, True


def _content_defaults(r, m, users, wp):
    status = {"publish": "publish", "private": "private"}.get(r["post_status"], "draft")
    acf = resolve_images(wp.acf_values(m))
    return {
        "title": r["post_title"],
        "slug": r["post_name"] or slugify(r["post_title"]),
        "status": status,
        "content": rewrite_urls(r["post_content"]),
        "excerpt": rewrite_urls(r["post_excerpt"]),
        "featured_image": media_by_wp_id(m.get("_thumbnail_id")),
        "author": users.get(r["post_author"]),
        "acf": acf,
        "published_at": gmt_datetime(r["post_date_gmt"]) or gmt_datetime(r["post_date"]),
        "modified_at": gmt_datetime(r["post_modified_gmt"]) or gmt_datetime(r["post_modified"]),
        "menu_order": r["menu_order"] or 0,
        **yoast_fields(m),
    }


def import_content(wp: WordPress):
    users = import_users(wp)
    front_id = int(wp.option("page_on_front") or 0)
    posts_page_id = int(wp.option("page_for_posts") or 0)

    # Pages (parents first)
    rows = wp.posts("page", statuses=("publish", "private", "draft"))
    meta = wp.postmeta([r["ID"] for r in rows])
    cat_by_slug = {c.slug: c for c in ProductCategory.objects.all()}
    pages = {}
    for r in sorted(rows, key=lambda x: (x["post_parent"] != 0, x["ID"])):
        m = meta.get(r["ID"], {})
        d = _content_defaults(r, m, users, wp)
        template = FORCED_PAGE_TEMPLATES.get(r["post_name"]) or PAGE_TEMPLATES.get(m.get("_wp_page_template") or "", Page.Template.DEFAULT)
        if r["ID"] == front_id:
            template = Page.Template.FRONT
        d.update({
            "template": template,
            "parent": pages.get(r["post_parent"]),
            "course_category": cat_by_slug.get(m.get("_course_category") or ""),
            "is_front_page": r["ID"] == front_id,
            "is_posts_page": r["ID"] == posts_page_id,
        })
        pages[r["ID"]], _ = upsert_content(Page, r["ID"], d)
    log(f"Pages: {len(pages)}")

    # Posts
    rows = wp.posts("post", statuses=("publish", "private", "draft", "future"))
    meta = wp.postmeta([r["ID"] for r in rows])
    cats = wp.object_terms("category")
    tags = wp.object_terms("post_tag")
    cat_map = {c.wp_id: c for c in Category.objects.all()}
    tag_map = {t.wp_id: t for t in Tag.objects.all()}
    for r in rows:
        m = meta.get(r["ID"], {})
        post, _ = upsert_content(Post, r["ID"], _content_defaults(r, m, users, wp))
        post.categories.set([cat_map[t] for t in cats.get(r["ID"], []) if t in cat_map])
        post.tags.set([tag_map[t] for t in tags.get(r["ID"], []) if t in tag_map])
        primary = m.get("_yoast_wpseo_primary_category")
        post.primary_category = cat_map.get(int(primary)) if primary and primary.isdigit() else None
        post.save(update_fields=["primary_category"], keep_modified=True)
    log(f"Posts: {len(rows)}")

    def import_type(post_type, model, taxonomy, term_model, skip=()):
        rows = [r for r in wp.posts(post_type, statuses=("publish", "private", "draft")) if r["ID"] not in skip]
        meta = wp.postmeta([r["ID"] for r in rows])
        rel = wp.object_terms(taxonomy) if taxonomy else {}
        term_map = {t.wp_id: t for t in term_model.objects.all()} if term_model else {}
        for r in rows:
            obj, _ = upsert_content(model, r["ID"], _content_defaults(r, meta.get(r["ID"], {}), users, wp))
            if taxonomy:
                field = "categories" if hasattr(obj, "categories") else "terms"
                getattr(obj, field).set([term_map[t] for t in rel.get(r["ID"], []) if t in term_map])
        log(f"{post_type}: {len(rows)}")
        return rows

    import_type("news", News, "news_categories", NewsCategory, skip=SKIP_NEWS_IDS)
    import_type("nebosh_course", NeboshCourse, "nebosh_courses", NeboshCourseTerm)
    import_type("safety_course", SafetyCourse, "safety_courses", SafetyCourseTerm)

    rows = wp.posts("sst_exam_paper", statuses=("publish", "draft"))
    meta = wp.postmeta([r["ID"] for r in rows])
    for r in rows:
        m = meta.get(r["ID"], {})
        opt = lambda g, k: DropdownOption.objects.filter(group=g, key=m.get(k) or "").first()  # noqa: E731
        upsert_content(ExamPaper, r["ID"], {
            **_content_defaults(r, m, users, wp), "file_url": rewrite_urls(m.get("_sst_epm_file_url") or ""),
            "course": opt("course", "_sst_epm_course"), "level": opt("level", "_sst_epm_level"),
            "year": opt("year", "_sst_epm_year"), "paper_type": opt("paper_type", "_sst_epm_paper_type")})
    log(f"Exam papers: {len(rows)}")


def render_content():
    """Run WordPress's the_content filters through a PHP bridge so the markup is identical."""
    ids = {}
    for model in (Page, Post, News, NeboshCourse, SafetyCourse, ExamPaper):
        ids.update({o.wp_id: (model, o.pk) for o in model.objects.exclude(wp_id=None).only("wp_id")})
    script = Path(settings.BASE_DIR) / "tools" / "wp_render.php"
    proc = subprocess.run([settings.WP_PHP_BIN, str(script), settings.WP_ROOT], input=json.dumps(list(ids)),
                          capture_output=True, text=True, encoding="utf-8", timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"wp_render.php failed: {proc.stderr[-2000:]}")
    start = proc.stdout.find("{")
    data = json.loads(proc.stdout[start:])
    for wp_id, rendered in data.items():
        model, pk = ids[int(wp_id)]
        model.objects.filter(pk=pk).update(content_rendered=rewrite_urls(rendered["content"]))
    log(f"Rendered content: {len(data)}")


# --------------------------------------------------------------------------------- products
def import_products(wp: WordPress):
    rows = wp.posts("product", statuses=("publish", "draft", "private"))
    meta = wp.postmeta([r["ID"] for r in rows])
    cats = wp.object_terms("product_cat")
    tags = wp.object_terms("product_tag")
    cat_map = {c.wp_id: c for c in ProductCategory.objects.all()}
    tag_map = {t.wp_id: t for t in ProductTag.objects.all()}
    seen = []
    for r in rows:
        m = meta.get(r["ID"], {})
        attrs_raw = unserialize(m.get("_product_attributes")) or {}
        attrs = sorted(attrs_raw.values(), key=lambda a: int(a.get("position") or 0)) if isinstance(attrs_raw, dict) else []
        attributes = [{"name": a.get("name"), "value": a.get("value"), "visible": bool(a.get("is_visible"))} for a in attrs]
        by_name = {a["name"].lower(): a["value"] for a in attributes if a.get("name")}
        is_nvq = bool(m.get("_mmc_nvq_id"))
        kind = Product.Kind.NVQ if is_nvq else (Product.Kind.SESSION if m.get("_mmc_session_id") else Product.Kind.SIMPLE)
        manage = m.get("_manage_stock") == "yes"
        stock = m.get("_stock")
        product, _ = Product.objects.update_or_create(wp_id=r["ID"], defaults={
            "kind": kind,
            "title": r["post_title"],
            "slug": r["post_name"],
            "sku": m.get("_sku") or "",
            "status": "publish" if r["post_status"] == "publish" else "draft",
            "description": rewrite_urls(r["post_content"]),
            "short_description": rewrite_urls(r["post_excerpt"]),
            "regular_price": to_decimal(m.get("_regular_price")),
            "sale_price": to_decimal(m.get("_sale_price")),
            "taxable": (m.get("_tax_status") or "taxable") == "taxable",
            "manage_stock": manage,
            "stock_qty": int(float(stock)) if manage and stock not in (None, "") else None,
            "stock_status": m.get("_stock_status") or "instock",
            "virtual": m.get("_virtual") == "yes",
            "mmc_session_id": m.get("_mmc_session_id") or None,
            "mmc_nvq_id": m.get("_mmc_nvq_id") or None,
            "mmc_course_id": by_name.get("course id", ""),
            "mmc_venue_id": m.get("_mmc_venue_id") or by_name.get("venue id", "") or "",
            "price_mode": m.get("_mmc_price_mode") or "",
            "first_date": to_date(by_name.get("first date") or m.get("_mmc_session_date")),
            "last_date": to_date(by_name.get("last date")),
            "start_time": by_name.get("start time", ""),
            "venue_name": by_name.get("venue name") or m.get("_mmc_session_location") or "",
            "is_online": (by_name.get("is online") or "").lower() in ("yes", "1", "true"),
            "attributes": attributes,
            "created_at": gmt_datetime(r["post_date_gmt"]) or gmt_datetime(r["post_date"]),
            **yoast_fields(m),
        })
        product.categories.set([cat_map[t] for t in cats.get(r["ID"], []) if t in cat_map])
        product.tags.set([tag_map[t] for t in tags.get(r["ID"], []) if t in tag_map])
        seen.append(r["ID"])
    log(f"Products: {len(seen)}")


# ------------------------------------------------------------------------------------ menus
def import_menus(wp: WordPress):
    menus = wp.terms("nav_menu")
    rel = wp.object_terms("nav_menu")
    menu_by_term = {}
    for r in menus:
        menu, _ = Menu.objects.update_or_create(wp_id=r["term_id"], defaults={"name": r["name"], "slug": r["slug"]})
        menu_by_term[r["term_id"]] = menu
    items = wp.posts("nav_menu_item")
    meta = wp.postmeta([i["ID"] for i in items])
    item_menu = {}
    for obj_id, term_ids in rel.items():
        for t in term_ids:
            if t in menu_by_term:
                item_menu[obj_id] = menu_by_term[t]
    product_meta = wp.postmeta([int(meta[i["ID"]].get("_menu_item_object_id") or 0) for i in items
                                if meta.get(i["ID"], {}).get("_menu_item_object") == "product"])
    created = {}
    # Build respecting parents.
    pending = list(items)
    while pending:
        progressed = False
        for i in list(pending):
            m = meta.get(i["ID"], {})
            parent_id = int(m.get("_menu_item_menu_item_parent") or 0)
            if parent_id and parent_id not in created:
                if parent_id not in {p["ID"] for p in items}:
                    parent_id = 0
                else:
                    continue
            menu = item_menu.get(i["ID"])
            if not menu:
                pending.remove(i)
                continue
            item_type = m.get("_menu_item_type")
            obj = m.get("_menu_item_object")
            obj_id = int(m.get("_menu_item_object_id") or 0)
            fields = {"menu": menu, "parent": created.get(parent_id), "title": i["post_title"], "order": i["menu_order"],
                      "url": rewrite_urls(m.get("_menu_item_url") or ""),
                      "css_classes": " ".join(c for c in (unserialize(m.get("_menu_item_classes")) or []) if c),
                      "link_target": m.get("_menu_item_target") or "", "target_type": MenuItem.Target.CUSTOM,
                      "page": None, "product_category": None, "product": None, "product_mmc_nvq_id": "", "post": None, "category": None}
            if item_type == "post_type" and obj == "page":
                fields.update(target_type=MenuItem.Target.PAGE, page=Page.objects.filter(wp_id=obj_id).first())
            elif item_type == "post_type" and obj == "product":
                pm = product_meta.get(obj_id, {})
                fields.update(target_type=MenuItem.Target.PRODUCT, product=Product.objects.filter(wp_id=obj_id).first(),
                              product_mmc_nvq_id=pm.get("_mmc_nvq_id") or "")
            elif item_type == "post_type" and obj == "post":
                fields.update(target_type=MenuItem.Target.POST, post=Post.objects.filter(wp_id=obj_id).first())
            elif item_type == "taxonomy" and obj == "product_cat":
                fields.update(target_type=MenuItem.Target.PRODUCT_CATEGORY,
                              product_category=ProductCategory.objects.filter(wp_id=obj_id).first())
            elif item_type == "taxonomy" and obj == "category":
                fields.update(target_type=MenuItem.Target.CATEGORY, category=Category.objects.filter(wp_id=obj_id).first())
            item, _ = MenuItem.objects.update_or_create(wp_id=i["ID"], defaults=fields)
            created[i["ID"]] = item
            pending.remove(i)
            progressed = True
        if not progressed:
            break
    MenuItem._tree_manager.rebuild()
    log(f"Menus: {len(menu_by_term)}, items: {len(created)}")


# ------------------------------------------------------------------------------------ forms
def _parse_cf7_fields(form_markup):
    fields = []
    for m in re.finditer(r"\[([a-z]+)(\*?)\s+([\w-]+)", form_markup):
        kind, star, name = m.groups()
        if kind in ("submit", "honeypot", "recaptcha"):
            continue
        fields.append({"name": name, "type": kind, "required": star == "*"})
    return fields


def _check_cf7_fields(wp_id, form_markup):
    """Warn when the WordPress form's fields no longer match its Django form class."""
    form_class = FORMS.get(wp_id)
    if form_class is None:
        log(f"Contact form {wp_id}: no Django form class in apps/contact/forms.py; it will not be shown.")
        return
    wanted = [(f["name"], f["type"], f["required"]) for f in _parse_cf7_fields(form_markup)]
    have = [(name, field.kind, field.required) for name, field in form_class.base_fields.items()]
    if wanted != have:
        log(f"Contact form {wp_id}: WordPress fields {wanted} differ from {form_class.__name__} {have}.")


def import_forms(wp: WordPress):
    rows = wp.posts("wpcf7_contact_form")
    meta = wp.postmeta([r["ID"] for r in rows])
    forms = {}
    for r in rows:
        m = meta.get(r["ID"], {})
        mail = unserialize(m.get("_mail")) or {}
        messages = unserialize(m.get("_messages")) or {}
        form, _ = ContactForm.objects.update_or_create(wp_id=r["ID"], defaults={
            "title": r["post_title"],
            "recipient": mail.get("recipient") or "",
            "sender": "",
            "subject": mail.get("subject") or "",
            "body": mail.get("body") or "",
            "additional_headers": mail.get("additional_headers") or "",
            "messages": messages if isinstance(messages, dict) else {},
        })
        forms[r["post_title"]] = form
        _check_cf7_fields(r["ID"], m.get("_form") or "")
    # Contact Form DB submissions: one row per field, grouped by submit_time.
    subs = {}
    for row in wp.query("SELECT submit_time, form_name, field_name, field_value FROM {p}cf7dbplugin_submits ORDER BY submit_time, field_order"):
        key = (str(row["submit_time"]), row["form_name"])
        subs.setdefault(key, {})[row["field_name"]] = row["field_value"]
    Submission.objects.filter(imported=True).delete()
    batch = []
    for (ts, form_name), data in subs.items():
        submitted = datetime.fromtimestamp(float(ts), tz=gmt_datetime("2000-01-01 00:00:00").tzinfo)
        # CFDB's "Submitted From" holds the sender's IP, not the page.
        ip = data.pop("Submitted From", "").strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            ip = None
        data.pop("submit", None)
        data.pop("g-recaptcha-response", None)
        page_url = data.pop("_url", "")
        batch.append(Submission(form=forms.get(form_name), form_title=form_name, submitted_at=submitted,
                                page_url=page_url[:500], ip=ip, data=data, imported=True, mail_status="imported"))
    Submission.objects.bulk_create(batch)
    log(f"Forms: {len(forms)}, submissions: {len(batch)}")


# ----------------------------------------------------------------------------------- orders
def import_orders(wp: WordPress):
    has_hpos = wp.scalar("SHOW TABLES LIKE %s", [f"{settings.WP_TABLE_PREFIX}wc_orders"])
    if not has_hpos:
        log("Orders: no HPOS table")
        return
    orders = wp.query("SELECT * FROM {p}wc_orders WHERE type='shop_order'")
    for o in orders:
        addr = {a["address_type"]: a for a in wp.query("SELECT * FROM {p}wc_order_addresses WHERE order_id=%s", [o["id"]])}
        b = addr.get("billing", {})
        ometa = {m["meta_key"]: m["meta_value"] for m in wp.query(
            "SELECT meta_key, meta_value FROM {p}wc_orders_meta WHERE order_id=%s", [o["id"]])}
        pmeta = wp.postmeta([o["id"]]).get(o["id"], {})  # plugin wrote MMC meta to postmeta
        ometa = {**pmeta, **ometa}
        with transaction.atomic():
            order, _ = Order.objects.update_or_create(wp_id=o["id"], defaults={
                "status": (o["status"] or "wc-pending").replace("wc-", ""),
                "currency": o["currency"] or "GBP",
                "billing_first_name": b.get("first_name") or "", "billing_last_name": b.get("last_name") or "",
                "billing_company": b.get("company") or "", "billing_address_1": b.get("address_1") or "",
                "billing_address_2": b.get("address_2") or "", "billing_city": b.get("city") or "",
                "billing_state": b.get("state") or "", "billing_postcode": b.get("postcode") or "",
                "billing_country": b.get("country") or "GB", "billing_email": b.get("email") or o.get("billing_email") or "",
                "billing_phone": b.get("phone") or "", "customer_note": o.get("customer_note") or "",
                "tax_total": to_decimal(o["tax_amount"]) or 0, "total": to_decimal(o["total_amount"]) or 0,
                "payment_method": o["payment_method"] or "", "payment_method_title": o["payment_method_title"] or "",
                "stripe_payment_intent": ometa.get("_stripe_intent_id") or o.get("transaction_id") or "",
                "paid_at": gmt_datetime(o["date_updated_gmt"]) if o["status"] in ("wc-processing", "wc-completed") else None,
                "nebosh_dl": ometa.get("_sst_nebosh_dl") == "1",
                "mmc_bookings_sent": ometa.get("_tz_mmc_bookings_sent") == "1",
                "emails_sent": True, "customer_ip": o.get("ip_address") or None, "user_agent": (o.get("user_agent") or "")[:500],
            })
            Order.objects.filter(pk=order.pk).update(created_at=gmt_datetime(o["date_created_gmt"]))
            order.items.all().delete()
            order.fees.all().delete()
            delegates = unserialize(ometa.get("_tz_mmc_delegates")) or {}
            subtotal = Decimal("0")
            for it in wp.query("SELECT * FROM {p}woocommerce_order_items WHERE order_id=%s", [o["id"]]):
                im = {m["meta_key"]: m["meta_value"] for m in wp.query(
                    "SELECT meta_key, meta_value FROM {p}woocommerce_order_itemmeta WHERE order_item_id=%s", [it["order_item_id"]])}
                if it["order_item_type"] == "line_item":
                    product = Product.objects.filter(wp_id=int(im.get("_product_id") or 0)).first()
                    qty = int(im.get("_qty") or 1)
                    line_sub = to_decimal(im.get("_line_subtotal")) or Decimal("0")
                    subtotal += line_sub
                    item = OrderItem.objects.create(
                        order=order, product=product, name=it["order_item_name"], sku=product.sku if product else "",
                        mmc_session_id=product.mmc_session_id or "" if product else "",
                        mmc_nvq_id=product.mmc_nvq_id or "" if product else "",
                        unit_price=(line_sub / qty) if qty else line_sub, quantity=qty, line_subtotal=line_sub,
                        line_total=to_decimal(im.get("_line_total")) or line_sub, line_tax=to_decimal(im.get("_line_tax")) or 0)
                    group = next((g for g in (delegates.values() if isinstance(delegates, dict) else [])
                                  if isinstance(g, dict) and str(g.get("product_id")) == str(im.get("_product_id"))), None)
                    rows = (group or {}).get("delegates") or []
                    for idx, d in enumerate(rows if isinstance(rows, list) else list(rows.values())):
                        dl = Delegate.objects.create(item=item, index=idx, name=d.get("name") or "", email=d.get("email") or "",
                                                     phone=d.get("phone") or "")
                        if order.mmc_bookings_sent:
                            MMCBooking.objects.create(delegate=dl, status=MMCBooking.Status.SENT, attempts=1)
                elif it["order_item_type"] == "fee":
                    OrderFee.objects.create(order=order, name=it["order_item_name"],
                                            amount=to_decimal(im.get("_line_total")) or 0, tax=to_decimal(im.get("_line_tax")) or 0)
            order.subtotal = subtotal
            order.fee_total = sum((f.amount for f in order.fees.all()), Decimal("0"))
            order.save(update_fields=["subtotal", "fee_total"])
            order.notes.all().delete()
            for n in wp.query("SELECT comment_content, comment_date_gmt FROM {p}comments WHERE comment_post_ID=%s AND comment_type='order_note'",
                              [o["id"]]):
                note = OrderNote.objects.create(order=order, note=n["comment_content"])
                OrderNote.objects.filter(pk=note.pk).update(created_at=gmt_datetime(n["comment_date_gmt"]))
    log(f"Orders: {len(orders)}")


# -------------------------------------------------------------------------------- redirects
def build_redirects(wp: WordPress):
    rules = {"/sample-page/": "/", "/checkout/": "/checkout-2/", "/my-account/": "/", "/feed/": "/blog/",
             "/comments/feed/": "410", "/blog/testimonials/": "/"}
    for r in wp.posts("news", statuses=("publish",), ids=list(SKIP_NEWS_IDS)):
        rules[f"/blog/news/{r['post_name']}/"] = "/blog/news/"
    for r in wp.posts("testimonials"):
        rules[f"/blog/testimonials/{r['post_name']}/"] = "/"
    for old, new in rules.items():
        Redirect.objects.update_or_create(old_path=old, defaults={"new_path": new, "permanent": True})
    log(f"Redirects: {len(rules)}")
