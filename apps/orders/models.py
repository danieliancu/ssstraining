import secrets
from decimal import Decimal

from django.db import models
from django.urls import reverse


def new_order_key():
    return "wc_order_" + secrets.token_hex(7)[:13]


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        PROCESSING = "processing", "Processing"
        ON_HOLD = "on-hold", "On hold"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Failed"

    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    order_key = models.CharField(max_length=40, default=new_order_key, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    currency = models.CharField(max_length=3, default="GBP")

    billing_first_name = models.CharField(max_length=100)
    billing_last_name = models.CharField(max_length=100)
    billing_company = models.CharField(max_length=200, blank=True)
    billing_address_1 = models.CharField(max_length=200)
    billing_address_2 = models.CharField(max_length=200, blank=True)
    billing_city = models.CharField(max_length=100)
    billing_state = models.CharField("County", max_length=100, blank=True)
    billing_postcode = models.CharField(max_length=20)
    billing_country = models.CharField(max_length=2, default="GB")
    billing_email = models.EmailField()
    billing_phone = models.CharField(max_length=40, blank=True)
    customer_note = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    discount_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    fee_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    tax_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    payment_method = models.CharField(max_length=50, default="stripe")
    payment_method_title = models.CharField(max_length=100, default="Card")
    stripe_payment_intent = models.CharField(max_length=100, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    nebosh_dl = models.BooleanField(default=False)
    mmc_bookings_sent = models.BooleanField(default=False)
    emails_sent = models.BooleanField(default=False)

    customer_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.number}"

    @property
    def number(self):
        return self.wp_id or (self.pk + 5000 if self.pk else None)

    @property
    def billing_full_name(self):
        return f"{self.billing_first_name} {self.billing_last_name}".strip()

    def get_received_url(self):
        return reverse("order_received", kwargs={"order_id": self.pk}) + f"?key={self.order_key}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", null=True, on_delete=models.SET_NULL, related_name="+")
    # Snapshot, so the order survives the product being resynced or deleted.
    name = models.CharField(max_length=300)
    sku = models.CharField(max_length=255, blank=True)
    mmc_session_id = models.CharField(max_length=64, blank=True)
    mmc_nvq_id = models.CharField(max_length=64, blank=True)
    cart_key = models.CharField(max_length=32, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    line_tax = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.name} × {self.quantity}"


class OrderFee(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="fees")
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2)


class OrderCoupon(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="coupons")
    code = models.CharField(max_length=100)
    discount = models.DecimalField(max_digits=10, decimal_places=2)
    discount_tax = models.DecimalField(max_digits=10, decimal_places=2)


class Delegate(models.Model):
    item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="delegates")
    index = models.PositiveIntegerField()
    name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["item", "index"]

    def __str__(self):
        return self.name or f"Delegate {self.index + 1}"


class MMCBooking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    delegate = models.OneToOneField(Delegate, on_delete=models.CASCADE, related_name="booking")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    mmc_booking_id = models.CharField(max_length=50, blank=True)
    mmc_reference = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class OrderNote(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="notes")
    note = models.TextField()
    is_customer_note = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
