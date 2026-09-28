import base64
from unittest import mock

import pytest
from django.core.mail import EmailMessage, EmailMultiAlternatives

from apps.emails import backends
from apps.emails.backends import BrevoEmailBackend, BrevoError


def _ok_response():
    r = mock.Mock(status_code=201, text='{"messageId":"<abc@smtp-relay>"}')
    r.json.return_value = {"messageId": "<abc@smtp-relay>"}
    return r


def test_payload_mapping():
    msg = EmailMultiAlternatives(
        subject="Booking confirmed", body="Plain body", from_email="Site Safety Training <noreply@example.com>",
        to=["Jane Smith <jane@example.com>", "bob@example.com"], cc=["cc@example.com"], bcc=["bcc@example.com"],
        reply_to=["Office <office@example.com>"], headers={"X-Tag": "order"},
    )
    msg.attach_alternative("<p>HTML body</p>", "text/html")
    msg.attach("invoice.pdf", b"%PDF-1.4 data", "application/pdf")
    with mock.patch.object(backends.requests.Session, "post", return_value=_ok_response()) as post:
        sent = BrevoEmailBackend(api_key="key-123").send_messages([msg])
    assert sent == 1
    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "https://api.brevo.com/v3/smtp/email"
    assert kwargs["headers"]["api-key"] == "key-123"
    assert kwargs["json"] == {
        "sender": {"email": "noreply@example.com", "name": "Site Safety Training"},
        "to": [{"email": "jane@example.com", "name": "Jane Smith"}, {"email": "bob@example.com"}],
        "cc": [{"email": "cc@example.com"}],
        "bcc": [{"email": "bcc@example.com"}],
        "replyTo": {"email": "office@example.com", "name": "Office"},
        "subject": "Booking confirmed",
        "textContent": "Plain body",
        "htmlContent": "<p>HTML body</p>",
        "attachment": [{"name": "invoice.pdf", "content": base64.b64encode(b"%PDF-1.4 data").decode()}],
        "headers": {"X-Tag": "order"},
    }
    assert msg.brevo_message_id == "<abc@smtp-relay>"


def test_html_only_message(settings):
    settings.DEFAULT_FROM_EMAIL = "SST <noreply@example.com>"
    msg = EmailMessage(subject="Hi", body="<b>Hi</b>", to=["a@example.com"])
    msg.content_subtype = "html"
    payload = BrevoEmailBackend(api_key="k").build_payload(msg)
    assert payload["htmlContent"] == "<b>Hi</b>"
    assert "textContent" not in payload
    assert payload["sender"] == {"email": "noreply@example.com", "name": "SST"}


def test_api_error_raises_unless_fail_silently():
    msg = EmailMessage(subject="Hi", body="x", from_email="a@example.com", to=["b@example.com"])
    bad = mock.Mock(status_code=400, text='{"code":"invalid_parameter"}')
    with mock.patch.object(backends.requests.Session, "post", return_value=bad):
        with pytest.raises(BrevoError):
            BrevoEmailBackend(api_key="k").send_messages([msg])
        assert BrevoEmailBackend(api_key="k", fail_silently=True).send_messages([msg]) == 0


def test_missing_api_key_raises(settings):
    settings.BREVO_API_KEY = ""
    msg = EmailMessage(subject="Hi", body="x", from_email="a@example.com", to=["b@example.com"])
    with pytest.raises(BrevoError):
        BrevoEmailBackend().send_messages([msg])


def test_works_through_django_mail(settings):
    settings.EMAIL_BACKEND = "apps.emails.backends.BrevoEmailBackend"
    settings.BREVO_API_KEY = "k"
    from django.core.mail import send_mail
    with mock.patch.object(backends.requests.Session, "post", return_value=_ok_response()) as post:
        assert send_mail("S", "B", "a@example.com", ["b@example.com"]) == 1
    assert post.call_args.kwargs["json"]["to"] == [{"email": "b@example.com"}]
