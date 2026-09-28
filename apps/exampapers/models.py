from django.db import models
from django.urls import reverse

from apps.core.models import Content


class DropdownOption(models.Model):
    class Group(models.TextChoices):
        COURSE = "course", "Course"
        LEVEL = "level", "Level"
        YEAR = "year", "Year"
        PAPER_TYPE = "paper_type", "Paper Type"

    group = models.CharField(max_length=20, choices=Group.choices)
    key = models.SlugField(max_length=100)
    label = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["group", "order", "label"]
        constraints = [models.UniqueConstraint(fields=["group", "key"], name="unique_option_per_group")]

    def __str__(self):
        return f"{self.get_group_display()}: {self.label}"


class ExamPaper(Content):
    file_url = models.CharField(max_length=500, blank=True)
    file = models.ForeignKey("core.Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    course = models.ForeignKey(DropdownOption, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                               limit_choices_to={"group": "course"})
    level = models.ForeignKey(DropdownOption, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                              limit_choices_to={"group": "level"})
    year = models.ForeignKey(DropdownOption, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                             limit_choices_to={"group": "year"})
    paper_type = models.ForeignKey(DropdownOption, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                   limit_choices_to={"group": "paper_type"})

    class Meta(Content.Meta):
        ordering = ["title"]
        constraints = [models.UniqueConstraint(fields=["slug"], name="unique_exampaper_slug")]

    def get_absolute_url(self):
        return reverse("exam_paper_detail", kwargs={"slug": self.slug})

    @property
    def download_url(self):
        return self.file.url if self.file else self.file_url

    @property
    def seo_type(self):
        return "sst_exam_paper"
