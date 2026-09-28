from django.http import Http404
from django.shortcuts import redirect

from apps.core.bodyclass import page_classes
from apps.core.models import Status
from apps.core.views import wp_render
from apps.seo.engine import Seo

from .models import Page

TEMPLATES = {
    Page.Template.DEFAULT: "pages/default.html",
    Page.Template.PAGE_ONLY: "pages/page_only.html",
    Page.Template.API: "pages/api.html",
    Page.Template.NVQ_LEVEL: "pages/nvq_level.html",
    Page.Template.NEBOSH_DL: "pages/nebosh_dl.html",
    Page.Template.CATEGORY: "pages/category_page.html",
    Page.Template.EXAM_PAPERS: "pages/exam_papers.html",
}

# Pages rendered by their own views (WooCommerce / blog index).
SYSTEM_SLUGS = {"shop", "basket", "checkout", "checkout-2", "my-account", "blog"}


def find_page(path):
    slugs = [s for s in path.strip("/").split("/") if s]
    if not slugs:
        return None
    page = None
    for slug in slugs:
        page = Page.objects.filter(slug=slug, parent=page).first()
        if page is None:
            return None
    return page


def page_detail(request, path, page=None):
    from apps.blog.views import category_archive

    page_number = page
    page = find_page(path)
    if page is None:
        # Blog categories live at the root (category base ".").
        return category_archive(request, path, page=page_number)
    if page_number:
        raise Http404
    if page.status != Status.PUBLISH and not request.user.is_staff:
        raise Http404
    if page.is_front_page:
        return redirect("/", permanent=True)
    return render_page(request, page)


def render_page(request, page, extra=None):
    from apps.pages import extras

    template = TEMPLATES.get(page.template, "pages/default.html")
    context = {"page": page, "cf7_container_post": 0}
    profile = "default"
    builder = extras.BUILDERS.get(page.template)
    if builder:
        extra_ctx, profile = builder(request, page)
        context.update(extra_ctx)
    context.update(extra or {})
    seo = Seo(request).singular(page, page.get_absolute_url())
    return wp_render(request, template, context, seo=seo, body_class=page_classes(page), profile=profile)


def front_page(request):
    from apps.pages import extras

    if "s" in request.GET:
        from apps.search.views import search_results
        return search_results(request)
    page = Page.objects.filter(is_front_page=True).first()
    if page is None:
        raise Http404
    context, profile = extras.front_page_context(request, page)
    seo = Seo(request).singular(page, "/", is_front=True)
    return wp_render(request, "pages/front.html", {"page": page, **context}, seo=seo,
                     body_class=page_classes(page), profile="home")
