import re
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from apps.cart import services as cart_services
from apps.catalog.models import Product, ProductCategory
from apps.checkout import services
from apps.mmc.models import MMCSettings
from apps.orders.models import MMCBooking, Order


def make_product(title="Site Management Safety Training Scheme | 03/10/2026", price="439", stock=8, cat="smsts", **kw):
    p = Product.objects.create(kind="session", title=title, slug=re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                               sku="SMSTS-1", regular_price=Decimal(price), stock_qty=stock, manage_stock=True,
                               mmc_session_id=kw.pop("session", "S1"), **kw)
    c, _ = ProductCategory.objects.get_or_create(slug=cat, defaults={"name": cat.upper()})
    p.categories.add(c)
    return p


class TotalsTests(TestCase):
    def test_vat_per_line_and_fee(self):
        p = make_product()
        n = make_product(title="NEBOSH General | 01/11/2026", price="999.99", cat="nebosh-general-certificate", session="S2")
        cart = cart_services.Cart.objects.create()
        cart_services.CartItem.objects.create(cart=cart, product=p, quantity=2)
        cart_services.CartItem.objects.create(cart=cart, product=n, quantity=1)
        t = cart_services.calculate(cart, nebosh_dl=False)
        self.assertEqual(t.subtotal, Decimal("1877.99"))
        self.assertEqual(t.tax_total, Decimal("175.60") + Decimal("200.00"))
        self.assertEqual(t.total, Decimal("2253.59"))
        t = cart_services.calculate(cart, nebosh_dl=True)
        self.assertEqual(t.fees, [("NEBOSH distance learning", Decimal("395.00"), Decimal("79.00"))])
        self.assertEqual(t.total, Decimal("2727.59"))

    def test_dl_fee_needs_nebosh_product(self):
        cart = cart_services.Cart.objects.create()
        cart_services.CartItem.objects.create(cart=cart, product=make_product(), quantity=1)
        self.assertEqual(cart_services.calculate(cart, nebosh_dl=True).fees, [])


class BasketViewTests(TestCase):
    def test_add_to_cart_redirects_and_counts(self):
        p = make_product()
        r = self.client.get(f"/shop/?add-to-cart={p.pk}&quantity=2")
        self.assertRedirects(r, "/basket/", fetch_redirect_response=False)
        page = self.client.get("/basket/").content.decode()
        self.assertIn('value="2"', page)
        self.assertIn("878.00", page)
        self.assertIn('<span class="basket-count">2</span>', page)

    def test_stock_limit(self):
        p = make_product(stock=1)
        self.client.get(f"/?add-to-cart={p.pk}&quantity=3")
        page = self.client.get("/basket/").content.decode()
        self.assertIn("woocommerce-error", page)
        self.assertIn("Your basket is currently empty.", page)


class FakeMMC:
    configured = True

    def __init__(self, spaces=8, fail=False):
        self.spaces, self.fail, self.bookings = spaces, fail, []

    def availability(self, sid, timeout=10):
        return {"available_spaces": self.spaces, "is_available": self.spaces > 0, "is_closed": False}

    def create_booking(self, payload):
        self.bookings.append(payload)
        return {"data": {"id": f"B{len(self.bookings)}", "reference": "REF"}}


BILLING = {"billing_email": "jo@example.com", "billing_first_name": "Jo", "billing_last_name": "Bloggs",
           "billing_country": "GB", "billing_address_1": "1 High St", "billing_city": "Sheffield",
           "billing_postcode": "S1 2AB", "billing_phone": "07700 900000", "payment_method": "stripe"}


@override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_PUBLISHABLE_KEY="pk_test_x", ORDER_ADMIN_EMAILS=["admin@example.com"])
class CheckoutFlowTests(TestCase):
    def setUp(self):
        s = MMCSettings.load()
        s.delegate_settings = {"enable_capture": True, "enforce_quantity": True,
                               "fields": {"name": {"label": "Delegate Name", "enabled": True, "required": True},
                                          "email": {"label": "Delegate Email", "enabled": True, "required": True},
                                          "phone": {"label": "Delegate Phone", "enabled": True, "required": True}}}
        s.save()
        self.product = make_product()
        self.client.get(f"/?add-to-cart={self.product.pk}&quantity=2")
        self.key = cart_services.CartItem.objects.get().key

    def delegates(self):
        data = {}
        for i in (1, 2):
            data[f"tz_mmc_delegates[{self.key}][{i}][name]"] = f"Delegate {i}"
            data[f"tz_mmc_delegates[{self.key}][{i}][email]"] = f"d{i}@example.com"
            data[f"tz_mmc_delegates[{self.key}][{i}][phone]"] = "0114 000000"
        return data

    def test_checkout_page_renders_delegates(self):
        html = self.client.get("/checkout-2/").content.decode()
        self.assertIn(f"tz_mmc_delegates[{self.key}][2][phone]", html)
        self.assertIn("payment_method_stripe", html)

    def test_update_order_review_fragments(self):
        r = self.client.post("/checkout-2/?wc-ajax=update_order_review", {"post_data": "billing_country=GB"})
        data = r.json()
        self.assertEqual(data["result"], "success")
        self.assertIn("1,053.60", data["fragments"][".woocommerce-checkout-review-order-table"])

    def test_validation_errors(self):
        r = self.client.post("/checkout-2/?wc-ajax=checkout", {**BILLING, "billing_email": "bad"})
        data = r.json()
        self.assertEqual(data["result"], "failure")
        self.assertIn("is not a valid email address", data["messages"])
        self.assertIn("Please provide details for all delegates", data["messages"])

    def test_unavailable_modal(self):
        with mock.patch("apps.checkout.services.MMCClient", return_value=FakeMMC(spaces=1)):
            data = self.client.post("/checkout-2/?wc-ajax=checkout", {**BILLING, **self.delegates(),
                                                                       "sst_stripe_confirmation_token": "ctoken"}).json()
        self.assertEqual(data["result"], "failure")
        self.assertIn("tz-mmc-availability-modal", data["messages"])

    def test_paid_order_books_delegates_and_emails(self):
        fake = FakeMMC()
        intent = SimpleNamespace(id="pi_1", status="succeeded", client_secret="cs")
        with mock.patch("apps.checkout.services.MMCClient", return_value=fake), \
                mock.patch("stripe.PaymentIntent.create", return_value=intent) as create:
            data = self.client.post("/checkout-2/?wc-ajax=checkout", {**BILLING, **self.delegates(),
                                                                       "sst_stripe_confirmation_token": "ctoken"}).json()
        self.assertEqual(data["result"], "success", data)
        order = Order.objects.get()
        self.assertEqual(order.status, "processing")
        self.assertEqual(create.call_args.kwargs["amount"], 105360)
        self.assertEqual(len(fake.bookings), 2)
        self.assertEqual(fake.bookings[0], {
            "payment_method": "card_details", "name": "Delegate 1", "email": "d1@example.com",
            "address_street": "1 High St", "address_city": "Sheffield", "address_postcode": "S1 2AB",
            "address_country": "GB", "customer_name": "Jo Bloggs", "customer_email": "jo@example.com",
            "session_id": "S1", "phone": "0114 000000"})
        self.assertEqual(MMCBooking.objects.filter(status="sent").count(), 2)
        self.assertTrue(Order.objects.get().mmc_bookings_sent)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 6)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(cart_services.CartItem.objects.count(), 0)
        page = self.client.get(data["redirect"].replace("http://127.0.0.1:8000", "")).content.decode()
        self.assertIn("Thank you. Your order has been received.", page)
        self.assertIn("Total:", page)
        self.assertIn("(+ VAT)", mail.outbox[0].alternatives[0][0])
        self.assertIn("Delegate 2", page)

    def test_finalize_is_idempotent(self):
        fake = FakeMMC()
        intent = SimpleNamespace(id="pi_1", status="succeeded", client_secret="cs")
        with mock.patch("apps.checkout.services.MMCClient", return_value=fake), \
                mock.patch("stripe.PaymentIntent.create", return_value=intent):
            self.client.post("/checkout-2/?wc-ajax=checkout", {**BILLING, **self.delegates(), "sst_stripe_confirmation_token": "t"})
            services.finalize_paid(Order.objects.get().pk, "pi_1")
        self.assertEqual(len(fake.bookings), 2)
        self.assertEqual(len(mail.outbox), 2)
