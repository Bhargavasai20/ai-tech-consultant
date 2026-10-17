"""Daily freshness: diff the sitemap against memory, touch only what changed."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .app import Brain
from .crawl import enqueue, process_queue
from .fetch import load_sitemap

log = logging.getLogger("brain.sync")


@dataclass
class Plan:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unknown_lastmod: list[str] = field(default_factory=list)   # no lastmod in sitemap -> re-fetch, compare hash
    removed: list[str] = field(default_factory=list)
    removal_blocked: bool = False


def make_plan(brain: Brain, entries: list[tuple[str, str | None]]) -> Plan:
    known = {r["url"]: r for r in brain.db.query("SELECT url,lastmod,status FROM pages WHERE kind='web'")}
    live = dict(entries)
    p = Plan()
    for url, lastmod in entries:
        k = known.get(url)
        if k is None or k["status"] == "removed":
            p.added.append(url)
        elif lastmod is None:
            p.unknown_lastmod.append(url)
        elif lastmod != k["lastmod"]:
            p.updated.append(url)
    active = [u for u, r in known.items() if r["status"] == "active"]
    gone = [u for u in active if u not in live]
    # Guard: a broken/partial sitemap must not wipe the brain.
    if active and len(live) < brain.settings.removal_guard * len(active):
        p.removal_blocked = True
    else:
        p.removed = gone
    return p


async def run_sync(brain: Brain) -> dict:
    entries = await load_sitemap(brain.fetcher, brain.settings.sitemap_url)
    plan = make_plan(brain, entries)
    for u in plan.removed:
        brain.index.remove_page(u)
    lm = dict(entries)
    todo = plan.added + plan.updated + plan.unknown_lastmod
    enqueue(brain, [(u, lm[u]) for u in todo])
    rep = await process_queue(brain)
    out = {"added": len(plan.added), "updated": len(plan.updated), "refetched_no_lastmod": len(plan.unknown_lastmod),
           "removed": len(plan.removed), "removal_blocked": plan.removal_blocked,
           "indexed": rep.indexed, "unchanged": rep.unchanged, "failed": rep.failed}
    log.info("sync: %s", out)
    return out
