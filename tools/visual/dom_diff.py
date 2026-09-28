"""Compare the DOM of a WordPress page with the Django page (structure, classes, text).

    python tools/visual/dom_diff.py /contact-us/ [--golden contact] [--part body|head] [--context 3]

URLs are normalised (both sites' origins removed, ?ver= dropped, autoptimize/static paths unified)
so only real markup differences remain.
"""
import argparse
import os
import difflib
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment

WP = "http://localhost/sst"
DJ = os.environ.get("SST_DJ_URL", "http://127.0.0.1:8000")
GOLDEN = Path(__file__).parent / "golden"

URL_RE = [
    (re.compile(r"https?:(?:\\?/){2}localhost(?:\\?/)sst"), ""),
    (re.compile(r"https?:(?:\\?/){2}127\.0\.0\.1:\d+"), ""),
    (re.compile(r"//localhost/sst"), ""),
    (re.compile(r"/sst/"), "/"),
    (re.compile(r"/static/wp/"), "/"),
    (re.compile(r"[?&](?:ver|_t)=[^\"'&\s]*"), ""),
    (re.compile(r"/wp-content/cache/autoptimize/autoptimize_single_[0-9a-f]+\.php"), "/AUTOPTIMIZED"),
]
VOLATILE_ATTRS = {"value"}  # nonces, timestamps


def normalise(html, part):
    for rx, rep in URL_RE:
        html = rx.sub(rep, html)
    soup = BeautifulSoup(html, "lxml")
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    root = soup.body if part == "body" else soup.head
    if root is None:
        return []
    for tag in root.find_all(["script", "style", "svg", "noscript"]):
        if part == "body":
            tag.decompose()
    lines = []

    def walk(node, depth):
        for child in node.children:
            if isinstance(child, str):
                text = re.sub(r"\s+", " ", child).strip()
                if text:
                    lines.append("  " * depth + "#" + text)
                continue
            attrs = []
            for k, v in sorted(child.attrs.items()):
                if isinstance(v, list):
                    v = " ".join(v)
                if k in VOLATILE_ATTRS and child.get("type") == "hidden":
                    v = "*"
                attrs.append(f'{k}="{v}"')
            lines.append("  " * depth + f"<{child.name} {' '.join(attrs)}>".replace(" >", ">"))
            walk(child, depth + 1)

    walk(root, 0)
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--golden", help="use tools/visual/golden/<name>.html instead of fetching WP")
    ap.add_argument("--part", default="body")
    ap.add_argument("--context", type=int, default=2)
    ap.add_argument("--max", type=int, default=300, help="max diff lines to print")
    args = ap.parse_args()

    wp_html = (GOLDEN / f"{args.golden}.html").read_text(encoding="utf-8") if args.golden else requests.get(WP + args.path).text
    dj_html = requests.get(DJ + args.path).text
    a, b = normalise(wp_html, args.part), normalise(dj_html, args.part)
    diff = list(difflib.unified_diff(a, b, "wordpress", "django", n=args.context, lineterm=""))
    changed = sum(1 for d in diff if d[:1] in "+-" and not d.startswith(("+++", "---")))
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(diff[: args.max]))
    print(f"\n{args.path}: {len(a)} vs {len(b)} nodes, {changed} changed lines")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
