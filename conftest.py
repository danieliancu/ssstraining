import pytest


@pytest.fixture(autouse=True)
def _locmem_email(settings):
    """Never send real mail from tests (prod settings use the Brevo backend)."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.RECAPTCHA_SECRET_KEY = ""
