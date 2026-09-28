"""URL map. Paths match the WordPress site so existing links and rankings carry over."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import RedirectView

from apps.blog import views as blog
from apps.cart import views as cart
from apps.catalog import views as catalog
from apps.checkout import views as checkout
from apps.contact import views as contact
from apps.courses import views as courses
from apps.exampapers import views as exampapers
from apps.mmc import views as mmc
from apps.news import views as news
from apps.pages import views as pages
from apps.search import views as search
from apps.seo import views as seo

P = r"(?:page/(?P<page>\d+)/)?"  # optional /page/N/ pagination suffix

urlpatterns = [
    path("admin/", admin.site.urls),
    path("tinymce/", __import__("django.urls", fromlist=["include"]).include("tinymce.urls")),

    # SEO / system
    path("robots.txt", seo.robots_txt),
    path("sitemap_index.xml", seo.sitemap_index, name="sitemap_index"),
    path("sitemap.xml", RedirectView.as_view(url="/sitemap_index.xml", permanent=True)),
    path("main-sitemap.xsl", seo.sitemap_xsl),
    re_path(r"^(?P<kind>[a-z_]+)-sitemap(?P<number>\d*)\.xml$", seo.sitemap, name="sitemap"),
    path("favicon.svg", seo.favicon),

    # AJAX / integrations (WordPress-compatible paths used by the unchanged theme JS)
    path("wp-admin/admin-ajax.php", search.admin_ajax),
    path("wp-json/contact-form-7/v1/contact-forms/<int:form_id>/feedback", contact.feedback),
    path("wp-json/contact-form-7/v1/contact-forms/<int:form_id>/feedback/schema", contact.schema),
    path("wp-json/contact-form-7/v1/contact-forms/<int:form_id>/refill", contact.refill),
    path("wp-json/mmc-wc/v1/webhook", mmc.webhook),
    path("mmc/webhook/", mmc.webhook, name="mmc_webhook"),
    path("stripe/webhook/", checkout.stripe_webhook, name="stripe_webhook"),
    re_path(r"^(?:wp-admin|wp-login\.php)", RedirectView.as_view(url="/admin/", permanent=False)),

    # Shop
    path("", pages.front_page, name="home"),
    re_path(rf"^shop/{P}$", catalog.shop, name="shop"),
    path("product/<str:slug>/", catalog.product_detail, name="product_detail"),
    re_path(rf"^product-category/(?P<path>[\w\-/]+?)/{P}$", catalog.category, name="product_category"),
    re_path(rf"^product-tag/(?P<slug>[\w\-]+)/{P}$", catalog.tag, name="product_tag"),
    path("basket/", cart.basket, name="basket"),
    path("checkout-2/", checkout.checkout, name="checkout"),
    path("checkout-2/order-received/<int:order_id>/", checkout.order_received, name="order_received"),
    path("checkout-2/order-pay/<int:order_id>/", checkout.order_pay, name="order_pay"),

    # Blog and post types (the permalink structure is /blog/%postname%/)
    re_path(rf"^blog/{P}$", blog.index, name="blog_index"),
    re_path(rf"^blog/author/(?P<nicename>[\w\-]+)/{P}$", blog.author, name="blog_author"),
    re_path(rf"^blog/tag/(?P<slug>[\w\-]+)/{P}$", blog.tag, name="blog_tag"),
    re_path(rf"^blog/(?P<year>\d{{4}})/(?:(?P<month>\d{{2}})/)?(?:(?P<day>\d{{2}})/)?{P}$", blog.date_archive, name="blog_date"),
    re_path(rf"^blog/news/{P}$", news.archive, name="news_archive"),
    path("blog/news/<str:slug>/", news.detail, name="news_detail"),
    re_path(rf"^blog/news-category/(?P<slug>[\w\-]+)/{P}$", news.category, name="news_category"),
    re_path(rf"^blog/nebosh_course/{P}$", courses.nebosh_archive, name="nebosh_archive"),
    path("blog/nebosh_course/<str:slug>/", courses.nebosh_detail, name="nebosh_detail"),
    re_path(rf"^blog/nebosh_courses/(?P<slug>[\w\-]+)/{P}$", courses.nebosh_term, name="nebosh_term"),
    re_path(rf"^blog/safety_course/{P}$", courses.safety_archive, name="safety_archive"),
    path("blog/safety_course/<str:slug>/", courses.safety_detail, name="safety_detail"),
    re_path(rf"^blog/safety_courses/(?P<slug>[\w\-]+)/{P}$", courses.safety_term, name="safety_term"),
    path("blog/exam-paper/<str:slug>/", exampapers.detail, name="exam_paper_detail"),
    path("blog/<str:slug>/", blog.post_detail, name="blog_post"),

    # Search results (?s=) are served by the front page view; /search/<term>/ is WP's pretty form.
    path("search/<str:term>/", search.pretty_search),

    # Pages and root-level blog categories (category base ".")
    re_path(rf"^(?P<path>[\w\-/]+?)/{P}$", pages.page_detail, name="page"),
]

# blog_category shares the catch-all; reverse() needs its own name.
urlpatterns.append(re_path(rf"^(?P<path>[\w\-/]+?)/{P}$", pages.page_detail, name="blog_category"))

handler404 = "apps.core.views.not_found"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
