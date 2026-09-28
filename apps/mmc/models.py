from django.db import models

DEFAULT_ATTRIBUTE_FIELDS = [
    # (source field in the session payload, label shown on the product page)
    ("course.title", "Course Title"),
    ("course.reference", "Course Reference"),
    ("course.id", "Course ID"),
    ("venue.id", "Venue ID"),
    ("venue.name", "Venue Name"),
    ("venue.address.street", "Venue Street"),
    ("venue.address.line_2", "Venue Address Line 2"),
    ("venue.address.city", "Venue City"),
    ("venue.address.county", "Venue County"),
    ("venue.address.postcode", "Venue Postcode"),
    ("venue.address.country", "Venue Country"),
    ("venue.address.formatted", "Venue Address"),
    ("trainer.name", "Trainer"),
    ("duration.first_date", "First Date"),
    ("duration.last_date", "Last Date"),
    ("duration.total_days", "Total Days"),
    ("duration.total_hours", "Total Hours"),
    ("days", "Days"),
    ("delivery_type.label", "Delivery Type"),
    ("price.amount", "Price Amount"),
    ("price.exclusive_amount", "Price Exclusive"),
    ("price.inclusive_amount", "Price Inclusive"),
    ("price.vat_amount", "Price VAT"),
    ("available_spaces", "Available Spaces"),
    ("is_full", "Is Full"),
    ("is_nearly_full", "Is Nearly Full"),
    ("is_online", "Is Online"),
    ("closed", "Closed"),
]


class MMCSettings(models.Model):
    """Non-secret MMC integration settings (secrets live in the environment)."""

    class ClosedBehaviour(models.TextChoices):
        DRAFT = "draft", "Unpublish (draft)"
        DELETE = "delete", "Delete"

    title_format = models.CharField(max_length=200, default="{course_title} | {first_date} | {venue_name}")
    sku_format = models.CharField(max_length=200, default="{course_reference}-{first_date}-{session_id}")
    future_only = models.BooleanField(default=True)
    auto_delete_past = models.BooleanField(default=True)
    closed_session_behaviour = models.CharField(max_length=10, choices=ClosedBehaviour.choices, default=ClosedBehaviour.DRAFT)
    price_sync_mode = models.CharField(max_length=10, default="auto", help_text="auto, initial or manual")
    allowed_venues = models.JSONField(default=list, blank=True, help_text="Venue names; empty = all.")
    allowed_course_types = models.JSONField(default=list, blank=True, help_text="Delivery type labels; empty = all.")
    allowed_course_refs = models.JSONField(default=list, blank=True, help_text="Course references; empty = all.")
    include_online_sessions = models.BooleanField(
        default=False, help_text="Keep online sessions (no venue) even when a venue filter is set. "
                                 "Off = same behaviour as the WordPress plugin.")
    # {"<mmc course id>": {"enabled": true, "price_mode": "full"|"50_50", "title": "..."}}
    nvq_settings = models.JSONField(default=dict, blank=True)
    # [{"field": "course.title", "label": "Course Title", "enabled": true, "visible": true}, ...]
    attribute_mapping = models.JSONField(default=list, blank=True)
    # {"fields": {"name": {"enabled": true, "required": true, "label": "Full Name"}, ...}, "enforce_quantity": true}
    delegate_settings = models.JSONField(default=dict, blank=True)
    venue_list = models.JSONField(default=list, blank=True, editable=False)
    course_ref_list = models.JSONField(default=list, blank=True, editable=False)
    course_type_list = models.JSONField(default=list, blank=True, editable=False)
    error_notification_email = models.EmailField(blank=True)
    unavailable_phone = models.CharField(max_length=50, default="0333 444 0018")

    class Meta:
        verbose_name = verbose_name_plural = "MMC settings"

    def __str__(self):
        return "MMC settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def attribute_fields(self):
        if self.attribute_mapping:
            return [m for m in self.attribute_mapping if m.get("enabled", True)]
        return [{"field": f, "label": label, "enabled": True, "visible": True} for f, label in DEFAULT_ATTRIBUTE_FIELDS]

    def delegate_fields(self):
        fields = (self.delegate_settings or {}).get("fields")
        if fields:
            return fields
        return {
            "name": {"enabled": True, "required": True, "label": "Full Name"},
            "email": {"enabled": True, "required": True, "label": "Email"},
            "phone": {"enabled": True, "required": True, "label": "Phone"},
        }


class MMCToken(models.Model):
    access_token = models.TextField()
    expires_at = models.DateTimeField()
    credentials_hash = models.CharField(max_length=64)


class SyncRun(models.Model):
    class Kind(models.TextChoices):
        SESSIONS = "sessions", "Sessions"
        NVQ = "nvq", "NVQ courses"
        VENUES = "venues", "Venues"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    dry_run = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    unpublished = models.PositiveIntegerField(default=0)
    deleted = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    report = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.kind} sync {self.started_at:%Y-%m-%d %H:%M}"


class MMCLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=10, default="info")
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "MMC log entry"
        verbose_name_plural = "MMC log"

    def __str__(self):
        return self.message[:80]


class WebhookEvent(models.Model):
    received_at = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=100, blank=True)
    signature_ok = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} @ {self.received_at:%Y-%m-%d %H:%M:%S}"
