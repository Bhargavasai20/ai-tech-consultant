"""LLM interface + deterministic mock (so the pipeline runs and tests offline)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    async def complete(self, *, system: str, user: str, model: str, max_tokens: int = 2000) -> LLMResult: ...


class AnthropicLLM:
    def __init__(self) -> None:
        import anthropic
        self._c = anthropic.AsyncAnthropic(max_retries=3)

    async def complete(self, *, system, user, model, max_tokens=2000) -> LLMResult:
        r = await self._c.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          messages=[{"role": "user", "content": user}])
        return LLMResult("".join(b.text for b in r.content if b.type == "text"), r.usage.input_tokens, r.usage.output_tokens)


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


_REQ = re.compile(r"\b(need|want|should|must|please|can we|would like|have to)\b", re.I)
_CHG = re.compile(r"\b(instead|actually|rather than|change (it|that|the .+) to|switch (it )?to)\b", re.I)
_RM = re.compile(r"\b(drop|remove|no longer need|don't need|forget about|cancel the)\b", re.I)
_VAGUE = re.compile(r"\b(better|faster|nicer|modern|improve|easier|good|clean)\b", re.I)


class MockLLM:
    """Heuristic stand-in. Proves wiring, NOT quality - never quote its numbers in EVALS.md."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, system, user, model, max_tokens=2000) -> LLMResult:
        self.calls += 1
        tag = system.split(".", 1)[0].strip()
        out = {"EXTRACT": self._extract, "CLARIFY": self._clarify, "ESTIMATE": self._estimate,
               "PROPOSAL": self._proposal, "RECONCILE": lambda u: {"matches": []}}[tag](user)
        text = json.dumps(out)
        return LLMResult(text, len(user) // 4, len(text) // 4)

    @staticmethod
    def _extract(user: str) -> dict:
        reqs = []
        for line in user.splitlines():
            m = re.match(r"^\s*([A-Za-z][\w ]{0,30}):\s*(.+)$", line)
            if not m:
                continue
            for s in re.split(r"(?<=[.!?])\s+", m.group(2)):
                if _RM.search(s):
                    typ = "remove"
                elif _CHG.search(s):
                    typ = "change"
                elif _REQ.search(s):
                    typ = "feature"
                else:
                    continue
                reqs.append({"text": s.strip().rstrip("."), "type": typ, "quote": s.strip(),
                             "priority": "must" if re.search(r"\b(must|need)\b", s, re.I) else "should"})
        return {"requirements": reqs}

    @staticmethod
    def _clarify(user: str) -> dict:
        return {"questions": [f'What does "{t}" mean in measurable terms, and how will we know it is done?'
                              for t in re.findall(r"^- \[R\d+\] (.+)$", user, re.M) if _VAGUE.search(t)]}

    @staticmethod
    def _estimate(user: str) -> dict:
        tasks = []
        for rid, text in re.findall(r"^- \[(R\d+)\] (.+)$", user, re.M):
            w = len(text.split())
            low = 4 + 2 * (w // 6)
            tasks.append({"requirement_id": rid, "title": text[:80], "hours_low": low, "hours_high": round(low * 1.6),
                          "assumptions": ["Design supplied by client", "One round of revisions"]})
        return {"tasks": tasks}

    @staticmethod
    def _proposal(user: str) -> dict:
        return {"summary": "Thank you for the time you spent with us. This proposal covers the work we discussed, "
                           "and shows what we can do with settings you already have to keep your cost down."}
