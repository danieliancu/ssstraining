"""/checkout-2/, WooCommerce checkout AJAX (update_order_review, checkout) and Stripe."""
import json
import logging
from urllib.parse import parse_qs

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.cart import services as cart_services
from apps.core.bodyclass import page_classes
from apps.core.views import wp_render
from apps.mmc.models import MMCSettings
from apps.orders.models import Order
from apps.pages.models import Page
from apps.seo.engine import Seo

from . import services

log = logging.getLogger("apps.checkout")


def stripe_enabled():
    return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PUBLISHABLE_KEY)


def _page():
    return Page.objects.filter(slug="checkout-2").first() or Page(title="Checkout", slug="checkout-2", wp_id=4635)


def _context(request, totals, nebosh_dl=False):
    mmc = MMCSettings.load()
    fields = {k: v for k, v in mmc.delegate_fields().items() if v.get("enabled")}
    groups = []
    if (mmc.delegate_settings or {}).get("enable_capture", True):
        for line in services.delegate_groups(totals.lines):
            groups.append({"line": line, "seats": list(range(1, line.quantity + 1))})
    return {
        "totals": totals,
        "delegate_groups": groups,
        "delegate_fields": fields,
        "show_nebosh_dl": cart_services.cart_has_nebosh(totals.lines),
        "nebosh_dl_checked": nebosh_dl,
        "stripe_enabled": stripe_enabled(),
        "stripe_key": settings.STRIPE_PUBLISHABLE_KEY,
        "dl_fee_name": cart_services.NEBOSH_DL_FEE_NAME,
        "display_subtotal": totals.subtotal + sum((f[1] for f in totals.fees if f[0] == cart_services.NEBOSH_DL_FEE_NAME), 0),
    }


def checkout(request):
    cart = cart_services.get_cart(request)
    if not cart or not cart.items.exists():
        return HttpResponseRedirect("/basket/")
    totals = cart_services.calculate(cart, nebosh_dl=False)
    page = _page()
    get_token(request)
    context = {"page": page, **_context(request, totals),
               "notices_html": cart_services.render_notices(cart_services.pop_notices(request))}
    seo = Seo(request).singular(page, "/checkout-2/")
    return wp_render(request, "woocommerce/checkout/checkout.html", context, seo=seo,
                     body_class=page_classes(page, woo=("woocommerce-checkout", "woocommerce-page")), profile="checkout")


def _post_data(request):
    raw = request.POST.get("post_data", "")
    return {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}


@require_POST
def update_order_review(request):
    cart = cart_services.get_cart(request)
    if not cart or not cart.items.exists():
        return JsonResponse({"result": "failure", "messages": "", "reload": True,
                             "fragments": {"form.woocommerce-checkout": '<div class="woocommerce-error">Sorry, your session has expired. <a href="/shop/" class="wc-backward">Return to shop</a></div>'}})
    dl = bool(_post_data(request).get("sst_nebosh_dl"))
    cart.nebosh_dl = dl
    cart.save(update_fields=["nebosh_dl"])
    totals = cart_services.calculate(cart, nebosh_dl=dl)
    ctx = _context(request, totals, dl)
    return JsonResponse({
        "result": "success", "messages": "", "reload": False,
        "fragments": {
            ".woocommerce-checkout-review-order-table": render_to_string("woocommerce/checkout/review-order.html", ctx, request=request),
            ".woocommerce-checkout-payment": render_to_string("woocommerce/checkout/payment.html", ctx, request=request),
        },
    })


def _failure(messages, reload=False):
    html = cart_services.render_notices([{"kind": "error", "message": m} for m in messages]) if isinstance(messages, list) else messages
    return JsonResponse({"result": "failure", "messages": html, "refresh": False, "reload": reload})


@require_POST
def checkout_submit(request):
    cart = cart_services.get_cart(request)
    if not cart or not cart.items.exists():
        return _failure(["Sorry, your session has expired. <a href=\"/shop/\" class=\"wc-backward\">Return to shop</a>"], reload=True)
    post = request.POST
    dl = bool(post.get("sst_nebosh_dl"))
    totals = cart_services.calculate(cart, nebosh_dl=dl)
    errors = services.validate(post, totals)
    for line in totals.lines:
        stock = cart_services.available_stock(line.product)
        if not line.product.is_purchasable or not line.product.in_stock or (stock is not None and line.quantity > stock):
            errors.append(f"Sorry, &quot;{line.product.title}&quot; is not in stock. Please edit your basket and try again. "
                          "We apologise for any inconvenience caused.")
    if errors:
        return _failure(errors)
    modal = services.availability_error(totals)
    if modal:
        return _failure([modal])
    if post.get("payment_method") != "stripe" or not stripe_enabled():
        return _failure(["Invalid payment method."])
    token = post.get("sst_stripe_confirmation_token", "")
    if not token:
        return _failure(["Please enter your payment details."])

    order = services.create_order(request, post, cart, totals)
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    received = settings.SITE_URL + order.get_received_url()
    try:
        intent = stripe.PaymentIntent.create(
            amount=int((order.total * 100).quantize(1)),
            currency="gbp",
            confirm=True,
            confirmation_token=token,
            automatic_payment_methods={"enabled": True},
            return_url=received,
            receipt_email=order.billing_email,
            description=f"Site Safety Training - Order {order.number}",
            metadata={"order_id": order.pk, "order_key": order.order_key, "order_number": order.number},
            idempotency_key=f"order-{order.pk}-{order.order_key}",
        )
    except stripe.StripeError as exc:
        order.status = Order.Status.FAILED
        order.save(update_fields=["status"])
        order.stock_holds.all().delete()
        services.add_note(order, f"Stripe error: {exc.user_message or exc}")
        return _failure([exc.user_message or "There was an error processing your payment. Please try again."])
    Order.objects.filter(pk=order.pk).update(stripe_payment_intent=intent.id)
    if intent.status == "succeeded":
        services.finalize_paid(order.pk, intent.id)
        cart_services.clear(cart)
        return JsonResponse({"result": "success", "redirect": received})
    if intent.status in ("requires_action", "requires_source_action"):
        # Handled by static/sst/stripe-checkout.js (hashchange), like the WC Stripe gateway does.
        return JsonResponse({"result": "success", "redirect": f"#sst-stripe-confirm:{intent.client_secret}:{received}"})
    if intent.status == "processing":
        cart_services.clear(cart)
        Order.objects.filter(pk=order.pk).update(status=Order.Status.ON_HOLD)
        return JsonResponse({"result": "success", "redirect": received})
    order.status = Order.Status.FAILED
    order.save(update_fields=["status"])
    return _failure(["Your payment was not successful. Please try another payment method."])


def order_received(request, order_id):
    order = Order.objects.filter(pk=order_id, order_key=request.GET.get("key", "")).first()
    if order is None:
        raise Http404
    if order.status == Order.Status.PENDING and order.stripe_payment_intent and stripe_enabled():
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            intent = stripe.PaymentIntent.retrieve(order.stripe_payment_intent)
            if intent.status == "succeeded":
                services.finalize_paid(order.pk, intent.id)
                cart = cart_services.get_cart(request)
                if cart:
                    cart_services.clear(cart)
            elif intent.status in ("requires_payment_method", "canceled"):
                Order.objects.filter(pk=order.pk).update(status=Order.Status.FAILED)
        except stripe.StripeError as exc:
            log.warning("Could not verify payment for order %s: %s", order.pk, exc)
        order.refresh_from_db()
    page = _page()
    mmc = MMCSettings.load()
    delegates = [d for item in order.items.all() for d in item.delegates.all()]
    context = {"page": page, "order": order, "totals_rows": services.order_totals_rows(order),
               "delegates": delegates,
               "delegate_fields": {k: v for k, v in mmc.delegate_fields().items() if v.get("enabled")},
               "notices_html": ""}
    seo = Seo(request).singular(page, "/checkout-2/")
    seo.robots = "noindex, follow"
    return wp_render(request, "woocommerce/checkout/order-received.html", context, seo=seo,
                     body_class=page_classes(page, woo=("woocommerce-order-received", "woocommerce-checkout", "woocommerce-page")),
                     profile="checkout")


def order_pay(request, order_id):
    return HttpResponseRedirect("/checkout-2/")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    import stripe
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=500)
    try:
        event = stripe.Webhook.construct_event(request.body, request.headers.get("Stripe-Signature", ""),
                                               settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)
    obj = event["data"]["object"]
    order_id = (obj.get("metadata") or {}).get("order_id")
    if event["type"] == "payment_intent.succeeded" and order_id:
        services.finalize_paid(int(order_id), obj["id"])
    elif event["type"] == "payment_intent.payment_failed" and order_id:
        order = Order.objects.filter(pk=int(order_id), paid_at__isnull=True).first()
        if order:
            order.status = Order.Status.FAILED
            order.save(update_fields=["status"])
            order.stock_holds.all().delete()
            services.add_note(order, "Stripe: payment failed.")
    elif event["type"] == "charge.refunded":
        order = Order.objects.filter(stripe_payment_intent=obj.get("payment_intent")).first()
        if order:
            full = obj.get("amount_refunded") == obj.get("amount")
            if full:
                order.status = Order.Status.REFUNDED
                order.save(update_fields=["status"])
            services.add_note(order, f"Stripe refund of £{obj.get('amount_refunded', 0) / 100:.2f}.")
    return HttpResponse(json.dumps({"received": True}), content_type="application/json")


AJAX = {
    "update_order_review": update_order_review,
    "checkout": checkout_submit,
}
