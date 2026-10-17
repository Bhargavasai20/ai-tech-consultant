"""Orchestrator: hands work between agents, versions the scope, gates everything behind human approval."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict

from . import agents as A
from . import prompts as P
from .brain_client import Brain
from .config import Settings
from .llm import LLM
from .models import Project, Requirement, Sow, TaskItem


def money(s: Settings, hours: float) -> str:
    return f"{s.currency} {hours * s.rate_per_hour:,.0f}"


class Pipeline:
    def __init__(self, llm: LLM, brain: Brain, s: Settings) -> None:
        self.llm, self.brain, self.s = llm, brain, s

    # ---- meeting 1 (or any set of transcripts, no baseline) --------------------------
    async def build_initial(self, project: Project, names: list[str]) -> Sow:
        issues: list[str] = []
        reqs: list[Requirement] = []
        for n in names:
            reqs += await A.extract(self.llm, self.s, n, project.transcripts[n], issues)
        reqs = [r for r in A.merge(reqs) if r.type != "remove"]
        A.number(reqs)
        questions = await A.clarify(self.llm, self.s, reqs)
        await A.check_settings(self.brain, reqs, issues)
        tasks = A.add_overhead(self.s, await A.estimate(self.llm, self.s, reqs, issues))
        sow = Sow(version=len(project.versions) + 1, requirements=reqs, tasks=tasks, questions=questions, sources=names)
        sow.review_issues = A.review(reqs, tasks, questions, issues)
        sow.proposal_md = await self._proposal(project, sow)
        project.versions.append(sow)
        return sow

    # ---- meeting 2+: update, don't restart --------------------------------------------
    async def build_followup(self, project: Project, names: list[str]) -> Sow:
        base = next((v for v in reversed(project.versions) if v.status == "approved"), None)
        if base is None:
            raise PermissionError("approve the previous scope first: a change is only a change against an agreed scope")
        issues: list[str] = []
        items: list[Requirement] = []
        for n in names:
            items += await A.extract(self.llm, self.s, n, project.transcripts[n], issues)
        items = A.merge(items)
        work = [i for i in items if i.type in ("feature", "change", "remove")]
        decisions = await A.reconcile(self.llm, self.s, base.requirements, work)

        kept = {r.id: copy.deepcopy(r) for r in base.requirements}
        same: list[str] = []
        removed: list[Requirement] = []
        modified: list[tuple[Requirement, str]] = []
        new_reqs: list[Requirement] = []
        for item, d in zip(work, decisions):
            bid, rel = d["baseline_id"], d["relation"]
            if rel == "remove":
                if bid in kept:
                    removed.append(kept.pop(bid))
                else:
                    issues.append(f'client dropped "{item.text}" but no matching agreed item was found - check by hand')
            elif rel == "same" and bid in kept:
                same.append(bid)
            elif rel == "modified" and bid in kept and all(m[0].id != bid for m in modified):
                before = kept[bid].text
                kept[bid].text, kept[bid].solution, kept[bid].kb_answer, kept[bid].kb_sources = item.text, "custom", "", []
                modified.append((kept[bid], before))
            else:
                item.origin = "change_order"
                new_reqs.append(item)
        start = max((int(r.id[1:]) for r in base.requirements), default=0) + 1
        A.number(new_reqs, start)
        changed = [m[0] for m in modified] + new_reqs
        questions = await A.clarify(self.llm, self.s, changed)
        await A.check_settings(self.brain, changed, issues)
        new_tasks = await A.estimate(self.llm, self.s, changed, issues)

        changed_ids = {r.id for r in changed}
        carried = [copy.deepcopy(t) for t in base.tasks if t.kind == "work" and t.requirement_id in kept and t.requirement_id not in changed_ids]
        tasks = A.add_overhead(self.s, carried + new_tasks)   # unchanged items keep their agreed numbers
        sow = Sow(version=len(project.versions) + 1, requirements=list(kept.values()) + new_reqs, tasks=tasks,
                  questions=questions, sources=names, baseline_version=base.version)
        sow.diff = self._diff(base, sow, same, removed, modified, new_reqs, new_tasks)
        sow.review_issues = A.review(sow.requirements, tasks, questions, issues)
        sow.proposal_md = await self._proposal(project, sow)
        project.versions.append(sow)
        return sow

    def _diff(self, base: Sow, v2: Sow, same, removed, modified, new_reqs, new_tasks) -> dict:
        avg = lambda ts, rid: sum(t.hours for t in ts if t.requirement_id == rid and t.kind == "work")  # noqa: E731
        mult = 1 + self.s.pm_overhead + self.s.qa_overhead
        co_hours = sum(avg(new_tasks, r.id) for r in new_reqs) * mult
        b_lo, b_hi = base.total_hours()
        v_lo, v_hi = v2.total_hours()
        return {
            "baseline_version": base.version,
            "unchanged": same,
            "modified": [{"id": r.id, "before": before, "after": r.text, "hours_before": avg(base.tasks, r.id),
                          "hours_after": avg(new_tasks, r.id), "delta_hours": round(avg(new_tasks, r.id) - avg(base.tasks, r.id), 1)}
                         for r, before in modified],
            "removed": [{"id": r.id, "text": r.text, "hours_credit": avg(base.tasks, r.id)} for r in removed],
            "new_out_of_scope": [{"id": r.id, "text": r.text, "hours_with_overhead": round(avg(new_tasks, r.id) * mult, 1),
                                  "price": money(self.s, avg(new_tasks, r.id) * mult),
                                  "note": "Not in the agreed scope - quote as a change order"} for r in new_reqs],
            "totals": {"agreed_hours": [b_lo, b_hi], "new_total_hours": [v_lo, v_hi],
                       "change_order_hours": round(co_hours, 1), "change_order_price": money(self.s, co_hours)},
        }

    # ---- proposal: text from the model, numbers from code -----------------------------
    async def _proposal(self, project: Project, sow: Sow) -> str:
        try:
            r = await self.llm.complete(system=P.PROPOSAL, model=self.s.strong_model, max_tokens=300,
                                        user="\n".join(f"- {q.text}" for q in sow.requirements))
            from .llm import parse_json
            summary = str(parse_json(r.text)["summary"])[:600]
        except Exception:
            summary = "Thank you for meeting with us. Below is what we will deliver, how long it takes and what it costs."
        lo, hi = sow.total_hours()
        L = [f"# Proposal: {project.name} (v{sow.version})", "", summary, "", "## What we will deliver", "",
             "| # | Requirement | How | Hours |", "|---|---|---|---|"]
        for r in sow.requirements:
            if r.type in ("feature", "change"):
                hrs = sum(t.hours for t in sow.tasks if t.requirement_id == r.id)
                how = "Existing setting (low cost)" if r.solution == "existing_setting" else "Custom build"
                L.append(f"| {r.id} | {r.text}{' *(change order)*' if r.origin == 'change_order' else ''} | {how} | {hrs:g} |")
        L += ["", "## Estimate", "", "| Task | Hours | Cost |", "|---|---|---|"]
        for t in sow.tasks:
            L.append(f"| {t.title} | {t.hours_low:g}-{t.hours_high:g} | {money(self.s, t.hours_low)} - {money(self.s, t.hours_high)} |")
        L += [f"| **Total** | **{lo:g}-{hi:g}** | **{money(self.s, lo)} - {money(self.s, hi)}** |", ""]
        saved = [r for r in sow.requirements if r.solution == "existing_setting"]
        if saved:
            L += ["## Cost savings", "", f"{len(saved)} item(s) use settings your product already has, so they need configuration, not code.", ""]
        if sow.diff:
            d = sow.diff
            L += ["## Changes since the agreed scope", ""]
            L += [f"- Changed {m['id']}: {m['after']} ({m['delta_hours']:+g}h)" for m in d["modified"]]
            L += [f"- Removed {m['id']}: {m['text']} (credit {m['hours_credit']:g}h)" for m in d["removed"]]
            L += [f"- **Extra, outside agreed scope** {n['id']}: {n['text']}: {n['hours_with_overhead']:g}h, {n['price']}" for n in d["new_out_of_scope"]]
            L.append("")
        assumptions = sorted({a for t in sow.tasks for a in t.assumptions})
        if assumptions:
            L += ["## Assumptions", ""] + [f"- {a}" for a in assumptions] + [""]
        if sow.questions:
            L += ["## Questions we need answered", ""] + [f"- {q}" for q in sow.questions] + [""]
        return "\n".join(L)


# ---- human approval gate -----------------------------------------------------------------
def approve(sow: Sow, who: str) -> None:
    if sow.status != "draft":
        raise ValueError(f"version is {sow.status}")
    sow.status, sow.approved_by = "approved", who


def reject(sow: Sow) -> None:
    sow.status = "rejected"


def client_view(sow: Sow) -> str:
    """The ONLY way proposal text leaves the system."""
    if sow.status != "approved":
        raise PermissionError("not approved by a human yet")
    return sow.proposal_md


# ---- persistence ----------------------------------------------------------------------------
class ProjectStore:
    def __init__(self, path: str | None) -> None:
        self.path, self.projects = path, {}
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            for d in data.values():
                self.projects[d["id"]] = project_from_dict(d)

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({k: v.to_dict() for k, v in self.projects.items()}, f, indent=1)
        os.replace(tmp, self.path)


def project_from_dict(d: dict) -> Project:
    vs = []
    for v in d["versions"]:
        v = dict(v)
        v["requirements"] = [Requirement(**r) for r in v["requirements"]]
        v["tasks"] = [TaskItem(**t) for t in v["tasks"]]
        vs.append(Sow(**v))
    return Project(d["id"], d["name"], d["transcripts"], vs)
