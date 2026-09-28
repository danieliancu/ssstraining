from django.contrib import admin
from mptt.admin import MPTTModelAdmin

from apps.blog.admin import TermAdmin
from apps.core.admin_utils import SEO_FIELDSET, ContentAdmin

from .models import News, NewsCategory


@admin.register(News)
class NewsAdmin(ContentAdmin):
    filter_horizontal = ("categories",)
    list_filter = ("status", "categories")
    extra_fieldsets = (("Categories", {"fields": ("categories",)}),)


@admin.register(NewsCategory)
class NewsCategoryAdmin(MPTTModelAdmin, TermAdmin):
    fieldsets = [(None, {"fields": ("name", "slug", "parent", "description", "acf")}), SEO_FIELDSET]
