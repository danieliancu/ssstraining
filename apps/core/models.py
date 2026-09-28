import math
import re

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.html import strip_tags

from apps.seo.models import SeoFields


class Media(models.Model):
    """An uploaded file. Paths mirror WordPress (YYYY/MM/name) so old URLs keep working."""

    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    file = models.FileField(upload_to="%Y/%m/", max_length=300)
    title = models.CharField(max_length=300, blank=True)
    alt = models.CharField(max_length=300, blank=True)
    caption = models.TextField(blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    # WP intermediate sizes: {"medium": {"file": "2018/01/x-300x200.jpg", "width": 300, "height": 200}, ...}
    sizes = models.JSONField(default=dict, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "media"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title or self.file.name

    @property
    def url(self):
        return self.file.url if self.file else ""

    def size_url(self, size="full"):
        """URL of a WP image size, falling back to the original file."""
        info = self.sizes.get(size)
        if info and info.get("file"):
            return settings.MEDIA_URL + info["file"]
        return self.url

    def size_dims(self, size="full"):
        info = self.sizes.get(size)
        if info:
            return info.get("width"), info.get("height")
        return self.width, self.height


class Status(models.TextChoices):
    PUBLISH = "publish", "Published"
    DRAFT = "draft", "Draft"
    PRIVATE = "private", "Private"


class PublishedQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Status.PUBLISH, published_at__lte=timezone.now())


class Content(SeoFields):
    """Fields shared by pages, posts, news, courses: the WordPress wp_posts row."""

    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200, allow_unicode=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    content = models.TextField(blank=True, help_text="HTML body.")
    # Body as WordPress rendered it (wpautop/wptexturize applied). Cleared when content is edited.
    content_rendered = models.TextField(blank=True, editable=False)
    excerpt = models.TextField(blank=True)
    featured_image = models.ForeignKey(Media, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # ACF fields as imported (repeaters are lists of dicts).
    acf = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(default=timezone.now)
    modified_at = models.DateTimeField(default=timezone.now)
    menu_order = models.IntegerField(default=0)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["-published_at"]

    def __str__(self):
        return self.title

    def save(self, *args, keep_modified=False, **kwargs):
        if not keep_modified:
            self.modified_at = timezone.now()
        if self.pk and self.content_rendered:
            old = type(self).objects.filter(pk=self.pk).values_list("content", flat=True).first()
            if old is not None and old != self.content:
                self.content_rendered = ""
        super().save(*args, **kwargs)

    @property
    def body_html(self):
        from apps.core.wp_format import wpautop
        return self.content_rendered or wpautop(self.content)

    @property
    def is_published(self):
        return self.status == Status.PUBLISH

    def get_excerpt(self, words=55):
        if self.excerpt:
            return self.excerpt
        text = re.sub(r"\s+", " ", strip_tags(self.content)).strip()
        parts = text.split(" ")
        return " ".join(parts[:words]) + (" [&hellip;]" if len(parts) > words else "")

    @property
    def reading_time(self):
        words = len(strip_tags(self.content).split())
        return max(1, math.ceil(words / 200))

    @property
    def seo_type(self):
        """Yoast post type key, used to pick title templates."""
        return self._meta.model_name


class SiteOptions(models.Model):
    """Global options (the ACF options page plus general WordPress settings)."""

    site_name = models.CharField(max_length=200, default="Site Safety Training")
    tagline = models.CharField(max_length=300, default="Build your business the right way, growth through knowledge")
    company_name = models.CharField(max_length=200, blank=True)
    main_logo = models.ForeignKey(Media, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    address = models.TextField(blank=True)
    google_map_link = models.CharField(max_length=500, blank=True)
    main_email_address = models.EmailField(blank=True)
    main_telephone_number = models.CharField(max_length=50, blank=True)
    banner_message = models.TextField(blank=True)
    about_us = models.TextField(blank=True)
    nebosh_about = models.TextField(blank=True)
    safety_about = models.TextField(blank=True)
    special_offer = models.TextField(blank=True)
    page_404_image = models.ForeignKey(Media, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    page_404_message = models.TextField(blank=True)
    enable_sidebar_on_posts = models.BooleanField(default=False)
    enable_sidebar_on_pages = models.BooleanField(default=False)
    posts_per_page = models.PositiveIntegerField(default=16)
    # Order emails
    order_email_from_name = models.CharField(max_length=200, default="Site Safety Training")
    order_email_footer = models.TextField(blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "site options"

    def __str__(self):
        return "Site options"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SocialLink(models.Model):
    options = models.ForeignKey(SiteOptions, on_delete=models.CASCADE, related_name="social_links")
    type = models.CharField(max_length=50)
    handle = models.CharField(max_length=200, blank=True)
    link = models.CharField(max_length=500)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]


class AccreditationLogo(models.Model):
    options = models.ForeignKey(SiteOptions, on_delete=models.CASCADE, related_name="accreditation_logos")
    image = models.ForeignKey(Media, null=True, on_delete=models.SET_NULL, related_name="+")
    link = models.CharField(max_length=500, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]


class Redirect(models.Model):
    old_path = models.CharField(max_length=255, unique=True, help_text="Path only, e.g. /old-page/")
    new_path = models.CharField(max_length=500)
    permanent = models.BooleanField(default=True)
    hits = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.old_path} -> {self.new_path}"


class NotFoundLog(models.Model):
    path = models.CharField(max_length=255, unique=True)
    hits = models.PositiveIntegerField(default=0)
    referer = models.CharField(max_length=500, blank=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-hits"]
        verbose_name = "404 log entry"
        verbose_name_plural = "404 log"

    def __str__(self):
        return self.path
