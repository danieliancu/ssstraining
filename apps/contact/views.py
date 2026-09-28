"""Contact Form 7 REST API (wp-json/contact-form-7/v1/...), answering CF7's unchanged front-end JS.

Port of contact-form-7/includes/rest-api.php + submission.php: the feedback endpoint validates the
posted fields with the form's Django form class (apps.contact.forms, same rules as CF7's SWV schema),
runs the spam checks (Akismet honeypot, optional reCAPTCHA v3), sends the mail template with mail-tag
replacement and returns the same JSON, key order included:

    {"contact_form_id", "status", "message", ["invalid_fields"], "posted_data_hash", "into", "invalid_fields"}

Every submission is stored in Submission (spam and failed ones too).
"""
import hashlib
import hmac
import json
import logging
import math
import re
import time

from django.apps import apps
from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django_recaptcha.client import submit as recaptcha_submit

from .forms import FORMS
from .models import ContactForm, Submission

log = logging.getLogger(__name__)

SCHEMA_VERSION = "Contact Form 7 SWV Schema 2024-10"
LOCALE = "en_GB"
RECAPTCHA_THRESHOLD = 0.50
NAME_RE = re.compile(r"^[A-Za-z][-A-Za-z0-9_:.]*$")  # wpcf7_is_name


# ----------------------------------------------------------------------------- responses
def wp_json(data, status=200):
    """rest_ensure_response + wp_json_encode: compact, "/" escaped, non-ASCII as \\uXXXX."""
    body = json.dumps(data, separators=(",", ":")).replace("/", "\\/")
    response = HttpResponse(body, status=status, content_type="application/json; charset=UTF-8")
    response["X-Robots-Tag"] = "noindex"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def wp_error(code, message, status):
    return wp_json({"code": code, "message": message, "data": {"status": status}}, status=status)


def no_route():
    return wp_error("rest_no_route", "No route was found matching the URL and request method.", 404)


def _form_or_error(form_id):
    """The ContactForm (mail settings, messages) and its Django form class."""
    contact = ContactForm.objects.filter(wp_id=form_id).first()
    if contact is None or form_id not in FORMS:
        return None, None, wp_error("wpcf7_not_found", "The requested contact form was not found.", 404)
    return contact, FORMS[form_id], None


# ----------------------------------------------------------------------------- request data
def remote_ip(request):
    return request.META.get("REMOTE_ADDR") or None


def request_url(request):
    """Submission meta 'url': the referer when it is on this site."""
    referer = (request.META.get("HTTP_REFERER") or "").strip()
    home = settings.SITE_URL.rstrip("/")
    if referer and (referer.startswith(home) or referer.startswith(request.build_absolute_uri("/").rstrip("/"))):
        return referer
    return ""


def container_post(post_id):
    """The WordPress post the form was embedded in (_wpcf7_container_post), if we know it."""
    try:
        post_id = int(post_id or 0)
    except ValueError:
        return None
    if post_id <= 0:
        return None
    from apps.core.models import Content
    for model in apps.get_models():
        if issubclass(model, Content) and not model._meta.abstract:
            obj = model.objects.filter(wp_id=post_id).first()
            if obj is not None:
                return obj
    return None


def posted_data_hash(tick, ip, unit_tag, data):
    """wp_hash(wpcf7_flat_join([tick, remote_ip, unit_tag, ...posted values]), 'wpcf7_submission')."""
    text = ", ".join(str(v) for v in [tick, ip or "", unit_tag, *data.values()])
    key = (settings.SECRET_KEY + "wpcf7_submission").encode()
    return hmac.new(key, text.encode(), hashlib.md5).hexdigest()


# ----------------------------------------------------------------------------- spam
def recaptcha_is_human(token, ip=None):
    """CF7's reCAPTCHA v3 check: human when the score is above the threshold (success is not checked)."""
    secret = getattr(settings, "RECAPTCHA_SECRET_KEY", "")
    if not secret:
        return True
    if not token:
        return False
    try:
        result = recaptcha_submit(token, secret, ip or "")
    except (OSError, ValueError, KeyError):
        log.warning("reCAPTCHA verification request failed", exc_info=True)
        return False
    try:
        score = float(result.extra_data.get("score", 0))
    except (TypeError, ValueError):
        return False
    return RECAPTCHA_THRESHOLD < score


def is_spam(request):
    """CF7's own check (User-Agent), Akismet's honeypot and CF7's reCAPTCHA v3 module."""
    if len(request.META.get("HTTP_USER_AGENT", "")) < 2:
        return True
    if request.POST.get("_wpcf7_ak_hp_textarea", "").strip():
        return True
    return not recaptcha_is_human(request.POST.get("_wpcf7_recaptcha_response", ""), remote_ip(request))


# ----------------------------------------------------------------------------- mail
MAIL_TAG_RE = re.compile(r"(\[?)\[[\t ]*([a-zA-Z_][0-9a-zA-Z:._-]*)[\t ]*\](\]?)")


def special_tags(request, form, meta):
    from apps.core.models import SiteOptions
    options = SiteOptions.load()
    now = timezone.localtime()
    post = meta.get("container")
    tags = {
        "_remote_ip": meta.get("ip") or "",
        "_user_agent": request.META.get("HTTP_USER_AGENT", "")[:254],
        "_url": meta.get("url", ""),
        "_date": f"{now:%B} {now.day}, {now.year}",
        "_time": f"{now.hour % 12 or 12}:{now:%M} {'am' if now.hour < 12 else 'pm'}",
        "_invalid_fields": "0",
        "_serial_number": str(Submission.objects.filter(form=form).count() + 1),
        "_site_title": options.site_name,
        "_site_description": options.tagline,
        "_site_url": settings.SITE_URL.rstrip("/"),
        "_site_domain": re.sub(r"^https?://", "", settings.SITE_URL).split("/")[0],
        "_site_admin_email": options.main_email_address,
        "_contact_form_title": form.title,
        "_post_id": str(getattr(post, "wp_id", "") or "") if post else "",
        "_post_name": getattr(post, "slug", "") if post else "",
        "_post_title": getattr(post, "title", "") if post else "",
        "_post_url": (settings.SITE_URL.rstrip("/") + post.get_absolute_url()) if post else "",
    }
    return tags


def replace_tags(template, data, tags):
    """WPCF7_MailTaggedText for a plain-text mail: unknown tags stay as they are."""
    def repl(m):
        if m.group(1) == "[" and m.group(3) == "]":
            return m.group(0)[1:-1]  # [[tag]] escapes to [tag]
        name = m.group(2)
        if name.startswith("_raw_"):
            name = name[5:]
        if name in data:
            value = data[name]
        elif name in tags:
            value = tags[name]
        else:
            return m.group(0)
        return m.group(1) + str(value).strip() + m.group(3)
    return MAIL_TAG_RE.sub(repl, template or "")


def parse_headers(text):
    headers = {}
    for line in (text or "").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() and value.strip():
                headers[key.strip()] = value.strip()
    return headers


def build_mail(request, form, data, meta):
    tags = special_tags(request, form, meta)
    subject = re.sub(r"[\r\n]+", " ", replace_tags(form.subject, data, tags)).strip()
    body = replace_tags(form.body, data, tags)
    recipients = [a.strip() for a in replace_tags(form.recipient, data, tags).split(",") if a.strip()]
    sender = replace_tags(form.sender, data, tags).strip() or settings.DEFAULT_FROM_EMAIL
    headers = parse_headers(replace_tags(form.additional_headers, data, tags))
    reply_to, cc, bcc = [], [], []
    extra = {}
    for key, value in headers.items():
        values = [v.strip() for v in value.split(",") if v.strip()]
        lower = key.lower()
        if lower == "reply-to":
            reply_to = values
        elif lower == "cc":
            cc = values
        elif lower == "bcc":
            bcc = values
        else:
            extra[key] = value
    return EmailMessage(subject=subject, body=body, from_email=sender, to=recipients, cc=cc, bcc=bcc,
                        reply_to=reply_to, headers=extra)


# ----------------------------------------------------------------------------- views
@csrf_exempt
def feedback(request, form_id):
    if request.method != "POST":
        return no_route()
    if not request.content_type.startswith("multipart/form-data"):
        return wp_error("wpcf7_unsupported_media_type", "The request payload format is not supported.", 415)
    contact, form_class, error = _form_or_error(form_id)
    if error:
        return error
    unit_tag = re.sub(r"[^A-Za-z0-9_-]", "", request.POST.get("_wpcf7_unit_tag", ""))
    if not unit_tag:
        return wp_error("wpcf7_unit_tag_not_found", "There is no valid unit tag.", 400)

    form = form_class(request.POST, messages=contact.messages)
    invalid = form.invalid_fields()
    data = {name: form.cleaned_data.get(name, "") for name in form.fields}
    ip = remote_ip(request)
    container = container_post(request.POST.get("_wpcf7_container_post"))
    url = request_url(request)
    meta = {"ip": ip, "url": url, "container": container}

    result = {"contact_form_id": contact.wp_id}
    spam = False
    if invalid:
        status, msg = "validation_failed", form.message("validation_error")
    elif is_spam(request):
        status, msg, spam = "spam", form.message("spam"), True
    else:
        try:
            build_mail(request, contact, data, meta).send(fail_silently=False)
            status, msg = "mail_sent", form.message("mail_sent_ok")
        except Exception:
            log.exception("Contact form %s: sending mail failed", contact.wp_id)
            status, msg = "mail_failed", form.message("mail_sent_ng")

    result["status"] = status
    result["message"] = msg
    if status == "validation_failed":
        result["invalid_fields"] = [
            {"field": name.replace(".", "_"), "message": reason, "idref": None,
             "error_id": f"{unit_tag}-ve-{name.replace('.', '_')}"}
            for name, reason in invalid.items() if NAME_RE.match(name)
        ]
    if status in ("validation_failed", "spam"):
        result["posted_data_hash"] = ""
    else:
        tick = math.ceil(time.time() / 1800)
        result["posted_data_hash"] = posted_data_hash(tick, ip, unit_tag, data)
    result["into"] = f"#{unit_tag}"
    result.setdefault("invalid_fields", [])

    if status != "validation_failed":
        page_url = url or (settings.SITE_URL.rstrip("/") + container.get_absolute_url() if container else "")
        Submission.objects.create(
            form=contact, form_title=contact.title, submitted_at=timezone.now(), page_url=page_url[:500],
            data=data, ip=ip, is_spam=spam, mail_status=status,
        )
    return wp_json(result)


def schema(request, form_id):
    if request.method != "GET":
        return no_route()
    contact, form_class, error = _form_or_error(form_id)
    if error:
        return error
    rules = form_class(messages=contact.messages).schema_rules()
    return wp_json({"version": SCHEMA_VERSION, "locale": LOCALE, "rules": rules})


def refill(request, form_id):
    if request.method != "GET":
        return no_route()
    contact, form_class, error = _form_or_error(form_id)
    if error:
        return error
    return wp_json([])
