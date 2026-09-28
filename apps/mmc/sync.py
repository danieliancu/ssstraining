"""MMC → catalog sync. Port of sync_single_session_to_product, sync_single_nvq_to_product and
friends from the WordPress plugin, with the same filters, titles, SKUs, prices and attributes."""
import json
import re
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import DeletedProduct, Product, ProductCategory, ProductTag

from .client import MMCClient, MMCError, mmc_log
from .models import MMCSettings, SyncRun

# get_manual_venue_name_to_id_map()
VENUE_NAME_TO_ID = {
    "Barking": "DweUP8eXOL", "Chelmsford": "L8PiBvlmpL", "Chelmsford - Moulsham Mill": "DnrSgAkxGD",
    "Chelmsford - The Willow Centre": "LmPIYbEnxM", "Classroom": "qkpfN5nAzD", "Colchester": "LdXuwoWaRL",
    "Crawley": "Me9iQJ3EBM", "Dartford": "DXQubk2ynM", "Grimsby": "DJPh4OnreL", "Historical": "DQ3T1BYnjL",
    "Hull": "qNbFgwvWYq", "Peterborough": "MB3H5mAYwL", "Sheffield": "DvEtodPzJq",
    "Sheffield Mexborough": "Mz5UAG1Y0D", "Stratford": "LybHWRmO7q", "Waltham Abbey": "MO0fV4GANL",
}
VENUE_ID_TO_NAME = {v: k for k, v in VENUE_NAME_TO_ID.items()}


def _norm_venue(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def resolve_venue_id(name, venue_id=""):
    venue_id = str(venue_id or "").strip()
    if venue_id:
        return venue_id
    needle = _norm_venue(name)
    if not needle:
        return ""
    return next((vid for vname, vid in VENUE_NAME_TO_ID.items() if _norm_venue(vname) == needle), "")


def resolve_venue_name(venue_id, name=""):
    name = str(name or "").strip()
    if name:
        return name
    return VENUE_ID_TO_NAME.get(str(venue_id or "").strip(), "")


def _get(data, *path):
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def php_str(value):
    """(string) cast as PHP does for JSON-decoded values."""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return "" if value is None else str(value)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def build_title(session, fmt):
    course_title = _get(session, "course", "title") or session.get("title") or ""
    first_raw = _get(session, "duration", "first_date") or session.get("date") or ""
    first = parse_date(first_raw)
    title = fmt or "{course_title} | {first_date}"
    for key, val in {
        "{course_title}": course_title,
        "{course_reference}": _get(session, "course", "reference") or "",
        "{venue_name}": _get(session, "venue", "name") or "",
        "{first_date}": first.strftime("%d/%m/%Y") if first else "",
    }.items():
        title = title.replace(key, str(val))
    title = title.replace("-", "|").replace("–", "|").replace("—", "|")
    title = re.sub(r"\s*\|\s*", " | ", title)
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"(\|\s*)+", "| ", title)
    title = title.strip(" \t\n\r\0\x0b|")
    return title or course_title or "MMC Session"


def build_sku(data, fmt, kind="session"):
    fmt = fmt or "{course_reference}-{first_date}"
    if kind == "session":
        first = parse_date(_get(data, "duration", "first_date") or data.get("date"))
        values = {"{course_id}": _get(data, "course", "id") or "", "{session_id}": data.get("id") or "",
                  "{course_reference}": _get(data, "course", "reference") or "",
                  "{first_date}": first.strftime("%Y%m%d") if first else ""}
    else:
        values = {"{course_id}": data.get("id") or "", "{session_id}": "",
                  "{course_reference}": data.get("reference") or "", "{first_date}": ""}
    sku = fmt
    for key, val in values.items():
        sku = sku.replace(key, str(val))
    sku = re.sub(r"\s+", "-", sku)
    sku = re.sub(r"[^a-zA-Z0-9\-_]", "", sku)
    sku = re.sub(r"-+", "-", sku).strip("-")
    return sku


def safe_sku(desired, product, hint):
    """set_product_sku_safe(): append -<hint> / -<hint>-N on collision."""
    if not desired:
        return product.sku
    hint = re.sub(r"[^a-zA-Z0-9\-_]", "", str(hint or "")) or "mmc"
    candidate = desired
    for attempt in range(30):
        clash = Product.objects.filter(sku=candidate).exclude(pk=product.pk).exists()
        if not clash:
            return candidate
        candidate = f"{desired}-{hint}" if attempt == 0 else f"{desired}-{hint}-{attempt + 1}"
    return product.sku


def unique_slug(title, product):
    base = slugify(title.replace("/", "-").replace(".", "-"))[:190] or "product"
    slug, n = base, 2
    while Product.objects.filter(slug=slug).exclude(pk=product.pk).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def extract_field(session, field):
    """extract_session_field_value()"""
    if field == "venue.id":
        return resolve_venue_id(_get(session, "venue", "name"), _get(session, "venue", "id"))
    if field == "venue.name":
        return resolve_venue_name(_get(session, "venue", "id"), _get(session, "venue", "name"))
    if field == "days":
        days = session.get("days")
        if not isinstance(days, list):
            return ""
        return ", ".join(d["date"] for d in days if isinstance(d, dict) and d.get("date"))
    value = session
    for seg in field.split("."):
        if not isinstance(value, dict) or seg not in value:
            return ""
        value = value[seg]
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        return ", ".join(json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else php_str(v) for v in value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return php_str(value)


def session_prices(session):
    price = sale = None
    p = session.get("price")
    if isinstance(p, dict):
        for key in ("exclusive_amount", "inclusive_amount", "amount"):
            if p.get(key) not in (None, ""):
                price = Decimal(str(p[key]))
                break
        s = p.get("sale_price")
        if isinstance(s, dict):
            for key in ("exclusive_amount", "inclusive_amount", "amount"):
                if s.get(key) not in (None, ""):
                    sale = Decimal(str(s[key]))
                    break
        elif s not in (None, ""):
            sale = Decimal(str(s))
    elif p not in (None, ""):
        price = Decimal(str(p))
    if sale is None and session.get("sale_price") not in (None, ""):
        sale = Decimal(str(session["sale_price"]))
    if price is not None and sale is not None and sale >= price:
        sale = None
    return price, sale


class Syncer:
    def __init__(self, client=None, settings=None, dry_run=False, today=None):
        self.client = client or MMCClient()
        self.settings = settings or MMCSettings.load()
        self.dry_run = dry_run
        self.today = today or timezone.localdate()
        self.report = []

    # --- filters --------------------------------------------------------------------
    def skip_reason(self, session):
        s = self.settings
        venue = _get(session, "venue", "name") or ""
        if s.allowed_venues and venue not in s.allowed_venues:
            if not (s.include_online_sessions and session.get("is_online") and not venue):
                return f"venue '{venue}' not allowed"
        if s.allowed_course_types:
            if (_get(session, "delivery_type", "label") or "") not in s.allowed_course_types:
                return "course type not allowed"
        if s.allowed_course_refs:
            if (_get(session, "course", "reference") or "") not in s.allowed_course_refs:
                return "course reference not allowed"
        if s.future_only:
            first = parse_date(_get(session, "duration", "first_date") or session.get("date"))
            if first and first < self.today:
                return "past session"
        return None

    # --- sessions -------------------------------------------------------------------
    def sync_session(self, session):
        """Returns 'created' | 'updated' | 'skipped'."""
        sid = session.get("id")
        if not sid:
            return "skipped"
        reason = self.skip_reason(session)
        if reason:
            self.report.append({"session": sid, "result": "skipped", "reason": reason})
            return "skipped"
        s = self.settings
        desired_sku = build_sku(session, s.sku_format, "session")
        product = Product.objects.filter(mmc_session_id=str(sid)).first()
        if product is None and desired_sku:
            product = Product.objects.filter(sku=desired_sku).first()
        created = product is None
        title = build_title(session, s.title_format)
        price, sale = session_prices(session)
        first_raw = _get(session, "duration", "first_date") or session.get("date") or ""
        raw_location = _get(session, "venue", "name") or ""
        venue_id = resolve_venue_id(raw_location, _get(session, "venue", "id"))
        location = resolve_venue_name(venue_id, raw_location)
        spaces = session.get("available_spaces")
        reference = _get(session, "course", "reference") or ""
        description = (_get(session, "course", "description") or _get(session, "course", "description_html")
                       or _get(session, "course", "description_text") or "")
        if not description and _get(session, "course", "id") and not self.dry_run:
            try:
                full = self.client.course(_get(session, "course", "id")) or {}
                description = full.get("description") or full.get("description_html") or full.get("description_text") or ""
            except MMCError:
                pass
        self.report.append({"session": sid, "result": "created" if created else "updated", "title": title,
                            "sku": desired_sku, "price": str(price), "spaces": spaces, "reference": reference})
        if self.dry_run:
            return "created" if created else "updated"

        with transaction.atomic():
            product = product or Product(kind=Product.Kind.SESSION, status="publish")
            product.kind = Product.Kind.SESSION
            product.title = title
            if created:
                product.slug = unique_slug(title, product)
            product.sku = safe_sku(desired_sku, product, sid)
            if price is not None and (created or s.price_sync_mode == "auto" or
                                      (s.price_sync_mode == "initial" and product.regular_price is None)):
                product.regular_price = price
                product.sale_price = sale
            if spaces is not None:
                product.stock_qty = int(spaces)
                product.manage_stock = True
                product.stock_status = "instock" if int(spaces) > 0 else "outofstock"
            elif created:
                product.manage_stock = False
            product.mmc_session_id = str(sid)
            product.mmc_course_id = str(_get(session, "course", "id") or "")
            product.mmc_venue_id = venue_id
            product.first_date = parse_date(first_raw) or product.first_date
            product.last_date = parse_date(_get(session, "duration", "last_date")) or product.last_date
            if location:
                product.venue_name = location
            product.is_online = bool(session.get("is_online"))
            product.attributes = self.session_attributes(session, product.attributes)
            product.raw_payload = session
            product.synced_at = timezone.now()
            product.save()
            self.assign_reference_category(product, reference, description)
        return "created" if created else "updated"

    def session_attributes(self, session, existing):
        """sync_session_attributes_to_product(): replace the MMC attributes, keep any others."""
        mapped_labels = {m["label"] for m in self.settings.attribute_mapping} if self.settings.attribute_mapping else set()
        keep = [a for a in (existing or []) if a.get("source") != "mmc" and a.get("name") not in mapped_labels]
        attrs = []
        for m in self.settings.attribute_fields():
            value = extract_field(session, m["field"])
            if value in ("", None):
                continue
            attrs.append({"name": m.get("label") or m["field"], "value": value, "visible": bool(m.get("visible")),
                          "source": "mmc"})
        return keep + attrs

    def assign_reference_category(self, product, reference, description=""):
        if not reference:
            return
        cat = ProductCategory.objects.filter(name=reference).first()
        if cat is None:
            base = slugify(reference) or "category"
            slug, n = base, 2
            while ProductCategory.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            cat = ProductCategory.objects.create(name=reference, slug=slug, description=description or "",
                                                 mmc_reference=reference)
        elif description and cat.description != description:
            cat.description = description
            cat.save(update_fields=["description"])
        product.categories.add(cat)

    def sync_sessions(self, limit=0):
        run = SyncRun.objects.create(kind=SyncRun.Kind.SESSIONS, dry_run=self.dry_run)
        try:
            if self.settings.auto_delete_past and not self.dry_run:
                run.deleted = self.delete_past()
            for session in self.client.sessions(per_page=50):
                result = self.sync_session(session)
                if result == "created":
                    run.created += 1
                elif result == "updated":
                    run.updated += 1
                else:
                    run.skipped += 1
                if limit and run.created + run.updated >= limit:
                    break
            run.ok = True
        except MMCError as exc:
            run.error = str(exc)
            mmc_log(f"Session sync failed: {exc}", "error")
        finally:
            run.finished_at = timezone.now()
            run.report = self.report[-2000:]
            run.save()
            _clear_catalog_caches()
        mmc_log(f"Session sync complete. Created {run.created}, updated {run.updated}, skipped {run.skipped}, "
                f"deleted {run.deleted}.")
        return run

    def delete_past(self):
        past = Product.objects.filter(kind=Product.Kind.SESSION, first_date__lt=self.today).exclude(mmc_session_id=None)
        count = 0
        for product in past:
            cat = product.categories.exclude(slug__in=["uncategorised", "uncategorized"]).first()
            DeletedProduct.objects.update_or_create(slug=product.slug, defaults={"category": cat})
            product.delete()
            count += 1
        mmc_log(f"Auto-delete past session products: {count} products removed.")
        return count

    # --- NVQs -------------------------------------------------------------------------
    def sync_nvqs(self):
        run = SyncRun.objects.create(kind=SyncRun.Kind.NVQ, dry_run=self.dry_run)
        try:
            for course in self.client.courses(per_page=100):
                conf = self.settings.nvq_settings.get(str(course.get("id"))) or {}
                if not conf.get("enabled") or _get(course, "type", "key") != "nvq":
                    run.skipped += 1
                    continue
                if self.sync_nvq(course, conf.get("price_mode") or "full") == "created":
                    run.created += 1
                else:
                    run.updated += 1
            run.ok = True
        except MMCError as exc:
            run.error = str(exc)
            mmc_log(f"NVQ sync failed: {exc}", "error")
        finally:
            run.finished_at = timezone.now()
            run.report = self.report[-2000:]
            run.save()
            _clear_catalog_caches()
        return run

    def sync_nvq(self, course, price_mode="full"):
        cid = str(course["id"])
        product = Product.objects.filter(mmc_nvq_id=cid).first()
        created = product is None
        title = course.get("title") or "NVQ Course"
        sku = build_sku(course, self.settings.sku_format, "nvq") + ("-DEP" if price_mode == "50_50" else "")
        p = course.get("price") or {}
        amount = p.get("amount") if isinstance(p, dict) else None
        if amount is None and isinstance(p, dict):
            amount = p.get("inclusive_amount")
        if amount is None:
            amount = course.get("cost") or 0
        price = Decimal(str(amount))
        if price_mode == "50_50":
            price = price * Decimal("0.5")
        description = (course.get("description") or "") + ("\n\n" if course.get("description") else "")
        units = course.get("nvq_units")
        if isinstance(units, list) and units:
            from django.utils.html import escape
            description += "<strong>Units:</strong><ul>" + "".join(
                f"<li>{escape(u['title'])}</li>" for u in units if isinstance(u, dict) and u.get("title")) + "</ul>"
        self.report.append({"nvq": cid, "result": "created" if created else "updated", "title": title, "price": str(price)})
        if self.dry_run:
            return "created" if created else "updated"
        with transaction.atomic():
            product = product or Product(kind=Product.Kind.NVQ)
            product.kind = Product.Kind.NVQ
            product.title = title
            if created:
                product.slug = unique_slug(title, product)
            if sku:
                product.sku = safe_sku(sku, product, cid)
            product.regular_price = price
            product.sale_price = None
            product.description = description
            product.mmc_nvq_id = cid
            product.price_mode = price_mode
            product.status = "publish"
            product.virtual = True
            product.manage_stock = False
            product.raw_payload = course
            product.synced_at = timezone.now()
            product.save()
            nvq_cat = ProductCategory.objects.filter(slug="nvq").first() or ProductCategory.objects.filter(name="NVQ").first()
            cat_desc = course.get("description") or course.get("description_text") or ""
            if nvq_cat is None:
                nvq_cat = ProductCategory.objects.create(name="NVQ", slug="nvq", description=cat_desc)
            elif cat_desc and nvq_cat.description != cat_desc:
                nvq_cat.description = cat_desc
                nvq_cat.save(update_fields=["description"])
            product.categories.set([nvq_cat])
            match = re.search(r"\b(Level\s+[2-7])\b", title, re.I)
            if match:
                label = re.sub(r"\s+", " ", match.group(1).strip())
                label = label[0].upper() + label[1:]
                tag, _ = ProductTag.objects.get_or_create(slug=slugify(label), defaults={"name": label})
                product.tags.remove(*product.tags.filter(name__iregex=r"^Level\s+[2-7]$"))
                product.tags.add(tag)
        return "created" if created else "updated"

    # --- single-session events ----------------------------------------------------------
    def update_availability(self, session_id):
        data = self.client.availability(session_id)
        spaces = data.get("available_spaces")
        if spaces is None:
            mmc_log(f"Availability response missing available_spaces for session {session_id}", "error")
            return 0
        spaces = int(spaces)
        n = Product.objects.filter(mmc_session_id=str(session_id)).update(
            stock_qty=spaces, manage_stock=True, stock_status="instock" if spaces > 0 else "outofstock")
        _clear_catalog_caches()
        return n

    def lifecycle(self, session_id, event_type):
        session = self.client.session(session_id)
        if not session:
            mmc_log(f"Failed to fetch session {session_id} for lifecycle event.", "error")
            return
        result = self.sync_session(session)
        mmc_log(f"Lifecycle sync for session {session_id} result: {result}")
        for product in Product.objects.filter(mmc_session_id=str(session_id)):
            if event_type == "session.closed":
                behaviour = self.settings.closed_session_behaviour
                if behaviour == "delete":
                    DeletedProduct.objects.update_or_create(slug=product.slug, defaults={"category": product.categories.first()})
                    product.delete()
                    continue
                if behaviour == "draft":
                    product.status = "draft"
                elif behaviour == "outofstock":
                    product.manage_stock, product.stock_qty, product.stock_status = True, 0, "outofstock"
            if event_type == "session.reopened" and product.status in ("draft", "private"):
                product.status = "publish"
            if event_type == "session.full":
                product.manage_stock, product.stock_qty, product.stock_status = True, 0, "outofstock"
            product.save()
        _clear_catalog_caches()

    def course_event(self, course_id):
        from django.core.cache import cache
        cache.delete(f"mmc_course_{course_id}")
        course = self.client.course(course_id, use_cache=False)
        if not course or _get(course, "type", "key") != "nvq":
            return
        conf = self.settings.nvq_settings.get(str(course_id)) or {}
        if not conf.get("enabled"):
            mmc_log(f"NVQ Course {course_id} is not enabled for sync.")
            return
        self.sync_nvq(course, conf.get("price_mode") or "full")
        _clear_catalog_caches()

    # --- lists for the admin filter checklists ------------------------------------------
    def refresh_lists(self):
        venues, refs, types = set(), set(), set()
        try:
            for v in self.client.venues():
                if v.get("name"):
                    venues.add(v["name"])
        except MMCError:
            pass
        for session in self.client.sessions(per_page=50):
            if _get(session, "venue", "name"):
                venues.add(session["venue"]["name"])
            if _get(session, "course", "reference"):
                refs.add(session["course"]["reference"])
            if _get(session, "delivery_type", "label"):
                types.add(session["delivery_type"]["label"])
        s = self.settings
        s.venue_list, s.course_ref_list, s.course_type_list = sorted(venues), sorted(refs), sorted(types)
        s.save(update_fields=["venue_list", "course_ref_list", "course_type_list"])


def _clear_catalog_caches():
    """Invalidate cached shop filters/menus after products change."""
    from django.core.cache import cache
    try:
        from apps.catalog import services
        if hasattr(services, "clear_caches"):
            services.clear_caches()
    except ImportError:
        pass
    from apps.navigation.render import clear_menu_cache
    clear_menu_cache()
    cache.delete("sst_filter_index")
