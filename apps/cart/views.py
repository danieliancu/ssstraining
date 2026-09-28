"""/basket/ and the WooCommerce cart AJAX endpoints used by the unchanged cart.js."""
import hashlib

from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.views.decorators.http import require_POST

from apps.core.bodyclass import page_classes
from apps.core.views import wp_render
from apps.pages.models import Page
from apps.seo.engine import Seo

from . import services
from .services import CartError


def basket(request):
    if request.method == "POST":
        return _basket_post(request)
    if "remove_item" in request.GET:
        key = request.GET["remove_item"]
        if request.GET.get("_wpnonce") == services.remove_nonce(request, key):
            product = services.remove_item(request, key)
            if product:
                services.add_notice(request, f'&ldquo;{product.title}&rdquo; removed. <a href="/basket/?undo_item={key}&#038;_wpnonce='
                                             f'{services.remove_nonce(request, key)}" class="restore-item">Undo?</a>')
        return HttpResponseRedirect("/basket/")
    if "undo_item" in request.GET:
        key = request.GET["undo_item"]
        if request.GET.get("_wpnonce") == services.remove_nonce(request, key):
            services.restore_item(request, key)
        return HttpResponseRedirect("/basket/")
    if "remove_coupon" in request.GET:
        services.remove_coupon(request, request.GET["remove_coupon"])
        services.add_notice(request, "Coupon has been removed.")
        return HttpResponseRedirect("/basket/")
    return render_basket(request)


def _basket_post(request):
    if "apply_coupon" in request.POST and request.POST.get("coupon_code"):
        try:
            services.apply_coupon(request, request.POST["coupon_code"])
            services.add_notice(request, "Coupon code applied successfully.")
        except CartError as exc:
            services.add_notice(request, str(exc), "error")
    elif "update_cart" in request.POST or "cart" in "".join(request.POST.keys()):
        errors = False
        for name, value in request.POST.items():
            if name.startswith("cart[") and name.endswith("][qty]"):
                key = name[5:-6]
                try:
                    services.set_quantity(request, key, value or 0)
                except (CartError, ValueError) as exc:
                    services.add_notice(request, str(exc), "error")
                    errors = True
        if not errors:
            services.add_notice(request, "Basket updated.")
    return HttpResponseRedirect("/basket/")


def render_basket(request):
    page = Page.objects.filter(slug="basket").first() or Page(title="Basket", slug="basket", wp_id=574)
    cart = services.get_cart(request)
    totals = services.calculate(cart, nebosh_dl=False) if cart else services.Totals()
    for line in totals.lines:
        line.nonce = services.remove_nonce(request, line.key)
        line.qty_id = hashlib.md5(line.key.encode()).hexdigest()[:13]
        line.max_qty = services.available_stock(line.product)
        if line.max_qty is not None:
            line.max_qty += 0
    get_token(request)
    context = {
        "page": page,
        "totals": totals,
        "notices_html": services.render_notices(services.pop_notices(request)),
        "cart_nonce": services.remove_nonce(request, "cart")[:10],
    }
    seo = Seo(request).singular(page, "/basket/")
    return wp_render(request, "woocommerce/basket.html", context, seo=seo,
                     body_class=page_classes(page, woo=("woocommerce-cart", "woocommerce-page")), profile="basket")


# --------------------------------------------------------------------- ?wc-ajax= endpoints
@require_POST
def ajax_apply_coupon(request):
    try:
        services.apply_coupon(request, request.POST.get("coupon_code", ""))
        services.add_notice(request, "Coupon code applied successfully.")
    except CartError as exc:
        services.add_notice(request, str(exc), "error")
    return HttpResponse(services.render_notices(services.pop_notices(request)))


@require_POST
def ajax_remove_coupon(request):
    services.remove_coupon(request, request.POST.get("coupon", ""))
    return HttpResponse(services.render_notices([{"kind": "success", "message": "Coupon has been removed."}]))


def ajax_get_cart_totals(request):
    from django.template.loader import render_to_string
    cart = services.get_cart(request)
    totals = services.calculate(cart, nebosh_dl=False) if cart else services.Totals()
    return HttpResponse(render_to_string("woocommerce/cart/cart-totals.html", {"totals": totals}, request=request))


def ajax_refreshed_fragments(request):
    from django.http import JsonResponse
    count = services.cart_count(request)
    return JsonResponse({"fragments": {}, "cart_hash": hashlib.md5(str(count).encode()).hexdigest()})


AJAX = {
    "apply_coupon": ajax_apply_coupon,
    "remove_coupon": ajax_remove_coupon,
    "get_cart_totals": ajax_get_cart_totals,
    "get_refreshed_fragments": ajax_refreshed_fragments,
}
