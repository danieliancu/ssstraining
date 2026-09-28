"""Admin home page: key figures and recent activity (UNFOLD["DASHBOARD_CALLBACK"])."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.template.defaultfilters import pluralize
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.models import Product
from apps.contact.models import Submission
from apps.mmc.models import SyncRun
from apps.orders.models import MMCBooking, Order

PAID = (Order.Status.PROCESSING, Order.Status.COMPLETED)
ORDER_VARIANTS = {
    Order.Status.PROCESSING: "info",
    Order.Status.COMPLETED: "success",
    Order.Status.ON_HOLD: "warning",
    Order.Status.PENDING: "warning",
    Order.Status.FAILED: "danger",
    Order.Status.CANCELLED: "danger",
}


def _label(text, variant=""):
    return render_to_string("unfold/helpers/label.html", {"text": text, "variant": variant})


def _change_link(obj, text):
    url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
    return format_html('<a href="{}" class="font-medium text-primary-600 dark:text-primary-500">{}</a>', url, text)


def _trend(current, previous):
    if not previous:
        return None
    change = (current - previous) / previous * 100
    return {"text": f"{change:+.0f}% vs previous 30 days", "up": change >= 0}


def dashboard_callback(request, context):
    now = timezone.now()
    last_30, prev_30 = now - timedelta(days=30), now - timedelta(days=60)
    paid = Order.objects.filter(status__in=PAID)
    revenue = paid.filter(paid_at__gte=last_30).aggregate(s=Sum("total"))["s"] or Decimal("0")
    revenue_prev = paid.filter(paid_at__gte=prev_30, paid_at__lt=last_30).aggregate(s=Sum("total"))["s"] or Decimal("0")
    orders = paid.filter(paid_at__gte=last_30).count()
    orders_prev = paid.filter(paid_at__gte=prev_30, paid_at__lt=last_30).count()
    submissions = Submission.objects.filter(is_spam=False)
    enquiries = submissions.filter(submitted_at__gte=now - timedelta(days=7)).count()
    sessions = Product.objects.filter(status="publish", first_date__gte=timezone.localdate()).count()

    failed_bookings = MMCBooking.objects.filter(status=MMCBooking.Status.FAILED).count()
    to_process = Order.objects.filter(status=Order.Status.PROCESSING).count()
    last_sync = SyncRun.objects.filter(dry_run=False).order_by("-started_at").first()

    kpis = [
        {"title": "Revenue (30 days)", "icon": "payments", "value": f"£{revenue:,.2f}",
         "trend": _trend(revenue, revenue_prev), "href": reverse("admin:orders_order_changelist")},
        {"title": "Paid orders (30 days)", "icon": "receipt_long", "value": orders,
         "trend": _trend(orders, orders_prev), "href": reverse("admin:orders_order_changelist")},
        {"title": "Enquiries (7 days)", "icon": "inbox", "value": enquiries,
         "href": reverse("admin:contact_submission_changelist")},
        {"title": "Upcoming sessions", "icon": "event", "value": sessions,
         "href": reverse("admin:catalog_product_changelist")},
    ]

    alerts = []
    if to_process:
        alerts.append({"variant": "info", "icon": "pending_actions",
                       "text": f"{to_process} order{pluralize(to_process)} waiting to be processed",
                       "href": reverse("admin:orders_order_changelist") + "?status__exact=processing"})
    if failed_bookings:
        alerts.append({"variant": "danger", "icon": "error",
                       "text": f"{failed_bookings} MMC booking{pluralize(failed_bookings)} failed",
                       "href": reverse("admin:orders_mmcbooking_changelist") + "?status__exact=failed"})
    if last_sync and not last_sync.ok:
        alerts.append({"variant": "danger", "icon": "sync_problem",
                       "text": f"Last MMC sync failed ({timezone.localtime(last_sync.started_at):%d %b %H:%M})",
                       "href": reverse("admin:mmc_syncrun_change", args=[last_sync.pk])})

    recent_orders = {
        "headers": ["Order", "Customer", "Date", "Status", "Total"],
        "rows": [[
            _change_link(o, f"#{o.number}"),
            o.billing_full_name or o.billing_email,
            f"{timezone.localtime(o.created_at):%d %b %Y, %H:%M}",
            _label(o.get_status_display(), ORDER_VARIANTS.get(o.status, "")),
            f"£{o.total:,.2f}",
        ] for o in Order.objects.order_by("-created_at")[:8]],
    }
    recent_enquiries = {
        "headers": ["Form", "Received"],
        "rows": [[
            _change_link(s, s.form_title),
            f"{timezone.localtime(s.submitted_at):%d %b, %H:%M}",
        ] for s in submissions.order_by("-submitted_at")[:8]],
    }

    context.update({
        "kpis": kpis,
        "alerts": alerts,
        "recent_orders": recent_orders,
        "recent_enquiries": recent_enquiries,
        "last_sync": last_sync,
    })
    return context
