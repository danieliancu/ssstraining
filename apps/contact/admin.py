import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone
from unfold.admin import ModelAdmin

from .models import ContactForm, Submission


@admin.register(ContactForm)
class ContactFormAdmin(ModelAdmin):
    list_display = ("title", "wp_id", "recipient", "subject", "submission_count")
    search_fields = ("title", "recipient", "subject")
    fieldsets = (
        (None, {"fields": ("title", "wp_id")}),
        ("Mail", {"fields": ("recipient", "sender", "subject", "body", "additional_headers"),
                  "description": "Mail tags such as [text-67], [email-999], [_url], [_remote_ip] and "
                                 "[_site_title] are replaced with the submitted values."}),
        ("Messages", {"classes": ("collapse",), "fields": ("messages",),
                      "description": "The form fields are defined in code (apps/contact/forms.py)."}),
    )

    @admin.display(description="Submissions")
    def submission_count(self, obj):
        return obj.submissions.count()


def export_csv(modeladmin, request, queryset):
    """Download the selected submissions; one column per form field."""
    queryset = queryset.select_related("form").order_by("submitted_at")
    field_names = []
    for sub in queryset:
        for key in (sub.data or {}):
            if key not in field_names:
                field_names.append(key)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="submissions-{timezone.localtime():%Y%m%d-%H%M}.csv"')
    response.write("﻿")  # Excel-friendly UTF-8
    writer = csv.writer(response)
    writer.writerow(["Submitted", "Form", "Page", "IP", "Spam", "Mail status", *field_names])
    for sub in queryset:
        writer.writerow([
            timezone.localtime(sub.submitted_at).strftime("%Y-%m-%d %H:%M:%S"), sub.form_title, sub.page_url,
            sub.ip or "", "yes" if sub.is_spam else "", sub.mail_status,
            *[(sub.data or {}).get(k, "") for k in field_names],
        ])
    return response


export_csv.short_description = "Export selected submissions to CSV"


@admin.register(Submission)
class SubmissionAdmin(ModelAdmin):
    list_display = ("submitted_at", "form_title", "sender_name", "sender_email", "page_url", "is_spam",
                    "mail_status")
    list_filter = ("form", "is_spam", "mail_status", "imported", ("submitted_at", admin.DateFieldListFilter))
    search_fields = ("form_title", "page_url", "ip", "data")
    readonly_fields = ("form", "form_title", "submitted_at", "page_url", "data", "ip", "mail_status", "imported")
    fields = ("form", "form_title", "submitted_at", "page_url", "ip", "data", "is_spam", "mail_status", "imported")
    actions = [export_csv]
    list_per_page = 50

    def _value(self, obj, prefix):
        for key, value in (obj.data or {}).items():
            if key.startswith(prefix) and value:
                return value
        return ""

    @admin.display(description="Name")
    def sender_name(self, obj):
        return self._value(obj, "text-") or self._value(obj, "your-name")

    @admin.display(description="Email")
    def sender_email(self, obj):
        return self._value(obj, "email-") or self._value(obj, "your-email")

    def has_add_permission(self, request):
        return False
