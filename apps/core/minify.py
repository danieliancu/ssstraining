"""Port of Autoptimize's AO_Minify_HTML (classes/external/php/ao-minify-html.php).

The WordPress site serves HTML through this minifier, and whitespace between inline
elements affects layout, so Django output goes through the same algorithm.
"""
import re
import secrets

_SCRIPT = re.compile(r"(\s*)(<script\b[^>]*?>)([\s\S]*?)</script>(\s*)", re.I)
_STYLE = re.compile(r"\s*(<style\b[^>]*?>)([\s\S]*?)</style>\s*", re.I)
_COMMENT = re.compile(r"<!--([\s\S]*?)-->")
_PRE = re.compile(r"\s*(<pre\b[^>]*?>[\s\S]*?</pre>)\s*", re.I)
_TEXTAREA = re.compile(r"\s*(<textarea\b[^>]*?>[\s\S]*?</textarea>)\s*", re.I)
# PHP: /(=("|\')data:.*\2)/Ui  (U = ungreedy)
_DATA_URI = re.compile(r"(=(\"|')data:.*?\2)", re.I)
_LINE_TRIM = re.compile(r"^\s+|\s+$", re.M)
_BLOCK_WS = re.compile(
    r"\s+(</?(?:area|article|aside|base(?:font)?|blockquote|body"
    r"|canvas|caption|center|col(?:group)?|dd|dir|div|dl|dt|fieldset|figcaption|figure|footer|form"
    r"|frame(?:set)?|h[1-6]|head|header|hgroup|hr|html|legend|li|link|main|map|menu|meta|nav"
    r"|ol|opt(?:group|ion)|output|p|param|section|t(?:able|body|head|d|h||r|foot|itle)"
    r"|ul|video)\b[^>]*>)", re.I)
_OUTSIDE = re.compile(r">([^<]+)<")
_EDGE_WS = re.compile(r"^\s+|\s+$")


def minify_html(html: str, keep_comments: bool = False) -> str:
    html = html.replace("\r\n", "\n").strip()
    token = "MINIFYHTML" + secrets.token_hex(16)
    placeholders = []

    def reserve(content):
        key = f"%{token}{len(placeholders)}%"
        placeholders.append((key, content))
        return key

    def script_cb(m):
        ws1 = "" if m.group(1) == "" else " "
        ws2 = "" if m.group(4) == "" else " "
        js = m.group(3)
        if not keep_comments:
            js = re.sub(r"(?:^\s*<!--\s*|\s*(?://)?\s*-->\s*$)", "", js)
            js = _remove_cdata(js)
        return reserve(f"{ws1}{m.group(2)}{js.strip()}</script>{ws2}")

    def style_cb(m):
        css = re.sub(r"(?:^\s*<!--|-->\s*$)", "", m.group(2))
        css = _remove_cdata(css)
        return reserve(f"{m.group(1)}{css.strip()}</style>")

    def comment_cb(m):
        body = m.group(1)
        return m.group(0) if body.startswith("[") or "<![" in body else ""

    html = _SCRIPT.sub(script_cb, html)
    html = _STYLE.sub(style_cb, html)
    if not keep_comments:
        html = _COMMENT.sub(comment_cb, html)
    html = _PRE.sub(lambda m: reserve(m.group(1)), html)
    html = _TEXTAREA.sub(lambda m: reserve(m.group(1)), html)
    html = _DATA_URI.sub(lambda m: reserve(m.group(1)), html)
    html = _LINE_TRIM.sub(" ", html)
    html = _BLOCK_WS.sub(r"\1", html)
    html = _OUTSIDE.sub(lambda m: ">" + _EDGE_WS.sub(" ", m.group(1)) + "<", html)
    for key, content in reversed(placeholders):
        html = html.replace(key, content)
    return html


def _remove_cdata(text):
    if "<![CDATA[" not in text:
        return text
    for s in ("/* <![CDATA[ */", "/* ]]> */", "/*<![CDATA[*/", "/*]]>*/", "<![CDATA[", "]]>"):
        text = text.replace(s, "")
    return text


class HtmlMinifyMiddleware:
    """Minify text/html responses like Autoptimize does (it skips basket and checkout)."""

    SKIP_PREFIXES = ("/basket/", "/checkout", "/admin/", "/wp-admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            getattr(response, "streaming", False)
            or not response.get("Content-Type", "").startswith("text/html")
            or request.path.startswith(self.SKIP_PREFIXES)
            or getattr(response, "skip_minify", False)
            or response.status_code >= 300 and response.status_code < 400
        ):
            return response
        content = response.content.decode(response.charset or "utf-8")
        response.content = minify_html(content).encode(response.charset or "utf-8")
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
