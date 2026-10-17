from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    brain_url: str
    brain_key: str
    cheap_model: str      # extraction over many windows: cheap and fast
    strong_model: str     # reconcile / review / proposal: quality matters
    rate_per_hour: float
    currency: str
    window_words: int
    overlap_words: int
    pm_overhead: float
    qa_overhead: float
    data_file: str


def load() -> Settings:
    e = os.environ.get
    return Settings(
        brain_url=e("BRAIN_URL", "http://localhost:8001"), brain_key=e("BRAIN_API_KEY", ""),
        cheap_model=e("SCOPE_CHEAP_MODEL", "claude-haiku-5-5"), strong_model=e("SCOPE_STRONG_MODEL", "claude-sonnet-5-5"),
        rate_per_hour=float(e("SCOPE_RATE", "40")), currency=e("SCOPE_CURRENCY", "USD"),
        window_words=int(e("SCOPE_WINDOW_WORDS", "2500")), overlap_words=int(e("SCOPE_OVERLAP_WORDS", "200")),
        pm_overhead=0.10, qa_overhead=0.15, data_file=e("SCOPE_DATA", "data/projects.json"))
