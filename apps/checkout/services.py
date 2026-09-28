"""Checkout: validation (WooCommerce billing rules + MMC delegate rules + live availability),
order creation, payment finalisation, MMC bookings and order emails."""
import logging
import re
from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape

from apps.cart import services as cart_services
from apps.mmc.client import MMCClient, MMCError, mmc_log
from apps.mmc.models import MMCSettings
from apps.orders.models import Delegate, MMCBooking, Order, OrderCoupon, OrderFee, OrderItem, OrderNote

log = logging.getLogger("apps.checkout")

BILLING_FIELDS = [
    # (name, label, required)
    ("billing_email", "Email address", True),
    ("billing_first_name", "First name", True),
    ("billing_last_name", "Last name", True),
    ("billing_country", "Country / Region", True),
    ("billing_address_1", "Street address", True),
    ("billing_address_2", "Flat, suite, unit, etc.", False),
    ("billing_city", "Town / City", True),
    ("billing_state", "County", False),
    ("billing_postcode", "Postcode", True),
    ("billing_phone", "Phone", False),
]
UK_POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?|GIR) ?\d[A-Z]{2}$", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UNAVAILABLE_PHONE_HREF = "03334440018"


def requires_delegates(product):
    """product_requires_delegate_details(): MMC session, MMC NVQ, or an NVQ category product."""
    slugs = {c.slug.lower() for c in product.categories.all()}
    return bool(product.mmc_session_id or product.mmc_nvq_id or slugs & {"nvq", "nvqs"})


def delegate_groups(lines):
    return [l for l in lines if requires_delegates(l.product)]


def parse_delegates(post):
    """tz_mmc_delegates[<cart key>][<i>][<field>] → {key: {i: {field: value}}}"""
    out = {}
    for name in post.keys():
        m = re.match(r"^tz_mmc_delegates\[([^\]]+)\]\[(\d+)\]\[([^\]]+)\]$", name)
        if m:
            key, idx, field = m.group(1), int(m.group(2)), m.group(3)
            out.setdefault(key, {}).setdefault(idx, {})[field] = post.get(name, "").strip()
    return out


def validate(post, totals, mmc_settings=None):
    errors = []
    for name, label, required in BILLING_FIELDS:
        value = (post.get(name) or "").strip()
        if required and not value:
            errors.append(f"<strong>Billing {label}</strong> is a required field.")
    email = (post.get("billing_email") or "").strip()
    if email and not EMAIL.match(email):
        errors.append("<strong>Billing Email address</strong> is not a valid email address.")
    postcode = (post.get("billing_postcode") or "").strip()
    if postcode and (post.get("billing_country") or "GB") == "GB" and not UK_POSTCODE.match(postcode):
        errors.append("<strong>Billing Postcode</strong> is not a valid postcode / ZIP.")
    phone = (post.get("billing_phone") or "").strip()
    if phone and re.sub(r"[\s\#0-9_\-\+/\(\)\.]", "", phone):
        errors.append("<strong>Billing Phone</strong> is not a valid phone number.")

    mmc_settings = mmc_settings or MMCSettings.load()
    ds = mmc_settings.delegate_settings or {}
    if ds.get("enable_capture", True):
        fields = mmc_settings.delegate_fields()
        posted = parse_delegates(post)
        for line in delegate_groups(totals.lines):
            group = posted.get(line.key, {})
            name = line.product.title
            if ds.get("enforce_quantity", True) and len(group) < line.quantity:
                errors.append(f'Please provide details for all delegates for &quot;{escape(name)}&quot;.')
                continue
            for i in range(1, line.quantity + 1):
                row = group.get(i, {})
                for key, conf in fields.items():
                    if not conf.get("enabled") or not conf.get("required"):
                        continue
                    value = row.get(key, "")
                    if not value:
                        label = conf.get("label") or key.capitalize()
                        errors.append(f'{escape(label)} is required for delegate {i} on &quot;{escape(name)}&quot;.')
                    if key == "email" and value and not EMAIL.match(value):
                        errors.append(f'Please enter a valid email for delegate {i} on &quot;{escape(name)}&quot;.')
    return errors


def availability_error(totals, client=None):
    """validate_session_availability_at_checkout(): live MMC check; API failures let checkout through."""
    client = client or MMCClient(timeout=10)
    if not client.configured:
        return None
    for line in totals.lines:
        sid = line.product.mmc_session_id
        if not sid:
            continue
        try:
            data = client.availability(sid)
        except MMCError as exc:
            mmc_log(f"Checkout availability check failed for session {sid}: {exc}", "error")
            continue
        spaces = int(data.get("available_spaces") or 0)
        is_available = bool(data.get("is_available", False))
        is_closed = bool(data.get("is_closed", True))
        if is_closed or not is_available or spaces < line.quantity:
            message = (f'Sorry, for <strong>{escape(line.product.title)}</strong> there are no more places available,<br>please call '
                       f'<a href="tel:{UNAVAILABLE_PHONE_HREF}" class="tz-mmc-tel">0333 444 0018</a> or edit your basket and try a '
                       f'different one. We apologise for any inconvenience caused.')
            return render_to_string("woocommerce/checkout/unavailable-modal.html", {"message": message})
    return None


@transaction.atomic
def create_order(request, post, cart, totals):
    order = Order.objects.create(
        status=Order.Status.PENDING,
        billing_first_name=post.get("billing_first_name", "").strip(),
        billing_last_name=post.get("billing_last_name", "").strip(),
        billing_company=post.get("billing_company", "").strip(),
        billing_address_1=post.get("billing_address_1", "").strip(),
        billing_address_2=post.get("billing_address_2", "").strip(),
        billing_city=post.get("billing_city", "").strip(),
        billing_state=post.get("billing_state", "").strip(),
        billing_postcode=post.get("billing_postcode", "").strip().upper(),
        billing_country=post.get("billing_country", "GB") or "GB",
        billing_email=post.get("billing_email", "").strip(),
        billing_phone=post.get("billing_phone", "").strip(),
        customer_note=post.get("order_comments", "").strip(),
        subtotal=totals.subtotal,
        discount_total=totals.discount_total,
        fee_total=totals.fee_total,
        tax_total=totals.tax_total,
        total=totals.total,
        payment_method=post.get("payment_method", "stripe"),
        payment_method_title="Card",
        nebosh_dl=any(f[0] == cart_services.NEBOSH_DL_FEE_NAME for f in totals.fees),
        customer_ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )
    posted = parse_delegates(post)
    fields = MMCSettings.load().delegate_fields()
    for line in totals.lines:
        item = OrderItem.objects.create(
            order=order, product=line.product, name=line.product.title, sku=line.product.sku,
            mmc_session_id=line.product.mmc_session_id or "", mmc_nvq_id=line.product.mmc_nvq_id or "",
            cart_key=line.key, unit_price=line.unit_price, quantity=line.quantity,
            line_subtotal=line.subtotal, line_total=line.total, line_tax=line.tax)
        if requires_delegates(line.product):
            group = posted.get(line.key, {})
            for i in range(1, line.quantity + 1):
                row = group.get(i, {})
                extra = {k: v for k, v in row.items() if k not in ("name", "email", "phone") and fields.get(k, {}).get("enabled")}
                Delegate.objects.create(item=item, index=i - 1, name=row.get("name", ""), email=row.get("email", ""),
                                        phone=row.get("phone", ""), extra=extra)
    for name, amount, tax in totals.fees:
        OrderFee.objects.create(order=order, name=name, amount=amount, tax=tax)
    for code, amount, tax in totals.discounts:
        OrderCoupon.objects.create(order=order, code=code, discount=amount, discount_tax=tax)
    cart_services.hold_stock(order, totals.lines)
    request.session["sst_pending_order"] = order.pk
    request.session["sst_order_cart"] = str(cart.token)
    return order


def add_note(order, text, customer=False):
    OrderNote.objects.create(order=order, note=text, is_customer_note=customer)


def finalize_paid(order_id, payment_intent=None):
    """Mark paid, reduce stock, send MMC bookings and emails. Safe to call more than once."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.paid_at:
            return order
        order.status = Order.Status.PROCESSING
        order.paid_at = timezone.now()
        if payment_intent:
            order.stripe_payment_intent = payment_intent
        order.save()
        for item in order.items.select_related("product"):
            p = item.product
            if p and p.manage_stock and p.stock_qty is not None:
                p.stock_qty = max(0, p.stock_qty - item.quantity)
                p.stock_status = "instock" if p.stock_qty > 0 else "outofstock"
                p.save(update_fields=["stock_qty", "stock_status"])
        order.stock_holds.all().delete()
        for coupon in order.coupons.all():
            from apps.cart.models import Coupon
            Coupon.objects.filter(code=coupon.code).update(usage_count=models_F("usage_count") + 1)
        add_note(order, f"Payment complete (Stripe {order.stripe_payment_intent}). Order status changed from Pending payment to Processing.")
    send_bookings(order)
    send_order_emails(order)
    return order


def models_F(name):
    from django.db.models import F
    return F(name)


def gateway_to_mmc_method(gateway):
    """map_wc_gateway_to_mmc_payment_method()"""
    g = (gateway or "").lower()
    for needle in ("stripe", "woocommerce_payments", "wcpay", "paypal", "ppcp", "square", "sagepay", "worldpay",
                   "klarna", "mollie", "adyen", "card"):
        if needle in g:
            return "card_details"
    return "manual"


def booking_payload(order, delegate, item):
    """process_booking_payload() for one delegate."""
    billing_name = order.billing_full_name
    name = delegate.name or billing_name
    email = delegate.email or order.billing_email
    phone = delegate.phone or order.billing_phone
    extra = delegate.extra or {}
    payload = {
        "payment_method": gateway_to_mmc_method(order.payment_method),
        "name": name,
        "email": email,
        "address_street": extra.get("address_street") or order.billing_address_1,
        "address_city": extra.get("address_city") or order.billing_city,
        "address_postcode": extra.get("address_postcode") or order.billing_postcode,
        "address_country": extra.get("address_country") or order.billing_country or "United Kingdom",
    }
    line_2 = extra.get("address_line_2") or order.billing_address_2
    if line_2:
        payload["address_line_2"] = line_2
    county = extra.get("address_county") or order.billing_state
    if county:
        payload["address_county"] = county
    if billing_name and billing_name != name:
        payload["customer_name"] = billing_name
    if order.billing_email and order.billing_email != email:
        payload["customer_email"] = order.billing_email
    if item.mmc_nvq_id:
        payload["course_id"] = item.mmc_nvq_id
    else:
        payload["session_id"] = item.mmc_session_id
    if phone:
        payload["phone"] = phone
    return payload


def send_bookings(order, client=None, only_failed=False):
    client = client or MMCClient()
    created = []
    for item in order.items.all():
        if not (item.mmc_session_id or item.mmc_nvq_id):
            continue
        entity = f"{'nvq' if item.mmc_nvq_id else 'session'} {item.mmc_nvq_id or item.mmc_session_id}"
        for delegate in item.delegates.all():
            booking, _ = MMCBooking.objects.get_or_create(delegate=delegate)
            if booking.status == MMCBooking.Status.SENT or (only_failed and booking.status != MMCBooking.Status.FAILED):
                continue
            payload = booking_payload(order, delegate, item)
            booking.payload = payload
            booking.attempts += 1
            if not (payload["name"] and payload["email"]):
                booking.status, booking.last_error = MMCBooking.Status.FAILED, "missing name/email"
                booking.save()
                continue
            try:
                result = client.create_booking(payload)
            except MMCError as exc:
                message = (exc.body or {}).get("message") if isinstance(exc.body, dict) else ""
                booking.status, booking.last_error = MMCBooking.Status.FAILED, message or str(exc)
                booking.response = exc.body if isinstance(exc.body, dict) else {}
                booking.save()
                add_note(order, f"MMC booking error for {entity}: {booking.last_error}")
                notify_error("MMC Booking Failed", f"Failed to create booking for {entity}", order, booking.last_error)
                continue
            data = (result or {}).get("data") or {}
            booking.response = result or {}
            if data.get("id"):
                booking.status = MMCBooking.Status.SENT
                booking.mmc_booking_id = str(data["id"])
                booking.mmc_reference = str(data.get("reference") or "")
                created.append(booking.mmc_booking_id)
                add_note(order, f"MMC booking created: {booking.mmc_booking_id} for {entity}")
            else:
                booking.status = MMCBooking.Status.FAILED
                booking.last_error = "response missing booking id"
                add_note(order, f"MMC Booking response missing ID for {entity}")
                notify_error("MMC Booking Response Missing ID", f"Booking was sent but response is missing booking ID for {entity}", order, "")
            booking.save()
    if created and not MMCBooking.objects.filter(delegate__item__order=order).exclude(status=MMCBooking.Status.SENT).exists():
        Order.objects.filter(pk=order.pk).update(mmc_bookings_sent=True)
    return created


def notify_error(subject, message, order, details):
    to = MMCSettings.load().error_notification_email
    if not to:
        return
    body = f"{message}\n\nOrder: #{order.number}\nDetails: {details}\nTime: {timezone.now():%Y-%m-%d %H:%M:%S}"
    try:
        EmailMultiAlternatives(f"[MMC Integration] {subject}", body, settings.DEFAULT_FROM_EMAIL, [to]).send()
    except Exception as exc:  # never break checkout because an alert email failed
        log.warning("Could not send MMC error email: %s", exc)


# ---------------------------------------------------------------------------------- emails
def order_totals_rows(order, for_email=False):
    """WC_Order::get_order_item_totals() plus the theme filters. The theme skips its filters on
    checkout pages (is_checkout() is true on order-received), so the thank-you page shows the
    plain WooCommerce rows; emails get the NEBOSH DL fee merged into Subtotal and '(+ VAT)' labels."""
    from apps.core.templatetags.wp import wc_price
    dl_fee = sum((f.amount for f in order.fees.all() if f.name == cart_services.NEBOSH_DL_FEE_NAME), Decimal("0"))
    merge = for_email and dl_fee > 0
    rows = OrderedDict()
    rows["cart_subtotal"] = ("Subtotal:", wc_price(order.subtotal + (dl_fee if merge else 0)))
    for c in order.coupons.all():
        rows[f"coupon_{c.code}"] = ("Discount:", "-" + str(wc_price(c.discount)))
    for f in order.fees.all():
        if not (merge and f.name == cart_services.NEBOSH_DL_FEE_NAME):
            rows[f"fee_{f.pk}"] = (f"{f.name}:", wc_price(f.amount))
    rows["tax"] = ("VAT:", wc_price(order.tax_total))
    if order.payment_method_title:
        rows["payment_method"] = ("Payment method:", escape(order.payment_method_title))
    rows["order_total"] = ("Total:", wc_price(order.total))
    out = []
    for key, (label, value) in rows.items():
        if for_email and "total" in label.lower():
            label = label.rstrip() + " (+ VAT)"
        out.append({"key": key, "label": label, "value": value})
    return out


def send_order_emails(order):
    if order.emails_sent:
        return
    from apps.core.models import SiteOptions
    opts = SiteOptions.load()
    fields = MMCSettings.load().delegate_fields()
    enabled = {k: v for k, v in fields.items() if v.get("enabled")}
    delegates = [d for item in order.items.all() for d in item.delegates.all()]
    ctx = {"order": order, "totals": order_totals_rows(order, True), "options": opts, "delegate_fields": enabled,
           "delegates": delegates, "site_url": settings.SITE_URL}
    sender = f"{opts.order_email_from_name} <{settings.DEFAULT_FROM_EMAIL.split('<')[-1].rstrip('>')}>" \
        if "<" in settings.DEFAULT_FROM_EMAIL else settings.DEFAULT_FROM_EMAIL
    messages = [
        (f"Your {opts.site_name} order has been received!", "woocommerce/emails/customer-processing-order.html", [order.billing_email]),
    ]
    admins = settings.ORDER_ADMIN_EMAILS or ([opts.main_email_address] if opts.main_email_address else [])
    if admins:
        messages.append((f"[{opts.site_name}]: New order #{order.number}", "woocommerce/emails/admin-new-order.html", admins))
    for subject, template, to in messages:
        html = render_to_string(template, {**ctx, "email_heading": subject, "is_admin": "admin" in template})
        try:
            from premailer import transform
            html = transform(html, disable_validation=True, cssutils_logging_level=logging.CRITICAL)
        except Exception:
            pass
        msg = EmailMultiAlternatives(subject, re.sub(r"<[^>]+>", "", html), sender, to)
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception as exc:
            add_note(order, f"Could not send email '{subject}': {exc}")
            log.warning("Order email failed: %s", exc)
    Order.objects.filter(pk=order.pk).update(emails_sent=True)
