"""FastAPI service + 3 simple screens. The client-facing endpoint refuses anything not approved."""
from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import pipeline as PL
from .brain_client import HttpBrain
from .config import load
from .llm import AnthropicLLM, MockLLM
from .models import Project

STATIC = Path(__file__).resolve().parent.parent / "static"


class NewProject(BaseModel):
    name: str = Field(min_length=1)


class TranscriptIn(BaseModel):
    name: str = Field(min_length=1, examples=["meeting-1"])
    text: str = Field(min_length=10)


class GenIn(BaseModel):
    transcripts: list[str] = Field(min_length=1)


class ApproveIn(BaseModel):
    approver: str = Field(min_length=1)


def create_app(pipe: PL.Pipeline | None = None, store: PL.ProjectStore | None = None) -> FastAPI:
    s = load()
    mock = os.environ.get("SCOPE_MOCK") == "1" or not os.environ.get("ANTHROPIC_API_KEY")
    pipe = pipe or PL.Pipeline(MockLLM() if mock else AnthropicLLM(), HttpBrain(s.brain_url, s.brain_key), s)
    st = store or PL.ProjectStore(s.data_file)
    app = FastAPI(title="Meeting to Scope of Work", version="0.1.0")

    def proj(pid: str) -> Project:
        if pid not in st.projects:
            raise HTTPException(404, "no such project")
        return st.projects[pid]

    @app.post("/projects")
    def create(b: NewProject):
        p = Project(uuid.uuid4().hex[:8], b.name); st.projects[p.id] = p; st.save(); return {"id": p.id}

    @app.get("/projects")
    def list_projects():
        return [{"id": p.id, "name": p.name, "versions": [{"version": v.version, "status": v.status} for v in p.versions]} for p in st.projects.values()]

    @app.post("/projects/{pid}/transcripts")
    def add_transcript(pid: str, b: TranscriptIn):
        proj(pid).transcripts[b.name] = b.text; st.save(); return {"ok": True}

    @app.post("/projects/{pid}/generate")
    async def generate(pid: str, b: GenIn):
        """First scope (no approved version yet) or a follow-up that diffs against the last approved scope."""
        p = proj(pid)
        missing = [n for n in b.transcripts if n not in p.transcripts]
        if missing:
            raise HTTPException(400, f"unknown transcripts: {missing}")
        has_approved = any(v.status == "approved" for v in p.versions)
        try:
            sow = await (pipe.build_followup(p, b.transcripts) if has_approved else pipe.build_initial(p, b.transcripts))
        except PermissionError as e:
            raise HTTPException(409, str(e))
        st.save()
        return asdict(sow)

    @app.get("/projects/{pid}/versions/{v}")
    def version(pid: str, v: int):
        p = proj(pid)
        if not 1 <= v <= len(p.versions):
            raise HTTPException(404, "no such version")
        return asdict(p.versions[v - 1])

    @app.post("/projects/{pid}/versions/{v}/approve")
    def approve(pid: str, v: int, b: ApproveIn):
        p = proj(pid)
        try:
            PL.approve(p.versions[v - 1], b.approver)
        except (IndexError, ValueError) as e:
            raise HTTPException(400, str(e))
        st.save(); return {"status": "approved"}

    @app.post("/projects/{pid}/versions/{v}/reject")
    def reject(pid: str, v: int):
        PL.reject(proj(pid).versions[v - 1]); st.save(); return {"status": "rejected"}

    @app.get("/projects/{pid}/versions/{v}/client-proposal", response_class=PlainTextResponse)
    def client_proposal(pid: str, v: int):
        try:
            return PL.client_view(proj(pid).versions[v - 1])
        except PermissionError as e:
            raise HTTPException(403, str(e))

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(STATIC / "index.html")

    return app
