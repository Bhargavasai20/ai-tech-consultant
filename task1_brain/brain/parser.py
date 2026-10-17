"""Turn help-center HTML into clean text + image list (stdlib only)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

_SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "pre", "section", "article", "ul", "ol"}
_JUNK_IMG = re.compile(r"(logo|icon|avatar|sprite|pixel|tracking|badge|emoji)", re.I)


@dataclass
class Article:
    title: str = ""
    text: str = ""
    images: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, alt)


class _Extractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.skip = 0
        self.main = 0
        self.in_h1 = False
        self.in_title = False
        self.h1 = ""
        self.page_title = ""
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []
        self.all_imgs: list[tuple[str, str]] = []
        self.main_imgs: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _SKIP:
            self.skip += 1
        if tag in ("article", "main"):
            self.main += 1
        if tag == "h1" and not self.h1:
            self.in_h1 = True
        if tag == "title":
            self.in_title = True
        if tag in _BLOCK:
            self._add("\n")
        if tag == "img" and not self.skip:
            src = a.get("data-src") or a.get("src") or ""
            if src and not src.startswith("data:") and not _JUNK_IMG.search(src) \
                    and urlparse(src).path.lower().rsplit(".", 1)[-1] not in ("svg", "ico", "gif"):
                item = (urljoin(self.base, src), (a.get("alt") or "").strip())
                self.all_imgs.append(item)
                if self.main:
                    self.main_imgs.append(item)

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in ("article", "main") and self.main:
            self.main -= 1
        if tag == "h1":
            self.in_h1 = False
        if tag == "title":
            self.in_title = False
        if tag in _BLOCK:
            self._add("\n")

    def handle_data(self, data):
        if self.in_title:
            self.page_title += data
        if self.skip:
            return
        if self.in_h1:
            self.h1 += data
        self._add(data)

    def _add(self, s: str) -> None:
        self.all_parts.append(s)
        if self.main:
            self.main_parts.append(s)


def _clean(parts: list[str]) -> str:
    text = "".join(parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_article(html: str, url: str) -> Article:
    p = _Extractor(url)
    p.feed(html)
    main_text = _clean(p.main_parts)
    use_main = len(main_text) >= 200
    title = (p.h1 or p.page_title).strip()
    return Article(title=re.sub(r"\s+", " ", title),
                   text=main_text if use_main else _clean(p.all_parts),
                   images=(p.main_imgs if use_main else p.all_imgs))


def section_from_url(url: str) -> str:
    parts = [s for s in urlparse(url).path.split("/") if s]
    return "/".join(parts[-3:-1]) if len(parts) > 2 else (parts[0] if parts else "")
