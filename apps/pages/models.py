from django.db import models
from django.urls import reverse

from apps.core.models import Content


class Page(Content):
    class Template(models.TextChoices):
        DEFAULT = "default", "Default (page.php)"
        FRONT = "front", "Front page"
        PAGE_ONLY = "page_only", "Page only"
        API = "api", "API page (course list by category)"
        NVQ_LEVEL = "nvq_level", "NVQ level page"
        NEBOSH_DL = "nebosh_dl", "NEBOSH distance learning"
        CATEGORY = "category", "Category page"
        EXAM_PAPERS = "exam_papers", "Exam papers"

    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    template = models.CharField(max_length=20, choices=Template.choices, default=Template.DEFAULT)
    course_category = models.ForeignKey(
        "catalog.ProductCategory", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Used by the API page template.",
    )
    is_front_page = models.BooleanField(default=False)
    is_posts_page = models.BooleanField(default=False, help_text="The blog index page.")

    class Meta(Content.Meta):
        ordering = ["menu_order", "title"]

    @property
    def path(self):
        parts, page = [], self
        while page:
            parts.insert(0, page.slug)
            page = page.parent
        return "/".join(parts)

    def get_absolute_url(self):
        if self.is_front_page:
            return "/"
        return reverse("page", kwargs={"path": self.path})

    @property
    def seo_type(self):
        return "page"
