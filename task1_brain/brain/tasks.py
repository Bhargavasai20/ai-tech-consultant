"""Human-expert loop: unanswerable question -> task -> expert answer -> becomes searchable memory."""
from __future__ import annotations

import hashlib
import re

from .app import Brain
from .index import terms


def _norm(q: str) -> str:
    return " ".join(sorted(set(terms(q))))


def create_task(brain: Brain, question: str, reason: str) -> int:
    norm = _norm(question)
    row = brain.db.query("SELECT id FROM tasks WHERE status='open' AND norm=?", (norm,))
    if row:  # same open question -> one task, not fifty
        return row[0]["id"]
    return brain.db.execute("INSERT INTO tasks(question,norm,reason) VALUES(?,?,?)", (question, norm, reason)).lastrowid


def list_tasks(brain: Brain, status: str = "open") -> list[dict]:
    return [dict(r) for r in brain.db.query("SELECT * FROM tasks WHERE status=? ORDER BY id", (status,))]


def resolve_task(brain: Brain, task_id: int, answer: str, expert: str) -> dict:
    rows = brain.db.query("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not rows:
        raise KeyError(task_id)
    t = rows[0]
    brain.db.execute("UPDATE tasks SET status='answered', answer=?, expert=?, answered_at=datetime('now') WHERE id=?",
                     (answer, expert, task_id))
    text = f"Question: {t['question']}\nExpert answer from {expert}: {answer}"
    brain.index.replace_page(url=f"expert://task/{task_id}", title=t["question"], section="expert", lastmod=None,
                             content_hash=hashlib.sha256(text.encode()).hexdigest(), kind="expert",
                             text_chunks=[text], image_chunks=[])
    return {"task_id": task_id, "indexed_as": f"expert://task/{task_id}"}
