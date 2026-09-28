"""Session cart and WooCommerce-equivalent totals (prices ex VAT, 20% GB VAT rounded per line,
taxable fees, itemised tax totals)."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.catalog.models import Product

from .models import Cart, CartItem, Coupon, StockHold

VAT_RATE = Decimal("0.20")
VAT_LABEL = "VAT"
NEBOSH_DL_FEE_NAME = "NEBOSH distance learning"
NEBOSH_DL_FEE = Decimal("395.00")
NEBOSH_DL_SLUGS = {"nebosh-general", "nebosh-general-certificate", "nebosh-construction"}
SESSION_KEY = "sst_cart"
NOTICES_KEY = "wc_notices"
CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------------------ cart lookup
def get_cart(request, create=False):
    cart = getattr(request, "_sst_cart", None)
    if cart is not None:
        return cart
    token = request.session.get(SESSION_KEY)
    if token:
        cart = Cart.objects.filter(token=token).first()
    if cart is None and create:
        cart = Cart.objects.create()
        request.session[SESSION_KEY] = str(cart.token)
    request._sst_cart = cart
    return cart


def cart_items(cart):
    if cart is None:
        return []
    return list(cart.items.select_related("product").prefetch_related("product__categories"))


def cart_count(request):
    cart = get_cart(request)
    return sum(i.quantity for i in cart.items.all()) if cart else 0


def remove_nonce(request, key):
    return salted_hmac("sst-cart-remove", f"{key}:{request.session.session_key}").hexdigest()[:10]


# --------------------------------------------------------------------------------- notices
def add_notice(request, message, kind="success"):
    notices = request.session.get(NOTICES_KEY, [])
    notices.append({"kind": kind, "message": message})
    request.session[NOTICES_KEY] = notices


def pop_notices(request):
    return request.session.pop(NOTICES_KEY, [])


def render_notices(notices):
    """notices/success.php, error.php, notice.php markup."""
    out = []
    errors = [n for n in notices if n["kind"] == "error"]
    for n in notices:
        if n["kind"] == "success":
            out.append(f'<div class="woocommerce-message" role="alert">\n\t\t{n["message"]}\t</div>\n')
    if errors:
        items = "".join(f"\t\t<li>\n\t\t\t{n['message']}\t\t</li>\n" for n in errors)
        out.append(f'<ul class="woocommerce-error" role="alert">\n{items}\t</ul>\n')
    for n in notices:
        if n["kind"] == "notice":
            out.append(f'<div class="woocommerce-info" role="status">\n\t\t{n["message"]}\t</div>\n')
    return "".join(out)


# ---------------------------------------------------------------------------------- stock
def held_quantity(product, exclude_order=None):
    qs = StockHold.objects.filter(product=product, expires_at__gt=timezone.now())
    if exclude_order is not None:
        qs = qs.exclude(order=exclude_order)
    return sum(h.quantity for h in qs)


def available_stock(product):
    if not product.manage_stock or product.stock_qty is None:
        return None
    return max(0, product.stock_qty - held_quantity(product))


# ------------------------------------------------------------------------------ mutations
class CartError(Exception):
    pass


def add_to_cart(request, product, quantity=1):
    quantity = max(1, int(quantity or 1))
    if not product.is_purchasable:
        raise CartError("Sorry, this product cannot be purchased.")
    if not product.in_stock:
        raise CartError(f'You cannot add &quot;{product.title}&quot; to the basket because the product is out of stock.')
    cart = get_cart(request, create=True)
    item = cart.items.filter(product=product).first()
    new_qty = quantity + (item.quantity if item else 0)
    stock = available_stock(product)
    if stock is not None and new_qty > stock:
        in_cart = item.quantity if item else 0
        raise CartError(
            f'You cannot add that amount to the basket &mdash; we have {stock} in stock and you already have {in_cart} in your basket.'
            if in_cart else
            f'You cannot add that amount of &quot;{product.title}&quot; to the basket because there is not enough stock ({stock} remaining).')
    if item:
        item.quantity = new_qty
        item.save(update_fields=["quantity"])
    else:
        CartItem.objects.create(cart=cart, product=product, quantity=quantity)
    cart.save(update_fields=["updated_at"])
    return cart


def set_quantity(request, key, quantity):
    cart = get_cart(request)
    if not cart:
        return
    item = cart.items.filter(key=key).select_related("product").first()
    if not item:
        return
    quantity = int(quantity or 0)
    if quantity <= 0:
        item.delete()
        return
    stock = available_stock(item.product)
    if stock is not None and quantity > stock:
        raise CartError(f'Sorry, we do not have enough &quot;{item.product.title}&quot; in stock to fulfil your order '
                        f'({stock} available). We apologise for any inconvenience caused.')
    item.quantity = quantity
    item.save(update_fields=["quantity"])


def remove_item(request, key):
    cart = get_cart(request)
    if not cart:
        return None
    item = cart.items.filter(key=key).select_related("product").first()
    if not item:
        return None
    request.session["wc_removed_item"] = {"product": item.product_id, "quantity": item.quantity, "key": key}
    product = item.product
    item.delete()
    return product


def restore_item(request, key):
    removed = request.session.pop("wc_removed_item", None)
    if not removed or removed.get("key") != key:
        return None
    product = Product.objects.filter(pk=removed["product"]).first()
    if product:
        cart = get_cart(request, create=True)
        CartItem.objects.update_or_create(cart=cart, product=product, defaults={"quantity": removed["quantity"], "key": key})
    return product


def apply_coupon(request, code):
    code = (code or "").strip().lower()
    if not code:
        raise CartError("Please enter a coupon code.")
    coupon = Coupon.objects.filter(code=code).first()
    if not coupon or not coupon.is_valid():
        raise CartError(f'Coupon "{code}" cannot be applied because it does not exist.' if not coupon
                        else "This coupon has expired.")
    cart = get_cart(request, create=True)
    if code in cart.coupon_codes:
        raise CartError("Coupon code already applied!")
    totals = calculate(cart)
    if coupon.minimum_spend and totals.subtotal < coupon.minimum_spend:
        raise CartError(f"The minimum spend for this coupon is &pound;{coupon.minimum_spend:.2f}.")
    cart.coupon_codes = [*cart.coupon_codes, code]
    cart.save(update_fields=["coupon_codes"])


def remove_coupon(request, code):
    cart = get_cart(request)
    if cart and code in cart.coupon_codes:
        cart.coupon_codes = [c for c in cart.coupon_codes if c != code]
        cart.save(update_fields=["coupon_codes"])


def clear(cart):
    cart.items.all().delete()
    cart.coupon_codes = []
    cart.nebosh_dl = False
    cart.save()


# ---------------------------------------------------------------------------------- totals
@dataclass
class Line:
    item: CartItem
    product: Product
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    total: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")

    @property
    def key(self):
        return self.item.key


@dataclass
class Totals:
    lines: list = field(default_factory=list)
    subtotal: Decimal = Decimal("0")
    subtotal_tax: Decimal = Decimal("0")
    discounts: list = field(default_factory=list)  # [(code, amount_ex, tax)]
    fees: list = field(default_factory=list)       # [(name, amount, tax)]
    tax_total: Decimal = Decimal("0")
    total: Decimal = Decimal("0")

    @property
    def discount_total(self):
        return sum((d[1] for d in self.discounts), Decimal("0"))

    @property
    def fee_total(self):
        return sum((f[1] for f in self.fees), Decimal("0"))

    @property
    def is_empty(self):
        return not self.lines


def cart_has_nebosh(lines):
    return any(NEBOSH_DL_SLUGS & {c.slug for c in l.product.categories.all()} for l in lines)


def calculate(cart, nebosh_dl=None):
    totals = Totals()
    for item in cart_items(cart):
        price = item.product.price or Decimal("0")
        sub = money(price * item.quantity)
        totals.lines.append(Line(item=item, product=item.product, quantity=item.quantity, unit_price=price, subtotal=sub, total=sub))
    totals.subtotal = sum((l.subtotal for l in totals.lines), Decimal("0"))

    # Coupons (applied in order, each on the running line totals).
    for code in (cart.coupon_codes if cart else []):
        coupon = Coupon.objects.filter(code=code).first()
        if not coupon or not coupon.is_valid():
            continue
        discount = Decimal("0")
        base = sum((l.total for l in totals.lines), Decimal("0"))
        for l in totals.lines:
            if coupon.type == Coupon.Type.PERCENT:
                d = money(l.total * coupon.amount / 100)
            elif coupon.type == Coupon.Type.FIXED_PRODUCT:
                d = min(l.total, money(coupon.amount * l.quantity))
            else:  # fixed_cart: split proportionally
                d = min(l.total, money(coupon.amount * l.total / base)) if base else Decimal("0")
            l.total -= d
            discount += d
        totals.discounts.append([code, discount, Decimal("0")])

    for l in totals.lines:
        l.tax = money(l.total * VAT_RATE) if l.product.taxable else Decimal("0")
        totals.subtotal_tax += money(l.subtotal * VAT_RATE) if l.product.taxable else Decimal("0")
    for d in totals.discounts:
        d[2] = money(d[1] * VAT_RATE)

    use_dl = cart.nebosh_dl if (nebosh_dl is None and cart) else bool(nebosh_dl)
    if use_dl and cart_has_nebosh(totals.lines):
        totals.fees.append((NEBOSH_DL_FEE_NAME, NEBOSH_DL_FEE, money(NEBOSH_DL_FEE * VAT_RATE)))

    items_total = sum((l.total for l in totals.lines), Decimal("0"))
    totals.tax_total = sum((l.tax for l in totals.lines), Decimal("0")) + sum((f[2] for f in totals.fees), Decimal("0"))
    totals.total = money(items_total + totals.fee_total + totals.tax_total)
    return totals


@transaction.atomic
def hold_stock(order, lines, minutes=60):
    expires = timezone.now() + timezone.timedelta(minutes=minutes)
    StockHold.objects.filter(order=order).delete()
    for l in lines:
        if l.product.manage_stock:
            StockHold.objects.create(product=l.product, order=order, quantity=l.quantity, expires_at=expires)
