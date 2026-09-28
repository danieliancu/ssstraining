"""MMC webhook endpoint (also served at the WordPress path /wp-json/mmc-wc/v1/webhook)."""
import hashlib
import hmac
import json
import time

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .client import MMCError, mmc_log
from .models import WebhookEvent

AVAILABILITY_EVENTS = {"session.availability.changed", "session.spaces_available", "session.full", "session.nearly_full"}
LIFECYCLE_EVENTS = {"session.closed", "session.reopened", "session.created", "session.updated", "session.sale_price.updated"}
COURSE_EVENTS = {"course.created", "course.updated"}


def verify_signature(payload: bytes, header: str, secret: str, tolerance=300, now=None) -> bool:
    """Stripe-style header 't=<unix>,v1=<hex hmac_sha256(secret, "t.payload")>'."""
    if not header or not secret:
        return False
    parts = {}
    for part in header.split(","):
        key, _, value = part.partition("=")
        if value:
            parts[key.strip()] = value.strip()
    if not parts.get("t") or not parts.get("v1"):
        return False
    try:
        timestamp = int(parts["t"])
    except ValueError:
        return False
    if abs((now or time.time()) - timestamp) > tolerance:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


@csrf_exempt
@require_POST
def webhook(request):
    secret = settings.MMC_WEBHOOK_SECRET
    if not secret:
        mmc_log("Webhook received but webhook secret not configured.", "error")
        return JsonResponse({"error": "Webhook secret not configured"}, status=500)
    header = request.headers.get("X-Webhook-Signature", "")
    if not header or not verify_signature(request.body, header, secret):
        mmc_log(f"Invalid webhook signature. Header: {header}", "error")
        return JsonResponse({"error": "Invalid signature"}, status=401)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Invalid payload"}, status=400)
    event_type = request.headers.get("X-Webhook-Event") or (payload.get("event") if isinstance(payload, dict) else "")
    if not event_type:
        return JsonResponse({"error": "Invalid payload"}, status=400)
    event = WebhookEvent.objects.create(event_type=event_type, signature_ok=True, payload=payload)
    process_event(event)
    return JsonResponse({"received": True})


def process_event(event):
    """Dispatch a stored webhook event (also used by the admin 'replay' action)."""
    from .sync import Syncer

    payload = event.payload if isinstance(event.payload, dict) else {}
    data = payload.get("data") or {}
    event_type = event.event_type
    mmc_log(f"Webhook received: {event_type}")
    try:
        syncer = Syncer()
        session_id = data.get("session_id") or data.get("id")
        if event_type in AVAILABILITY_EVENTS:
            if not session_id:
                raise MMCError("Session availability event missing session identifier.")
            syncer.update_availability(session_id)
        elif event_type in LIFECYCLE_EVENTS:
            if not session_id:
                raise MMCError("Session lifecycle event missing session identifier.")
            syncer.lifecycle(session_id, event_type)
        elif event_type in COURSE_EVENTS:
            if not data.get("id"):
                raise MMCError("Course event missing ID.")
            syncer.course_event(data["id"])
        else:
            mmc_log(f"Webhook event not specifically handled: {event_type}")
        event.processed = True
        event.error = ""
    except Exception as exc:  # stored for replay; MMC still gets 200 so it doesn't retry-storm
        event.error = str(exc)
        mmc_log(f"Webhook {event_type} failed: {exc}", "error")
    event.save(update_fields=["processed", "error"])
