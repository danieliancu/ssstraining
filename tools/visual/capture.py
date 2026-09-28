"""Screenshot the same URLs on WordPress and Django and pixel-diff them.

    python tools/visual/capture.py /contact-us/ /blog/ ...      # specific paths
    python tools/visual/capture.py --all                         # every path in URLS
    python tools/visual/capture.py --widths 1440,375 /contact-us/
    python tools/visual/capture.py "/?add-to-cart=2823&quantity=2>>/basket/"   # prep path >> page

Writes tools/visual/out/<slug>-<width>-{wp,dj,diff}.png and prints the % of differing pixels.
Animations, carousels and third-party iframes are frozen/masked so only real differences show.
"""
import argparse
import os
import re
import sys
from pathlib import Path

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch
from playwright.sync_api import sync_playwright

WP = "http://localhost/sst"
WP_PREFIX = "/sst"
DJ = os.environ.get("SST_DJ_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).parent / "out"

URLS = [
    "/", "/contact-us/", "/privacy-policy/", "/cookie-policy/", "/nebosh-tutoring/",
    "/certificate-in-fire-safety/", "/environmental-management-certificate/", "/nebosh-distance-learning/",
    "/level-2-nvqs/", "/shop/", "/product-category/smsts/", "/product-category/nvq/",
    "/product/site-management-safety-training-scheme-03-10-2026/", "/product/level-7-senior-site-management/",
    "/blog/", "/blog/smsts-online-vs-classroom/", "/blog/author/daniel/", "/blog/news/",
    "/blog/news/nebosh-course-offers/", "/blog/nebosh_course/", "/blog/nebosh_course/nebosh-general-certificate/",
    "/blog/safety_course/", "/blog/safety_course/site-manager-safety-training-scheme-smsts/",
    "/?s=smsts", "/this-page-does-not-exist/", "/basket/",
]

FREEZE_CSS = """
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
iframe { visibility: hidden !important; }
#full-page-widget, .reviews-io-carousel-widget, [id^="carousel-inline-widget"], .grecaptcha-badge { visibility: hidden !important; }
"""


def shoot(page, url, path, prep=None):
    """prep: a path visited first on the same site (e.g. '/?add-to-cart=2823&quantity=2')."""
    if prep:
        base = url.split("/", 3)
        page.goto("/".join(base[:3]) + (WP_PREFIX if url.startswith(WP) else "") + prep, wait_until="networkidle", timeout=60000)
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.add_style_tag(content=FREEZE_CSS)
    page.evaluate("""() => {
        if (window.jQuery) { jQuery('.slick-initialized').each(function(){ try { jQuery(this).slick('slickPause').slick('slickGoTo', 0, true); } catch(e){} }); }
        window.scrollTo(0, 0);
    }""")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(400)
    page.screenshot(path=str(path), full_page=True)


def diff(a_path, b_path, out_path):
    a, b = Image.open(a_path).convert("RGBA"), Image.open(b_path).convert("RGBA")
    w, h = max(a.width, b.width), max(a.height, b.height)
    canvas_a = Image.new("RGBA", (w, h), (255, 0, 255, 255))
    canvas_b = Image.new("RGBA", (w, h), (255, 0, 255, 255))
    canvas_a.paste(a, (0, 0))
    canvas_b.paste(b, (0, 0))
    out = Image.new("RGBA", (w, h))
    mismatch = pixelmatch(canvas_a, canvas_b, out, threshold=0.1, includeAA=False)
    out.save(out_path)
    return mismatch / (w * h) * 100, (a.height, b.height)


def slug(path):
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") or "home"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--widths", default="1440,375")
    ap.add_argument("--threshold", type=float, default=0.1, help="max %% of differing pixels to count as a pass")
    args = ap.parse_args()
    paths = URLS if args.all else args.paths
    widths = [int(w) for w in args.widths.split(",")]
    OUT.mkdir(exist_ok=True)
    failed = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in widths:
            ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
            page = ctx.new_page()
            for spec in paths:
                prep, _, path = spec.rpartition(">>")
                prep = prep or None
                name = f"{slug(path)}{'-' + slug(prep) if prep else ''}-{width}"
                wp_png, dj_png, diff_png = OUT / f"{name}-wp.png", OUT / f"{name}-dj.png", OUT / f"{name}-diff.png"
                try:
                    shoot(page, WP + path, wp_png, prep)
                    ctx.clear_cookies()
                    shoot(page, DJ + path, dj_png, prep)
                    ctx.clear_cookies()
                    pct, heights = diff(wp_png, dj_png, diff_png)
                except Exception as exc:  # keep going for the other pages
                    print(f"ERROR {path} @{width}: {exc}")
                    failed += 1
                    continue
                ok = pct <= args.threshold and heights[0] == heights[1]
                failed += not ok
                print(f"{'OK  ' if ok else 'DIFF'} {path:<70} @{width:<5} {pct:6.3f}%  heights wp={heights[0]} dj={heights[1]}")
            ctx.close()
        browser.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
