"""One job per agent. Numbers (hours, prices, totals) come from code, never from free text."""
from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher

from . import prompts as P
from .brain_client import Brain
from .chunking import windows
from .config import Settings
from .llm import LLM, parse_json
from .models import Requirement, SchemaError, TaskItem, need

_VAGUE = re.compile(r"\b(better|faster|nicer|modern|improve|easier|good|clean)\b", re.I)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower()).strip()


def sim(a: str, b: str) -> float:
    """Fuzzy similarity. An agreed sentence restated with <=5 extra filler words counts as the same item."""
    a, b = norm(a), norm(b)
    r = SequenceMatcher(None, a, b).ratio()
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if short and short in long_ and len(long_.split()) - len(short.split()) <= 5:
        r = max(r, 0.95)
    return r


async def _json_call(llm: LLM, system: str, user: str, model: str, check, tries: int = 2):
    last: Exception | None = None
    for _ in range(tries):
        try:
            r = await llm.complete(system=system, user=user, model=model)
            return check(parse_json(r.text))
        except (ValueError, SchemaError, KeyError, TypeError) as e:  # bad JSON or bad schema -> retry once
            last = e
    raise SchemaError(f"model output failed validation twice: {last}")


# 1) Extractor: map over windows, then merge ---------------------------------
async def extract(llm: LLM, s: Settings, name: str, transcript: str, issues: list[str]) -> list[Requirement]:
    wins = windows(transcript, s.window_words, s.overlap_words)
    sem = asyncio.Semaphore(4)

    async def one(i: int, w: str) -> list[Requirement]:
        async with sem:
            try:
                return await _json_call(llm, P.EXTRACT, w, s.cheap_model,
                                        lambda d: [Requirement.from_llm(x, name) for x in need(d, "requirements", list)])
            except SchemaError as e:
                issues.append(f"{name}: window {i + 1}/{len(wins)} could not be read ({e}); a human should check it")
                return []
    parts = await asyncio.gather(*(one(i, w) for i, w in enumerate(wins)))
    return merge([r for p in parts for r in p])


def merge(reqs: list[Requirement], threshold: float = 0.82) -> list[Requirement]:
    out: list[Requirement] = []
    for r in reqs:
        dup = next((o for o in out if o.type == r.type and sim(o.text, r.text) >= threshold), None)
        if dup:
            if r.priority == "must":
                dup.priority = "must"
        else:
            out.append(r)
    return out


def number(reqs: list[Requirement], start: int = 1) -> None:
    for i, r in enumerate(reqs, start):
        r.id = f"R{i}"


# 2) Clarifier -----------------------------------------------------------------
async def clarify(llm: LLM, s: Settings, reqs: list[Requirement]) -> list[str]:
    if not reqs:
        return []
    user = "\n".join(f"- [{r.id}] {r.text}" for r in reqs)
    try:
        return await _json_call(llm, P.CLARIFY, user, s.strong_model,
                                lambda d: [str(q) for q in need(d, "questions", list)][:8])
    except SchemaError:
        return [f'What does "{r.text}" mean in measurable terms?' for r in reqs if _VAGUE.search(r.text)][:8]


# 3) Settings checker: ask Task 1 before quoting custom code -------------------
async def check_settings(brain: Brain, reqs: list[Requirement], issues: list[str]) -> None:
    async def one(r: Requirement) -> None:
        if r.type not in ("feature", "change"):
            return
        rep = await brain.ask("Can a site owner do this with an existing setting or built-in feature, without custom code? " + r.text)
        if rep.unavailable:
            issues.append(f"{r.id}: knowledge brain unavailable, quoted as custom work - recheck for an existing setting")
        elif rep.answered:
            r.solution, r.kb_answer, r.kb_sources = "existing_setting", rep.answer, rep.sources
    await asyncio.gather(*(one(r) for r in reqs))


# 4) Estimator -----------------------------------------------------------------
def _validate_tasks(d: dict, known: set[str]) -> list[TaskItem]:
    out = []
    for t in need(d, "tasks", list):
        rid = need(t, "requirement_id", str)
        lo, hi = float(t["hours_low"]), float(t["hours_high"])
        if rid not in known or not (0 < lo <= hi <= 200):
            raise SchemaError(f"bad task {rid} {lo}-{hi}")
        out.append(TaskItem(rid, str(t.get("title", rid))[:120], lo, hi, "work", [str(a) for a in t.get("assumptions", [])][:5]))
    return out


async def estimate(llm: LLM, s: Settings, reqs: list[Requirement], issues: list[str]) -> list[TaskItem]:
    tasks: list[TaskItem] = []
    custom = [r for r in reqs if r.type in ("feature", "change") and r.solution == "custom"]
    for r in reqs:
        if r.type in ("feature", "change") and r.solution == "existing_setting":
            tasks.append(TaskItem(r.id, f"Configure existing setting: {r.text[:70]}", 0.5, 1.5,
                                  assumptions=["Solved with a setting the product already has (see knowledge base sources)"]))
    if custom:
        user = "\n".join(f"- [{r.id}] {r.text}" for r in custom)
        try:
            tasks += await _json_call(llm, P.ESTIMATE, user, s.strong_model, lambda d: _validate_tasks(d, {r.id for r in custom}), tries=2)
        except SchemaError as e:
            issues.append(f"estimator failed ({e}); conservative defaults used - a developer must estimate these")
        have = {t.requirement_id for t in tasks}
        for r in custom:
            if r.id not in have:
                tasks.append(TaskItem(r.id, r.text[:80], 8, 24, assumptions=["DEFAULT ESTIMATE - not reviewed by a developer"]))
                issues.append(f"{r.id}: no estimate returned; default 8-24h applied")
    return tasks


def add_overhead(s: Settings, tasks: list[TaskItem]) -> list[TaskItem]:
    work = [t for t in tasks if t.kind == "work"]
    lo, hi = sum(t.hours_low for t in work), sum(t.hours_high for t in work)
    over = [TaskItem("-", f"Project management ({int(s.pm_overhead * 100)}%)", round(lo * s.pm_overhead, 1), round(hi * s.pm_overhead, 1), "overhead"),
            TaskItem("-", f"QA and testing ({int(s.qa_overhead * 100)}%)", round(lo * s.qa_overhead, 1), round(hi * s.qa_overhead, 1), "overhead")]
    return work + over


# 5) Reviewer (the "senior check") -----------------------------------------------
def review(reqs: list[Requirement], tasks: list[TaskItem], questions: list[str], prior: list[str]) -> list[str]:
    issues = list(prior)
    ids = {r.id for r in reqs if r.type in ("feature", "change")}
    covered = {t.requirement_id for t in tasks}
    for rid in sorted(ids - covered):
        issues.append(f"{rid} has no task")
    for t in tasks:
        if t.kind == "work" and t.hours_high > 40:
            issues.append(f"{t.requirement_id}: {t.hours_high:.0f}h in one task - split it before quoting")
        if t.kind == "work" and t.hours_low >= 2 and t.hours_high > 2.5 * t.hours_low:
            issues.append(f"{t.requirement_id}: range {t.hours_low:.0f}-{t.hours_high:.0f}h is very wide - ask a clarifying question")
    for r in reqs:
        if r.type == "constraint":
            issues.append(f"constraint to honour: {r.text}")
    if questions:
        issues.append(f"{len(questions)} open question(s) should be answered by the client before sending")
    return issues


# 6) Reconciler (follow-up meetings) ----------------------------------------------
async def reconcile(llm: LLM, s: Settings, baseline: list[Requirement], new: list[Requirement]) -> list[dict]:
    """Returns one decision per new item: {relation: same|modified|new|remove, baseline_id|None}."""
    decisions: list[dict | None] = [None] * len(new)
    ambiguous: list[int] = []
    for i, n in enumerate(new):
        best = max(baseline, key=lambda b: sim(b.text, n.text), default=None)
        r = sim(best.text, n.text) if best else 0.0
        if n.type == "remove":
            decisions[i] = {"relation": "remove", "baseline_id": best.id if best and r >= 0.35 else None}
        elif best and r >= 0.9:
            decisions[i] = {"relation": "same", "baseline_id": best.id}
        elif best and (r >= 0.6 or (n.type == "change" and r >= 0.4)):
            decisions[i] = {"relation": "modified", "baseline_id": best.id}
        elif best and r >= 0.4:
            ambiguous.append(i)
        else:
            decisions[i] = {"relation": "new", "baseline_id": None}
    if ambiguous:
        user = "AGREED SCOPE:\n" + "\n".join(f"- [{b.id}] {b.text}" for b in baseline) + "\n\nITEMS:\n" + \
               "\n".join(f"{i}. {new[i].text}" for i in ambiguous)
        try:
            got = await _json_call(llm, P.RECONCILE, user, s.strong_model, lambda d: need(d, "matches", list))
            for m in got:
                if m.get("index") in ambiguous and m.get("relation") in ("same", "modified", "new"):
                    decisions[m["index"]] = {"relation": m["relation"], "baseline_id": m.get("baseline_id")}
        except SchemaError:
            pass
        for i in ambiguous:  # undecided -> treat as NEW: the safe default is "quote it extra", a human can overrule
            decisions[i] = decisions[i] or {"relation": "new", "baseline_id": None}
    return [d for d in decisions if d is not None]
