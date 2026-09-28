from django.conf import settings

from .models import SiteOptions


def site(request):
    return {
        "site_options": SiteOptions.load(),
        "site_url": settings.SITE_URL,
        "ga4_id": settings.GA4_MEASUREMENT_ID,
        "google_site_verification": settings.GOOGLE_SITE_VERIFICATION,
    }
