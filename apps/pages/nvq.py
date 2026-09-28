"""NVQ helpers from twentyseventeen-child/functions.php (sst_get_nvq_level_page_links,
custom_shop_get_nvq_level_pages, custom_shop_get_nvq_products_by_level, ...)."""
import re

from apps.catalog.models import Product, ProductCategory
from apps.core.models import Status

NVQ_LEVEL_PAGES = [(n, f"Level {n} NVQ’s", f"level-{n}-nvqs") for n in range(2, 8)]


def nvq_level_page_links():
    """sst_get_nvq_level_page_links(): [{'label', 'url'}]."""
    from .models import Page
    pages = {p.slug: p for p in Page.objects.filter(slug__in=[s for _, _, s in NVQ_LEVEL_PAGES], parent=None)}
    links = []
    for _, label, slug in NVQ_LEVEL_PAGES:
        page = pages.get(slug)
        links.append({"label": label, "url": page.get_absolute_url() if page else f"/{slug}/"})
    return links


def nvq_level_pages(absolute=""):
    """custom_shop_get_nvq_level_pages(): {level: {'label', 'url'}}."""
    levels = {}
    for link in nvq_level_page_links():
        m = re.search(r"Level\s*([2-7])", link["label"], re.I)
        if m:
            levels[int(m.group(1))] = {"label": link["label"].strip(), "url": absolute + link["url"]}
    return levels


def all_nvq_levels():
    """custom_shop_get_all_nvq_levels()."""
    levels = [{"slug": f"level-{n}-nvqs", "name": f"Level {n} NVQ"} for n in range(2, 8)]
    names = dict(ProductCategory.objects.filter(slug__in=[l["slug"] for l in levels]).values_list("slug", "name"))
    for level in levels:
        level["name"] = names.get(level["slug"], level["name"])
    return levels


def _nvq_products():
    return (Product.objects.filter(status=Status.PUBLISH, categories__slug="nvq").distinct()
            .prefetch_related("tags").order_by("-created_at", "wp_id", "pk"))  # post_date DESC, ties by ID


def nvq_product_levels(product):
    """custom_shop_get_nvq_product_levels(): levels 2–7 from the product's tags."""
    levels = []
    for t in product.tags.all():
        m = re.search(r"level\s*([2-7])", f"{t.name} {t.slug}".strip().lower())
        if m and int(m.group(1)) not in levels:
            levels.append(int(m.group(1)))
    return levels


def all_nvq_courses():
    """custom_shop_get_all_nvq_courses(): {sanitize_title(title): title}, natcasesorted."""
    from apps.catalog.services import normalize_course_title, natural_key
    from django.utils.text import slugify
    courses = {}
    for p in _nvq_products():
        title = normalize_course_title(p.title)
        if title:
            courses[slugify(title)] = title
    return dict(sorted(courses.items(), key=lambda kv: natural_key(kv[1].lower())))


def nvq_products_by_level(absolute=""):
    """custom_shop_get_nvq_products_by_level(): {level: [{'id', 'title', 'url'}]}."""
    from apps.catalog.services import normalize_course_title
    grouped = {level: [] for level in range(2, 8)}
    for p in _nvq_products():
        levels = nvq_product_levels(p)
        title = normalize_course_title(p.title)
        if not levels or not title:
            continue
        for level in levels:
            if level in grouped:
                grouped[level].append({"id": p.pk, "title": title, "url": absolute + p.get_absolute_url()})
    return grouped
