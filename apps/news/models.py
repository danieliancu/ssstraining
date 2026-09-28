from django.db import models
from django.urls import reverse
from mptt.models import MPTTModel, TreeForeignKey

from apps.core.models import Content
from apps.seo.models import SeoFields


class NewsCategory(MPTTModel, SeoFields):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    parent = TreeForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    # ACF "Category Fields" (header_style, background_image, overlay, ...)
    acf = models.JSONField(default=dict, blank=True)

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        verbose_name_plural = "news categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("news_category", kwargs={"slug": self.slug})

    seo_type = "news_categories"


class News(Content):
    categories = models.ManyToManyField(NewsCategory, blank=True, related_name="news")

    class Meta(Content.Meta):
        verbose_name_plural = "news"
        constraints = [models.UniqueConstraint(fields=["slug"], name="unique_news_slug")]

    def get_absolute_url(self):
        return reverse("news_detail", kwargs={"slug": self.slug})

    @property
    def seo_type(self):
        return "news"
