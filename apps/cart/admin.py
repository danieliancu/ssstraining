from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Coupon


@admin.register(Coupon)
class CouponAdmin(ModelAdmin):
    list_display = ("code", "type", "amount", "expires_at", "usage_count", "usage_limit", "active")
    list_filter = ("type", "active")
    search_fields = ("code",)
