import re
from datetime import datetime, timezone as dt_tz

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.blog.models import AuthorProfile, Category, Post
from apps.pages.models import Page
from apps.seo.engine import Seo, SeoData, esc_attr
from apps.seo.models import SeoSettings

SITE = "https://www.example.test"


def dt(*args):
    return datetime(*args, tzinfo=dt_tz.utc)


@pytest.fixture
def site(db, settings):
    settings.SITE_URL = SITE
    s = SeoSettings.load()
    s.separator = "-"
    s.title_templates = {
        "title-page": "%%title%% %%page%% %%sep%% %%sitename%%",
        "title-post": "%%title%% %%page%% %%sep%% %%sitename%%",
        "metadesc-page": "",
        "title-search-wpseo": "You searched for %%searchphrase%% %%page%% %%sep%% %%sitename%%",
        "title-404-wpseo": "Page not found %%sep%% %%sitename%%",
        "title-tax-category": "%%term_title%% Archives %%page%% %%sep%% %%sitename%%",
    }
    s.save()
    return s


def make_page(title, slug, **kw):
    page = Page(title=title, slug=slug, status="publish", **kw)
    page.published_at = kw.pop("published_at", dt(2024, 1, 2, 9, 0, 0))
    page.modified_at = dt(2025, 3, 4, 10, 30, 0)
    page.save(keep_modified=True)
    return page


@pytest.fixture
def content(site):
    front = make_page("Home", "home", is_front_page=True)
    about = make_page("About & Contact", "about-us",
                      content='<p>Hi</p><img class="alignnone" src="/wp-content/uploads/2024/01/team.jpg" />')
    make_page("Draft", "draft-page").__class__.objects.filter(slug="draft-page").update(status="draft")
    make_page("Hidden", "hidden", noindex=True)
    user = get_user_model().objects.create(username="daniel", email="daniel@example.com")
    AuthorProfile.objects.create(user=user, nicename="daniel", display_name="Daniel")
    cat = Category.objects.create(name="Guides", slug="guides")
    post = Post(title="SMSTS online vs classroom", slug="smsts-online-vs-classroom", status="publish",
                author=user, content="<p>" + "word " * 450 + "</p>")
    post.published_at = dt(2026, 6, 1, 8, 0, 0)
    post.modified_at = dt(2026, 6, 10, 9, 59, 39)
    post.save(keep_modified=True)
    post.categories.add(cat)
    return {"front": front, "about": about, "post": post, "user": user}


# ----------------------------------------------------------------------------- titles
def test_title_template_rendering(site):
    rf = RequestFactory()
    seo = Seo(rf.get("/"))
    assert seo.replace_vars("%%title%% %%page%% %%sep%% %%sitename%%", title="About") == "About - Site Safety Training"
    seo = Seo(rf.get("/"), page_number=2, total_pages=5)
    assert (seo.replace_vars("%%title%% %%page%% %%sep%% %%sitename%%", title="News")
            == "News - Page 2 of 5 - Site Safety Training")
    assert seo.replace_vars("%%sitename%% %%unknownvar%% %%sep%% %%sitedesc%%").startswith("Site Safety Training - ")


def test_singular_page_head(content):
    data = Seo(RequestFactory().get("/about-us/")).singular(content["about"], "/about-us/")
    assert data.title == "About & Contact - Site Safety Training"
    assert data.canonical == SITE + "/about-us/"
    assert data.og_type == "article"
    assert data.modified == "2025-03-04T10:30:00+00:00"
    html = data.head_html
    assert "<title>About &amp; Contact - Site Safety Training</title>" in html
    assert '<meta property="og:title" content="About &amp; Contact - Site Safety Training" />' in html
    assert '<link rel="canonical" href="https://www.example.test/about-us/" />' in html
    types = [n["@type"] for n in data.graph]
    assert types[0] == "WebPage" and "BreadcrumbList" in types and "WebSite" in types
    assert data.graph[0]["primaryImageOfPage"]["@id"] == SITE + "/about-us/#primaryimage"


def test_post_head_has_article_and_reading_time(content):
    data = Seo(RequestFactory().get("/")).singular(content["post"], content["post"].get_absolute_url())
    assert data.published == "2026-06-01T08:00:00+00:00"
    assert data.author == "Daniel"
    assert data.twitter == [("Written by", "Daniel"), ("Estimated reading time", "2 minutes")]
    article = data.graph[0]
    assert article["@type"] == "Article"
    assert article["articleSection"] == ["Guides"]
    assert any(n["@type"] == "Person" for n in data.graph)


def test_search_and_404(site):
    rf = RequestFactory()
    data = Seo(rf.get("/?s=smsts")).search("smsts")
    assert data.title == "You searched for smsts - Site Safety Training"
    assert data.robots == "noindex, follow"
    nf = Seo(rf.get("/x/")).not_found()
    assert nf.title == "Page not found - Site Safety Training"
    assert 'og:type' not in nf.head_html and "twitter:card" not in nf.head_html


def test_escaping_matches_wordpress():
    assert esc_attr('Tom & Jerry "quoted" <b>') == "Tom &amp; Jerry &quot;quoted&quot; &lt;b&gt;"
    assert esc_attr("R&amp;D &hellip; &#8211; &bogus;") == "R&amp;D &hellip; &#8211; &amp;bogus;"
    assert esc_attr("it's") == "it&#039;s"
    assert SeoData(title="A & B").head_html.startswith("<title>A &amp; B</title>")


# ----------------------------------------------------------------------------- robots / sitemaps
def test_robots_txt(client, site):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r["Content-Type"] == "text/plain; charset=utf-8"
    text = r.content.decode()
    assert text.startswith("User-agent: *\nDisallow: /wp-content/uploads/wc-logs/\n")
    assert "Disallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n" in text
    assert "/sst/" not in text
    assert "# START YOAST BLOCK" in text and text.rstrip().endswith("# END YOAST BLOCK")
    assert f"Sitemap: {SITE}/sitemap_index.xml" in text


def test_sitemap_index(client, content):
    r = client.get("/sitemap_index.xml")
    assert r.status_code == 200
    assert r["Content-Type"] == "text/xml; charset=UTF-8"
    assert r["X-Robots-Tag"] == "noindex, follow"
    xml = r.content.decode()
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?><?xml-stylesheet type="text/xsl" '
                          'href="//www.example.test/main-sitemap.xsl"?>\n<sitemapindex ')
    assert xml.endswith("</sitemapindex>\n<!-- XML Sitemap generated by Yoast SEO -->")
    locs = re.findall(r"<loc>(.*?)</loc>", xml)
    assert locs == [f"{SITE}/post-sitemap.xml", f"{SITE}/page-sitemap.xml", f"{SITE}/category-sitemap.xml",
                    f"{SITE}/author-sitemap.xml"]
    assert ("\t<sitemap>\n\t\t<loc>https://www.example.test/post-sitemap.xml</loc>\n"
            "\t\t<lastmod>2026-06-10T09:59:39+00:00</lastmod>\n\t</sitemap>\n") in xml


def test_page_sitemap_entries(client, content):
    xml = client.get("/page-sitemap.xml").content.decode()
    assert '<urlset xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' in xml
    locs = re.findall(r"<loc>(.*?)</loc>", xml)
    # front page first, then by modified date; drafts, noindex pages and the front page row excluded
    assert locs[0] == SITE + "/"
    assert SITE + "/about-us/" in locs
    assert not any("draft-page" in u or "hidden" in u for u in locs)
    assert locs.count(SITE + "/") == 1
    assert ("\t<url>\n\t\t<loc>https://www.example.test/about-us/</loc>\n"
            "\t\t<lastmod>2025-03-04T10:30:00+00:00</lastmod>\n"
            "\t\t<image:image>\n\t\t\t<image:loc>https://www.example.test/wp-content/uploads/2024/01/team.jpg"
            "</image:loc>\n\t\t</image:image>\n\t</url>\n") in xml


def test_other_sitemaps(client, content):
    post_xml = client.get("/post-sitemap.xml").content.decode()
    assert f"<loc>{SITE}/blog/smsts-online-vs-classroom/</loc>" in post_xml
    cat_xml = client.get("/category-sitemap.xml").content.decode()
    assert f"<loc>{SITE}/guides/</loc>\n\t\t<lastmod>2026-06-10T09:59:39+00:00</lastmod>" in cat_xml
    author_xml = client.get("/author-sitemap.xml").content.decode()
    assert f"<loc>{SITE}/blog/author/daniel/</loc>" in author_xml
    assert client.get("/page-sitemap1.xml").status_code == 301
    assert client.get("/page-sitemap2.xml").status_code == 404
    assert client.get("/testimonials-sitemap.xml").status_code == 404
    assert client.get("/main-sitemap.xsl").content.startswith(b"<?xml")
