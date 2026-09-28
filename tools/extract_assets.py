"""Build the static asset tree and <head>/<footer> asset partials from the WordPress clone.

Reads the golden HTML captured by tools/visual/golden.sh and:
  * copies every local CSS/JS source (the originals, not Autoptimize's cache copies)
    into static/wp/<same path as in WordPress>, so relative url() references keep working;
  * writes templates/wp_assets/<id>.html with the exact tag markup of every enqueued
    asset (external <link>/<script> and inline <style>/<script> blocks);
  * writes apps/core/wp_assets.json with the head/footer order per page profile.

Run again whenever the WordPress theme or plugins change:
    python tools/extract_assets.py
"""
import base64
import json
import re
import shutil
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
WP = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent
GOLDEN = ROOT / "tools/visual/golden"
STATIC = ROOT / "static/wp"
PARTIALS = ROOT / "templates/wp_assets"
MANIFEST = ROOT / "apps/core/wp_assets.json"
OLD_BASE = "http://localhost/sst/"

# Autoptimize serves minified copies; map each handle back to its source file.
AUTOPTIMIZED = {
    "twentyseventeen-parent-style-css": "wp-content/themes/twentyseventeen/style.css",
    "wc-blocks-style-css": "wp-content/plugins/woocommerce/assets/client/blocks/wc-blocks.css",
    "contact-form-7-css": "wp-content/plugins/contact-form-7/includes/css/styles.css",
    "woocommerce-layout-css": "wp-content/plugins/woocommerce/assets/css/woocommerce-layout.css",
    "woocommerce-smallscreen-css": "wp-content/plugins/woocommerce/assets/css/woocommerce-smallscreen.css",
    "woocommerce-general-css": "wp-content/plugins/woocommerce/assets/css/twenty-seventeen.css",
    "slick-css": "wp-content/themes/twentyseventeen-child/assets/css/slick.css",
    "lightbox-css": "wp-content/themes/twentyseventeen-child/assets/css/lightbox.css",
    "twentyseventeen-style-css": "wp-content/themes/twentyseventeen-child/style.css",
    "twentyseventeen-block-style-css": "wp-content/themes/twentyseventeen/assets/css/blocks.css",
    "twentyseventeen-global-js": "wp-content/themes/twentyseventeen/assets/js/global.js",
    "swv-js": "wp-content/plugins/contact-form-7/includes/swv/js/index.js",
    "contact-form-7-js": "wp-content/plugins/contact-form-7/includes/js/index.js",
    "cf7apps-honeypot-refill-js": "wp-content/plugins/contact-form-7-honeypot/legacy-honeypot/includes/js/honeypot-refill.js",
    "customjs-js": "wp-content/themes/twentyseventeen-child/assets/js/custom.js",
    "jquery-scrollto-js": "wp-content/themes/twentyseventeen/assets/js/jquery.scrollTo.js",
    "wpcf7-recaptcha-js": "wp-content/plugins/contact-form-7/modules/recaptcha/index.js",
    "wc-stripe-upe-classic-css": "wp-content/plugins/woocommerce-gateway-stripe/build/upe-classic.css",
    "stripelink_styles-css": "wp-content/plugins/woocommerce-gateway-stripe/assets/css/stripe-link.css",
}

# Handles not carried over: WP-only features, or replaced by Django code.
DROP_PREFIXES = (
    "wp-emoji", "akismet", "comment-reply", "sourcebuster", "wc-order-attribution",
    "react", "wc-types", "wp-private-apis", "wp-url", "wp-api-fetch", "wc-settings",
    "wp-deprecated", "wp-dom", "wp-escape-html", "wp-element", "wp-is-shallow-equal",
    "wp-keycodes", "wp-priority-queue", "wp-undo-manager", "wp-compose", "wp-redux-routine",
    "wp-data", "wc-stripe-upe-classic-js", "stripe-js", "wc-custom-place-order-button",
    "sst-critical-",
)

# Directories copied whole so that relative url() references resolve.
COPY_TREES = [
    "wp-content/themes/twentyseventeen-child/assets",
    "wp-content/themes/twentyseventeen/assets/css",
    "wp-content/themes/twentyseventeen/assets/js",
    "wp-content/themes/twentyseventeen/assets/images",
    "wp-content/plugins/woocommerce/assets/css",
    "wp-content/plugins/woocommerce/assets/fonts",
    "wp-content/plugins/woocommerce/assets/images",
    "wp-content/plugins/woocommerce/assets/js/frontend",
    "wp-content/plugins/woocommerce/assets/js/jquery-blockui",
    "wp-content/plugins/woocommerce/assets/js/js-cookie",
    "wp-content/plugins/woocommerce/assets/js/selectWoo",
    "wp-content/plugins/woocommerce/assets/js/zoom",
    "wp-content/plugins/woocommerce/assets/js/flexslider",
    "wp-content/plugins/woocommerce/assets/js/photoswipe",
    "wp-content/plugins/contact-form-7/includes/css",
    "wp-content/plugins/contact-form-7/includes/js",
    "wp-content/plugins/contact-form-7/includes/swv/js",
    "wp-content/plugins/contact-form-7/modules/recaptcha",
    "wp-content/plugins/contact-form-7-honeypot/legacy-honeypot/includes",
    "wp-content/plugins/woocommerce-gateway-stripe/assets/css",
    "wp-content/plugins/woocommerce-gateway-stripe/build",
]
COPY_FILES = [
    "wp-content/themes/twentyseventeen/style.css",
    "wp-content/themes/twentyseventeen-child/style.css",
    "wp-content/plugins/woocommerce/assets/client/blocks/wc-blocks.css",
    "wp-includes/js/jquery/jquery.min.js",
    "wp-includes/js/jquery/jquery-migrate.min.js",
    "wp-includes/js/hoverIntent.min.js",
    "wp-includes/js/dist/hooks.min.js",
    "wp-includes/js/dist/i18n.min.js",
    "wp-includes/js/dist/vendor/wp-polyfill.min.js",
]
SKIP_SUFFIXES = (".php", ".map", ".scss", ".md", ".txt")

# Which golden page defines each profile's asset list.
PROFILES = {
    "default": "contact.html",
    "home": "home.html",
    "shop": "shop.html",
    "product_category": "cat_smsts.html",
    "page_with_datepicker": "fire_safety.html",
    "product": "product_session.html",
    "basket": "basket_full.html",
    "checkout": "checkout.html",
}


def copy_sources():
    if STATIC.exists():
        shutil.rmtree(STATIC)
    for tree in COPY_TREES:
        src = WP / tree
        if src.is_dir():
            shutil.copytree(
                src, STATIC / tree,
                ignore=lambda d, names: [n for n in names if n.endswith(SKIP_SUFFIXES) or n == "_notes"],
            )
    for f in COPY_FILES:
        dst = STATIC / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WP / f, dst)


def is_local(url: str) -> bool:
    return url.startswith(OLD_BASE) or url.startswith("//localhost/sst/")


def local_url(url: str, handle: str) -> str:
    """Map a WP asset URL to its /static/wp/ counterpart."""
    path, _, query = url.replace(OLD_BASE, "").replace("//localhost/sst/", "").partition("?")
    if "cache/autoptimize" in path:
        path = AUTOPTIMIZED[handle]
    query = re.sub(r"&#038;|&amp;", "&", query)
    return "/static/wp/" + path + (("?" + query) if query else "")


def rewrite_inline(text: str) -> str:
    text = text.replace("http:\\/\\/localhost\\/sst\\/", "\\/").replace("\\/sst\\/", "\\/")
    return text.replace(OLD_BASE, "/").replace("/sst/", "/")


def handle_of(tag):
    return tag.get("id")


def dropped(handle):
    return handle.startswith(DROP_PREFIXES)


DATA_JS = "data:text/javascript;base64,"


def normalise(tag, handle):
    """Rewrite one asset tag in place so it points at Django-served files."""
    src = tag.get("src", "")
    if src.startswith(DATA_JS):
        # Autoptimize moved inline scripts into deferred data: URIs; keep that
        # (it preserves execution order) but fix the URLs inside.
        code = rewrite_inline(base64.b64decode(src[len(DATA_JS):]).decode("utf-8"))
        tag["src"] = DATA_JS + base64.b64encode(code.encode("utf-8")).decode("ascii")
    elif is_local(src):
        tag["src"] = local_url(src, handle)
    if tag.name == "link" and is_local(tag.get("href", "")):
        tag["href"] = local_url(tag["href"], handle)
    if tag.string:
        tag.string.replace_with(rewrite_inline(str(tag.string)))
    return str(tag) + "\n"


def extract():
    PARTIALS.mkdir(parents=True, exist_ok=True)
    for old in PARTIALS.glob("*.html"):
        old.unlink()
    manifest = {}
    written = {}
    for profile, page in PROFILES.items():
        soup = BeautifulSoup((GOLDEN / page).read_text(encoding="utf-8"), "lxml")
        order = {"head": [], "footer": []}
        for tag in soup.find_all(["link", "style", "script"]):
            handle = handle_of(tag)
            if not handle or dropped(handle) or tag.get("type") == "application/ld+json":
                continue
            if tag.name == "link" and tag.get("rel") != ["stylesheet"]:
                continue
            where = "head" if tag.find_parent("head") else "footer"
            markup = normalise(tag, handle)
            name = handle
            if handle not in written:
                written[handle] = markup
            elif written[handle] != markup:
                # Same handle, different content on this page type (e.g. is_checkout).
                name = f"{handle}.{profile}"
            if not (PARTIALS / f"{name}.html").exists():
                (PARTIALS / f"{name}.html").write_text(markup, encoding="utf-8")
            order[where].append(name)
        manifest[profile] = order
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    copy_sources()
    m = extract()
    for k, v in m.items():
        print(f"{k}: head={len(v['head'])} footer={len(v['footer'])}")
