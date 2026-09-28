from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.cart.models import StockHold
from apps.orders.models import Order


class Command(BaseCommand):
    help = "Delete expired stock holds and cancel unpaid orders older than the hold time (cron every 5 minutes)."

    def handle(self, *args, **opts):
        expired = StockHold.objects.filter(expires_at__lte=timezone.now())
        order_ids = set(expired.values_list("order_id", flat=True))
        deleted = expired.delete()[0]
        cancelled = Order.objects.filter(pk__in=order_ids, status=Order.Status.PENDING).update(status=Order.Status.CANCELLED)
        self.stdout.write(f"Released {deleted} holds, cancelled {cancelled} unpaid orders.")
