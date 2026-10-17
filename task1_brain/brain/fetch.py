"""Polite HTTP: one global rate limit, robots.txt, Retry-After, exponential backoff."""
from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .config import Settings


@dataclass
class FetchResult:
    url: str
    status: int
    body: bytes = b""
    content_type: str = ""


class Fetcher(Protocol):
    async def get(self, url: str) -> FetchResult: ...


class FetchError(Exception):
    pass


class PoliteFetcher:
    def __init__(self, s: Settings) -> None:
        import httpx  # lazy

        self.s = s
        self._client = httpx.AsyncClient(headers={"User-Agent": s.user_agent}, timeout=30, follow_redirects=True)
        self._lock = asyncio.Lock()
        self._next_ok = 0.0
        self._robots: dict[str, RobotFileParser | None] = {}
        self._delay = s.min_delay_s

    async def _throttle(self) -> None:
        async with self._lock:  # global: N workers still share ONE request budget
            wait = self._next_ok - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_ok = time.monotonic() + self._delay

    async def _allowed(self, url: str) -> bool:
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origin not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                await self._throttle()
                r = await self._client.get(origin + "/robots.txt")
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    cd = rp.crawl_delay(self.s.user_agent) or rp.crawl_delay("*")
                    if cd:
                        self._delay = max(self._delay, float(cd))
                else:
                    rp = None  # no robots.txt -> allowed
            except Exception:
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(self.s.user_agent, url)

    async def get(self, url: str) -> FetchResult:
        if not await self._allowed(url):
            return FetchResult(url, 403, b"", "robots-disallowed")
        last = "unknown"
        for attempt in range(self.s.max_attempts + 1):
            await self._throttle()
            try:
                r = await self._client.get(url)
                if r.status_code in (429, 500, 502, 503, 504):
                    ra = r.headers.get("retry-after", "")
                    wait = float(ra) if ra.isdigit() else 2 ** (attempt + 1)
                    last = f"HTTP {r.status_code}"
                    self._delay = min(self._delay * 1.5, 10)  # back off globally when the server struggles
                    await asyncio.sleep(min(wait, 60))
                    continue
                return FetchResult(url, r.status_code, r.content, r.headers.get("content-type", ""))
            except Exception as e:  # timeouts, resets
                last = type(e).__name__
                await asyncio.sleep(2 ** (attempt + 1))
        raise FetchError(f"{url}: gave up after retries ({last})")

    async def aclose(self) -> None:
        await self._client.aclose()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml: bytes) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Returns ([(page_url, lastmod)], [child_sitemap_urls])."""
    root = ET.fromstring(xml)
    pages, children = [], []
    for el in root:
        loc = lastmod = None
        for ch in el:
            if _local(ch.tag) == "loc":
                loc = (ch.text or "").strip()
            elif _local(ch.tag) == "lastmod":
                lastmod = (ch.text or "").strip() or None
        if not loc:
            continue
        (children if _local(root.tag) == "sitemapindex" else pages).append(loc if _local(root.tag) == "sitemapindex" else (loc, lastmod))
    return pages, children


async def load_sitemap(fetcher: Fetcher, url: str, depth: int = 0) -> list[tuple[str, str | None]]:
    r = await fetcher.get(url)
    if r.status != 200:
        raise FetchError(f"sitemap {url} returned HTTP {r.status}")
    pages, children = parse_sitemap(r.body)
    if depth < 3:
        for c in children:
            pages += await load_sitemap(fetcher, c, depth + 1)
    return pages
