from django.db import models


class SeoFields(models.Model):
    """Per-object SEO overrides, the equivalent of Yoast's post/term meta box."""

    seo_title = models.CharField(
        max_length=300, blank=True,
        help_text="Overrides the title template. Yoast variables such as %%title%% and %%sep%% work.",
    )
    seo_description = models.TextField(blank=True, help_text="Meta description.")
    focus_keyword = models.CharField(max_length=200, blank=True)
    canonical_url = models.URLField(max_length=500, blank=True)
    noindex = models.BooleanField(default=False)
    og_title = models.CharField("OpenGraph title", max_length=300, blank=True)
    og_description = models.TextField("OpenGraph description", blank=True)
    og_image = models.ForeignKey(
        "core.Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name="OpenGraph image",
    )
    breadcrumb_title = models.CharField(max_length=200, blank=True)

    class Meta:
        abstract = True


class SeoSettings(models.Model):
    """Site-wide SEO configuration, imported from Yoast's wpseo / wpseo_titles / wpseo_social."""

    separator = models.CharField(max_length=10, default="-")
    # {"title-page": "%%title%% %%page%% %%sep%% %%sitename%%", "metadesc-safety_course": "...", ...}
    title_templates = models.JSONField(default=dict, blank=True)
    breadcrumbs_home = models.CharField(max_length=50, default="Home")
    breadcrumbs_sep = models.CharField(max_length=10, default="/")
    breadcrumbs_bold_last = models.BooleanField(default=True)
    noindex_date_archives = models.BooleanField(default=True)
    noindex_empty_authors = models.BooleanField(default=True)
    company_name = models.CharField(max_length=200, blank=True)
    company_logo = models.ForeignKey("core.Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    social_profiles = models.JSONField(default=list, blank=True)
    og_default_image = models.ForeignKey("core.Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    twitter_card = models.CharField(max_length=40, default="summary_large_image")
    robots_txt_extra = models.TextField(blank=True, help_text="Extra lines appended to robots.txt.")

    class Meta:
        verbose_name = verbose_name_plural = "SEO settings"

    def __str__(self):
        return "SEO settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SeoMeta(models.Model):
    """Values Yoast keeps in its own tables/meta that have no home on the content models:

    - estimated reading time (``_yoast_wpseo_estimated-reading-time-minutes``), which Yoast only
      stores when a post is saved in the editor. It is used while the object's ``modified_at``
      still equals ``source_modified``; after an edit in Django the engine recomputes it.
    - for users: the schema.org Person id hash (``wp_hash(user_login . ID)``) and
      ``_yoast_wpseo_profile_updated`` (author sitemap lastmod).
    """

    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    estimated_reading_time = models.IntegerField(null=True, blank=True)
    source_modified = models.DateTimeField(null=True, blank=True)
    person_schema_id = models.CharField(max_length=64, blank=True)
    profile_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "SEO meta"
        constraints = [models.UniqueConstraint(fields=["content_type", "object_id"], name="unique_seo_meta")]

    def __str__(self):
        return f"{self.content_type.model} #{self.object_id}"

    @classmethod
    def for_object(cls, obj):
        from django.contrib.contenttypes.models import ContentType
        if obj is None or obj.pk is None:
            return None
        ct = ContentType.objects.get_for_model(obj)
        return cls.objects.filter(content_type=ct, object_id=obj.pk).first()
