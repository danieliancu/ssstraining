from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.mmc.models import MMCLog, SyncRun, WebhookEvent


class Command(BaseCommand):
    help = "Delete MMC logs, sync runs and processed webhook events older than N days (default 30, like the WP plugin)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, days=30, **opts):
        cutoff = timezone.now() - timedelta(days=days)
        a = MMCLog.objects.filter(created_at__lt=cutoff).delete()[0]
        b = SyncRun.objects.filter(started_at__lt=cutoff).delete()[0]
        c = WebhookEvent.objects.filter(received_at__lt=cutoff, processed=True).delete()[0]
        self.stdout.write(f"Deleted {a} log entries, {b} sync runs, {c} webhook events.")
