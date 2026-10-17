from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

REQ_TYPES = {"feature", "change", "remove", "constraint", "question"}


class SchemaError(ValueError):
    pass


def need(d: dict, key: str, typ: type | tuple, ctx: str = "") -> Any:
    if key not in d or not isinstance(d[key], typ):
        raise SchemaError(f"{ctx}{key}: expected {typ}, got {d.get(key)!r}")
    return d[key]


@dataclass
class Requirement:
    id: str
    text: str
    type: str = "feature"
    priority: str = "should"            # must | should | could
    quote: str = ""                     # the client's words, so a human can verify
    source: str = ""                    # transcript name
    origin: str = "agreed"              # agreed | change_order (added after the scope was approved)
    solution: str = "custom"            # custom | existing_setting
    kb_answer: str = ""
    kb_sources: list[str] = field(default_factory=list)

    @staticmethod
    def from_llm(d: dict, source: str) -> "Requirement":
        t = need(d, "type", str, "requirement.")
        if t not in REQ_TYPES:
            raise SchemaError(f"bad requirement type {t}")
        return Requirement(id="", text=need(d, "text", str, "requirement.").strip(), type=t,
                           priority=d.get("priority", "should") if d.get("priority") in ("must", "should", "could") else "should",
                           quote=str(d.get("quote", ""))[:300], source=source)


@dataclass
class TaskItem:
    requirement_id: str
    title: str
    hours_low: float
    hours_high: float
    kind: str = "work"                  # work | overhead
    assumptions: list[str] = field(default_factory=list)

    @property
    def hours(self) -> float:
        return round((self.hours_low + self.hours_high) / 2, 1)


@dataclass
class Sow:
    version: int
    status: str = "draft"               # draft | approved | rejected
    requirements: list[Requirement] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    review_issues: list[str] = field(default_factory=list)
    proposal_md: str = ""
    sources: list[str] = field(default_factory=list)
    diff: dict | None = None
    approved_by: str | None = None
    baseline_version: int | None = None

    def total_hours(self) -> tuple[float, float]:
        return (round(sum(t.hours_low for t in self.tasks), 1), round(sum(t.hours_high for t in self.tasks), 1))


@dataclass
class Project:
    id: str
    name: str
    transcripts: dict[str, str] = field(default_factory=dict)
    versions: list[Sow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
