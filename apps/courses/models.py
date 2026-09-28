"""The theme's NEBOSH and safety course post types (marketing pages, not bookable sessions)."""
from django.db import models
from django.urls import reverse
from mptt.models import MPTTModel, TreeForeignKey

from apps.core.models import Content
from apps.seo.models import SeoFields


class CourseTerm(MPTTModel, SeoFields):
    wp_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, allow_unicode=True)
    description = models.TextField(blank=True)
    parent = TreeForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    acf = models.JSONField(default=dict, blank=True)

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class NeboshCourseTerm(CourseTerm):
    seo_type = "nebosh_courses"

    class Meta:
        verbose_name = "NEBOSH course category"
        verbose_name_plural = "NEBOSH course categories"

    def get_absolute_url(self):
        return reverse("nebosh_term", kwargs={"slug": self.slug})


class SafetyCourseTerm(CourseTerm):
    seo_type = "safety_courses"

    class Meta:
        verbose_name = "safety course category"
        verbose_name_plural = "safety course categories"

    def get_absolute_url(self):
        return reverse("safety_term", kwargs={"slug": self.slug})


class NeboshCourse(Content):
    """ACF: course_price, nebsosh_content_repeater [{header, sub_header, content}],
    course_date_repeater [{block_title, date_repeater: [{date}], exam_dates: [{exam_date}]}]."""

    terms = models.ManyToManyField(NeboshCourseTerm, blank=True, related_name="courses")

    class Meta(Content.Meta):
        verbose_name = "NEBOSH course"
        constraints = [models.UniqueConstraint(fields=["slug"], name="unique_nebosh_slug")]
        ordering = ["menu_order", "title"]

    def get_absolute_url(self):
        return reverse("nebosh_detail", kwargs={"slug": self.slug})

    @property
    def seo_type(self):
        return "nebosh_course"


class SafetyCourse(Content):
    """ACF: course_price, content_repeater [{header, content}]."""

    terms = models.ManyToManyField(SafetyCourseTerm, blank=True, related_name="courses")

    class Meta(Content.Meta):
        verbose_name = "safety course"
        constraints = [models.UniqueConstraint(fields=["slug"], name="unique_safety_slug")]
        ordering = ["menu_order", "title"]

    def get_absolute_url(self):
        return reverse("safety_detail", kwargs={"slug": self.slug})

    @property
    def seo_type(self):
        return "safety_course"
