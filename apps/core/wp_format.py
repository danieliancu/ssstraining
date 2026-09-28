"""Python port of WordPress's wpautop() (wp-includes/formatting.php), used for text that
was not pre-rendered by the import bridge (ACF textareas, content edited in Django admin
without HTML paragraphs)."""
import re

_ALLBLOCKS = (
    "(?:table|thead|tfoot|caption|col|colgroup|tbody|tr|td|th|div|dl|dd|dt|ul|ol|li|pre|form|map|area|"
    "blockquote|address|style|p|h[1-6]|hr|fieldset|legend|section|article|aside|hgroup|header|footer|"
    "nav|figure|figcaption|details|menu|summary)"
)


def wpautop(text: str, br: bool = True) -> str:
    if not text or not text.strip():
        return ""
    if re.search(r"<p[\s>]", text, re.I) and "\n\n" not in text:
        # Already HTML with paragraphs (e.g. TinyMCE output): leave as is.
        return text
    pre_tags = {}
    text = text + "\n"
    if "<pre" in text:
        parts = text.split("</pre>")
        last = parts.pop()
        text = ""
        for i, part in enumerate(parts):
            start = part.find("<pre")
            if start == -1:
                text += part
                continue
            name = f"<pre wp-pre-tag-{i}></pre>"
            pre_tags[name] = part[start:] + "</pre>"
            text += part[:start] + name
        text += last

    text = re.sub(r"<br\s*/?>\s*<br\s*/?>", "\n\n", text)
    text = re.sub(r"(<" + _ALLBLOCKS + r"[\s/>])", r"\n\n\1", text)
    text = re.sub(r"(</" + _ALLBLOCKS + r">)", r"\1\n\n", text)
    text = re.sub(r"<hr\s*?/?>", "<hr />\n\n", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "<option" in text:
        text = re.sub(r"\s*<option", "<option", text)
        text = re.sub(r"</option>\s*", "</option>", text)
    if "</object>" in text:
        text = re.sub(r"(<object[^>]*>)\s*", r"\1", text)
        text = re.sub(r"\s*</object>", "</object>", text)
    text = re.sub(r"\n\n+", "\n\n", text)

    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    text = "".join("<p>" + p.strip("\n") + "</p>\n" for p in paragraphs)

    text = re.sub(r"<p>\s*</p>", "", text)
    text = re.sub(r"<p>([^<]+)</(div|address|form)>", r"<p>\1</p></\2>", text)
    text = re.sub(r"<p>\s*(</?" + _ALLBLOCKS + r"[^>]*>)\s*</p>", r"\1", text)
    text = re.sub(r"<p>(<li.+?)</p>", r"\1", text)
    text = re.sub(r"<p><blockquote([^>]*)>", r"<blockquote\1><p>", text, flags=re.I)
    text = text.replace("</blockquote></p>", "</p></blockquote>")
    text = re.sub(r"<p>\s*(</?" + _ALLBLOCKS + r"[^>]*>)", r"\1", text)
    text = re.sub(r"(</?" + _ALLBLOCKS + r"[^>]*>)\s*</p>", r"\1", text)

    if br:
        text = re.sub(r"<(script|style|svg).*?</\1>", lambda m: m.group(0).replace("\n", "<WPPreserveNewline />"), text, flags=re.S)
        text = re.sub(r"<br\s*/?>", "<br />", text)
        text = re.sub(r"(?<!<br />)\s*\n", "<br />\n", text)
        text = text.replace("<WPPreserveNewline />", "\n")

    text = re.sub(r"(</?" + _ALLBLOCKS + r"[^>]*>)\s*<br />", r"\1", text)
    text = re.sub(r"<br />(\s*</?(?:p|li|div|dl|dd|dt|th|pre|td|ul|ol)[^>]*>)", r"\1", text)
    text = re.sub(r"\n</p>$", "</p>", text)

    for name, pre in pre_tags.items():
        text = text.replace(name, pre)
    return text


def nl2br(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\n", "<br />\n")


_TEXTURIZE_STATIC = [
    ("---", "&#8212;"), (" -- ", " &#8212; "), ("--", "&#8211;"), (" - ", " &#8211; "),
    ("...", "&#8230;"), ("``", "&#8220;"), ("''", "&#8221;"), (" (tm)", " &#8482;"),
]
_TEXTURIZE_RE = [
    (re.compile(r"'(\d\d)"), r"&#8217;\1"),                     # '99
    (re.compile(r"(?<=[\w\]\)])'(?=[\w])"), "&#8217;"),          # don't, it's
    (re.compile(r"(^|[\s(\[{\"-])'"), r"\1&#8216;"),              # opening single
    (re.compile(r"'"), "&#8217;"),                                # closing single
    (re.compile(r"(^|[\s(\[{-])\""), r"\1&#8220;"),               # opening double
    (re.compile(r"\""), "&#8221;"),                               # closing double
    (re.compile(r"(\d+)x(\d+)"), r"\1&#215;\2"),
]


def wptexturize(text: str) -> str:
    """Simplified WordPress wptexturize() for plain strings (titles, menu labels).
    Text inside HTML tags is left alone."""
    if not text:
        return text or ""
    parts = re.split(r"(<[^>]*>|&#?\w+;)", text)
    for i, part in enumerate(parts):
        if not part or part.startswith("<") or (part.startswith("&") and part.endswith(";")):
            continue
        for a, b in _TEXTURIZE_STATIC:
            part = part.replace(a, b)
        for rx, rep in _TEXTURIZE_RE:
            part = rx.sub(rep, part)
        parts[i] = part
    return "".join(parts)
