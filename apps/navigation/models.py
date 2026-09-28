from django.db import models
from mptt.models import MPTTModel, TreeForeignKey


class Menu(models.Model):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class MenuItem(MPTTModel):
    class Target(models.TextChoices):
        CUSTOM = "custom", "Custom URL"
        PAGE = "page", "Page"
        PRODUCT_CATEGORY = "product_cat", "Product category"
        PRODUCT = "product", "Product"
        POST = "post", "Post"
        CATEGORY = "category", "Blog category"

    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name="items")
    parent = TreeForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    # Keeps the WordPress menu-item-N ids so CSS/JS hooks stay identical.
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    title = models.CharField(max_length=200, blank=True, help_text="Leave blank to use the linked object's title.")
    target_type = models.CharField(max_length=20, choices=Target.choices, default=Target.CUSTOM)
    url = models.CharField(max_length=500, blank=True)
    page = models.ForeignKey("pages.Page", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    product_category = models.ForeignKey("catalog.ProductCategory", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    # Products are resynced from MMC, so link NVQs by their stable MMC id.
    product_mmc_nvq_id = models.CharField(max_length=64, blank=True)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    post = models.ForeignKey("blog.Post", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    category = models.ForeignKey("blog.Category", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    css_classes = models.CharField(max_length=200, blank=True)
    link_target = models.CharField(max_length=20, blank=True)
    order = models.IntegerField(default=0)

    class MPTTMeta:
        order_insertion_by = ["order"]

    def __str__(self):
        return self.title or f"{self.target_type} #{self.pk}"
