"""WooCommerce catalog pages: shop (archive-product.php + inc/custom-shop.php), product categories
(taxonomy-product_cat.php), product tags (archive-product.php loop) and single products."""
import math
import random
import re
from decimal import Decimal

from django.conf import settings
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt

from apps.core.bodyclass import archive_classes, single_classes
from apps.core.models import Status
from apps.core.views import page_number, wp_render
from apps.seo.engine import Seo

from . import services
from .models import Product, ProductCategory, ProductTag

WOO = ("woocommerce", "woocommerce-page")
PER_PAGE = 16  # loop_shop_per_page (4 columns x 4 rows)


def _params(request):
    """$_GET values through sanitize_text_field()."""
    out = {}
    for key in request.GET:
        value = request.GET.get(key, "")
        value = strip_tags(value)
        value = re.sub(r"[\r\n\t ]+", " ", value).strip()
        out[key] = value
    return out


def _today():
    return timezone.localdate()


def _trusted_logos():
    from apps.pages.extras import _image_files, _logo
    return [_logo(f) for f in _image_files("trusted")] * 2


def _wc_json(data):
    """WC_Structured_Data output: wp_json_encode(JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)."""
    import json
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def _wc_breadcrumb(crumbs):
    """WC_Structured_Data::generate_breadcrumblist_data(): crumbs = [(name, absolute url)]."""
    from django.conf import settings
    items = []
    for i, (name, url) in enumerate(crumbs, start=1):
        items.append({"@type": "ListItem", "position": i, "item": {"name": name, "@id": url}})
    return {"@context": "https://schema.org/", "@type": "BreadcrumbList", "itemListElement": items}


# --------------------------------------------------------------------------------------------- shop
def shop(request, page=None, search=None):
    """/shop/ and — with `search` — the product search /?s=<term>&post_type=product, which WordPress
    renders with the same shop template (is_shop() is true for a product post-type search)."""
    from django.utils.html import escape
    from apps.pages.models import Page

    # custom_course_filter_query() sets posts_per_page=-1, so WP serves /shop/page/N/ (any N) with
    # the full grouped list; only the breadcrumbs and SEO head reflect the page number.
    number = page_number(request, page)
    params = _params(request)
    today = _today()
    rows = services.shop_matches(params, today)
    if search is not None:
        rows = services.search_filter(rows, search)
    groups = services.grouped_results(rows) if rows else []

    shop_url = settings.SITE_URL + "/shop/"
    crumbs = [("Home", settings.SITE_URL), ("Shop", shop_url)]
    if search is not None:
        # WC_Breadcrumb::add_crumbs_search(): label via esc_html, link = request URI without paged.
        last = f"Search results for &ldquo;{escape(search)}&rdquo;"
        uri = re.sub(r"([?&])paged=[^&]*&?", lambda m: m.group(1), request.get_full_path()).rstrip("?&")
        crumbs.append((escape(last), escape(uri)))
    elif number > 1:
        last = f"Page {number}"
        crumbs.append((last, f"{shop_url}page/{number}/"))
    else:
        last = None

    if search is not None:
        seo = Seo(request, number).search(search, first_item=rows[0]["product"] if rows else None)
    else:
        shop_page = Page.objects.filter(slug="shop").first()
        seo = Seo(request, page_number=number).singular(shop_page, "/shop/") if shop_page else None
    references = services.all_course_references()
    venues = services.all_course_venues()
    context = {
        "shop_title": services.shop_title(params),
        "shop_crumb": last,
        "groups": groups,
        "references": references,
        "venues": venues,
        "current_reference": params.get("reference", ""),
        "current_venue": params.get("venue", ""),
        "current_date": params.get("from", ""),
        "current_mode": params.get("is_online", ""),
        "tomorrow": (today + timezone.timedelta(days=1)).isoformat(),
        "ref_venue_map_json": services.wp_json_encode(services.reference_venue_date_map()),
        "venue_labels_json": services.wp_json_encode(venues),
        "trusted_logos": _trusted_logos(),
        "wc_structured_data": _wc_json(_wc_breadcrumb(crumbs)),
    }
    extra = ["post-type-archive", "post-type-archive-product"]
    if search is not None:
        extra = ["search", "search-results" if rows else "search-no-results", *extra]
    body = archive_classes(extra, woo=("woocommerce-shop", *WOO))
    return wp_render(request, "catalog/shop.html", context, seo=seo, body_class=body, profile="shop")


# ----------------------------------------------------------------------------------- categories
def _menu_title(category):
    """custom_shop_get_product_cat_menu_title(): the Main Menu item's label for this term."""
    from apps.navigation.models import MenuItem

    items = MenuItem.objects.filter(menu__name="Main Menu").select_related("product_category").order_by("tree_id", "lft")
    for item in items:
        if item.target_type == MenuItem.Target.PRODUCT_CATEGORY and item.product_category_id == category.pk:
            return strip_tags(item.title or category.name).strip()
    link = category.get_absolute_url().rstrip("/")
    for item in items:
        if item.url and re.sub(r"^https?://[^/]+(/sst)?", "", item.url).rstrip("/") == link:
            return strip_tags(item.title).strip()
    return ""


def _category_from_path(path):
    slugs = [s for s in path.strip("/").split("/") if s]
    if not slugs:
        raise Http404
    category = get_object_or_404(ProductCategory, slug=slugs[-1])
    if [a.slug for a in category.get_ancestors(include_self=True)] != slugs:
        raise Http404
    return category


def category(request, path, page=None):
    from apps.pages.models import Page

    term = _category_from_path(path)
    number = page_number(request, page)
    params = _params(request)
    today = _today()
    tomorrow = today + timezone.timedelta(days=1)
    filter_date = params["filter_date"] if "filter_date" in request.GET else tomorrow.isoformat()
    filter_venue = params.get("filter_venue", "")
    sort_by = params.get("sort_by", "date_asc")

    products = list(term.products.filter(status=Status.PUBLISH)
                    .prefetch_related("categories", "tags").order_by("-created_at", "wp_id", "pk"))
    total_pages = max(1, math.ceil(len(products) / PER_PAGE))
    if number > total_pages:
        raise Http404

    items, venues = [], []
    for p in products:
        first = services.product_first_date(p)
        venue = services.product_venue_name(p)
        if venue:
            venues.append(venue)
        items.append({
            "product": p,
            "id": p.pk,
            "name": p.title,
            "price": p.price,
            "regular_price": p.regular_price,
            "sale_price": p.sale_price,
            "is_on_sale": p.on_sale,
            "start_date": services.product_first_date_value(p),
            "end_date": services.product_end_date_value(p),
            "start_time": p.attr("Start Time"),
            "spaces": p.attr("Available Spaces"),
            "date": first,
            "venue": venue,
            "month_label": first.strftime("%B %Y") if first else "No Date",
        })
    venues = sorted(dict.fromkeys(venues))

    filter_d = services.php_strtotime_date(filter_date) if filter_date else None

    def keep(item):
        if filter_d and filter_d > today and item["date"] and item["date"] < filter_d:
            return False
        if filter_venue and item["venue"].lower() != filter_venue.lower():
            return False
        return True

    filtered = [i for i in items if keep(i)]
    ts = lambda i: services.php_ts(i["date"])  # noqa: E731
    price = lambda i: Decimal(i["price"] or 0)  # noqa: E731
    if sort_by == "price_asc":
        filtered.sort(key=price)
    elif sort_by == "price_desc":
        filtered.sort(key=price, reverse=True)
    elif sort_by == "date_desc":
        filtered.sort(key=ts, reverse=True)
    else:
        filtered.sort(key=ts)
    groups = {}
    for item in filtered:
        groups.setdefault(item["month_label"], []).append(item)

    nebosh_dl_url = ""
    if term.slug in ("nebosh-general", "nebosh-general-certificate", "nebosh-construction"):
        dl = Page.objects.filter(template=Page.Template.NEBOSH_DL).order_by("-published_at").first()
        nebosh_dl_url = dl.get_absolute_url() if dl else ""

    context = {
        "term": term,
        "menu_current_path": term.get_absolute_url(),  # current-menu-item on /page/N/ too
        "page_title": _menu_title(term) or term.name,
        "filter_date": filter_date,
        "filter_venue": filter_venue,
        "sort_by": sort_by,
        "tomorrow": tomorrow.isoformat(),
        "venues": venues,
        "groups": list(groups.items()),
        "nebosh_dl_url": nebosh_dl_url,
        "trusted_logos": _trusted_logos(),
        "sort_options": [("date_asc", "Date (Soonest First)"), ("date_desc", "Date (Latest First)"),
                         ("price_asc", "Price (Low to High)"), ("price_desc", "Price (High to Low)")],
    }
    seo = Seo(request, page_number=number, total_pages=total_pages).archive(
        kind="product_cat", url=term.get_absolute_url(), name=term.name, term=term)
    body = archive_classes(["tax-product_cat", f"term-{term.slug}", f"term-{term.wp_id or term.pk}"], woo=WOO)
    return wp_render(request, "catalog/category.html", context, seo=seo, body_class=body, profile="product_category")


# ------------------------------------------------------------------------------------------ tags
def tag(request, slug, page=None):
    term = get_object_or_404(ProductTag, slug=slug)
    number = page_number(request, page)
    qs = (term.products.filter(status=Status.PUBLISH).prefetch_related("categories", "tags")
          .order_by("title", "pk"))  # woocommerce_default_catalog_orderby = menu_order → menu_order, title
    total = qs.count()
    total_pages = max(1, math.ceil(total / PER_PAGE))
    if number > total_pages:
        raise Http404
    products = list(qs[(number - 1) * PER_PAGE:number * PER_PAGE])
    from django.utils.html import escape
    crumb = escape(f"Products tagged &ldquo;{term.name}&rdquo;")
    context = {"term": term, "products": products, "trusted_logos": _trusted_logos(),
               "wc_structured_data": _wc_json(_wc_breadcrumb([("Home", settings.SITE_URL),
                                                              (crumb, settings.SITE_URL + term.get_absolute_url())]))}
    seo = Seo(request, page_number=number, total_pages=total_pages).archive(
        kind="product_tag", url=term.get_absolute_url(), name=term.name, term=term)
    body = archive_classes(["tax-product_tag", f"term-{term.slug}", f"term-{term.wp_id or term.pk}"], woo=WOO)
    return wp_render(request, "catalog/tag.html", context, seo=seo, body_class=body, profile="default")


# --------------------------------------------------------------------------------------- product
def _related(product, limit=4):
    """wc_get_related_products(): same category or tag, shuffled."""
    cats = [c.pk for c in product.categories.all()]
    tags = [t.pk for t in product.tags.all()]
    ids = list(Product.objects.published().filter(Q(categories__in=cats) | Q(tags__in=tags))
               .exclude(pk=product.pk).order_by("wp_id", "pk").values_list("pk", flat=True).distinct()[:limit + 10])
    random.shuffle(ids)
    chosen = ids[:limit]
    by_id = {p.pk: p for p in Product.objects.filter(pk__in=chosen).prefetch_related("categories", "tags")}
    return [by_id[i] for i in chosen if i in by_id]


def _primary_category(product):
    """wc_get_product_terms(orderby parent DESC) first term, minus the hidden 'uncategorised'."""
    cats = [c for c in product.categories.all() if c.slug.lower() not in ("uncategorized", "uncategorised")]
    cats.sort(key=lambda c: (-(c.parent_id or 0), c.name.lower()))
    return cats[0] if cats else None


def _product_structured_data(product, primary):
    from apps.core.models import SiteOptions
    url = settings.SITE_URL + product.get_absolute_url()
    crumbs = [("Home", settings.SITE_URL)]
    if primary:
        crumbs.append((primary.name, settings.SITE_URL + primary.get_absolute_url()))
    crumbs.append((product.title, url))
    graph = [_wc_breadcrumb(crumbs)]
    if product.price is not None:
        price = product.price_incl_vat
        valid = f"{_today().year + 1}-12-31"
        graph.append({
            "@context": "https://schema.org/", "@type": "Product", "@id": url + "#product",
            "name": product.title, "url": url,
            "description": strip_tags(product.short_description or product.description).strip(),
            "sku": product.sku or str(product.pk),
            "offers": [{
                "@type": "Offer",
                "priceSpecification": [{"@type": "UnitPriceSpecification", "price": f"{price:.2f}", "priceCurrency": "GBP",
                                        "validThrough": valid, "valueAddedTaxIncluded": True}],
                "priceValidUntil": valid,
                "availability": "https://schema.org/" + ("InStock" if product.in_stock else "OutOfStock"),
                "url": url,
                "seller": {"@type": "Organization", "name": SiteOptions.load().site_name, "url": settings.SITE_URL},
                "price": f"{price:.2f}", "priceCurrency": "GBP",
            }],
        })
    return _wc_json({"@context": "https://schema.org/", "@graph": graph})


@csrf_exempt
def product_detail(request, slug):
    product = get_object_or_404(Product.objects.prefetch_related("categories", "tags"), slug=slug)
    if product.status != Status.PUBLISH and not request.user.is_staff:
        raise Http404
    if request.method == "POST" and request.POST.get("add-to-cart"):
        from apps.cart import services as cart
        try:
            qty = int(request.POST.get("quantity") or 1)
        except ValueError:
            qty = 1
        try:
            cart.add_to_cart(request, product, qty)
        except cart.CartError as exc:
            cart.add_notice(request, str(exc), "error")
        return redirect(product.get_absolute_url())

    categories = sorted([c for c in product.categories.all() if c.slug.lower() not in ("uncategorized", "uncategorised")],
                        key=lambda c: c.name.lower())
    tags = sorted(product.tags.all(), key=lambda t: t.name.lower())
    max_qty = product.stock_qty if product.manage_stock and product.stock_qty is not None else None
    context = {
        "product": product,
        "primary_category": _primary_category(product),
        "categories": categories,
        "tags": tags,
        "related": _related(product),
        "max_qty": max_qty,
        "wc_structured_data": _product_structured_data(product, _primary_category(product)),
        "menu_parent_term_urls": {c.get_absolute_url() for c in categories},
        "qty_id": "quantity_" + format(random.getrandbits(52), "x")[:13],
    }
    product.published_at = product.created_at  # Yoast datePublished (post_date)
    shop_crumb = ("Shop", "/shop/")
    seo_obj = Seo(request)
    crumbs = [(seo_obj.settings.breadcrumbs_home, "/"), shop_crumb, (product.title, None)]
    seo = seo_obj.singular(product, product.get_absolute_url(), crumbs=crumbs)
    body = single_classes(product, "product", woo=WOO, format_standard=False)
    return wp_render(request, "catalog/product.html", context, seo=seo, body_class=body, profile="product")
