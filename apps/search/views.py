"""Site search: search.php (/?s=term and /search/<term>/) and the header search modal's
admin-ajax.php endpoint (functions.php sst_search_modal_ajax)."""
import html
from urllib.parse import quote
import re
from datetime import date, datetime

from django.db.models import Q
from django.http import Http404, JsonResponse
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.blog import loop
from apps.core.bodyclass import search_classes
from apps.core.templatetags.wp import money_plain, php_date, price_html
from apps.core.views import page_number, wp_render
from apps.seo.engine import Seo

# WordPress's wp_search_stopwords() (en).
STOPWORDS = set("about an are as at be by com for from how in is it of on or that the this to was what when where who will with www".split())
TERM_RE = re.compile(r'".*?("|$)|((?<=[\t ",+])|^)[^\t ",+]+')
HIDDEN = loop.HIDDEN_CATEGORY_SLUGS


# ---------------------------------------------------------------------------- query
def search_terms(s):
    """WP_Query::parse_search(): (terms, search_terms_count). The count includes stopwords."""
    s = s.replace(chr(10), "").replace(chr(13), "").strip()
    if not s:
        return [], 0
    matches = [m.group(0) for m in TERM_RE.finditer(s)]
    if not matches:
        return [s], 1
    terms = []
    for term in matches:
        if re.match(r'^".+"$', term):
            term = term.strip('"')
        else:
            term = term.strip('" ')
        if not term or (len(term) == 1 and re.match(r"^[a-z\-]$", term, re.I)):
            continue
        if term.lower() in STOPWORDS:
            continue
        terms.append(term)
    if not terms or len(terms) > 9:
        terms = [s]
    return terms, len(matches)


def _sources(main_query):
    """(label, queryset, title field, text fields, date field) for every searchable post type."""
    from apps.blog.models import Post
    from apps.catalog.models import Product
    from apps.courses.models import NeboshCourse, SafetyCourse
    from apps.exampapers.models import ExamPaper
    from apps.news.models import News
    from apps.pages.models import Page

    posts = Post.objects.published()
    products = Product.objects.published()
    if main_query:
        # functions.php sst_exclude_hidden_terms_from_search (main query only; admin-ajax skips it).
        posts = posts.exclude(categories__slug__in=HIDDEN)
        products = products.exclude(categories__slug__in=HIDDEN)
    content = ("excerpt", "content")
    return [
        ("Post", posts, content, "published_at"),
        ("Page", Page.objects.published(), content, "published_at"),
        ("Product", products, ("short_description", "description"), "created_at"),
        ("News", News.objects.published(), content, "published_at"),
        ("NEBOSH Course", NeboshCourse.objects.published(), content, "published_at"),
        ("Safety Course", SafetyCourse.objects.published(), content, "published_at"),
        ("Exam Paper", ExamPaper.objects.published(), content, "published_at"),
    ]


def run_search(s, main_query=True):
    """Matching objects in WordPress relevance order."""
    terms, count = search_terms(s)
    phrase = s.strip()
    results = []
    for label, qs, (excerpt_f, content_f), date_f in _sources(main_query):
        cond = Q()
        for term in terms:
            cond &= Q(title__icontains=term) | Q(**{f"{excerpt_f}__icontains": term}) | Q(**{f"{content_f}__icontains": term})
        # An empty ?s= is still a search: WP lists every searchable post, newest first.
        for obj in qs.filter(cond).distinct():
            if not terms:
                results.append((0, getattr(obj, date_f), obj.wp_id or 10 ** 9 + obj.pk, label, obj))
                continue
            title = (obj.title or "").lower()
            if count > 1:
                like = phrase.lower() if not re.search(r"(?:\s|^)-", phrase) else ""
                if like and like in title:
                    rank = 1
                elif len(terms) < 7 and all(t.lower() in title for t in terms):
                    rank = 2
                elif 1 < len(terms) < 7 and any(t.lower() in title for t in terms):
                    rank = 3
                elif like and like in (getattr(obj, excerpt_f) or "").lower():
                    rank = 4
                elif like and like in (getattr(obj, content_f) or "").lower():
                    rank = 5
                else:
                    rank = 6
            else:
                rank = 0 if terms[0].lower() in title else 1
            results.append((rank, getattr(obj, date_f), obj.wp_id or 10 ** 9 + obj.pk, label, obj))
    # ORDER BY relevance, post_date DESC
    # ORDER BY relevance, post_date DESC (MySQL returns ties in ID order).
    results.sort(key=lambda r: (r[0], -r[1].timestamp(), r[2]))
    return [(label, obj) for _, _, _, label, obj in results]


# ---------------------------------------------------------------------------- product facts
def _parse_date(value):
    if isinstance(value, (date, datetime)):
        return value
    value = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", str(value or "").strip(), flags=re.I)
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%m/%d/%Y", "%d %B %Y", "%A %d %B %Y", "%B %d %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def product_first_date(product):
    """custom_shop_get_product_first_date_value()."""
    value = product.attr("First Date", "first date") or product.attr("Start Date", "start date", "Date", "course date")
    if not value and product.first_date:
        value = product.first_date.isoformat()
    return value


def _looks_like_date(value):
    value = (value or "").strip()
    return bool(value) and (bool(_parse_date(value)) or bool(re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", value)))


def product_venue(product):
    """custom_shop_get_product_venue_name(): venue attribute, else online flag, else the title's venue part."""
    venue = re.sub(r"\s+", " ", product.attr("Venue Name", "venue.name", "venue")).strip()
    if venue.lower() in ("online (instructor-led)", "online (instructor led)"):
        venue = "Online (Instructor-Led)"
    if _looks_like_date(venue):
        venue = ""
    if venue:
        return venue
    if product.attr("Is Online", "is online").strip().lower() in ("1", "yes", "true", "online"):
        return "Online (Instructor-Led)"
    parts = [p.strip() for p in (product.title or "").split("|") if p.strip()]
    if len(parts) < 2:
        return ""
    candidate = ""
    for part in reversed(parts):
        if _parse_date(part) or part.lower() == parts[0].lower():
            continue
        candidate = part
        break
    return "" if _looks_like_date(candidate) else candidate


def product_price_text(product):
    """wp_strip_all_tags(get_price_html()) as search.php prints it: WooCommerce displays shop
    prices including VAT there (woocommerce_tax_display_shop = incl) plus the theme's '+ VAT'."""
    from decimal import Decimal

    from apps.core.templatetags.wp import _money

    if product.price is None:
        return ""

    def incl(value):
        value = Decimal(value)
        return (value * Decimal("1.2")).quantize(Decimal("0.01")) if product.taxable else value

    price = f"£{_money(incl(product.price))}"
    if product.on_sale:
        regular = f"£{_money(incl(product.regular_price))}"
        text = f"{regular} Original price was: {regular}.{price} Current price is: {price}."
    else:
        text = price
    if product.is_nvq:
        text = f"PAY 50% UPFRONT {text}"
    return re.sub(r"\s+", " ", f"{text} + VAT").strip()


def product_spaces(product):
    return product.attr("Available Spaces") or product.attr("spaces")


# ---------------------------------------------------------------------------- views
def search_results(request, page=None, term=None):
    s = term if term is not None else request.GET.get("s", "")
    s = s.strip()
    if term is None and request.GET.get("post_type", "") == "product":
        # A product post-type search is is_shop() in WooCommerce: archive-product.php + custom-shop.php.
        from apps.catalog.views import shop
        return shop(request, page, search=s)
    n = page_number(request, page)
    is_product_search = request.GET.get("post_type", "") == "product"
    found = run_search(s, main_query=True)
    if is_product_search:
        found = [(label, obj) for label, obj in found if label == "Product"]
    paged = loop.Paged(found, n, loop.per_page(), "/", query={"s": s})
    items = []
    for label, obj in paged.items:
        if label == "Product":
            price_text = product_price_text(obj)
            price_text = re.sub(r"\.00(?=\s|$)", "", price_text)
            first = product_first_date(obj)
            parsed = _parse_date(first)
            items.append({
                "product": obj,
                "price_text": price_text,
                "first_date_value": first,
                "compact_date": php_date(parsed, "d/m/Y") if parsed else "",
                "first_date_text": php_date(parsed, "l jS F Y") if parsed else first,
                "venue": product_venue(obj),
                "spaces": product_spaces(obj),
            })
        else:
            items.append({"obj": obj, "excerpt": loop.the_excerpt(obj)})
    title = re.sub(r"\s+", " ", re.sub(r"^for\s+", "", re.split(r"\s*\|\s*", s)[0].strip(), flags=re.I)).strip()
    seo = Seo(request, n, paged.max_pages).search(s, first_item=paged.items[0][1] if paged.items else None)
    seo = loop.link_crumbs(seo, f"/search/{quote(s, safe='')}/")
    context = {"items": items, "paged": paged, "search_title": title, "search_query": s,
               "is_product_search": is_product_search}
    return wp_render(request, "search.html", context, seo=seo, body_class=search_classes(bool(items)))


def pretty_search(request, term):
    """/search/<term>/ is WordPress's pretty search permalink: it renders the results directly."""
    return search_results(request, term=term.replace("+", " "))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def admin_ajax(request):
    action = request.POST.get("action") or request.GET.get("action")
    if action != "sst_search_modal":
        # admin-ajax.php answers unknown actions with "0" (HTTP 400).
        from django.http import HttpResponse
        return HttpResponse("0", status=400)
    term = re.sub(r"\s+", " ", strip_tags(request.POST.get("term", ""))).strip()
    if term == "":
        return JsonResponse({"success": True, "data": {"results": []}})
    results = []
    for label, obj in run_search(term, main_query=False)[:8]:
        is_product = label == "Product"
        compact_date = ""
        details = []
        if is_product:
            if obj.price is not None:
                details.append({"label": "Price", "value": f"{money_plain(obj.price)} + VAT"})
            parsed = _parse_date(product_first_date(obj))
            if parsed:
                compact_date = php_date(parsed, "d/m/Y")
                details.append({"label": "Date", "value": php_date(parsed, "l jS F Y")})
            venue = product_venue(obj)
            if venue:
                details.append({"label": "Venue", "value": venue})
            spaces = product_spaces(obj)
            if spaces:
                details.append({"label": "Spaces", "value": spaces})
        from apps.core.wp_format import wptexturize
        results.append({
            "title": re.sub(r"&(?!#?\w+;)", "&#038;", wptexturize(obj.title)),
            "url": _absolute(obj.get_absolute_url()),
            "type": label,
            "is_product": is_product,
            "compact_date": compact_date,
            "details": details,
        })
    return JsonResponse({"success": True, "data": {"results": results}})


def _absolute(url):
    from apps.seo.engine import absolute
    return absolute(url)
