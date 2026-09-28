from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.checkout.services import send_bookings
from apps.orders.models import MMCBooking, Order

MAX_ATTEMPTS = 5


class Command(BaseCommand):
    help = "Resend failed MMC bookings for paid orders (cron every 10 minutes; gives up after 5 attempts)."

    def handle(self, *args, **opts):
        orders = Order.objects.filter(
            paid_at__isnull=False, paid_at__gte=timezone.now() - timedelta(days=14),
            items__delegates__booking__status=MMCBooking.Status.FAILED,
            items__delegates__booking__attempts__lt=MAX_ATTEMPTS,
        ).distinct()
        total = 0
        for order in orders:
            total += len(send_bookings(order, only_failed=True))
        self.stdout.write(f"Retried bookings on {orders.count()} orders; {total} created.")
