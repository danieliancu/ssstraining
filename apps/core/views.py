from django.http import Http404
from django.shortcuts import render

from apps.core.bodyclass import error404_classes
from apps.seo.engine import Seo


def wp_render(request, template, context, *, seo, body_class, profile="default", status=200):
    """Render a theme template with the context base.html expects."""
    context = {**context, "seo": seo, "body_class": body_class, "asset_profile": profile}
    return render(request, template, context, status=status)


def page_number(request, page=None):
    try:
        return max(1, int(page or request.GET.get("paged") or 1))
    except (TypeError, ValueError):
        raise Http404


def not_found(request, exception=None):
    from apps.core.models import SiteOptions
    return wp_render(request, "404.html", {"options": SiteOptions.load()}, seo=Seo(request).not_found(),
                     body_class=error404_classes(), status=404)
