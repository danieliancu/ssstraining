"""The site's Contact Form 7 forms as Django forms.

Each form reproduces its CF7 original: the same field names (the mail templates and CF7's front-end JS
use them), the same markup (widget templates in templates/contact/widgets/) and the same validation
as CF7's SWV rules — required, email (WordPress is_email), tel (wpcf7_is_tel) and maxlength counted in
UTF-16 code units. Error texts come from the form's CF7 messages stored on ContactForm.
"""
import re

from django import forms
from django.core.exceptions import ValidationError
from django.forms.renderers import TemplatesSetting

DEFAULT_MESSAGES = {
    "mail_sent_ok": "Thank you for your message. It has been sent.",
    "mail_sent_ng": "There was an error trying to send your message. Please try again later.",
    "validation_error": "One or more fields have an error. Please check and try again.",
    "spam": "There was an error trying to send your message. Please try again later.",
    "invalid_required": "Please fill out this field.",
    "invalid_too_long": "This field has a too long input.",
    "invalid_email": "Please enter an email address.",
    "invalid_tel": "Please enter a telephone number.",
}

# PHP's trim() set plus the Unicode spaces wpcf7_strip_whitespaces() removes.
_WHITESPACE = ("\u0009\u000b\u000c  ﻿ ᠎       "
               "    ​    　\u000a\u000d\u0000")


def strip_whitespaces(value):
    return value.strip(_WHITESPACE)


def sanitize(value):
    """wp_check_invalid_utf8 + wp_kses_no_null."""
    return re.sub(r"\\+0+", "", value.replace("\0", ""))


def is_email(text):
    """WordPress is_email()."""
    if len(text) < 6 or "@" not in text[1:]:
        return False
    local, domain = text.split("@", 1)
    if not re.fullmatch(r"[a-zA-Z0-9!#$%&'*+/=?^_`{|}~.-]+", local):
        return False
    if ".." in domain or domain.strip(" \t\n\r\0\x0b.") != domain:
        return False
    subs = domain.split(".")
    if len(subs) < 2:
        return False
    for sub in subs:
        if sub.strip(" \t\n\r\0\x0b-") != sub or not re.fullmatch(r"[a-z0-9-]+", sub, re.I):
            return False
    return True


def is_tel(text):
    """wpcf7_is_tel()."""
    text = re.sub(r"[#*].*$", "", text)
    text = re.sub(r"[()/.*#\s-]+", "", text)
    if text.startswith(("+", "00")):
        text = "+" + re.sub(r"^[+0]+", "", text)
    return bool(re.fullmatch(r"[+]?[0-9]+", text)) and 5 < len(text) < 16


def code_units(text):
    """wpcf7_count_code_units(): UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def validate_email(value):
    if not is_email(value):
        raise ValidationError("", code="invalid_email")


def validate_tel(value):
    if not is_tel(value):
        raise ValidationError("", code="invalid_tel")


class MaxCodeUnitsValidator:
    def __init__(self, limit):
        self.limit = limit

    def __call__(self, value):
        if code_units(value) > self.limit:
            raise ValidationError("", code="invalid_too_long")


# ----------------------------------------------------------------------------- widgets
class CF7Input(forms.TextInput):
    template_name = "contact/widgets/input.html"


class CF7Textarea(forms.Textarea):
    template_name = "contact/widgets/textarea.html"


# ----------------------------------------------------------------------------- fields
class CF7Field(forms.CharField):
    """A CF7 form-tag: [text], [email], [tel] or [textarea], with a trailing * when required."""

    kind = "text"
    input_type = "text"
    widget = CF7Input
    default_maxlength = 400
    # CF7 adds these classes after wpcf7-form-control wpcf7-<kind> [wpcf7-validates-as-required].
    extra_classes = ()

    def __init__(self, *, placeholder="", maxlength=None, **kwargs):
        self.maxlength = maxlength or self.default_maxlength
        self.placeholder = placeholder
        kwargs.setdefault("required", False)
        super().__init__(strip=False, **kwargs)
        self.validators.append(MaxCodeUnitsValidator(self.maxlength))

    def to_python(self, value):
        # The mail and the stored submission get the value CF7 validated: sanitised, whitespace trimmed.
        return strip_whitespaces(sanitize(super().to_python(value)))

    def widget_attrs(self, widget):
        classes = ["wpcf7-form-control", f"wpcf7-{self.kind}"]
        if self.required:
            classes.append("wpcf7-validates-as-required")
        classes.extend(self.extra_classes)
        attrs = {"class": " ".join(classes), "maxlength": self.maxlength, "placeholder": self.placeholder}
        if isinstance(widget, CF7Input):
            widget.input_type = self.input_type
        return attrs


class TextField(CF7Field):
    pass


class EmailField(CF7Field):
    kind = input_type = "email"
    extra_classes = ("wpcf7-text", "wpcf7-validates-as-email")
    default_validators = [validate_email]


class TelField(CF7Field):
    kind = input_type = "tel"
    extra_classes = ("wpcf7-text", "wpcf7-validates-as-tel")
    default_validators = [validate_tel]


class TextareaField(CF7Field):
    kind = "textarea"
    widget = CF7Textarea
    default_maxlength = 2000


# ----------------------------------------------------------------------------- forms
class CF7Form(forms.Form):
    """Base for the CF7 forms. Subclasses set wp_id, layout and submit_label.

    layout: [(field name or "submit", wrapper classes)] in markup order.
    """

    wp_id = None
    layout = ()
    submit_label = "Send"
    template_name = "contact/cf7_form.html"
    default_renderer = TemplatesSetting

    def __init__(self, *args, messages=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = messages or {}
        for field in self.fields.values():
            field.error_messages = {
                "required": self.message("invalid_required"),
                **{code: self.message(code) for code in ("invalid_email", "invalid_tel", "invalid_too_long")},
            }

    def message(self, key):
        return self.messages.get(key) or DEFAULT_MESSAGES.get(key, "")

    def rule_order(self):
        """CF7's text module (text, email, tel) adds its rules before the textarea module."""
        names = list(self.fields)
        return ([n for n in names if not isinstance(self.fields[n], TextareaField)]
                + [n for n in names if isinstance(self.fields[n], TextareaField)])

    def schema_rules(self):
        """The SWV rules served at .../feedback/schema, used by CF7's JS for client-side validation."""
        rules = []
        for name in self.rule_order():
            field = self.fields[name]
            if field.required:
                rules.append({"rule": "required", "field": name, "error": self.message("invalid_required")})
            if isinstance(field, EmailField):
                rules.append({"rule": "email", "field": name, "error": self.message("invalid_email")})
            elif isinstance(field, TelField):
                rules.append({"rule": "tel", "field": name, "error": self.message("invalid_tel")})
            rules.append({"rule": "maxlength", "field": name, "threshold": field.maxlength,
                          "error": self.message("invalid_too_long")})
        return rules

    def invalid_fields(self):
        """{name: first error} in rule order (WPCF7_Validation keeps one error per field)."""
        self.is_valid()
        return {name: self.errors[name][0] for name in self.rule_order() if name in self.errors}

    def rows(self):
        for name, wrapper in self.layout:
            yield {"wrapper": wrapper, "submit": name == "submit", "field": None if name == "submit" else self[name]}


def cf7_names(cls):
    """CF7 field names have hyphens: text_67 is declared, "text-67" is posted and used in mail tags."""
    cls.base_fields = cls.declared_fields = {name.replace("_", "-"): f for name, f in cls.base_fields.items()}
    return cls


@cf7_names
class ContactPageForm(CF7Form):
    """CF7 #166 "Contact Page Contact Form" (the contact-us page)."""

    wp_id = 166
    submit_label = "Submit My enquiry"
    layout = (("text-67", "full"), ("email-999", "full"), ("tel-87", "full"), ("textarea-725", "full"),
              ("submit", "full"))

    text_67 = TextField(label="Your Name", placeholder="Your Name", required=True)
    email_999 = EmailField(label="Your email", placeholder="your Email", required=True)
    tel_87 = TelField(label="Contact number", placeholder="your telephone number")
    textarea_725 = TextareaField(label="Comments", placeholder="Enter your optional message here")


@cf7_names
class CourseContactForm(CF7Form):
    """CF7 #290 "Course Contact" (course pages, posts and default pages)."""

    wp_id = 290
    submit_label = "Submit My enquiry"
    layout = (("text-67", "half"), ("textarea-725", "half right"), ("email-999", "half"), ("tel-87", "half"),
              ("submit", "half right"))

    text_67 = TextField(label="Your Name", placeholder="Your Name", required=True)
    textarea_725 = TextareaField(label="Comments", placeholder="Enter your message here", required=True)
    email_999 = EmailField(label="Your email", placeholder="your Email", required=True)
    tel_87 = TelField(label="Contact number", placeholder="your telephone number", required=True)


FORMS = {form.wp_id: form for form in (ContactPageForm, CourseContactForm)}
