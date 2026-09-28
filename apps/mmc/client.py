"""ManageMyCourses (MMC) API client — port of TZ_MMC_WC_Integration::get_access_token/api_request."""
import hashlib
import logging
import re
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import MMCLog, MMCToken

log = logging.getLogger("apps.mmc")


class MMCError(Exception):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


def mmc_log(message, level="info", **context):
    MMCLog.objects.create(level=level, message=message[:5000], context=context)
    getattr(log, "warning" if level == "error" else "info")(message)


class MMCClient:
    def __init__(self, base=None, client_id=None, client_secret=None, timeout=30):
        self.base = (base or settings.MMC_API_BASE).rstrip("/")
        self.client_id = client_id if client_id is not None else settings.MMC_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else settings.MMC_CLIENT_SECRET
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def token_url(self):
        return re.sub(r"/api/v1$", "", self.base).rstrip("/") + "/oauth/token"

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.base)

    def _creds_hash(self):
        return hashlib.md5(f"{self.client_id}|{self.client_secret}".encode()).hexdigest()

    def access_token(self, force=False):
        if not self.configured:
            raise MMCError("Missing MMC API credentials or base URL.")
        creds = self._creds_hash()
        if not force:
            token = MMCToken.objects.filter(credentials_hash=creds, expires_at__gt=timezone.now()).order_by("-expires_at").first()
            if token:
                return token.access_token
        resp = self.session.post(self.token_url, json={
            "grant_type": "client_credentials", "client_id": self.client_id,
            "client_secret": self.client_secret, "scope": "",
        }, headers={"Accept": "application/json"}, timeout=20)
        data = _json(resp)
        if resp.status_code != 200 or not data.get("access_token"):
            mmc_log(f"Error getting access token: HTTP {resp.status_code} {str(data)[:300]}", "error")
            raise MMCError(f"Failed to obtain access token from MMC (HTTP {resp.status_code}).", resp.status_code, data)
        expires_in = int(data.get("expires_in") or 31536000)
        MMCToken.objects.all().delete()
        MMCToken.objects.create(access_token=data["access_token"], credentials_hash=creds,
                                expires_at=timezone.now() + timedelta(seconds=max(60, expires_in - 60)))
        mmc_log("Obtained new access token from MMC.")
        return data["access_token"]

    def request(self, method, path, params=None, json=None, timeout=None, _retry=True):
        token = self.access_token()
        url = self.base + path
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        for attempt in range(3):
            try:
                resp = self.session.request(method, url, params=params, json=json, headers=headers,
                                            timeout=timeout or self.timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    mmc_log(f"API request error {method} {path}: {exc}", "error")
                    raise MMCError(f"MMC API connection error: {exc}") from exc
                time.sleep(1 + attempt)
                continue
            if resp.status_code == 401 and _retry:
                self.access_token(force=True)
                return self.request(method, path, params, json, timeout, _retry=False)
            if resp.status_code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            break
        body = resp.text
        mmc_log(f"API response {method} {path} HTTP {resp.status_code} body: {body[:500]}")
        data = _json(resp)
        if not 200 <= resp.status_code < 300:
            raise MMCError(f"MMC API error: HTTP {resp.status_code}", resp.status_code, data)
        return data

    # --- endpoints ----------------------------------------------------------------
    def paged(self, path, per_page=50):
        page = 1
        while True:
            data = self.request("GET", path, params={"per_page": per_page, "page": page})
            items = data.get("data") or []
            if not items:
                return
            yield from items
            if not (data.get("links") or {}).get("next"):
                return
            page += 1

    def sessions(self, per_page=50):
        return self.paged("/sessions", per_page)

    def session(self, session_id):
        return (self.request("GET", f"/sessions/{session_id}") or {}).get("data")

    def availability(self, session_id, timeout=10):
        return (self.request("GET", f"/sessions/{session_id}/availability", timeout=timeout) or {}).get("data") or {}

    def courses(self, per_page=100):
        return self.paged("/courses", per_page)

    def course(self, course_id, use_cache=True):
        key = f"mmc_course_{course_id}"
        if use_cache and (cached := cache.get(key)) is not None:
            return cached
        data = (self.request("GET", f"/courses/{course_id}") or {}).get("data")
        cache.set(key, data, 3600)
        return data

    def venues(self):
        return (self.request("GET", "/venues") or {}).get("data") or []

    def create_booking(self, payload):
        return self.request("POST", "/bookings", json=payload)


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        return {}
