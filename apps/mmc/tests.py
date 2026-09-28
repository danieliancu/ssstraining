import hashlib
import hmac
import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import TestCase, override_settings

from apps.catalog.models import DeletedProduct, Product
from apps.mmc.models import MMCSettings, WebhookEvent
from apps.mmc.sync import Syncer, build_sku, build_title, extract_field, session_prices
from apps.mmc.views import verify_signature

FIXTURE = Path(__file__).parent / "fixtures" / "sessions_sample.json"
SECRET = "whsec_test"


def sign(body: bytes, t=None, secret=SECRET):
    t = int(t or time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


class SignatureTests(TestCase):
    def test_valid(self):
        body = b'{"event":"session.full"}'
        self.assertTrue(verify_signature(body, sign(body), SECRET))

    def test_tampered_body(self):
        self.assertFalse(verify_signature(b'{"x":2}', sign(b'{"x":1}'), SECRET))

    def test_expired(self):
        body = b"{}"
        self.assertFalse(verify_signature(body, sign(body, t=time.time() - 301), SECRET))

    def test_malformed(self):
        self.assertFalse(verify_signature(b"{}", "v1=abc", SECRET))
        self.assertFalse(verify_signature(b"{}", "", SECRET))


class FakeClient:
    def __init__(self, sessions=(), courses=()):
        self._sessions = list(sessions)
        self._courses = list(courses)

    def sessions(self, per_page=50):
        return iter(self._sessions)

    def courses(self, per_page=100):
        return iter(self._courses)

    def course(self, course_id, use_cache=True):
        return {"description": "<p>Course description</p>"}

    def session(self, session_id):
        return next((s for s in self._sessions if s["id"] == session_id), None)

    def availability(self, session_id, timeout=10):
        return {"available_spaces": 3}


def mmc_settings(**kw):
    s = MMCSettings.load()
    s.attribute_mapping = [
        {"field": "course.title", "label": "Course Title", "enabled": True, "visible": True},
        {"field": "duration.first_date", "label": "First Date", "enabled": True, "visible": True},
        {"field": "days", "label": "Session Days (comma separated)", "enabled": True, "visible": True},
        {"field": "available_spaces", "label": "Available Spaces", "enabled": True, "visible": True},
        {"field": "is_online", "label": "Is Online", "enabled": True, "visible": True},
    ]
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    return s


SESSION = {
    "id": "abc123", "course": {"id": "C1", "title": "Site Management Safety Training Scheme", "reference": "SMSTS"},
    "venue": {"id": None, "name": "Sheffield"}, "days": [{"date": "2026-10-03"}, {"date": "2026-10-04"}],
    "duration": {"first_date": "2026-10-03", "last_date": "2026-10-04"}, "is_online": False,
    "price": {"amount": 439, "exclusive_amount": 439, "inclusive_amount": 526.8, "sale_price": None},
    "available_spaces": 8,
}


class MappingTests(TestCase):
    def test_title_and_sku(self):
        self.assertEqual(build_title(SESSION, "{course_title} | {first_date} | {venue_name}"),
                         "Site Management Safety Training Scheme | 03/10/2026 | Sheffield")
        self.assertEqual(build_sku(SESSION, "{course_reference}-{first_date}-{session_id}"), "SMSTS-20261003-abc123")

    def test_hyphens_become_pipes(self):
        s = {**SESSION, "course": {**SESSION["course"], "title": "Mental Health First Aid - 2 day"}}
        self.assertEqual(build_title(s, "{course_title} | {first_date}"), "Mental Health First Aid | 2 day | 03/10/2026")

    def test_prices(self):
        self.assertEqual(session_prices(SESSION), (Decimal("439"), None))
        s = {**SESSION, "price": {"exclusive_amount": 439, "sale_price": {"exclusive_amount": 399}}}
        self.assertEqual(session_prices(s), (Decimal("439"), Decimal("399")))
        s = {**SESSION, "price": {"exclusive_amount": 439, "sale_price": 500}}
        self.assertEqual(session_prices(s), (Decimal("439"), None))

    def test_field_values(self):
        self.assertEqual(extract_field(SESSION, "days"), "2026-10-03, 2026-10-04")
        self.assertEqual(extract_field(SESSION, "is_online"), "No")
        self.assertEqual(extract_field(SESSION, "price.inclusive_amount"), "526.8")
        self.assertEqual(extract_field(SESSION, "venue.id"), "DvEtodPzJq")  # manual venue map

    def test_real_payloads_map_cleanly(self):
        sessions = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for s in sessions[:40]:
            title = build_title(s, "{course_title} | {first_date} | {venue_name}")
            self.assertNotIn("||", title)
            self.assertTrue(title)


class SyncTests(TestCase):
    def test_create_then_update(self):
        s = mmc_settings(allowed_venues=["Sheffield"], allowed_course_refs=["SMSTS"])
        syncer = Syncer(client=FakeClient([SESSION]), settings=s, today=date(2026, 9, 25))
        self.assertEqual(syncer.sync_session(SESSION), "created")
        p = Product.objects.get(mmc_session_id="abc123")
        self.assertEqual(p.slug, "site-management-safety-training-scheme-03-10-2026-sheffield")
        self.assertEqual(p.stock_qty, 8)
        self.assertEqual(p.attr("First Date"), "2026-10-03")
        self.assertEqual([c.name for c in p.categories.all()], ["SMSTS"])
        self.assertEqual(syncer.sync_session({**SESSION, "available_spaces": 0}), "updated")
        p.refresh_from_db()
        self.assertEqual(p.stock_status, "outofstock")

    def test_filters(self):
        s = mmc_settings(allowed_venues=["Crawley"], allowed_course_refs=[])
        syncer = Syncer(client=FakeClient(), settings=s, today=date(2026, 9, 25))
        self.assertEqual(syncer.sync_session(SESSION), "skipped")
        s = mmc_settings(allowed_venues=[], allowed_course_refs=[])
        syncer = Syncer(client=FakeClient(), settings=s, today=date(2026, 11, 1))
        self.assertEqual(syncer.sync_session(SESSION), "skipped")  # past session

    def test_delete_past_leaves_tombstone(self):
        s = mmc_settings(allowed_venues=[], allowed_course_refs=[])
        Syncer(client=FakeClient(), settings=s, today=date(2026, 9, 25)).sync_session(SESSION)
        deleted = Syncer(client=FakeClient(), settings=s, today=date(2026, 12, 1)).delete_past()
        self.assertEqual(deleted, 1)
        self.assertTrue(DeletedProduct.objects.filter(slug__startswith="site-management").exists())

    def test_nvq(self):
        s = mmc_settings(nvq_settings={"N1": {"enabled": True, "price_mode": "50_50"}})
        course = {"id": "N1", "title": "Level 3 Bricklaying", "reference": "L3-Brick", "type": {"key": "nvq"},
                  "price": {"amount": 1000}, "nvq_units": [{"title": "Unit A"}], "description": "<p>Desc</p>"}
        run = Syncer(client=FakeClient(courses=[course]), settings=s).sync_nvqs()
        self.assertEqual(run.created, 1)
        p = Product.objects.get(mmc_nvq_id="N1")
        self.assertEqual(p.regular_price, Decimal("500.00"))
        self.assertEqual(p.sku, "L3-Brick-DEP")
        self.assertEqual([t.name for t in p.tags.all()], ["Level 3"])
        self.assertIn("<li>Unit A</li>", p.description)


@override_settings(MMC_WEBHOOK_SECRET=SECRET)
class WebhookViewTests(TestCase):
    def test_rejects_bad_signature(self):
        r = self.client.post("/wp-json/mmc-wc/v1/webhook", data=b"{}", content_type="application/json",
                             HTTP_X_WEBHOOK_SIGNATURE="t=1,v1=bad")
        self.assertEqual(r.status_code, 401)

    def test_accepts_and_stores(self):
        body = json.dumps({"event": "booking.created", "data": {"id": "B1"}}).encode()
        r = self.client.post("/mmc/webhook/", data=body, content_type="application/json",
                             HTTP_X_WEBHOOK_SIGNATURE=sign(body))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"received": True})
        self.assertTrue(WebhookEvent.objects.filter(event_type="booking.created", processed=True).exists())
