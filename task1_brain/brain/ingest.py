"""Fetch one page -> parse -> caption images (cached by hash) -> swap into the index."""
from __future__ import annotations

import hashlib
import logging

from .app import Brain
from .index import chunk_text
from .llm import ImageInput
from .parser import parse_article, section_from_url

log = logging.getLogger("brain.ingest")

VISION_SYSTEM = ("You describe screenshots from a software help center so they can be found by search. "
                 "In 2-4 sentences say what screen it is, quote the visible labels, setting names and values, "
                 "and what the screenshot is demonstrating. No guessing beyond what is visible.")
MAX_IMG_BYTES = 5_000_000
ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/gif"}


async def caption_image(brain: Brain, url: str, alt: str) -> str | None:
    r = await brain.fetcher.get(url)
    ctype = r.content_type.split(";")[0].strip().lower()
    if r.status != 200 or ctype not in ALLOWED or not (0 < len(r.body) <= MAX_IMG_BYTES):
        return None
    sha = hashlib.sha256(r.body).hexdigest()
    row = brain.db.query("SELECT caption FROM images WHERE sha=?", (sha,))
    if row:  # unchanged image -> no new vision cost
        return row[0]["caption"]
    res = await brain.ask_llm("vision", system=VISION_SYSTEM, model=brain.settings.vision_model, max_tokens=300,
                              user=f"Alt text from the page (may be empty): {alt!r}. Describe the screenshot.",
                              image=ImageInput(r.body, ctype))
    caption = res.text.strip()
    brain.db.execute("INSERT OR REPLACE INTO images(sha,caption,model) VALUES(?,?,?)",
                     (sha, caption, brain.settings.vision_model))
    return caption


async def ingest_url(brain: Brain, url: str, lastmod: str | None) -> str:
    """Returns: 'indexed' | 'unchanged' | 'gone' | 'skipped'. Raises on transient failure (caller retries)."""
    r = await brain.fetcher.get(url)
    if r.status in (404, 410):
        brain.index.remove_page(url)
        return "gone"
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}")
    html = r.body.decode("utf-8", errors="replace")
    art = parse_article(html, url)
    if len(art.text) < 40:
        return "skipped"
    content_hash = hashlib.sha256(art.text.encode()).hexdigest()
    old = brain.db.query("SELECT content_hash,status FROM pages WHERE url=?", (url,))
    if old and old[0]["content_hash"] == content_hash and old[0]["status"] == "active":
        brain.db.execute("UPDATE pages SET lastmod=?, fetched_at=datetime('now') WHERE url=?", (lastmod, url))
        return "unchanged"
    image_chunks: list[tuple[str, str]] = []
    for img_url, alt in art.images[: brain.settings.max_images_per_page]:
        try:
            cap = await caption_image(brain, img_url, alt)
        except Exception as e:  # one bad image must not lose the page
            log.warning("image failed %s: %s", img_url, e)
            cap = None
        if cap or alt:
            image_chunks.append((img_url, cap or f"Image with alt text: {alt}"))
    brain.index.replace_page(url=url, title=art.title or url, section=section_from_url(url), lastmod=lastmod,
                             content_hash=content_hash, kind="web", text_chunks=chunk_text(art.text),
                             image_chunks=image_chunks)
    return "indexed"
