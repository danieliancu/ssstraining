"""Import the Yoast values that live outside post meta into SeoMeta:

- estimated reading time per post (wp_yoast_indexable.estimated_reading_time_minutes),
- the post's WordPress modified date (so the stored reading time is used until it is edited,
  and products keep WordPress's modified date),
- per author: _yoast_wpseo_profile_updated (author sitemap lastmod) and the schema.org Person
  id hash, read from the running WordPress site's author archive (it is derived from the WP
  auth salts, so it can't be computed here).

    python manage.py seo_import_meta [--wp-url http://localhost/sst] [--skip-http]
"""
import re
from datetime import datetime, timezone as dt_tz

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from apps.seo.models import SeoMeta
from apps.wpimport.wp import WordPress, gmt_datetime

POST_TYPES = {
    "post": "blog.Post", "page": "pages.Page", "news": "news.News",
    "nebosh_course": "courses.NeboshCourse", "safety_course": "courses.SafetyCourse",
    "product": "catalog.Product", "sst_exam_paper": "exampapers.ExamPaper",
}


class Command(BaseCommand):
    help = "Import Yoast reading times, author profile dates and Person schema ids into SeoMeta."

    def add_arguments(self, parser):
        parser.add_argument("--wp-url", default="http://localhost/sst")
        parser.add_argument("--skip-http", action="store_true")

    def handle(self, *args, wp_url, skip_http, **opts):
        wp = WordPress()
        rows = wp.query(
            "SELECT p.ID, p.post_type, p.post_modified_gmt, i.estimated_reading_time_minutes AS ert "
            "FROM {p}posts p LEFT JOIN {p}yoast_indexable i ON i.object_id = p.ID AND i.object_type = 'post' "
            "WHERE p.post_type IN (%s)" % ",".join(["%s"] * len(POST_TYPES)), list(POST_TYPES))
        count = 0
        for row in rows:
            model = apps.get_model(POST_TYPES[row["post_type"]])
            obj = model.objects.filter(wp_id=row["ID"]).first()
            if obj is None:
                continue
            SeoMeta.objects.update_or_create(
                content_type=ContentType.objects.get_for_model(model), object_id=obj.pk,
                defaults={"estimated_reading_time": row["ert"],
                          "source_modified": gmt_datetime(row["post_modified_gmt"])})
            count += 1
        self.stdout.write(f"posts: {count}")

        from apps.blog.models import AuthorProfile
        user_ct = None
        for profile in AuthorProfile.objects.select_related("user"):
            if not profile.wp_id:
                continue
            updated = wp.scalar("SELECT meta_value FROM {p}usermeta WHERE user_id=%s AND meta_key='_yoast_wpseo_profile_updated'",
                                [profile.wp_id])
            defaults = {"profile_updated": datetime.fromtimestamp(int(updated), dt_tz.utc) if updated else None}
            if not skip_http:
                digest = self.person_hash(wp_url, profile)
                if digest:
                    defaults["person_schema_id"] = digest
            user_ct = user_ct or ContentType.objects.get_for_model(profile.user)
            SeoMeta.objects.update_or_create(content_type=user_ct, object_id=profile.user.pk, defaults=defaults)
            self.stdout.write(f"author {profile.nicename}: {defaults}")

    def person_hash(self, wp_url, profile):
        import requests
        try:
            html = requests.get(f"{wp_url.rstrip('/')}/blog/author/{profile.nicename}/", timeout=30).text
        except requests.RequestException:
            return ""
        m = re.search(r"schema\\?/person\\?/([0-9a-f]{32})", html)
        return m.group(1) if m else ""
