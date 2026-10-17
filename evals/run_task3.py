"""Task 3 evals. Offline: python evals/run_task3.py  (MockLLM: wiring only, NOT model quality)
Real: ANTHROPIC_API_KEY=... BRAIN_URL=http://localhost:8001 SCOPE_CHEAP_MODEL=... python evals/run_task3.py --real
Measures: requirement recall, junk rejection, existing-setting detection, clarifying questions, follow-up classification."""
import asyncio, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "task3_scope"))
from scope import agents as A  # noqa: E402
from scope.brain_client import FakeBrain, HttpBrain, KbReply  # noqa: E402
from scope.config import load  # noqa: E402
from scope.llm import AnthropicLLM, MockLLM  # noqa: E402
from scope.models import Requirement  # noqa: E402


async def main() -> None:
    real = "--real" in sys.argv
    s = load(); data = json.loads((ROOT / "task3_cases.json").read_text())
    llm = AnthropicLLM() if real else MockLLM()
    brain = HttpBrain(s.brain_url, s.brain_key) if real else FakeBrain({k: KbReply(True, "Use the built-in setting.", ["https://h/x"]) for k in ("newsletter", "spanish", "domain", "export")})
    rec = settings_ok = q_ok = q_n = junk_ok = n_ext = 0
    fails: list[str] = []; t0 = time.perf_counter()
    for c in data["extraction"]:
        issues: list[str] = []
        reqs = [r for r in await A.extract(llm, s, "eval", c["text"], issues) if r.type in ("feature", "change")]
        if c.get("expect_none"):
            junk_ok += not reqs
            if reqs: fails.append(f"junk produced requirements: {c['text'][:40]}")
            continue
        n_ext += 1
        hit = [r for r in reqs if any(k in r.text.lower() for k in c["keywords"])]
        if hit: rec += 1
        else: fails.append(f"missed: {c['keywords']}"); continue
        A.number(hit); await A.check_settings(brain, hit, issues)
        settings_ok += (hit[0].solution == "existing_setting") == c["existing_setting"]
        if c.get("needs_question"):
            q_n += 1; q_ok += bool(await A.clarify(llm, s, hit))
    base = [Requirement(f"R{i+1}", t, "feature") for i, t in enumerate(data["baseline"])]
    rc_ok = 0
    for c in data["reconcile"]:
        items = [r for r in await A.extract(llm, s, "eval", c["text"], []) if r.type in ("feature", "change", "remove")]
        d = await A.reconcile(llm, s, base, items) if items else []
        got = d[0]["relation"] if d else "none"
        rc_ok += got == c["expect"]
        if got != c["expect"]: fails.append(f"reconcile: expected {c['expect']} got {got}: {c['text'][:50]}")
    print(json.dumps({"mode": "real" if real else "MOCK (not model quality)", "cheap_model": s.cheap_model, "strong_model": s.strong_model,
        "cases": len(data["extraction"]) + len(data["reconcile"]),
        "requirement_recall": f"{rec}/{n_ext}", "junk_rejected": f"{junk_ok}/1", "existing_setting_correct": f"{settings_ok}/{rec}",
        "vague_got_question": f"{q_ok}/{q_n}", "followup_classified": f"{rc_ok}/{len(data['reconcile'])}",
        "seconds": round(time.perf_counter() - t0, 1), "failed": fails}, indent=1))

asyncio.run(main())
