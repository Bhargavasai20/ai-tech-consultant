"""LLM access behind one tiny interface so models can be swapped, mocked and costed."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class ImageInput:
    data: bytes
    media_type: str


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLM(Protocol):
    async def complete(self, *, system: str, user: str, model: str, max_tokens: int = 800,
                       image: ImageInput | None = None) -> LLMResult: ...


class AnthropicLLM:
    def __init__(self, api_key: str | None = None) -> None:
        import anthropic  # lazy: tests and offline demo never need it

        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=3)

    async def complete(self, *, system, user, model, max_tokens=800, image=None) -> LLMResult:
        content: list[dict] = []
        if image:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": image.media_type,
                "data": base64.b64encode(image.data).decode()}})
        content.append({"type": "text", "text": user})
        r = await self._client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return LLMResult(text, r.usage.input_tokens, r.usage.output_tokens, model)


class MockLLM:
    """Deterministic stand-in: lets the whole system run and be tested offline."""

    def __init__(self, handler: Callable[[str, str, bool], str] | None = None) -> None:
        self.handler = handler or self._default
        self.calls = 0

    @staticmethod
    def _default(system: str, user: str, has_image: bool) -> str:
        if has_image:
            return "Screenshot of the admin panel showing a settings form (mock caption)."
        m = re.search(r"\[S1\][^\n]*\n(.+?)(?:\n\[S2\]|\n\nQuestion:|$)", user, re.S)
        snippet = (m.group(1).strip() if m else "")[:400]
        return json.dumps({"answer": snippet or "No answer.", "sources": [1] if m else [],
                           "confident": bool(m)})

    async def complete(self, *, system, user, model, max_tokens=800, image=None) -> LLMResult:
        self.calls += 1
        text = self.handler(system, user, image is not None)
        return LLMResult(text, len(user) // 4, len(text) // 4, model)


def cost_usd(prices: dict, model: str, inp: int, out: int) -> float:
    p = prices.get(model)
    return 0.0 if not p else (inp * p[0] + out * p[1]) / 1_000_000


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply; raises ValueError if none."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))
