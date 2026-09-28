from django.core.management.base import BaseCommand, CommandError

from apps.mmc.client import MMCClient
from apps.mmc.sync import Syncer


class Command(BaseCommand):
    help = "Sync MMC sessions and/or NVQ courses into the catalog (cron: sessions every 15 min, NVQs every 6 h)."

    def add_arguments(self, parser):
        parser.add_argument("--sessions", action="store_true")
        parser.add_argument("--nvq", action="store_true")
        parser.add_argument("--lists", action="store_true", help="Refresh venue/course lists for the admin filters.")
        parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing products.")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, sessions=False, nvq=False, lists=False, dry_run=False, limit=0, **opts):
        if not MMCClient().configured:
            raise CommandError("MMC_CLIENT_ID / MMC_CLIENT_SECRET are not set.")
        if not (sessions or nvq or lists):
            sessions = nvq = True
        syncer = Syncer(dry_run=dry_run)
        if lists:
            syncer.refresh_lists()
            self.stdout.write("Venue and course lists refreshed.")
        if sessions:
            run = syncer.sync_sessions(limit=limit)
            self.stdout.write(f"Sessions: created {run.created}, updated {run.updated}, skipped {run.skipped}, "
                              f"deleted {run.deleted}, ok={run.ok} {run.error}")
        if nvq:
            run = syncer.sync_nvqs()
            self.stdout.write(f"NVQs: created {run.created}, updated {run.updated}, skipped {run.skipped}, ok={run.ok} {run.error}")
