import json
from unittest import mock

import pytest
from django.core import mail

from django.template import Context, Template
from django.test import RequestFactory
from django_recaptcha.client import RecaptchaResponse

from apps.contact import forms, views
from apps.contact.models import ContactForm, Submission

MESSAGES = {
    "mail_sent_ok": "Thank you for your message. It has been sent.",
    "mail_sent_ng": "There was an error trying to send your message. Please try again later.",
    "validation_error": "One or more fields have an error. Please check and try again.",
    "spam": "There was an error trying to send your message. Please try again later.",
    "invalid_required": "The field is required.",
    "invalid_too_long": "The field is too long.",
    "invalid_email": "The e-mail address entered is invalid.",
    "invalid_tel": "The telephone number is invalid.",
}
URL = "/wp-json/contact-form-7/v1/contact-forms/166/feedback"
UA = {"HTTP_USER_AGENT": "Mozilla/5.0 (pytest)"}


@pytest.fixture
def form(db):
    return ContactForm.objects.create(
        wp_id=166, title="Contact Page Contact Form", recipient="office@example.com",
        subject="Contact Form - [_site_title] Website",
        body="Name:\n[text-67]\n\nMessage Body:\n[textarea-725]\n\nTel: [tel-87]\nEmail: [email-999]\n"
             "URL of enquiry : [_url]\nIP: [_remote_ip]\nUnknown: [nope]",
        additional_headers="Reply-To: [email-999]",
        messages=MESSAGES,
    )


def post(client, **fields):
    data = {"_wpcf7": "166", "_wpcf7_version": "6.1.7", "_wpcf7_locale": "en_GB",
            "_wpcf7_unit_tag": "wpcf7-f166-o1", "_wpcf7_container_post": "0", "_wpcf7_posted_data_hash": "",
            "_wpcf7_recaptcha_response": "", "_wpcf7_ak_hp_textarea": "", "_wpcf7_ak_js": "1700000000000",
            "text-67": "Jane Smith", "email-999": "jane@example.com", "tel-87": "0114 496 0000",
            "textarea-725": "When is the next SMSTS course?"}
    data.update(fields)
    return client.post(URL, data, HTTP_REFERER="http://127.0.0.1:8000/contact-us/", **UA)  # multipart


def test_valid_submission_sends_mail(client, form, settings):
    settings.SITE_URL = "http://127.0.0.1:8000"
    r = post(client)
    assert r.status_code == 200
    assert r["Content-Type"] == "application/json; charset=UTF-8"
    body = json.loads(r.content)
    assert list(body) == ["contact_form_id", "status", "message", "posted_data_hash", "into", "invalid_fields"]
    assert body["contact_form_id"] == 166
    assert body["status"] == "mail_sent"
    assert body["message"] == MESSAGES["mail_sent_ok"]
    assert len(body["posted_data_hash"]) == 32
    assert body["into"] == "#wpcf7-f166-o1"
    assert body["invalid_fields"] == []

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["office@example.com"]
    assert msg.reply_to == ["jane@example.com"]
    assert msg.subject == "Contact Form - Site Safety Training Website"
    assert "Name:\nJane Smith" in msg.body
    assert "URL of enquiry : http://127.0.0.1:8000/contact-us/" in msg.body
    assert "IP: 127.0.0.1" in msg.body
    assert "Unknown: [nope]" in msg.body  # unknown mail tags are left alone

    sub = Submission.objects.get()
    assert sub.form == form and not sub.is_spam and sub.mail_status == "mail_sent"
    assert sub.page_url == "http://127.0.0.1:8000/contact-us/"
    assert sub.data["email-999"] == "jane@example.com"
    assert sub.ip == "127.0.0.1"


def test_missing_required_is_validation_failed(client, form):
    r = post(client, **{"text-67": "  ", "email-999": "not-an-email", "tel-87": "abc"})
    body = json.loads(r.content)
    # invalid_fields keeps its place from the submission result, before posted_data_hash
    assert list(body) == ["contact_form_id", "status", "message", "invalid_fields", "posted_data_hash", "into"]
    assert body["status"] == "validation_failed"
    assert body["message"] == MESSAGES["validation_error"]
    assert body["posted_data_hash"] == ""
    assert body["invalid_fields"] == [
        {"field": "text-67", "message": "The field is required.", "idref": None,
         "error_id": "wpcf7-f166-o1-ve-text-67"},
        {"field": "email-999", "message": "The e-mail address entered is invalid.", "idref": None,
         "error_id": "wpcf7-f166-o1-ve-email-999"},
        {"field": "tel-87", "message": "The telephone number is invalid.", "idref": None,
         "error_id": "wpcf7-f166-o1-ve-tel-87"},
    ]
    assert mail.outbox == []
    assert not Submission.objects.exists()


def test_maxlength(client, form):
    body = json.loads(post(client, **{"textarea-725": "x" * 2001}).content)
    assert body["invalid_fields"][0]["field"] == "textarea-725"
    assert body["invalid_fields"][0]["message"] == "The field is too long."


def test_honeypot_is_spam(client, form):
    body = json.loads(post(client, _wpcf7_ak_hp_textarea="buy now").content)
    assert body["status"] == "spam"
    assert body["message"] == MESSAGES["spam"]
    assert body["posted_data_hash"] == ""
    assert mail.outbox == []
    assert Submission.objects.get().is_spam


def test_recaptcha_low_score_is_spam(client, form, settings):
    settings.RECAPTCHA_SECRET_KEY = "secret"
    with mock.patch.object(views, "recaptcha_submit", return_value=RecaptchaResponse(True, extra_data={"score": 0.3})) as rs:
        body = json.loads(post(client, _wpcf7_recaptcha_response="token").content)
    assert body["status"] == "spam"
    assert rs.call_args.args == ("token", "secret", "127.0.0.1")
    with mock.patch.object(views, "recaptcha_submit", return_value=RecaptchaResponse(True, extra_data={"score": 0.9})):
        body = json.loads(post(client, _wpcf7_recaptcha_response="token").content)
    assert body["status"] == "mail_sent"
    with mock.patch.object(views, "recaptcha_submit", side_effect=OSError("timeout")):
        body = json.loads(post(client, _wpcf7_recaptcha_response="token").content)
    assert body["status"] == "spam"


def test_mail_failure(client, form):
    with mock.patch("django.core.mail.EmailMessage.send", side_effect=OSError("down")):
        body = json.loads(post(client).content)
    assert body["status"] == "mail_failed"
    assert body["message"] == MESSAGES["mail_sent_ng"]
    assert Submission.objects.get().mail_status == "mail_failed"


def test_errors(client, form):
    r = client.post(URL, "a=b", content_type="application/x-www-form-urlencoded", **UA)
    assert r.status_code == 415
    assert r.content == (b'{"code":"wpcf7_unsupported_media_type","message":"The request payload format is not '
                         b'supported.","data":{"status":415}}')
    r = client.post(URL, {"a": "b"}, **UA)
    assert r.status_code == 400 and json.loads(r.content)["code"] == "wpcf7_unit_tag_not_found"
    r = client.post(URL.replace("166", "9"), {"_wpcf7_unit_tag": "x"}, **UA)
    assert r.status_code == 404 and json.loads(r.content)["code"] == "wpcf7_not_found"


def test_schema_and_refill(client, form):
    r = client.get(URL + "/schema")
    data = json.loads(r.content)
    assert data["version"] == "Contact Form 7 SWV Schema 2024-10"
    assert data["rules"][:3] == [
        {"rule": "required", "field": "text-67", "error": "The field is required."},
        {"rule": "maxlength", "field": "text-67", "threshold": 400, "error": "The field is too long."},
        {"rule": "required", "field": "email-999", "error": "The field is required."},
    ]
    assert data["rules"][-1] == {"rule": "maxlength", "field": "textarea-725", "threshold": 2000,
                                 "error": "The field is too long."}
    assert client.get("/wp-json/contact-form-7/v1/contact-forms/166/refill").content == b"[]"


@pytest.mark.parametrize("value,ok", [
    ("jane@example.com", True), ("a@b.co", True), ("a@b", False), ("a@-b.com", False), ("a..b@c.com", True),
    ("a@b..com", False), ("ab@c.d", True), ("x@y", False),
])
def test_is_email(value, ok):
    assert forms.is_email(value) is ok


@pytest.mark.parametrize("value,ok", [
    ("0114 496 0000", True), ("+44 (0)114 496 0000", True), ("12345", False), ("abc", False),
    ("07700 900123 #22", True),
])
def test_is_tel(value, ok):
    assert forms.is_tel(value) is ok


def test_admin_list_and_csv_export(admin_client, form):
    sub = Submission.objects.create(form=form, form_title=form.title, submitted_at="2026-01-02T03:04:05Z",
                                    data={"text-67": "Jane", "email-999": "jane@example.com"}, is_spam=False,
                                    mail_status="mail_sent")
    r = admin_client.get("/admin/contact/submission/?is_spam__exact=0&q=jane")
    assert r.status_code == 200 and b"jane@example.com" in r.content
    assert admin_client.get("/admin/contact/contactform/").status_code == 200
    r = admin_client.post("/admin/contact/submission/", {"action": "export_csv", "_selected_action": [sub.pk]})
    assert r["Content-Type"] == "text/csv; charset=utf-8"
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "Submitted,Form,Page,IP,Spam,Mail status,text-67,email-999"
    assert lines[1].endswith(",mail_sent,Jane,jane@example.com")


def test_form_classes_match_cf7_tags():
    assert list(forms.ContactPageForm.base_fields) == ["text-67", "email-999", "tel-87", "textarea-725"]
    assert [f.required for f in forms.ContactPageForm.base_fields.values()] == [True, True, False, False]
    assert list(forms.CourseContactForm.base_fields) == ["text-67", "textarea-725", "email-999", "tel-87"]
    assert all(f.required for f in forms.CourseContactForm.base_fields.values())


def test_course_form_validation_order_and_cleaning():
    form = forms.CourseContactForm({"text-67": " Jane　", "email-999": "x", "tel-87": "", "textarea-725": ""},
                                   messages=MESSAGES)
    # CF7 validates text/email/tel before textareas
    assert form.invalid_fields() == {"email-999": "The e-mail address entered is invalid.",
                                     "tel-87": "The field is required.", "textarea-725": "The field is required."}
    assert form.cleaned_data["text-67"] == "Jane"
    long = forms.CourseContactForm({"text-67": "😀" * 201, "email-999": "jane@example.com",
                                    "tel-87": "0114 496 0000", "textarea-725": "Hi"})
    assert long.invalid_fields() == {"text-67": "This field has a too long input."}  # 402 UTF-16 code units


def test_rendered_markup_matches_cf7():
    html = Template("{% contact_form 290 %}").render(Context({"request": RequestFactory().get("/nebosh/")}))
    assert html.startswith('<div class="wpcf7 no-js" id="wpcf7-f290-o1" lang="en-GB" dir="ltr" data-wpcf7-id="290">')
    assert ('<div class="fields half right"><p><label><br /> <b>Comments</b><br /> <span class="wpcf7-form-control-wrap" '
            'data-name="textarea-725"><textarea cols="40" rows="10" maxlength="2000" class="wpcf7-form-control '
            'wpcf7-textarea wpcf7-validates-as-required" aria-required="true" aria-invalid="false" placeholder="Enter '
            'your message here" name="textarea-725"></textarea></span><br /> </label></p></div>') in html
    assert ('<input size="40" maxlength="400" class="wpcf7-form-control wpcf7-tel wpcf7-validates-as-required '
            'wpcf7-text wpcf7-validates-as-tel" aria-required="true" aria-invalid="false" placeholder="your telephone '
            'number" value="" type="tel" name="tel-87" />') in html
    assert '<div class="fields half right"><p><input class="wpcf7-form-control wpcf7-submit has-spinner" type="submit" value="Submit My enquiry" /></p></div>' in html
    assert html.endswith('<div class="wpcf7-response-output" aria-hidden="true"></div></form></div>')
