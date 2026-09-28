"""Compare the Yoast SEO <head> output of WordPress and Django.

    python tools/visual/seo_compare.py                    # default path list (golden.sh pages)
    python tools/visual/seo_compare.py /contact-us/ /blog/
    python tools/visual/seo_compare.py --golden            # use tools/visual/golden/*.html for WP
    python tools/visual/seo_compare.py --show /contact-us/ # print both sides in full

Compared: <title>, meta description/robots/author, canonical, prev/next, og:*, article:*,
twitter:* (raw attribute text, so escaping differences show) and the JSON-LD @graph (parsed,
with both origins normalised to {O}). Set SST_DJ_URL for the Django dev server
(default http://127.0.0.1:8003).
"""
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

import requests

WP = os.environ.get("SST_WP_URL", "http://localhost/sst")
DJ = os.environ.get("SST_DJ_URL", "http://127.0.0.1:8003")
GOLDEN = Path(__file__).parent / "golden"

# name -> path, same list as golden.sh (HTML pages only)
DEFAULT_PAGES = [
    ("home", "/"), ("shop", "/shop/"), ("cat_smsts", "/product-category/smsts/"),
    ("cat_nvq", "/product-category/nvq/"),
    ("product_session", "/product/site-management-safety-training-scheme-03-10-2026/"),
    ("product_nvq", "/product/level-7-senior-site-management/"), ("nvq_level2", "/level-2-nvqs/"),
    ("nebosh_dl", "/nebosh-distance-learning/"), ("fire_safety", "/certificate-in-fire-safety/"),
    ("env_mgmt", "/environmental-management-certificate/"), ("contact", "/contact-us/"),
    ("privacy", "/privacy-policy/"), ("cookie", "/cookie-policy/"), ("ssip", "/nebosh-tutoring/"),
    ("blog", "/blog/"), ("post", "/blog/smsts-online-vs-classroom/"), ("category", "/uncategorised/"),
    ("author", "/blog/author/daniel/"), ("news_archive", "/blog/news/"),
    ("news_single", "/blog/news/nebosh-course-offers/"), ("news_cat", "/blog/news-category/news/"),
    ("nebosh_archive", "/blog/nebosh_course/"),
    ("nebosh_single", "/blog/nebosh_course/nebosh-general-certificate/"),
    ("safety_archive", "/blog/safety_course/"),
    ("safety_single", "/blog/safety_course/site-manager-safety-training-scheme-smsts/"),
    ("search", "/?s=smsts"), ("notfound", "/this-page-does-not-exist/"),
]

ORIGIN_RE = re.compile(r"https?:(?:\\?/){2}(?:localhost(?:\\?/)sst|127\.0\.0\.1:\d+|localhost:\d+|(?:www\.)?sstcourses\.co\.uk)")
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


def norm(s):
    return ORIGIN_RE.sub("{O}", s)


def attrs(tag):
    return {m.group(1).lower(): (m.group(2) if m.group(2) is not None else m.group(3)) for m in ATTR_RE.finditer(tag)}


def extract(page):
    """Return (fields: dict[str, list[str]], graph: list|None) from an HTML page."""
    head = page.split("</head>", 1)[0]
    fields = {}

    def add(key, value):
        fields.setdefault(key, []).append(norm(value))

    m = re.search(r"<title>(.*?)</title>", head, re.S)
    if m:
        add("title", m.group(1))
    for tag in re.findall(r"<meta\s[^>]*>", head, re.S):
        a = attrs(tag)
        key = a.get("property") or a.get("name") or ""
        if key in ("description", "robots", "author") or key.startswith(("og:", "article:", "twitter:")):
            add(key, a.get("content", ""))
    for tag in re.findall(r"<link\s[^>]*>", head, re.S):
        a = attrs(tag)
        if a.get("rel") in ("canonical", "prev", "next"):
            add("link:" + a["rel"], a.get("href", ""))
    graph = None
    m = re.search(r'<script type=["\']?application/ld\+json["\']? class=["\']?yoast-schema-graph["\']?>(.*?)</script>', page, re.S)
    if m:
        try:
            graph = json.loads(m.group(1))
        except ValueError as e:
            graph = {"_error": str(e)}
        graph = json.loads(norm(json.dumps(graph)))
    raw_json = m.group(1) if m else ""
    return fields, graph, raw_json


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def graph_by_type(graph):
    """Key graph nodes by @type so ordering differences show clearly."""
    if not isinstance(graph, dict):
        return {}
    nodes = {}
    for node in graph.get("@graph", []):
        t = node.get("@type")
        t = "+".join(t) if isinstance(t, list) else str(t)
        key = t
        n = 2
        while key in nodes:
            key = f"{t}#{n}"
            n += 1
        nodes[key] = node
    return nodes


def compare(name, path, use_golden, show=False, check_format=True):
    try:
        if use_golden and name and (GOLDEN / f"{name}.html").exists():
            wp = (GOLDEN / f"{name}.html").read_text(encoding="utf-8")
        else:
            wp = requests.get(WP + path, timeout=60).text
    except requests.RequestException as e:
        return [f"WP fetch failed: {e}"]
    try:
        r = requests.get(DJ + path, timeout=60)
    except requests.RequestException as e:
        return [f"Django fetch failed: {e}"]
    dj = r.text
    wf, wg, wraw = extract(wp)
    df, dg, draw = extract(dj)
    if show:
        print("--- WP", json.dumps(wf, indent=1, ensure_ascii=False))
        print("--- DJ", json.dumps(df, indent=1, ensure_ascii=False))
    diffs = []
    if r.status_code >= 400 and "og:site_name" not in df:
        return [f"Django HTTP {r.status_code} (view not ported / error page)"]
    for key in sorted(set(wf) | set(df)):
        a, b = wf.get(key), df.get(key)
        if a != b:
            diffs.append(f"{key}:\n      WP: {a}\n      DJ: {b}")
    # order of meta tags
    worder = [k for k in re.findall(r'(?:property|name)=["\']((?:og|article|twitter):[\w:]+)', wp.split("</head>")[0])]
    dorder = [k for k in re.findall(r'(?:property|name)=["\']((?:og|article|twitter):[\w:]+)', dj.split("</head>")[0])]
    if worder != dorder and not diffs:
        diffs.append(f"meta order:\n      WP: {worder}\n      DJ: {dorder}")
    if (wg is None) != (dg is None):
        diffs.append(f"JSON-LD present: WP={wg is not None} DJ={dg is not None}")
    elif wg is not None:
        wt = [n.get("@type") for n in wg.get("@graph", [])]
        dt = [n.get("@type") for n in dg.get("@graph", [])]
        if wt != dt:
            diffs.append(f"graph node types:\n      WP: {wt}\n      DJ: {dt}")
        wn, dn = graph_by_type(wg), graph_by_type(dg)
        for t in sorted(set(wn) | set(dn)):
            fa, fb = flatten(wn.get(t, {})), flatten(dn.get(t, {}))
            for k in sorted(set(fa) | set(fb), key=lambda k: (k not in fa, k)):
                if fa.get(k, "<missing>") != fb.get(k, "<missing>"):
                    diffs.append(f"graph {t}.{k}:\n      WP: {fa.get(k, '<missing>')!r}\n      DJ: {fb.get(k, '<missing>')!r}")
            if list(fa) != list(fb) and all(fa.get(k) == fb.get(k) for k in set(fa) | set(fb)):
                diffs.append(f"graph {t}: key order differs\n      WP: {list(wn[t])}\n      DJ: {list(dn[t])}")
        if check_format and not diffs and norm(wraw).replace("\r\n", "\n") != norm(draw).replace("\r\n", "\n"):
            diffs.append("JSON-LD text formatting differs (whitespace/escaping)")
    return diffs


SITEMAP_NORM = [
    (re.compile(r"^\ufeff"), ""),
    (re.compile(r"//(?:localhost/sst|127\.0\.0\.1:\d+)(?:/wp-content/plugins/wordpress-seo/css)?/main-sitemap\.xsl"), "//{O}/main-sitemap.xsl"),
    (re.compile(r"\r\n"), "\n"),
]


def compare_sitemaps(show_max=40):
    """Diff /robots.txt, /sitemap_index.xml and every sitemap it lists (line by line)."""
    import difflib
    wp_index = requests.get(WP + "/sitemap_index.xml", timeout=120).text
    paths = ["/robots.txt", "/sitemap_index.xml"] + [
        norm(loc).replace("{O}", "") for loc in re.findall(r"<loc>(.*?)</loc>", wp_index)]
    failing = 0
    for path in paths:
        texts = []
        for base in (WP, DJ):
            t = requests.get(base + path, timeout=300).text
            for rx, rep in SITEMAP_NORM:
                t = rx.sub(rep, t)
            t = norm(t).replace("{O}/./", "{O}/")
            if path == "/robots.txt":
                t = t.replace("/sst/", "/")
            texts.append(t.splitlines())
        diff = list(difflib.unified_diff(texts[0], texts[1], "WP" + path, "DJ" + path, lineterm="", n=2))
        if diff:
            failing += 1
            print(f"DIFF {path} ({len(texts[0])} vs {len(texts[1])} lines)")
            for line in diff[:show_max]:
                print("    " + line)
        else:
            print(f"OK   {path}")
    print(f"\n{len(paths) - failing}/{len(paths)} match")
    return 1 if failing else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--golden", action="store_true", help="read WP side from tools/visual/golden/")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-format", action="store_true", help="skip the JSON-LD raw text check")
    ap.add_argument("--sitemaps", action="store_true", help="compare robots.txt and the XML sitemaps instead")
    args = ap.parse_args()
    if args.sitemaps:
        return compare_sitemaps()
    pages = [(n, p) for n, p in DEFAULT_PAGES if not args.paths or p in args.paths]
    known = {p for _, p in pages}
    pages += [(None, p) for p in args.paths if p not in known]
    failing = 0
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1 if args.show else 6) as pool:
        results = list(pool.map(lambda np: compare(np[0], np[1], args.golden, args.show, not args.no_format), pages))
    for (name, path), diffs in zip(pages, results):
        label = f"{path}" + (f" [{name}]" if name else "")
        if diffs:
            failing += 1
            print(f"DIFF {label}")
            for d in diffs:
                print("   ", d)
        else:
            print(f"OK   {label}")
    print(f"\n{len(pages) - failing}/{len(pages)} match")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
