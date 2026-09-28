from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin
from unfold.admin import ModelAdmin

from .models import Menu, MenuItem
from .render import clear_menu_cache


@admin.register(Menu)
class MenuAdmin(ModelAdmin):
    list_display = ("name", "slug")


@admin.register(MenuItem)
class MenuItemAdmin(DraggableMPTTAdmin, ModelAdmin):
    list_display = ("tree_actions", "indented_title", "target_type", "menu")
    list_display_links = ("indented_title",)
    list_filter = ("menu",)
    raw_id_fields = ("page", "product_category", "product", "post", "category")
    fieldsets = [
        (None, {"fields": ("menu", "parent", "title", "target_type")}),
        ("Link target (fill the one matching the type)", {"fields": ("url", "page", "product_category",
                                                                       "product_mmc_nvq_id", "product", "post", "category")}),
        ("Advanced", {"classes": ("collapse",), "fields": ("css_classes", "link_target", "order", "wp_id")}),
    ]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_menu_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_menu_cache()
