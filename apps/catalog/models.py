from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone
from mptt.models import MPTTModel, TreeForeignKey

from apps.core.models import Media, Status
from apps.seo.models import SeoFields

# Categories that never show as "course references" (functions.php sst_is_hidden_reference_term).
HIDDEN_REFERENCE_SLUGS = {"uncategorized", "uncategorised", "nvq", "wusr-water-hygiene-session", "spill-training"}


class ProductCategory(MPTTModel, SeoFields):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    parent = TreeForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    mmc_reference = models.CharField(max_length=100, blank=True, help_text="MMC course reference mapped to this category.")
    thumbnail = models.ForeignKey(Media, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    menu_order = models.IntegerField(default=0)

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        verbose_name_plural = "product categories"

    def __str__(self):
        return self.name

    @property
    def is_hidden_reference(self):
        return self.slug.lower() in HIDDEN_REFERENCE_SLUGS or self.name.strip().lower() in {
            "uncategorized", "uncategorised", "nvq", "wusr water hygiene session", "spill training"}

    def get_absolute_url(self):
        path = "/".join(a.slug for a in self.get_ancestors(include_self=True))
        return reverse("product_category", kwargs={"path": path})

    seo_type = "product_cat"


class ProductTag(SeoFields):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("product_tag", kwargs={"slug": self.slug})

    seo_type = "product_tag"


class Venue(models.Model):
    mmc_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    address = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Status.PUBLISH)


class Product(SeoFields):
    class Kind(models.TextChoices):
        SESSION = "session", "MMC session"
        NVQ = "nvq", "MMC NVQ course"
        SIMPLE = "simple", "Simple product"

    class StockStatus(models.TextChoices):
        IN_STOCK = "instock", "In stock"
        OUT_OF_STOCK = "outofstock", "Out of stock"

    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SIMPLE)
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    sku = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PUBLISH)
    description = models.TextField(blank=True)
    short_description = models.TextField(blank=True)

    # Prices are stored excluding VAT (woocommerce_prices_include_tax = no).
    regular_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    taxable = models.BooleanField(default=True)
    manage_stock = models.BooleanField(default=True)
    stock_qty = models.IntegerField(null=True, blank=True)
    stock_status = models.CharField(max_length=12, choices=StockStatus.choices, default=StockStatus.IN_STOCK)
    virtual = models.BooleanField(default=False)

    categories = models.ManyToManyField(ProductCategory, blank=True, related_name="products")
    tags = models.ManyToManyField(ProductTag, blank=True, related_name="products")

    # MMC linkage
    mmc_session_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    mmc_nvq_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    mmc_course_id = models.CharField(max_length=64, blank=True)
    mmc_venue_id = models.CharField(max_length=64, blank=True)
    price_mode = models.CharField(max_length=10, blank=True, help_text="NVQ: full or 50_50")
    raw_payload = models.JSONField(default=dict, blank=True, editable=False)
    synced_at = models.DateTimeField(null=True, blank=True, editable=False)

    # Denormalised session facts (also present in `attributes`) for filtering.
    first_date = models.DateField(null=True, blank=True, db_index=True)
    last_date = models.DateField(null=True, blank=True)
    start_time = models.CharField(max_length=20, blank=True)
    venue_name = models.CharField(max_length=200, blank=True)
    is_online = models.BooleanField(default=False)

    # WooCommerce custom attributes shown on the product page, in order:
    # [{"name": "First Date", "value": "2026-10-03", "visible": true}, ...]
    attributes = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    modified_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["first_date", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("product_detail", kwargs={"slug": self.slug})

    seo_type = "product"

    @property
    def price(self):
        if self.sale_price is not None and self.regular_price is not None and self.sale_price < self.regular_price:
            return self.sale_price
        return self.regular_price

    @property
    def on_sale(self):
        return self.price is not None and self.regular_price is not None and self.price < self.regular_price

    @property
    def is_purchasable(self):
        return self.status == Status.PUBLISH and self.price is not None

    @property
    def in_stock(self):
        if self.stock_status == self.StockStatus.OUT_OF_STOCK:
            return False
        return not self.manage_stock or self.stock_qty is None or self.stock_qty > 0

    def attr(self, *names):
        """First non-empty attribute value matching any of the names (case-insensitive),
        like custom_shop_get_product_attr()."""
        wanted = [n.lower() for n in names]
        for want in wanted:
            for a in self.attributes:
                if a.get("name", "").lower() == want and str(a.get("value", "")).strip():
                    return str(a["value"]).strip()
        return ""

    @property
    def category_slugs(self):
        return {c.slug for c in self.categories.all()}

    @property
    def is_nvq(self):
        return self.kind == self.Kind.NVQ or "nvq" in self.category_slugs

    @property
    def price_incl_vat(self):
        if self.price is None:
            return None
        return (self.price * Decimal("1.2")).quantize(Decimal("0.01")) if self.taxable else self.price


class DeletedProduct(models.Model):
    """Tombstone for products removed by the MMC sync, so old URLs can redirect."""

    slug = models.CharField(max_length=200, unique=True)
    category = models.ForeignKey(ProductCategory, null=True, on_delete=models.SET_NULL)
    deleted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.slug
