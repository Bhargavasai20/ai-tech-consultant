"""Wiring: one Brain object holds db, index, llm, fetcher. Every LLM call is logged with cost + latency."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .config import Settings, load_settings
from .db import DB
from .fetch import Fetcher
from .index import Index
from .llm import LLM, ImageInput, LLMResult, MockLLM, cost_usd


@dataclass
class Brain:
    settings: Settings
    db: DB
    index: Index
    llm: LLM
    fetcher: Fetcher

    @classmethod
    def create(cls, settings: Settings | None = None, llm: LLM | None = None,
               fetcher: Fetcher | None = None, db_path: str | None = None) -> "Brain":
        s = settings or load_settings()
        db = DB(db_path or s.db_path)
        if llm is None:
            if os.environ.get("BRAIN_MOCK") == "1":
                llm = MockLLM()
            else:
                from .llm import AnthropicLLM
                llm = AnthropicLLM()
        if fetcher is None:
            from .fetch import PoliteFetcher
            fetcher = PoliteFetcher(s)
        return cls(s, db, Index(db), llm, fetcher)

    async def ask_llm(self, purpose: str, *, system: str, user: str, model: str, max_tokens: int = 800,
                      image: ImageInput | None = None) -> LLMResult:
        t = time.perf_counter()
        r = await self.llm.complete(system=system, user=user, model=model, max_tokens=max_tokens, image=image)
        ms = int((time.perf_counter() - t) * 1000)
        self.db.execute("INSERT INTO usage(purpose,model,input_tokens,output_tokens,usd,ms) VALUES(?,?,?,?,?,?)",
                        (purpose, model, r.input_tokens, r.output_tokens,
                         cost_usd(self.settings.prices, model, r.input_tokens, r.output_tokens), ms))
        return r
