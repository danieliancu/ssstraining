from django.http import Http404, HttpResponseRedirect

from apps.catalog.models import Product


class WooCommerceCompatMiddleware:
    """Handles WooCommerce-style query strings on any URL, as WordPress does:

    * ?add-to-cart=<id>[&quantity=N] adds the product and redirects to the basket
      (functions.php template_redirect hooks; the add-to-cart notice is suppressed).
    * ?wc-ajax=<endpoint> dispatches the AJAX calls made by WooCommerce's cart.js / checkout.js.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        endpoint = request.GET.get("wc-ajax")
        if endpoint:
            return self._ajax(request, endpoint)
        if "add-to-cart" in request.GET and request.method in ("GET", "POST"):
            self._add_to_cart(request)
            return HttpResponseRedirect("/basket/")
        return self.get_response(request)

    def _add_to_cart(self, request):
        from apps.cart import services

        raw = request.GET.get("add-to-cart", "")
        if not raw.isdigit():
            return
        product = Product.objects.filter(pk=int(raw), status="publish").first() or \
            Product.objects.filter(wp_id=int(raw), status="publish").first()
        if not product:
            return
        try:
            quantity = int(request.GET.get("quantity") or request.POST.get("quantity") or 1)
        except ValueError:
            quantity = 1
        try:
            services.add_to_cart(request, product, quantity)
        except services.CartError as exc:
            services.add_notice(request, str(exc), "error")

    def _ajax(self, request, endpoint):
        from apps.cart.views import AJAX as CART_AJAX
        from apps.checkout.views import AJAX as CHECKOUT_AJAX

        handler = CART_AJAX.get(endpoint) or CHECKOUT_AJAX.get(endpoint)
        if handler is None:
            raise Http404
        # Mirror WC_AJAX: these endpoints return data, never a cached page.
        response = handler(request)
        response["Cache-Control"] = "no-store"
        return response
