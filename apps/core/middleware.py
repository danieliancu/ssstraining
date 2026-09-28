from django.db.models import F
from django.http import HttpResponseGone, HttpResponsePermanentRedirect, HttpResponseRedirect

from .models import NotFoundLog, Redirect


class RedirectMiddleware:
    """Serve admin-managed redirects and legacy WordPress URL forms before routing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        # The local WP clone lived under /sst/; strip it if an old link still uses it.
        if path == "/sst" or path.startswith("/sst/"):
            target = path[4:] or "/"
            qs = request.META.get("QUERY_STRING")
            return HttpResponsePermanentRedirect(target + (f"?{qs}" if qs else ""))

        if request.method == "GET":
            response = self._legacy_query_redirect(request)
            if response:
                return response
            redirect = Redirect.objects.filter(old_path=path).first()
            if redirect:
                Redirect.objects.filter(pk=redirect.pk).update(hits=F("hits") + 1)
                if redirect.new_path == "410":
                    return HttpResponseGone()
                cls = HttpResponsePermanentRedirect if redirect.permanent else HttpResponseRedirect
                return cls(redirect.new_path)
        return self.get_response(request)

    def _legacy_query_redirect(self, request):
        """/?p=123, /?page_id=123, /?attachment_id=123 → canonical URL."""
        if request.path != "/":
            return None
        from apps.wpimport.legacy import resolve_legacy_query
        target = resolve_legacy_query(request.GET)
        return HttpResponsePermanentRedirect(target) if target else None


class NotFoundLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 404 and not request.path.startswith(("/static/", "/admin/")):
            log, _ = NotFoundLog.objects.get_or_create(path=request.path[:255])
            NotFoundLog.objects.filter(pk=log.pk).update(
                hits=F("hits") + 1, referer=request.META.get("HTTP_REFERER", "")[:500])
        return response
