"""Django email backend for Brevo's transactional HTTP API (SMTP ports are blocked on the host).

    EMAIL_BACKEND = "apps.emails.backends.BrevoEmailBackend"
    BREVO_API_KEY = "xkeysib-..."

Maps an EmailMessage / EmailMultiAlternatives to POST https://api.brevo.com/v3/smtp/email:
from -> sender, to/cc/bcc, reply_to (first address), subject, body -> textContent or htmlContent
(by content_subtype), text/html alternatives -> htmlContent, attachments -> base64 "attachment",
extra headers -> "headers".
"""
import base64
import logging
from email.utils import getaddresses, parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

log = logging.getLogger(__name__)

API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoError(Exception):
    pass


def _contact(address):
    name, email = parseaddr(address)
    data = {"email": email}
    if name:
        data["name"] = name
    return data


def _contacts(addresses):
    return [_contact(f"{n} <{e}>" if n else e) for n, e in getaddresses(list(addresses or [])) if e]


class BrevoEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, api_key=None, timeout=20, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or getattr(settings, "BREVO_API_KEY", "")
        self.timeout = timeout
        self.session = None

    def open(self):
        if self.session is None:
            self.session = requests.Session()
            return True
        return False

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        new_session = self.open()
        sent = 0
        try:
            for message in email_messages:
                try:
                    if self._send(message):
                        sent += 1
                except Exception:
                    if not self.fail_silently:
                        raise
                    log.exception("Brevo: sending failed")
        finally:
            if new_session:
                self.close()
        return sent

    def build_payload(self, message):
        payload = {"sender": _contact(message.from_email or settings.DEFAULT_FROM_EMAIL)}
        to = _contacts(message.to)
        if to:
            payload["to"] = to
        cc = _contacts(message.cc)
        if cc:
            payload["cc"] = cc
        bcc = _contacts(message.bcc)
        if bcc:
            payload["bcc"] = bcc
        reply_to = _contacts(message.reply_to)
        if reply_to:
            payload["replyTo"] = reply_to[0]
        payload["subject"] = message.subject

        if message.content_subtype == "html":
            payload["htmlContent"] = message.body
        elif message.body:
            payload["textContent"] = message.body
        for content, mimetype in getattr(message, "alternatives", None) or []:
            if mimetype == "text/html":
                payload["htmlContent"] = content

        attachments = []
        for attachment in message.attachments:
            if hasattr(attachment, "get_payload"):  # MIMEBase instance
                name = attachment.get_filename() or "attachment"
                content = attachment.get_payload(decode=True) or b""
            else:
                name, content = attachment[0], attachment[1]
                if isinstance(content, str):
                    content = content.encode("utf-8")
            attachments.append({"name": name or "attachment", "content": base64.b64encode(content).decode("ascii")})
        if attachments:
            payload["attachment"] = attachments

        headers = {k: str(v) for k, v in (message.extra_headers or {}).items()
                   if k.lower() not in ("from", "to", "cc", "bcc", "reply-to", "subject")}
        if headers:
            payload["headers"] = headers
        return payload

    def _send(self, message):
        if not message.recipients():
            return False
        if not self.api_key:
            raise BrevoError("BREVO_API_KEY is not set")
        payload = self.build_payload(message)
        session = self.session or requests
        response = session.post(
            API_URL, json=payload, timeout=self.timeout,
            headers={"api-key": self.api_key, "accept": "application/json", "content-type": "application/json"},
        )
        if response.status_code >= 300:
            raise BrevoError(f"Brevo API error {response.status_code}: {response.text[:500]}")
        try:
            message.brevo_message_id = response.json().get("messageId", "")
        except (ValueError, AttributeError, requests.exceptions.JSONDecodeError):
            pass
        return True
