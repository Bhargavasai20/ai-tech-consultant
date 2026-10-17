"""Task 3 talks to Task 1 only through its HTTP API (stdlib urllib, run in a thread)."""
from __future__ import annotations

import asyncio
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class KbReply:
    answered: bool
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    unavailable: bool = False


class Brain(Protocol):
    async def ask(self, question: str) -> KbReply: ...


class HttpBrain:
    def __init__(self, base_url: str, key: str = "") -> None:
        self.base, self.key = base_url.rstrip("/"), key

    def _post(self, question: str) -> KbReply:
        req = urllib.request.Request(f"{self.base}/v1/ask", data=json.dumps({"question": question}).encode(),
                                     headers={"content-type": "application/json", **({"x-api-key": self.key} if self.key else {})})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    j = json.load(r)
                return KbReply(bool(j["answered"]), j.get("answer", ""), [s["url"] for s in j.get("sources", [])])
            except Exception:
                if attempt == 2:
                    return KbReply(False, unavailable=True)  # degrade: treat as custom work, flag it
                import time; time.sleep(2 ** attempt)
        return KbReply(False, unavailable=True)

    async def ask(self, question: str) -> KbReply:
        return await asyncio.to_thread(self._post, question)


class FakeBrain:
    """answers[keyword] -> reply; used by tests and the offline demo."""

    def __init__(self, answers: dict[str, KbReply] | None = None) -> None:
        self.answers, self.asked = answers or {}, []

    async def ask(self, question: str) -> KbReply:
        self.asked.append(question)
        for k, v in self.answers.items():
            if k.lower() in question.lower():
                return v
        return KbReply(False)
