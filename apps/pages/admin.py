from django.contrib import admin

from apps.core.admin_utils import ContentAdmin

from .models import Page


@admin.register(Page)
class PageAdmin(ContentAdmin):
    list_display = ("title", "path_display", "template", "status", "modified_at")
    list_filter = ("status", "template")
    raw_id_fields = ContentAdmin.raw_id_fields + ("parent",)
    extra_fieldsets = (("Page settings", {"fields": ("parent", "template", "course_category", "is_front_page", "is_posts_page")}),)

    @admin.display(description="URL")
    def path_display(self, obj):
        return obj.get_absolute_url()
