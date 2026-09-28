from django.core.management.base import BaseCommand

from apps.mmc.client import MMCClient, MMCError


class Command(BaseCommand):
    help = "Request an MMC token and fetch one page of sessions."

    def handle(self, *args, **opts):
        client = MMCClient()
        try:
            client.access_token(force=True)
            data = client.request("GET", "/sessions", params={"per_page": 1, "page": 1})
        except MMCError as exc:
            self.stderr.write(f"Connection failed: {exc}")
            return
        total = (data.get("meta") or {}).get("total")
        self.stdout.write(self.style.SUCCESS(f"Connected. Sessions available: {total}"))
