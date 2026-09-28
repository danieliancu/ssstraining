from django.contrib import admin
from mptt.admin import MPTTModelAdmin
from unfold.admin import ModelAdmin

from apps.blog.admin import TermAdmin
from apps.core.admin_utils import SEO_FIELDSET, json_widget_overrides

from .models import DeletedProduct, Product, ProductCategory, ProductTag, Venue


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ("title", "kind", "sku", "regular_price", "sale_price", "stock_qty", "first_date", "venue_name", "status")
    list_filter = ("status", "kind", "stock_status", "categories", "is_online", "venue_name")
    search_fields = ("title", "sku", "mmc_session_id", "mmc_nvq_id")
    date_hierarchy = "first_date"
    filter_horizontal = ("categories", "tags")
    readonly_fields = ("wp_id", "synced_at", "raw_payload")
    raw_id_fields = ("og_image",)
    formfield_overrides = json_widget_overrides()
    fieldsets = [
        (None, {"fields": ("title", "slug", "kind", "status", "sku", "categories", "tags")}),
        ("Price (ex VAT) and stock", {"fields": ("regular_price", "sale_price", "taxable", "manage_stock", "stock_qty", "stock_status", "virtual")}),
        ("Description", {"classes": ("collapse",), "fields": ("description", "short_description")}),
        ("Session", {"fields": ("first_date", "last_date", "start_time", "venue_name", "is_online", "attributes")}),
        ("MMC", {"classes": ("collapse",), "fields": ("mmc_session_id", "mmc_nvq_id", "mmc_course_id", "mmc_venue_id",
                                                      "price_mode", "synced_at", "raw_payload", "wp_id")}),
        SEO_FIELDSET,
    ]
    actions = ["unpublish", "publish"]

    @admin.action(description="Unpublish (draft)")
    def unpublish(self, request, queryset):
        queryset.update(status="draft")

    @admin.action(description="Publish")
    def publish(self, request, queryset):
        queryset.update(status="publish")


@admin.register(ProductCategory)
class ProductCategoryAdmin(MPTTModelAdmin, TermAdmin):
    list_display = ("name", "slug", "mmc_reference")
    raw_id_fields = ("og_image", "thumbnail")
    fieldsets = [(None, {"fields": ("name", "slug", "parent", "description", "mmc_reference", "thumbnail", "menu_order")}), SEO_FIELDSET]


admin.site.register(ProductTag, TermAdmin)


@admin.register(Venue)
class VenueAdmin(ModelAdmin):
    list_display = ("name", "mmc_id")


@admin.register(DeletedProduct)
class DeletedProductAdmin(ModelAdmin):
    list_display = ("slug", "category", "deleted_at")
    search_fields = ("slug",)
