"""Task 1 evals. Offline: python evals/run_task1.py   (MockLLM: checks wiring + retrieval, NOT model quality)
Real:    ANTHROPIC_API_KEY=... BRAIN_PRICES='{"model":[in,out]}' BRAIN_ANSWER_MODEL=claude-sonnet-5-5 python evals/run_task1.py --real
Compare models by running once per BRAIN_ANSWER_MODEL and pasting the printed rows into EVALS.md.
For the REAL help center, point --cases at a file built from real crawled articles with the same shape."""
import asyncio, dataclasses, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "task1_brain"))
from brain.app import Brain  # noqa: E402
from brain.config import load_settings  # noqa: E402
from brain.fetch import FetchResult  # noqa: E402
from brain.ingest import ingest_url  # noqa: E402
from brain.llm import MockLLM  # noqa: E402
from brain.qa import ask  # noqa: E402


class Site:
    def __init__(self, pages): self.pages = pages
    async def get(self, url): return FetchResult(url, 200, self.pages[url].encode(), "text/html")


async def main() -> None:
    real = "--real" in sys.argv
    data = json.loads((ROOT / "task1_cases.json").read_text())
    s = dataclasses.replace(load_settings(), min_delay_s=0)
    if real:
        b = Brain.create(s, fetcher=Site(data["corpus"]), db_path=":memory:")
    else:
        b = Brain.create(s, llm=MockLLM(), fetcher=Site(data["corpus"]), db_path=":memory:")
    for u in data["corpus"]:
        await ingest_url(b, u, "1")
    ok = cite_ok = abst_ok = n_ans = n_abs = 0
    lat, fails = [], []
    for c in data["cases"]:
        t = time.perf_counter(); a = await ask(b, c["q"]); lat.append(time.perf_counter() - t)
        if c["expect"] == "abstain":
            n_abs += 1; good = not a.answered; abst_ok += good
        else:
            n_ans += 1
            cited = any(c["cite"] in x.url for x in a.sources)
            has = all(w in a.answer.lower() for w in c["contains"])
            good = a.answered and cited and has; cite_ok += cited
        ok += good
        if not good: fails.append(c["q"])
    use = b.db.query("SELECT sum(input_tokens) i,sum(output_tokens) o,round(sum(usd),4) usd FROM usage WHERE purpose='answer'")[0]
    print(json.dumps({"mode": "real" if real else "MOCK (not model quality)", "model": s.answer_model, "cases": len(data["cases"]),
        "overall_pass": round(ok / len(data["cases"]), 3), "answerable_cited_correctly": f"{cite_ok}/{n_ans}",
        "unanswerable_abstained": f"{abst_ok}/{n_abs}", "avg_latency_s": round(sum(lat) / len(lat), 3),
        "answer_tokens_in_out": [use["i"], use["o"]], "answer_usd": use["usd"], "failed": fails}, indent=1))

asyncio.run(main())
