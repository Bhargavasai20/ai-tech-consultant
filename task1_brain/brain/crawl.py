"""Resumable, batched crawl driven by a SQLite queue. Kill it any time; run again and it continues."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .app import Brain
from .fetch import load_sitemap
from .ingest import ingest_url

log = logging.getLogger("brain.crawl")


@dataclass
class CrawlReport:
    indexed: int = 0
    unchanged: int = 0
    gone: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def enqueue(brain: Brain, entries: list[tuple[str, str | None]]) -> int:
    n = 0
    for url, lastmod in entries:
        brain.db.conn.execute(
            """INSERT INTO queue(url,state,attempts,lastmod) VALUES(?,'pending',0,?)
               ON CONFLICT(url) DO UPDATE SET state='pending', attempts=0, lastmod=excluded.lastmod, last_error=NULL""",
            (url, lastmod))
        n += 1
    brain.db.conn.commit()
    return n


async def process_queue(brain: Brain, limit: int | None = None, retry_failed: bool = False) -> CrawlReport:
    s = brain.settings
    rep = CrawlReport()
    if retry_failed:
        brain.db.execute("UPDATE queue SET state='pending', attempts=0 WHERE state='failed'")
    sem = asyncio.Semaphore(s.concurrency)
    done = 0

    async def work(url: str, lastmod: str | None) -> None:
        async with sem:
            att = brain.db.query("SELECT attempts FROM queue WHERE url=?", (url,))[0]["attempts"] + 1
            try:
                res = await ingest_url(brain, url, lastmod)
                brain.db.execute("UPDATE queue SET state='done', attempts=?, last_error=NULL WHERE url=?", (att, url))
                setattr(rep, res, getattr(rep, res) + 1)
            except Exception as e:
                state = "failed" if att >= s.max_attempts else "pending"
                brain.db.execute("UPDATE queue SET state=?, attempts=?, last_error=? WHERE url=?",
                                 (state, att, str(e)[:300], url))
                if state == "failed":
                    rep.failed += 1
                    rep.errors.append(f"{url}: {e}")

    while True:
        rows = brain.db.query("SELECT url,lastmod FROM queue WHERE state='pending' ORDER BY url LIMIT ?",
                              (s.batch_size,))
        if not rows or (limit is not None and done >= limit):
            break
        if limit is not None:
            rows = rows[: limit - done]
        await asyncio.gather(*(work(r["url"], r["lastmod"]) for r in rows))
        done += len(rows)
        log.info("batch done (%d total): %s", done, rep)
        if brain.db.query("SELECT 1 FROM queue WHERE state='pending' LIMIT 1") and s.batch_pause_s > 0:
            await asyncio.sleep(s.batch_pause_s)  # rest between batches: the politeness knob
    return rep


async def first_crawl(brain: Brain, limit: int | None = None) -> CrawlReport:
    if not brain.db.query("SELECT 1 FROM queue LIMIT 1"):
        entries = await load_sitemap(brain.fetcher, brain.settings.sitemap_url)
        log.info("sitemap lists %d pages", len(entries))
        enqueue(brain, entries)
    return await process_queue(brain, limit=limit)
