"""All tunables in one place. Every value can be overridden by an env var."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    sitemap_url: str
    user_agent: str
    min_delay_s: float          # minimum gap between ANY two requests (global, not per worker)
    concurrency: int            # parallel fetches (the delay above still applies)
    batch_size: int             # pages per batch
    batch_pause_s: float        # rest between batches
    max_attempts: int           # per page, then marked 'failed' (retry with --retry-failed)
    max_images_per_page: int
    vision_model: str
    answer_model: str
    min_coverage: float         # share of question terms that must appear in retrieved text
    sync_interval_h: float
    removal_guard: float        # abort removals if sitemap shrank below this share of known pages
    api_key: str | None
    prices: dict                # model -> [usd per 1M input tokens, usd per 1M output tokens]


def load_settings() -> Settings:
    e = os.environ.get
    return Settings(
        db_path=e("BRAIN_DB", "data/brain.sqlite"),
        sitemap_url=e("BRAIN_SITEMAP", "https://support.brilliantdirectories.com/support/sitemap.xml"),
        user_agent=e("BRAIN_UA", "AITechConsultantBot/0.1 (student capstone; set BRAIN_UA with contact email)"),
        min_delay_s=float(e("BRAIN_MIN_DELAY", "1.0")),
        concurrency=int(e("BRAIN_CONCURRENCY", "2")),
        batch_size=int(e("BRAIN_BATCH", "25")),
        batch_pause_s=float(e("BRAIN_BATCH_PAUSE", "10")),
        max_attempts=int(e("BRAIN_MAX_ATTEMPTS", "3")),
        max_images_per_page=int(e("BRAIN_MAX_IMAGES", "8")),
        vision_model=e("BRAIN_VISION_MODEL", "claude-haiku-5-5"),
        answer_model=e("BRAIN_ANSWER_MODEL", "claude-sonnet-5-5"),
        min_coverage=float(e("BRAIN_MIN_COVERAGE", "0.5")),
        sync_interval_h=float(e("BRAIN_SYNC_HOURS", "24")),
        removal_guard=float(e("BRAIN_REMOVAL_GUARD", "0.5")),
        api_key=e("BRAIN_API_KEY") or None,
        # Fill from the Anthropic pricing page; left empty so we never invent numbers.
        prices=json.loads(e("BRAIN_PRICES", "{}")),
    )
