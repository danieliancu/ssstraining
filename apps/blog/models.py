from django.conf import settings
from django.db import models
from django.urls import reverse
from mptt.models import MPTTModel, TreeForeignKey

from apps.core.models import Content
from apps.seo.models import SeoFields


class Category(MPTTModel, SeoFields):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    parent = TreeForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        # WordPress category base is "." so categories live at the site root.
        return reverse("blog_category", kwargs={"path": "/".join(a.slug for a in self.get_ancestors(include_self=True))})

    seo_type = "category"


class Tag(SeoFields):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("blog_tag", kwargs={"slug": self.slug})

    seo_type = "post_tag"


class AuthorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="author_profile")
    nicename = models.SlugField(max_length=100, unique=True, help_text="URL slug: /blog/author/<nicename>/")
    display_name = models.CharField(max_length=200)
    bio = models.TextField(blank=True)
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("blog_author", kwargs={"nicename": self.nicename})


class Post(Content):
    categories = models.ManyToManyField(Category, blank=True, related_name="posts")
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts")
    primary_category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta(Content.Meta):
        constraints = [models.UniqueConstraint(fields=["slug"], name="unique_post_slug")]

    def get_absolute_url(self):
        return reverse("blog_post", kwargs={"slug": self.slug})

    @property
    def seo_type(self):
        return "post"
