"""Shared admin building blocks: TinyMCE for content, Yoast-style SEO fieldset, singleton admin.
Admin classes extend django-unfold's ModelAdmin so they pick up the admin theme."""
from django.conf import settings
from django.db import models
from django.shortcuts import redirect
from django.urls import reverse
from tinymce.widgets import TinyMCE
from unfold.admin import ModelAdmin
from unfold.overrides import FORMFIELD_OVERRIDES
from unfold.widgets import UnfoldAdminTextareaWidget

SEO_FIELDSET = ("SEO (Yoast)", {
    "classes": ("collapse",),
    "fields": ("seo_title", "seo_description", "focus_keyword", "canonical_url", "noindex",
               "og_title", "og_description", "og_image", "breadcrumb_title"),
    "description": "Leave blank to use the templates in SEO settings. Variables like %%title%%, %%sep%%, %%sitename%% work.",
})

CONTENT_FIELDS = ("title", "slug", "status", "published_at", "author", "content", "excerpt", "featured_image", "menu_order")


class ContentAdmin(ModelAdmin):
    list_display = ("title", "status", "published_at", "modified_at")
    list_filter = ("status",)
    search_fields = ("title", "content")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("modified_at", "wp_id")
    raw_id_fields = ("featured_image", "og_image")
    date_hierarchy = "published_at"
    extra_fieldsets = ()

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "content":
            kwargs["widget"] = TinyMCE()
        elif db_field.name == "acf":
            kwargs["help_text"] = "ACF fields imported from WordPress (JSON)."
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_fieldsets(self, request, obj=None):
        model_fields = {f.name for f in self.model._meta.get_fields()}
        main = [f for f in CONTENT_FIELDS if f in model_fields]
        return [(None, {"fields": main}), *self.extra_fieldsets,
                ("Advanced", {"classes": ("collapse",), "fields": ("acf", "modified_at", "wp_id")}), SEO_FIELDSET]

    def view_on_site(self, obj):
        return obj.get_absolute_url()


class SingletonAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return not self.model.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = self.model.load()
        return redirect(reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk]))


def json_widget_overrides():
    return {**FORMFIELD_OVERRIDES,
            models.JSONField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 6, "class": "font-mono text-xs"})}}


def environment_callback(request):
    """Badge next to the admin title so a local copy isn't mistaken for production."""
    return ["Development", "warning"] if settings.DEBUG else None
