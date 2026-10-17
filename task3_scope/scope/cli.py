"""python -m scope.cli demo   -> runs meeting 1 -> approve -> meeting 2 offline (mock LLM + fake brain)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from . import pipeline as PL
from .brain_client import FakeBrain, KbReply
from .config import load
from .llm import MockLLM
from .models import Project

FIX = Path(__file__).resolve().parent.parent / "fixtures"


async def demo() -> None:
    s = load()
    brain = FakeBrain({"newsletter": KbReply(True, "Enable the Email Capture widget.", ["https://help.example.com/email-capture"]),
                       "spanish": KbReply(True, "Turn on a language under Admin > Languages.", ["https://help.example.com/languages"])})
    pipe = PL.Pipeline(MockLLM(), brain, s)
    p = Project("demo", "Family Bakery")
    for f in sorted(FIX.glob("*.txt")):
        p.transcripts[f.stem] = f.read_text()
    v1 = await pipe.build_initial(p, ["meeting-1", "meeting-2"])
    print(v1.proposal_md, "\n--- issues:", *v1.review_issues, sep="\n")
    try:
        PL.client_view(v1)
    except PermissionError as e:
        print("\nclient view blocked:", e)
    PL.approve(v1, "senior@company.com")
    v2 = await pipe.build_followup(p, ["meeting-3-followup"])
    import json
    print("\n=== DIFF ===\n", json.dumps(v2.diff, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(), host="0.0.0.0", port=8003)
    else:
        asyncio.run(demo())
