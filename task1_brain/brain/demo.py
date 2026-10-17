"""Offline demo data: lets `make demo` show the whole loop with no network and no API key."""
from __future__ import annotations

import os

from .app import Brain
from .config import load_settings
from .llm import MockLLM

PAGES = {
    "https://help.example.com/a/membership-pricing": (
        "<html><title>t</title><body><nav>menu</nav><article><h1>Change membership pricing</h1>"
        "<p>Go to Admin > Members > Membership Plans. Click the plan name, edit the Monthly Price field, then Save. "
        "Existing subscribers keep their old price until their next renewal date.</p></article></body></html>"),
    "https://help.example.com/a/refunds": (
        "<html><body><article><h1>Refund policy</h1><p>Refunds are available within 14 days of purchase for "
        "annual plans. Monthly plans can be cancelled at any time but are not refunded for the current month. "
        "Contact support with your invoice number to request a refund.</p></article></body></html>"),
}


async def seed() -> None:
    os.environ["BRAIN_MOCK"] = "1"
    from .ingest import ingest_url

    class F:
        async def get(self, url):
            from .fetch import FetchResult
            return FetchResult(url, 200, PAGES[url].encode(), "text/html")

    b = Brain.create(load_settings(), llm=MockLLM(), fetcher=F())
    for u in PAGES:
        print(u, await ingest_url(b, u, "2026-10-01"))
    print(b.index.stats())
