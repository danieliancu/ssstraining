"""Course shop logic ported from twentyseventeen-child/inc/custom-shop.php.

Function names mirror the PHP (custom_shop_* without the prefix). Dates are handled as
datetime.date; PHP timestamps (UTC midnight) are produced only where the output needs them
(the filter bar's reference → venue → dates JSON map).
"""
import calendar
import datetime
import json
import re

from django.utils.text import slugify

from apps.core.models import Status

ONLINE_VENUE = "Online (Instructor-Led)"

# --------------------------------------------------------------------------------------------
# strtotime() subset — enough for the formats that occur in product attributes and titles.
# --------------------------------------------------------------------------------------------
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_DAYS = {d.lower() for d in calendar.day_name} | {d.lower() for d in calendar.day_abbr}
_MON = r"(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"


def _mk(y, m, d):
    try:
        y = int(y)
        if y < 100:
            y += 2000 if y < 70 else 1900
        return datetime.date(y, int(m), int(d))
    except (TypeError, ValueError):
        return None


_TIME = r"(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"
_PATTERNS = [
    (re.compile(r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})" + _TIME + "$"), lambda g: _mk(g["y"], g["m"], g["d"])),
    (re.compile(r"^(?P<y>\d{4})/(?P<m>\d{1,2})/(?P<d>\d{1,2})" + _TIME + "$"), lambda g: _mk(g["y"], g["m"], g["d"])),
    # American m/d/y — PHP reads slashes that way.
    (re.compile(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4}|\d{2})" + _TIME + "$"), lambda g: _mk(g["y"], g["m"], g["d"])),
    # d-m-Y and d.m.Y
    (re.compile(r"^(?P<d>\d{1,2})[-.](?P<m>\d{1,2})[-.](?P<y>\d{4})" + _TIME + "$"), lambda g: _mk(g["y"], g["m"], g["d"])),
    (re.compile(r"^(?P<d>\d{1,2})[ -]" + _MON + r"[ -,]*(?P<y>\d{4})" + _TIME + "$", re.I),
     lambda g: _mk(g["y"], _MONTHS[g["mon"].lower()], g["d"])),
    (re.compile(r"^" + _MON + r" (?P<d>\d{1,2}),? (?P<y>\d{4})" + _TIME + "$", re.I),
     lambda g: _mk(g["y"], _MONTHS[g["mon"].lower()], g["d"])),
]


def php_strtotime_date(value):
    """date for the strings strtotime() understands in this data set, else None."""
    s = re.sub(r"\s+", " ", str(value or "").strip())
    if not s:
        return None
    # Leading weekday name ("Tuesday 2 June 2026", "Tue, 2 June 2026")
    m = re.match(r"^([A-Za-z]+),? (.+)$", s)
    if m and m.group(1).lower() in _DAYS:
        s = m.group(2)
    for rx, build in _PATTERNS:
        mm = rx.match(s)
        if mm:
            return build(mm.groupdict())
    return None


def parse_date_to_timestamp(raw):
    """custom_shop_parse_date_to_timestamp() as a date (None for 0)."""
    if not raw:
        return None
    return php_strtotime_date(re.sub(r"(\d+)(st|nd|rd|th)", r"\1", str(raw), flags=re.I))


def php_ts(d):
    return calendar.timegm(d.timetuple()) if d else 0


# --------------------------------------------------------------------------------------------
# Product attribute helpers
# --------------------------------------------------------------------------------------------
def product_attr(p, *keys):
    return p.attr(*keys)


def normalize_course_title(title):
    title = str(title or "").strip()
    if not title:
        return ""
    parts = re.split(r"\s*\|\s*", title)
    if parts and parts[0]:
        title = parts[0].strip()
    title = re.sub(r"^for\s+", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def normalize_venue_label(value):
    value = str(value or "").strip()
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", value)
    if normalized.lower() in ("online (instructor-led)", "online (instructor led)"):
        return ONLINE_VENUE
    return normalized


def looks_like_date_label(value):
    value = str(value or "").strip()
    if not value:
        return False
    if parse_date_to_timestamp(value):
        return True
    return bool(re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", value))


def normalize_mode_value(value):
    value = str(value or "").strip().lower()
    return "online" if value in ("1", "yes", "true", "online") else ""


def product_is_online(p):
    return normalize_mode_value(p.attr("Is Online", "is online")) == "online"


def is_online_venue_label(value):
    return normalize_venue_label(value) == ONLINE_VENUE


def extract_first_date_from_title(title):
    for part in (x.strip() for x in str(title or "").split("|")):
        if part and parse_date_to_timestamp(part):
            return part
    return ""


def _sanitize_title(s):
    return slugify(str(s or ""))


def extract_venue_from_title(title):
    parts = [x.strip() for x in str(title or "").split("|") if x.strip()]
    if len(parts) < 2:
        return ""
    candidate = ""
    for part in reversed(parts):
        if parse_date_to_timestamp(part):
            continue
        if _sanitize_title(part) == _sanitize_title(parts[0]):
            continue
        candidate = part
        break
    return normalize_venue_label(candidate)


def product_venue_name(p):
    """custom_shop_get_product_venue_name()"""
    venue = normalize_venue_label(p.attr("Venue Name", "venue.name", "venue"))
    if looks_like_date_label(venue):
        venue = ""
    if venue:
        return venue
    if product_is_online(p):
        return ONLINE_VENUE
    title_venue = extract_venue_from_title(p.title)
    return "" if looks_like_date_label(title_venue) else title_venue


def product_first_date_value(p):
    """custom_shop_get_product_first_date_value() — the raw string."""
    value = p.attr("First Date", "first date")
    if not value:
        value = p.attr("Start Date", "start date", "Date", "course date")
    if not value:
        value = extract_first_date_from_title(p.title)
    return value


def product_first_date(p):
    """custom_shop_get_product_first_date_timestamp() as a date (None when WP gets 0)."""
    return parse_date_to_timestamp(product_first_date_value(p))


def product_end_date_value(p):
    value = p.attr("End Date", "end date", "Last Date", "last date")
    if not value:
        value = p.attr("duration.last_date", "last_date")
    return value


def format_display_date(date_string):
    """custom_shop_format_display_date(): 'l jS F Y', raw string when unparseable."""
    date_string = str(date_string or "").strip()
    if not date_string:
        return ""
    d = php_strtotime_date(date_string)
    if not d:
        return date_string
    day = d.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{d.strftime('%A')} {day}{suffix} {d.strftime('%B')} {d.year}"


def dates_are_same_day(start_date, end_date):
    a = php_strtotime_date(start_date)
    b = php_strtotime_date(end_date)
    return bool(a and b and a == b)


def product_reference_terms(p):
    """custom_shop_get_product_reference_terms(): categories (by name, as wp_get_post_terms) minus hidden."""
    cats = sorted(p.categories.all(), key=lambda c: c.name.lower())
    return [{"slug": c.slug, "name": c.name} for c in cats if not c.is_hidden_reference]


# --------------------------------------------------------------------------------------------
# Reference names and ordering
# --------------------------------------------------------------------------------------------
REFERENCE_ORDER = [
    "Site Management Safety Training Scheme",
    "Site Management Safety Training Scheme Refresher",
    "Site Supervisors Safety Training Scheme",
    "Site Supervisors Safety Training Scheme Refresher",
    "Health and Safety Awareness",
    "Temporary Works Coordinator",
    "Temporary Works Co-ordinator Training Refresher",
    "Temporary Works Supervisor",
    "Site Environmental Awareness Training Scheme",
    "Foundation Certificate in Environmental Management",
    "CITB Director's Role for Health and Safety",
    "IOSH Managing Safely",
    "IOSH Working Safely",
    "NEBOSH General",
    "NEBOSH Construction",
    "EUSR CAT 1 & 2",
    "EURS CAT 1 & 2",
    "EUSR Water Hygiene",
    "EUSR CAT 1 Location Underground Services",
    "EUSR SHEA Power",
    "EUSR SHEA Telecom",
    "First Aid at Work (Blended)",
    "Emergency First Aid at Work",
    "Mental Health First Aid - 2 day",
    "First Aid at Work ReQualification",
]

REFERENCE_DISPLAY_NAMES = {
    "sssts": "Site Supervisors Safety Training Scheme",
    "sssts-refresher": "Site Supervisors Safety Training Scheme Refresher",
    "smsts": "Site Management Safety Training Scheme",
    "smsts-refresher": "Site Management Safety Training Scheme Refresher",
    "hsa": "Health and Safety Awareness",
    "twc": "Temporary Works Coordinator",
    "twc-refresher": "Temporary Works Co-ordinator Training Refresher",
    "tws": "Temporary Works Supervisor",
    "seats": "Site Environmental Awareness Training Scheme",
    "foundation-certificate-in-environmental-management": "Foundation Certificate in Environmental Management",
    "citb-directors-role-for-health-and-safety": "CITB Director's Role for Health and Safety",
    "iosh-managing-safely": "IOSH Managing Safely",
    "iosh-working-safely": "IOSH Working Safely",
    "nebosh-general-certificate": "NEBOSH General",
    "nebosh-general": "NEBOSH General",
    "nebosh-construction": "NEBOSH Construction",
    "eusr-cat-1-2": "EUSR CAT 1 & 2",
    "eurs-cat-1-2": "EUSR CAT 1 & 2",
    "eusr-water-hygiene": "EUSR Water Hygiene",
    "eusr-cat-1-location-underground-services": "EUSR CAT 1 Location Underground Services",
    "eusr-shea-power": "EUSR SHEA Power",
    "eusr-shea-telecom": "EUSR SHEA Telecom",
    "first-aid-at-work-blended": "First Aid at Work (Blended)",
    "emergency-first-aid-at-work": "Emergency First Aid at Work",
    "mental-health-first-aid-2-day": "Mental Health First Aid - 2 day",
    "first-aid-at-work-requalification": "First Aid at Work ReQualification",
}


def normalize_reference_sort_label(label):
    label = str(label or "").strip().lower().replace("&", " and ")
    label = re.sub(r"[^a-z0-9]+", " ", label)
    return re.sub(r"\s+", " ", label).strip()


_ORDER_MAP = {normalize_reference_sort_label(label): i for i, label in enumerate(REFERENCE_ORDER)}


def reference_sort_weight(label):
    return _ORDER_MAP.get(normalize_reference_sort_label(label), 9999)


def reference_display_name(slug, name):
    return REFERENCE_DISPLAY_NAMES.get(_sanitize_title(slug), str(name or "").strip())


def natural_key(s):
    """strnatcasecmp()-like sort key."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", str(s).lower()) if t != ""]


# --------------------------------------------------------------------------------------------
# Filter index (custom_shop_get_filter_product_index) and derived lists
# --------------------------------------------------------------------------------------------
_cache = {"key": None}


def _index_version():
    from django.db.models import Count, Max
    from apps.catalog.models import Product
    agg = Product.objects.aggregate(n=Count("id"), m=Max("modified_at"))
    return (agg["n"], agg["m"])


def filter_product_index():
    """List of dicts, one per published product, in wc_get_products() order (date DESC)."""
    from apps.catalog.models import Product
    version = _index_version()
    if _cache.get("key") == version:
        return _cache["index"]
    products = (Product.objects.filter(status=Status.PUBLISH)
                .prefetch_related("categories", "tags").order_by("-created_at", "wp_id", "pk"))
    index = []
    for p in products:
        refs = product_reference_terms(p)
        venue = product_venue_name(p)
        first = product_first_date(p)
        index.append({
            "id": p.pk,
            "product": p,
            "name": p.title,
            "references": list(dict.fromkeys(r["slug"] for r in refs)),
            "reference_terms": refs,
            "venue": venue,
            "venue_normalized": normalize_venue_label(venue),
            "is_online": product_is_online(p),
            "is_nvq": "nvq" in {c.slug for c in p.categories.all()},
            "date": first,
            "date_ts": php_ts(first),
            "price": float(p.price or 0),
        })
    _cache.clear()
    _cache.update(key=version, index=index)
    return index


def reference_venue_date_map():
    """custom_shop_get_reference_venue_date_map(): {slug: {venue: [timestamps asc]}}."""
    out = {}
    for row in filter_product_index():
        if row["is_nvq"]:
            continue
        venue = row["venue_normalized"]
        if looks_like_date_label(venue):
            venue = ""
        if not venue or not row["date_ts"]:
            continue
        for term in row["reference_terms"]:
            lst = out.setdefault(term["slug"], {}).setdefault(venue, [])
            if row["date_ts"] not in lst:
                lst.append(row["date_ts"])
    for slug, venues in out.items():
        out[slug] = {v: sorted(venues[v]) for v in sorted(venues, key=natural_key)}
    return out


def all_course_references():
    """custom_shop_get_all_course_references() as [(slug, display_name), ...]."""
    refs = {}
    for row in filter_product_index():
        if row["is_nvq"]:
            continue
        for term in row["reference_terms"]:
            refs[term["slug"]] = reference_display_name(term["slug"], term["name"])
    items = list(refs.items())
    items.sort(key=lambda kv: (reference_sort_weight(kv[1]), kv[1].lower()))
    return items


def all_course_venues():
    venues = {}
    for row in filter_product_index():
        if row["is_nvq"]:
            continue
        v = row["venue_normalized"]
        if not v or looks_like_date_label(v):
            continue
        venues[v] = v
    return sorted(venues.values(), key=natural_key)


def course_name_by_reference(reference):
    if not reference:
        return ""
    for row in filter_product_index():
        if product_matches_reference(row, reference):
            return normalize_course_title(row["name"])
    return ""


def product_matches_reference(row, reference):
    reference = str(reference or "").strip()
    if not reference:
        return True
    slug = _sanitize_title(reference)
    return any(t["slug"] == slug or t["slug"].lower() == reference.lower() for t in row["reference_terms"])


def wp_json_encode(value):
    """json_encode() defaults: escaped slashes and \\uXXXX for non-ASCII; empty arrays as []."""
    def fix(v):
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()} if v else []
        if isinstance(v, (list, tuple)):
            return [fix(x) for x in v]
        return v
    return json.dumps(fix(value), separators=(",", ":"), ensure_ascii=True).replace("/", "\\/")


# --------------------------------------------------------------------------------------------
# Shop query (custom_course_filter_query) and grouped results
# --------------------------------------------------------------------------------------------
def shop_title(params):
    """custom_shop_page_title() for the shop."""
    if "course" in params:
        name = params.get("course", "").strip()
    elif "reference" in params:
        name = course_name_by_reference(params.get("reference", "").strip())
    else:
        name = ""
    name = name.strip()
    return f"Course Available for {name}" if name else "Course Available"


def nvq_levels_for(product):
    """custom_shop_get_nvq_product_levels(): levels 2–7 from the product's tags."""
    levels = []
    for t in product.tags.all():
        m = re.search(r"level\s*([2-7])", f"{t.name} {t.slug}".strip().lower())
        if m and int(m.group(1)) not in levels:
            levels.append(int(m.group(1)))
    return levels


def _absint(v):
    try:
        return abs(int(re.match(r"^\s*-?\d+", str(v)).group(0)))
    except (AttributeError, ValueError):
        return 0


def shop_matches(params, today):
    course = params.get("course", "").strip()
    reference = params.get("reference", "").strip()
    venue_filter = params.get("venue", "").strip()
    from_filter = params.get("from", "").strip()
    mode = normalize_mode_value(params.get("is_online", ""))
    search_mode = params.get("search_mode", "").strip()
    nvq_level = _absint(params.get("nvq_level", 0))
    nvq_course = _absint(params.get("nvq_course", 0))
    from_date = php_strtotime_date(from_filter) if from_filter else None
    tomorrow = today + datetime.timedelta(days=1)
    is_nvq_mode = search_mode == "nvq" or nvq_level > 0 or nvq_course > 0
    ref_slug = _sanitize_title(reference)

    matched = []
    for row in filter_product_index():
        if row["is_nvq"]:
            if is_nvq_mode:
                if nvq_level and nvq_level not in nvq_levels_for(row["product"]):
                    continue
                if nvq_course and row["product"].wp_id != nvq_course and row["id"] != nvq_course:
                    continue
                matched.append(row)
            continue
        if is_nvq_mode:
            continue
        if course and row["name"].lower() != course.lower():
            continue
        if reference and ref_slug not in row["references"] and reference.lower() not in [r.lower() for r in row["references"]]:
            continue
        if mode == "online" and not row["is_online"]:
            continue
        d = row["date"]
        if d and d < tomorrow:
            continue
        if from_date and d and d < from_date:
            continue
        if venue_filter:
            if is_online_venue_label(venue_filter):
                if not row["is_online"]:
                    continue
            elif row["venue_normalized"].lower() != normalize_venue_label(venue_filter).lower():
                continue
        matched.append(row)
    # uasort by date_ts (stable)
    matched.sort(key=lambda r: r["date_ts"])
    return matched


def card_item(p):
    first = product_first_date(p)
    return {
        "id": p.pk,
        "product": p,
        "name": normalize_course_title(p.title),
        "start_date": product_first_date_value(p),
        "end_date": product_end_date_value(p),
        "start_time": p.attr("Start Time", "start time"),
        "venue": product_venue_name(p),
        "spaces": p.attr("Available Spaces", "spaces"),
        "date": first,
    }


def grouped_results(rows):
    """[(month_label, [item, ...]), ...] like render_custom_shop_grouped_results()."""
    groups = {}
    for row in rows:
        item = card_item(row["product"])
        label = item["date"].strftime("%B %Y") if item["date"] else "No Date"
        groups.setdefault(label, []).append(item)
    return list(groups.items())


def search_filter(rows, s):
    """The main query's `s` on top of custom_course_filter_query(): every search term must occur in
    the title, excerpt or content (WP_Query::parse_search), and sst_exclude_hidden_terms_from_search
    drops products in the hidden 'uncategorised' category."""
    from apps.search.views import search_terms
    terms, _ = search_terms(s)
    hidden = {"uncategorized", "uncategorised"}
    out = []
    for row in rows:
        p = row["product"]
        if any(c.slug.lower() in hidden for c in p.categories.all()):
            continue
        haystacks = [(p.title or "").lower(), (p.short_description or "").lower(), (p.description or "").lower()]
        if all(any(t.lower() in h for h in haystacks) for t in terms):
            out.append(row)
    return out
