"""Post content rendering: BB-codes, sanitization, slugs."""
from __future__ import annotations

import re
import unicodedata
from html import escape as html_escape
from typing import Optional

import bleach

ALLOWED_TAGS = [
    "p", "br", "hr",
    "strong", "b", "em", "i", "u", "s",
    "h2", "h3", "h4",
    "ul", "ol", "li",
    "blockquote", "code", "pre",
    "a", "img",
    "figure", "figcaption",
]

ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height"],
    "*": ["class"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]

_translit = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    out = []
    for ch in value:
        if ch in _translit:
            out.append(_translit[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in (" ", "-", "_", "."):
            out.append("-")
    s = "".join(out)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "post"


_bb_img = re.compile(r"\[img\](.+?)\[/img\]", re.IGNORECASE | re.DOTALL)
_bb_b = re.compile(r"\[b\](.+?)\[/b\]", re.IGNORECASE | re.DOTALL)
_bb_i = re.compile(r"\[i\](.+?)\[/i\]", re.IGNORECASE | re.DOTALL)
_bb_u = re.compile(r"\[u\](.+?)\[/u\]", re.IGNORECASE | re.DOTALL)
_bb_url1 = re.compile(r"\[url\](.+?)\[/url\]", re.IGNORECASE | re.DOTALL)
_bb_url2 = re.compile(r"\[url=(.+?)\](.+?)\[/url\]", re.IGNORECASE | re.DOTALL)
_bb_h2 = re.compile(r"\[h2\](.+?)\[/h2\]", re.IGNORECASE | re.DOTALL)
_bb_h3 = re.compile(r"\[h3\](.+?)\[/h3\]", re.IGNORECASE | re.DOTALL)
_bb_quote = re.compile(r"\[quote\](.+?)\[/quote\]", re.IGNORECASE | re.DOTALL)


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<\s*[a-zA-Z]", text))


def _convert_bb(text: str) -> str:
    text = _bb_img.sub(lambda m: f'<img src="{html_escape(m.group(1).strip(), quote=True)}" alt="">', text)
    text = _bb_h2.sub(r"<h2>\1</h2>", text)
    text = _bb_h3.sub(r"<h3>\1</h3>", text)
    text = _bb_b.sub(r"<strong>\1</strong>", text)
    text = _bb_i.sub(r"<em>\1</em>", text)
    text = _bb_u.sub(r"<u>\1</u>", text)
    text = _bb_url2.sub(
        lambda m: f'<a href="{html_escape(m.group(1).strip(), quote=True)}" rel="noopener" target="_blank">{m.group(2)}</a>',
        text,
    )
    text = _bb_url1.sub(
        lambda m: f'<a href="{html_escape(m.group(1).strip(), quote=True)}" rel="noopener" target="_blank">{m.group(1)}</a>',
        text,
    )
    text = _bb_quote.sub(r"<blockquote>\1</blockquote>", text)
    return text


def _autolink_urls(text: str) -> str:
    """Convert bare https?://... URLs (outside tags) to anchors."""
    pattern = re.compile(r"(?<![\"'>=])(https?://[^\s<>\"']+)")
    return pattern.sub(
        lambda m: f'<a href="{m.group(1)}" rel="noopener" target="_blank">{m.group(1)}</a>',
        text,
    )


def render_body(raw: Optional[str]) -> str:
    """Render post body. Supports HTML, BB-codes, or plain text with line breaks."""
    text = (raw or "").strip()
    if not text:
        return ""

    has_html = _looks_like_html(text)
    has_bb = bool(re.search(r"\[(/?)(img|b|i|u|url|h2|h3|quote)\b", text, re.IGNORECASE))

    if has_html or has_bb:
        text = _convert_bb(text)
        # add line-break paragraphs only where there's no block markup
        # for simplicity, wrap in a div and let bleach clean it
        cleaned = bleach.clean(
            text,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        cleaned = bleach.linkify(cleaned, callbacks=[_link_callback])
        return cleaned

    # plain text — escape and convert paragraphs / line breaks
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out = []
    for p in paragraphs:
        out.append("<p>" + html_escape(p).replace("\n", "<br>") + "</p>")
    rendered = "".join(out)
    rendered = _autolink_urls(rendered)
    return bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


def _link_callback(attrs, new=False):
    attrs[(None, "rel")] = "noopener"
    attrs[(None, "target")] = "_blank"
    return attrs


def make_summary(body_html: str, max_len: int = 220) -> str:
    text = re.sub(r"<[^>]+>", " ", body_html or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"
