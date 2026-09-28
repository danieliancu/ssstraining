"""Extra context for page templates that pull in other data (course lists, NVQs, front page)."""
import datetime
import re
from pathlib import Path

from django.conf import settings
from django.utils.safestring import mark_safe

from apps.core.models import Status

THEME_IMAGES = Path(settings.BASE_DIR) / "static" / "wp" / "wp-content" / "themes" / "twentyseventeen-child" / "assets" / "images"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def today():
    """current_time('Y-m-d') — the site's local date."""
    from django.utils import timezone
    return timezone.localdate()


def esc_html(text):
    """esc_html(): escapes markup but leaves existing entities alone (no double encoding)."""
    text = str(text or "")
    text = re.sub(r"&(?!#?\w+;)", "&amp;", text)
    return mark_safe(text.replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#039;"))


def _natsort_key(name):
    """PHP natsort(): case-sensitive natural order."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", name) if t]


def _image_files(folder):
    path = THEME_IMAGES / folder
    if not path.is_dir():
        return []
    files = [f.name for f in path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
             and f.suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}]  # glob braces are case-sensitive
    return sorted(files, key=_natsort_key)


def _logo(name):
    return {"file": name, "name": name.rsplit(".", 1)[0]}


# ------------------------------------------------------------------------------------ front page
DISTANCE_LEARNING_COURSES = [
    ("NEBOSH General Certificate", "/product-category/nebosh-general-certificate/"),
    ("NEBOSH Construction Certificate", "/product-category/nebosh-construction/"),
    ("Certificate in Fire Safety", "/certificate-in-fire-safety/"),
    ("Environmental Management Certificate", "/environmental-management-certificate/"),
]

TRAINING_CARD_SPECS = [
    ("CITB", ["CITB Courses", "CITB"], "https://images.unsplash.com/photo-1541888946425-d81bb19240f5?w=600&h=400&fit=crop"),
    ("IOSH", ["IOSH Courses", "IOSH"], "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=600&h=400&fit=crop"),
    ("NEBOSH", ["NEBOSH Courses", "NEBOSH"], "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?w=600&h=400&fit=crop"),
    ("Other Courses", ["Other Courses"], "https://images.unsplash.com/photo-1503387762-592deb58ef4e?w=600&h=400&fit=crop"),
]

NVQ_IMAGES = {
    2: "https://images.unsplash.com/photo-1590402494682-cd3fb53b1f70?w=600&h=400&fit=crop",
    3: "https://images.unsplash.com/photo-1581092160562-40aa08e78837?w=600&h=400&fit=crop",
    4: "https://images.unsplash.com/photo-1486312338219-ce68d2c6f44d?w=600&h=400&fit=crop",
    5: "https://images.unsplash.com/photo-1497032628192-86f99bcd76bc?w=600&h=400&fit=crop",
    6: "https://images.unsplash.com/photo-1552664730-d307ca884978?w=600&h=400&fit=crop",
    7: "https://images.unsplash.com/photo-1523050854058-8df90110c9f1?w=600&h=400&fit=crop",
}


def _plain_title(title):
    """trim(wp_strip_all_tags(wp_specialchars_decode(title)))"""
    t = re.sub(r"<[^>]*>", "", str(title or ""))
    t = t.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'").replace("&lt;", "<").replace("&gt;", ">")
    return t.strip()


def _nvq_level_number(title):
    m = re.match(r"^\s*Level\s+(\d+)", title or "", re.I)
    return int(m.group(1)) if m else 0


def _matches(title, needles):
    return any(title.lower() == n.lower() or n.lower() in title.lower() for n in needles)


def _links(items):
    return [{"title": esc_html(_plain_title_keep_entities(c["title"])), "url": c["url"]} for c in items]


def _plain_title_keep_entities(title):
    """wp_specialchars_decode() only (entities like &#8211; stay)."""
    return str(title or "").replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")


def bottom_tabs_context():
    """template-parts/page/content-bottom-tabs.php"""
    from apps.catalog.models import Product
    from apps.navigation.render import _menu_tree

    # NVQ product links per level (products in the 'nvqs' category — none on the live site,
    # so the cards fall back to the menu, exactly as WordPress does).
    by_level = {n: [] for n in range(2, 8)}
    nvq_products = Product.objects.filter(status=Status.PUBLISH, categories__slug__in=["nvqs"]).distinct()
    for p in nvq_products:
        title = p.attr("Course Title", "course title") or p.title
        level = _nvq_level_number(title)
        if level in by_level:
            by_level[level].append({"title": esc_html(title), "url": p.get_absolute_url()})
    for level in by_level:
        by_level[level].sort(key=lambda x: str(x["title"]).lower())

    tree = _menu_tree("Main Menu")
    if not tree:
        return {"training_cards": [], "nvq_cards": []}
    nvq_parent = next((n for n in tree if "nvq" in _plain_title(n["title"]).lower()), None)
    nvq_children = nvq_parent["children"] if nvq_parent else []

    nvq_specs = []
    for child in nvq_children:
        title = _plain_title(child["title"])
        level = _nvq_level_number(title)
        if 2 <= level <= 7:
            nvq_specs.append({"title": title, "level": level, "match": [title, f"Level {level}"],
                              "image": NVQ_IMAGES.get(level, ""), "item": child})
    nvq_specs.sort(key=lambda s: s["level"])

    training_cards = []
    for title, needles, image in TRAINING_CARD_SPECS:
        links = []
        for top in tree:
            if _matches(_plain_title(top["title"]), needles):
                links = _links(top["children"])
                break
        training_cards.append({"title": title, "image": image, "links": links})

    if not nvq_specs:
        nvq_specs = [{"title": f"Level {n} NVQ's", "level": n, "match": [f"Level {n} NVQ's", f"Level {n} NVQs", f"Level {n}"],
                      "image": NVQ_IMAGES[n], "item": None} for n in range(2, 8)]

    nvq_cards = []
    for spec in nvq_specs:
        level = _nvq_level_number(spec["title"])
        if by_level.get(level):
            links = by_level[level]
        elif spec["item"] and spec["item"]["children"]:
            links = _links(spec["item"]["children"])
        else:
            links = []
            for item in nvq_children:
                if _matches(_plain_title(item["title"]), spec["match"]):
                    links = _links(item["children"])
                    break
        nvq_cards.append({"title": spec["title"], "image": spec["image"], "links": links})
    return {"training_cards": training_cards, "nvq_cards": nvq_cards}


def hero_context(request):
    """template-parts/page/content-front-page-hero.php"""
    from apps.catalog import services
    from apps.pages import nvq

    site = settings.SITE_URL
    search_mode = request.GET.get("search_mode", "courses").strip()
    if search_mode != "nvq":
        search_mode = "courses"
    selected_mode = services.normalize_mode_value(request.GET.get("is_online", "")) if "is_online" in request.GET else ""
    delivery_mode = re.sub(r"[^a-z0-9_\-]", "", request.GET.get("delivery_mode", "").lower())
    if delivery_mode not in ("classroom", "online", "distance_learning"):
        delivery_mode = "online" if selected_mode == "online" else "classroom"

    level_pages = nvq.nvq_level_pages(absolute=site)
    dl_courses = [{"label": label, "url": site + url} for label, url in DISTANCE_LEARNING_COURSES]
    js = {
        "masterMap": services.wp_json_encode(services.reference_venue_date_map()),
        "nvqLevelPages": services.wp_json_encode(level_pages),
        "nvqProductsByLevel": services.wp_json_encode(nvq.nvq_products_by_level(absolute=site)),
        "distanceLearningCourses": services.wp_json_encode(dl_courses),
        "distanceLearningUrl": services.wp_json_encode(site + "/nebosh-distance-learning/"),
    }
    return {
        "tomorrow": today() + datetime.timedelta(days=1),
        "hero_search_mode": search_mode,
        "hero_selected_mode": selected_mode,
        "hero_delivery_mode": delivery_mode,
        "hero_references": services.all_course_references(),
        "hero_venues": services.all_course_venues(),
        "hero_nvq_level_pages": level_pages,
        "hero_js": js,
    }


def nebosh_dl_url():
    from .models import Page
    page = Page.objects.filter(template=Page.Template.NEBOSH_DL).order_by("-published_at", "-pk").first()
    return page.get_absolute_url() if page else "/nebosh-distance-learning/"


def front_page_context(request, page):
    context = hero_context(request)
    context.update(bottom_tabs_context())
    context.update({
        "nebosh_dl_cta_url": nebosh_dl_url(),
        "course_logos": [_logo(f) for f in _image_files("logos")],
        "trusted_logos": [_logo(f) for f in _image_files("trusted")] * 2,
    })
    return context, "home"


# ------------------------------------------------------------------------------------ page templates
def _has_content(page):
    return bool(re.sub(r"\s+", "", page.body_html or ""))


def page_only(request, page):
    """page-only.php. The fire-safety page carries page-api.php as its template meta (so WP enqueues
    the datepicker assets for it) but is rendered with page-only.php by a template_include filter."""
    datepicker = page.slug == "certificate-in-fire-safety"
    post_id = page.wp_id or page.pk
    return {"cf7_container_post": post_id, "cf7_in_loop": post_id, "datepicker_dns": datepicker}, (
        "page_with_datepicker" if datepicker else "default")


NEBOSH_DL_SLUGS = ["nebosh-general", "nebosh-general-certificate", "nebosh-construction"]


def _api_sort_key(sort_by):
    if sort_by == "price_asc":
        return lambda i: float(i["price"] or 0), False
    if sort_by == "price_desc":
        return lambda i: float(i["price"] or 0), True
    if sort_by == "date_desc":
        return lambda i: i["timestamp"], True
    return lambda i: i["timestamp"], False


def api_page(request, page):
    """page-api.php: the page's course category sessions, filtered by date/venue and grouped by month."""
    from django.utils.text import slugify
    from apps.catalog import services
    from apps.catalog.models import Product
    from apps.core.templatetags.wp import php_date

    tomorrow = (today() + datetime.timedelta(days=1)).isoformat()
    filter_date = request.GET.get("filter_date", tomorrow).strip()
    filter_venue = request.GET.get("filter_venue", "").strip()
    sort_by = request.GET.get("sort_by", "date_asc").strip()

    category = page.course_category.slug if page.course_category else slugify(page.title)
    items, venues = [], []
    if category:
        products = (Product.objects.filter(status=Status.PUBLISH, categories__slug=category).distinct()
                    .order_by("-created_at", "-pk"))
        for p in products:
            first = services.product_first_date(p)
            venue = services.product_venue_name(p)
            if venue:
                venues.append(venue)
            items.append({
                "product": p, "id": p.pk, "name": p.title, "price": p.price,
                "regular_price": p.regular_price, "sale_price": p.sale_price, "is_on_sale": p.on_sale,
                "start_date": services.product_first_date_value(p), "end_date": services.product_end_date_value(p),
                "start_time": p.attr("Start Time"), "spaces": p.attr("Available Spaces"),
                "timestamp": services.php_ts(first) if first else 0, "venue": venue,
                "month_label": php_date(first, "F Y") if first else "No Date",
            })
    venues = sorted(set(venues))

    today_ts = services.php_ts(today())
    filter_d = services.php_strtotime_date(filter_date)
    filter_ts = services.php_ts(filter_d) if filter_d else 0

    def keep(item):
        if filter_ts > today_ts and item["timestamp"] < filter_ts:
            return False
        if filter_venue and item["venue"].lower() != filter_venue.lower():
            return False
        return True

    filtered = [i for i in items if keep(i)]
    key, reverse = _api_sort_key(sort_by)
    filtered.sort(key=key, reverse=reverse)
    groups = {}
    for item in filtered:
        groups.setdefault(item["month_label"], []).append(item)

    return {
        "tomorrow": tomorrow, "filter_date": filter_date, "filter_venue": filter_venue, "sort_by": sort_by,
        "available_venues": venues, "groups": groups, "page_has_content": _has_content(page),
        "nebosh_dl_url": nebosh_dl_url() if category in NEBOSH_DL_SLUGS else "",
        "sort_options": [("date_asc", "Date (Soonest First)"), ("date_desc", "Date (Latest First)"),
                         ("price_asc", "Price (Low to High)"), ("price_desc", "Price (High to Low)")],
    }, "page_with_datepicker"


def nvq_level_page(request, page):
    """page-templates/nvq-level-page.php"""
    from apps.catalog.models import Product
    level = 0
    for candidate in (page.title, page.slug):
        m = re.search(r"\bLevel\s*([2-7])\b", candidate or "", re.I)
        if m:
            level = int(m.group(1))
            break
    label = f"Level {level} NVQ’s" if 2 <= level <= 7 else ""
    products = []
    if level:
        products = sorted(Product.objects.filter(status=Status.PUBLISH, tags__name=f"Level {level}").distinct()
                          .prefetch_related("categories", "tags"), key=lambda p: (p.title.lower(), p.pk))
    return {"level_label": label, "nvq_products": products, "page_has_content": _has_content(page)}, "default"


NEBOSH_DL_SECTIONS = [
    ("fa-sign-in-alt", "Enrolment Induction", "nebosh_dl_enrolment_text",
     "Your enrolment begins with an induction session delivered in person, over Zoom, or via Microsoft Teams.\n\n"
     "This session provides:\n• An overview of the course syllabus\n• Exam structure and technique\n• Advice on recommended study time"),
    ("fa-book", "Study Materials", "nebosh_dl_study_materials_text",
     "All study materials are provided as part of your enrolment:\n\n• Official NEBOSH study book\n• NEBOSH course materials"),
    ("fa-pen-square", "Mock Exams", "nebosh_dl_mock_exams_text",
     "Two mock exams are included to prepare you for the real assessment:\n\n• Full mock exam papers provided\n"
     "• Detailed written feedback given on your answers to help you improve before the final exam"),
    ("fa-clipboard", "Practical Exams", "nebosh_dl_practical_exams_text",
     "A dedicated study session is provided to prepare you for the practical exam:\n\n• The tutor walks through the exam format in detail\n"
     "• Guidance on the types of information required in each section of the NEBOSH format"),
    ("fa-headphones", "Tutor Support", "nebosh_dl_tutor_support_text",
     "Full tutor support is available throughout your studies via:\n\n• Email\n• Phone\n• Zoom or Microsoft Teams"),
    ("fa-calendar-check", "Enrol at Any Time", "nebosh_dl_enrolment_timing_text",
     "Enrolment onto the course can take place at any time — there are no fixed start dates. "
     "Begin your NEBOSH distance learning journey whenever you are ready."),
]

NEBOSH_DL_INTRO = ("Our NEBOSH distance learning courses allow you to study at your own pace from anywhere in the world. "
                   "With full tutor support and structured study materials, you can achieve your NEBOSH qualification "
                   "without attending a classroom. Enrolment is open at any time — start when it suits you.")


def _nl2br_esc(text):
    from apps.core import wp_format
    return mark_safe(wp_format.nl2br(str(esc_html(text))))


def nebosh_dl_page(request, page):
    """page-templates/nebosh-distance-learning.php (ACF fields with the template's defaults)."""
    acf = page.acf or {}
    sections = [{"icon": icon, "title": title, "content": _nl2br_esc(acf.get(field) or default)}
                for icon, title, field, default in NEBOSH_DL_SECTIONS]
    return {"nebosh_dl_intro": _nl2br_esc(acf.get("nebosh_dl_intro") or NEBOSH_DL_INTRO),
            "nebosh_dl_sections": sections}, "default"


def category_page(request, page):
    """page-templates/category-page.php (ACF 'content_repeater' rows of header/content)."""
    rows = (page.acf or {}).get("content_repeater") or []
    return {"content_rows": rows if isinstance(rows, list) else []}, "default"


BUILDERS = {
    "page_only": page_only,
    "api": api_page,
    "nvq_level": nvq_level_page,
    "nebosh_dl": nebosh_dl_page,
    "category": category_page,
}
