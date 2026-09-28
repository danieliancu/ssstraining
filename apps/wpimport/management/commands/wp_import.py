from django.core.management.base import BaseCommand

from apps.wpimport import importers
from apps.wpimport.wp import WordPress

STEPS = ["media", "options", "terms", "content", "render", "products", "menus", "forms", "orders", "redirects"]


class Command(BaseCommand):
    help = "Import content from the WordPress database (settings.DATABASES['wordpress']). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("steps", nargs="*", choices=STEPS + [[]], help=f"Steps to run (default: all): {', '.join(STEPS)}")
        parser.add_argument("--skip-files", action="store_true", help="Do not copy the uploads folder.")

    def handle(self, *args, steps=None, skip_files=False, **options):
        wp = WordPress()
        steps = steps or STEPS
        for step in STEPS:
            if step not in steps:
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {step}"))
            if step == "media":
                importers.import_media(wp, copy_files=not skip_files)
            elif step == "options":
                importers.import_options(wp)
            elif step == "terms":
                importers.import_terms(wp)
            elif step == "content":
                importers.import_content(wp)
            elif step == "render":
                importers.render_content()
            elif step == "products":
                importers.import_products(wp)
            elif step == "menus":
                importers.import_menus(wp)
            elif step == "forms":
                importers.import_forms(wp)
            elif step == "orders":
                importers.import_orders(wp)
            elif step == "redirects":
                importers.build_redirects(wp)
        self.stdout.write(self.style.SUCCESS("Import finished."))
