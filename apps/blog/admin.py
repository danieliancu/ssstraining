from django.contrib import admin
from mptt.admin import MPTTModelAdmin
from unfold.admin import ModelAdmin

from apps.core.admin_utils import SEO_FIELDSET, ContentAdmin

from .models import AuthorProfile, Category, Post, Tag


@admin.register(Post)
class PostAdmin(ContentAdmin):
    list_display = ("title", "status", "published_at", "author")
    list_filter = ("status", "categories", "tags")
    filter_horizontal = ("categories", "tags")
    extra_fieldsets = (("Taxonomies", {"fields": ("categories", "primary_category", "tags")}),)


class TermAdmin(ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = [(None, {"fields": ("name", "slug", "description")}), SEO_FIELDSET]
    raw_id_fields = ("og_image",)


@admin.register(Category)
class CategoryAdmin(MPTTModelAdmin, TermAdmin):
    fieldsets = [(None, {"fields": ("name", "slug", "parent", "description")}), SEO_FIELDSET]


admin.site.register(Tag, TermAdmin)


@admin.register(AuthorProfile)
class AuthorProfileAdmin(ModelAdmin):
    list_display = ("display_name", "nicename", "user")
