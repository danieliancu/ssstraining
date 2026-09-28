from decimal import Decimal

from django.conf import settings
from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from .models import Delegate, MMCBooking, Order, OrderCoupon, OrderFee, OrderItem, OrderNote


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    fields = ("name", "sku", "quantity", "unit_price", "line_subtotal", "line_tax", "mmc_session_id", "mmc_nvq_id")
    readonly_fields = fields
    can_delete = False


class OrderFeeInline(TabularInline):
    model = OrderFee
    extra = 0
    readonly_fields = ("name", "amount", "tax")


class OrderCouponInline(TabularInline):
    model = OrderCoupon
    extra = 0
    readonly_fields = ("code", "discount", "discount_tax")


class OrderNoteInline(TabularInline):
    model = OrderNote
    extra = 1
    fields = ("note", "is_customer_note", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ("number", "created_at", "billing_full_name", "billing_email", "status_label", "total_display", "bookings")
    list_filter = ("status", "mmc_bookings_sent", "nebosh_dl", "created_at")
    search_fields = ("billing_first_name", "billing_last_name", "billing_email", "order_key", "stripe_payment_intent",
                     "items__delegates__name", "items__delegates__email")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline, OrderFeeInline, OrderCouponInline, OrderNoteInline]
    readonly_fields = ("order_key", "created_at", "paid_at", "subtotal", "discount_total", "fee_total", "tax_total", "total",
                       "stripe_link", "delegates_table", "customer_ip", "user_agent", "wp_id")
    fieldsets = [
        (None, {"fields": ("status", "created_at", "paid_at", "order_key", "wp_id")}),
        ("Billing", {"fields": (("billing_first_name", "billing_last_name"), "billing_company", "billing_email", "billing_phone",
                                "billing_address_1", "billing_address_2", "billing_city", "billing_state", "billing_postcode",
                                "billing_country", "customer_note")}),
        ("Delegates & MMC", {"fields": ("delegates_table", "mmc_bookings_sent")}),
        ("Totals", {"fields": ("subtotal", "discount_total", "fee_total", "tax_total", "total", "nebosh_dl")}),
        ("Payment", {"fields": ("payment_method", "payment_method_title", "stripe_link", "customer_ip", "user_agent")}),
    ]
    actions = ["resend_bookings", "mark_completed", "refund_stripe"]

    @admin.display(description="Order", ordering="pk")
    def number(self, obj):
        return f"#{obj.number}"

    @display(description="Status", ordering="status", label={
        Order.Status.PROCESSING: "info", Order.Status.COMPLETED: "success", Order.Status.ON_HOLD: "warning",
        Order.Status.PENDING: "warning", Order.Status.FAILED: "danger", Order.Status.CANCELLED: "danger",
    })
    def status_label(self, obj):
        return obj.status, obj.get_status_display()

    @admin.display(description="Total", ordering="total")
    def total_display(self, obj):
        return f"£{obj.total:,.2f}"

    @admin.display(description="MMC", boolean=True)
    def bookings(self, obj):
        return obj.mmc_bookings_sent

    @admin.display(description="Stripe payment")
    def stripe_link(self, obj):
        if not obj.stripe_payment_intent:
            return "—"
        mode = "test/" if settings.STRIPE_SECRET_KEY.startswith("sk_test") else ""
        return format_html('<a href="https://dashboard.stripe.com/{}payments/{}" target="_blank">{}</a>',
                           mode, obj.stripe_payment_intent, obj.stripe_payment_intent)

    @admin.display(description="Delegates")
    def delegates_table(self, obj):
        rows = []
        for item in obj.items.all():
            for d in item.delegates.all():
                booking = getattr(d, "booking", None)
                status = booking.get_status_display() if booking else "—"
                ref = booking.mmc_booking_id if booking and booking.mmc_booking_id else (booking.last_error if booking else "")
                rows.append(format_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
                                        item.name, d.name, d.email, d.phone, status, ref))
        if not rows:
            return "—"
        head = "<tr><th>Course</th><th>Name</th><th>Email</th><th>Phone</th><th>MMC booking</th><th>ID / error</th></tr>"
        return format_html("<table>{}{}</table>", format_html(head), format_html("".join(rows)))

    @admin.action(description="Resend failed/pending MMC bookings")
    def resend_bookings(self, request, queryset):
        from apps.checkout.services import send_bookings
        total = 0
        for order in queryset.filter(paid_at__isnull=False):
            MMCBooking.objects.filter(delegate__item__order=order, status=MMCBooking.Status.PENDING).update(status=MMCBooking.Status.FAILED)
            total += len(send_bookings(order, only_failed=True))
        self.message_user(request, f"{total} booking(s) created in MMC.")

    @admin.action(description="Mark as completed")
    def mark_completed(self, request, queryset):
        queryset.filter(status=Order.Status.PROCESSING).update(status=Order.Status.COMPLETED)

    @admin.action(description="Refund in full via Stripe")
    def refund_stripe(self, request, queryset):
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        for order in queryset:
            if not order.stripe_payment_intent or order.status == Order.Status.REFUNDED:
                continue
            try:
                stripe.Refund.create(payment_intent=order.stripe_payment_intent)
            except stripe.StripeError as exc:
                self.message_user(request, f"Order #{order.number}: {exc.user_message or exc}", messages.ERROR)
                continue
            order.status = Order.Status.REFUNDED
            order.save(update_fields=["status"])
            OrderNote.objects.create(order=order, note=f"Refunded £{order.total} via Stripe (admin: {request.user}).")
            self.message_user(request, f"Order #{order.number} refunded.")


@admin.register(Delegate)
class DelegateAdmin(ModelAdmin):
    list_display = ("name", "email", "phone", "item")
    search_fields = ("name", "email", "item__name", "item__order__billing_email")


@admin.register(MMCBooking)
class MMCBookingAdmin(ModelAdmin):
    list_display = ("delegate", "status", "attempts", "mmc_booking_id", "last_error", "updated_at")
    list_filter = ("status",)
    readonly_fields = ("payload", "response")
