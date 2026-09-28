import hashlib
import uuid

from django.db import models
from django.utils import timezone


class Coupon(models.Model):
    class Type(models.TextChoices):
        PERCENT = "percent", "Percentage discount"
        FIXED_CART = "fixed_cart", "Fixed basket discount"
        FIXED_PRODUCT = "fixed_product", "Fixed product discount"

    code = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=15, choices=Type.choices, default=Type.PERCENT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    expires_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    minimum_spend = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().lower()
        super().save(*args, **kwargs)

    def is_valid(self):
        if not self.active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        if self.usage_limit is not None and self.usage_count >= self.usage_limit:
            return False
        return True


class Cart(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    coupon_codes = models.JSONField(default=list, blank=True)
    nebosh_dl = models.BooleanField(default=False)

    def __str__(self):
        return str(self.token)

    @property
    def count(self):
        return sum(i.quantity for i in self.items.all())


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    key = models.CharField(max_length=32, editable=False)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at", "pk"]
        constraints = [models.UniqueConstraint(fields=["cart", "product"], name="one_line_per_product")]

    def save(self, *args, **kwargs):
        if not self.key:
            # WooCommerce cart keys are md5 hashes; delegate field names use them.
            self.key = hashlib.md5(f"{self.product_id}-{uuid.uuid4()}".encode()).hexdigest()
        super().save(*args, **kwargs)


class StockHold(models.Model):
    """Seats held for a pending order (woocommerce_hold_stock_minutes = 60)."""

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="holds")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="stock_holds")
    quantity = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
