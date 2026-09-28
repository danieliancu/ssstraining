from django.contrib import admin, messages
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.core.admin_utils import SingletonAdmin, json_widget_overrides

from .client import MMCClient, MMCError
from .models import MMCLog, MMCSettings, SyncRun, WebhookEvent


@admin.register(MMCSettings)
class MMCSettingsAdmin(SingletonAdmin):
    formfield_overrides = json_widget_overrides()
    actions_detail = [
        {"title": "MMC tools", "icon": "build", "items": [
            "test_connection", "refresh_token", "refresh_lists", "dry_run_sync", "sync_nvqs"]},
        "sync_sessions",
    ]
    readonly_fields = ("connection", "venue_list", "course_ref_list", "course_type_list")
    fieldsets = [
        ("Connection", {"fields": ("connection",),
                        "description": "API credentials and the webhook secret are set in the server environment (.env): "
                                       "MMC_API_BASE, MMC_CLIENT_ID, MMC_CLIENT_SECRET, MMC_WEBHOOK_SECRET."}),
        ("Products", {"fields": ("title_format", "sku_format", "price_sync_mode", "future_only", "auto_delete_past",
                                 "closed_session_behaviour")}),
        ("Sync filters (empty list = everything)", {"fields": ("allowed_venues", "allowed_course_types", "allowed_course_refs",
                                                               "include_online_sessions", "venue_list", "course_ref_list", "course_type_list")}),
        ("NVQ courses", {"fields": ("nvq_settings",), "description": '{"<MMC course id>": {"enabled": true, "price_mode": "full" or "50_50"}}'}),
        ("Product attributes", {"classes": ("collapse",), "fields": ("attribute_mapping",)}),
        ("Checkout", {"fields": ("delegate_settings", "unavailable_phone")}),
        ("Alerts", {"fields": ("error_notification_email",)}),
    ]

    @admin.display(description="Status")
    def connection(self, obj):
        client = MMCClient()
        return format_html("API: <code>{}</code> — credentials {}", client.base,
                           "set" if client.configured else format_html("<b>missing</b>"))

    @action(description="Test connection", icon="lan")
    def test_connection(self, request, object_id):
        return self.run_action(request, "test")

    @action(description="Refresh token", icon="key")
    def refresh_token(self, request, object_id):
        return self.run_action(request, "token")

    @action(description="Refresh venues / courses", icon="refresh")
    def refresh_lists(self, request, object_id):
        return self.run_action(request, "lists")

    @action(description="Dry-run sync", icon="science")
    def dry_run_sync(self, request, object_id):
        return self.run_action(request, "dry-run")

    @action(description="Sync sessions", icon="sync", variant="primary",
            attrs={"onclick": "return confirm('Sync all MMC sessions into the shop now?')"})
    def sync_sessions(self, request, object_id):
        return self.run_action(request, "sync")

    @action(description="Sync NVQs", icon="school")
    def sync_nvqs(self, request, object_id):
        return self.run_action(request, "nvq")

    def get_urls(self):
        return [path("run/<str:action>/", self.admin_site.admin_view(self.run_action), name="mmc_run")] + super().get_urls()

    def run_action(self, request, action):
        from .sync import Syncer
        back = reverse("admin:mmc_mmcsettings_change", args=[MMCSettings.load().pk])
        try:
            if action == "test":
                data = MMCClient().request("GET", "/sessions", params={"per_page": 1, "page": 1})
                self.message_user(request, f"Connected. Sessions available: {(data.get('meta') or {}).get('total')}")
            elif action == "token":
                MMCClient().access_token(force=True)
                self.message_user(request, "New access token obtained.")
            elif action in ("dry-run", "sync"):
                run = Syncer(dry_run=action == "dry-run").sync_sessions()
                self.message_user(request, f"{'Dry run' if action == 'dry-run' else 'Sync'}: created {run.created}, updated "
                                           f"{run.updated}, skipped {run.skipped}, deleted {run.deleted}. {run.error}",
                                  messages.SUCCESS if run.ok else messages.ERROR)
                return HttpResponseRedirect(reverse("admin:mmc_syncrun_change", args=[run.pk]))
            elif action == "nvq":
                run = Syncer().sync_nvqs()
                self.message_user(request, f"NVQ sync: created {run.created}, updated {run.updated}. {run.error}",
                                  messages.SUCCESS if run.ok else messages.ERROR)
            elif action == "lists":
                Syncer().refresh_lists()
                self.message_user(request, "Venue / course lists refreshed.")
        except MMCError as exc:
            self.message_user(request, f"MMC error: {exc}", messages.ERROR)
        return HttpResponseRedirect(back)


@admin.register(SyncRun)
class SyncRunAdmin(ModelAdmin):
    list_display = ("started_at", "kind", "dry_run", "ok", "created", "updated", "skipped", "deleted", "error")
    list_filter = ("kind", "ok", "dry_run")
    readonly_fields = [f.name for f in SyncRun._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(MMCLog)
class MMCLogAdmin(ModelAdmin):
    list_display = ("created_at", "level", "message")
    list_filter = ("level",)
    search_fields = ("message",)
    actions = ["download"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Download selected as .log")
    def download(self, request, queryset):
        text = "\n".join(f"[{l.created_at:%Y-%m-%d %H:%M:%S}] {l.level.upper()}: {l.message}" for l in queryset.order_by("created_at"))
        response = HttpResponse(text, content_type="text/plain")
        response["Content-Disposition"] = 'attachment; filename="mmc.log"'
        return response


@admin.register(WebhookEvent)
class WebhookEventAdmin(ModelAdmin):
    list_display = ("received_at", "event_type", "processed", "error")
    list_filter = ("event_type", "processed")
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]
    actions = ["replay"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Replay selected events")
    def replay(self, request, queryset):
        from .views import process_event
        for event in queryset:
            process_event(event)
        self.message_user(request, f"Replayed {queryset.count()} event(s).")
