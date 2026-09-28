from django.db import models


class ContactForm(models.Model):
    """A Contact Form 7 form's mail settings and messages. Its fields and markup are the Django form
    with the same wp_id in apps.contact.forms."""

    wp_id = models.PositiveIntegerField(unique=True, help_text="The CF7 form id (used in markup and API URLs).")
    title = models.CharField(max_length=200)
    recipient = models.CharField(max_length=500, help_text="Comma-separated addresses.")
    sender = models.CharField(max_length=300, blank=True, help_text="From header; blank uses DEFAULT_FROM_EMAIL.")
    subject = models.CharField(max_length=300)
    body = models.TextField(help_text="Mail tags like [text-67] and [_url] are replaced.")
    additional_headers = models.TextField(blank=True, help_text="e.g. Reply-To: [email-999]")
    # CF7 _messages: {"mail_sent_ok": "...", "validation_error": "...", ...}
    messages = models.JSONField(default=dict)

    def __str__(self):
        return self.title


class Submission(models.Model):
    form = models.ForeignKey(ContactForm, null=True, on_delete=models.SET_NULL, related_name="submissions")
    form_title = models.CharField(max_length=200)
    submitted_at = models.DateTimeField(db_index=True)
    page_url = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict)
    ip = models.GenericIPAddressField(null=True, blank=True)
    is_spam = models.BooleanField(default=False)
    mail_status = models.CharField(max_length=20, blank=True)
    imported = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.form_title} – {self.submitted_at:%Y-%m-%d %H:%M}"
