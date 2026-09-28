"""Resolve old WordPress query-string URLs (?p=, ?page_id=, ?attachment_id=) to canonical paths."""
from django.apps import apps


def resolve_legacy_query(params):
    for key in ("p", "page_id", "attachment_id"):
        value = params.get(key, "")
        if value.isdigit():
            return url_for_wp_id(int(value), key)
    return None


def url_for_wp_id(wp_id, key="p"):
    if key == "attachment_id":
        media = apps.get_model("core", "Media").objects.filter(wp_id=wp_id).first()
        return media.url if media else None
    for label in ("pages.Page", "blog.Post", "news.News", "courses.NeboshCourse",
                  "courses.SafetyCourse", "catalog.Product", "exampapers.ExamPaper"):
        obj = apps.get_model(label).objects.filter(wp_id=wp_id).first()
        if obj:
            return obj.get_absolute_url()
    return None
