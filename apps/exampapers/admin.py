from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.core.admin_utils import ContentAdmin

from .models import DropdownOption, ExamPaper


@admin.register(ExamPaper)
class ExamPaperAdmin(ContentAdmin):
    list_display = ("title", "course", "level", "year", "paper_type", "status")
    list_filter = ("status", "course", "level", "year", "paper_type")
    raw_id_fields = ContentAdmin.raw_id_fields + ("file",)
    extra_fieldsets = (("Paper", {"fields": ("file", "file_url", "course", "level", "year", "paper_type")}),)


@admin.register(DropdownOption)
class DropdownOptionAdmin(ModelAdmin):
    list_display = ("label", "key", "group", "order")
    list_filter = ("group",)
    list_editable = ("order",)
    prepopulated_fields = {"key": ("label",)}
