"""HTTP API (FastAPI). Interactive docs at /docs, machine spec at /openapi.json."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import qa, tasks
from .app import Brain
from .crawl import first_crawl, process_queue
from .sync import run_sync

STATIC = Path(__file__).resolve().parent.parent / "static"


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000, examples=["How do I change my membership prices?"])
    k: int = Field(6, ge=1, le=12)


class ResolveIn(BaseModel):
    answer: str = Field(min_length=3)
    expert: str = Field(min_length=1, examples=["jane@company.com"])


class FeedbackIn(BaseModel):
    question: str
    answer: str
    helpful: bool
    comment: str | None = None


def create_app(brain: Brain | None = None, run_scheduler: bool = True) -> FastAPI:
    b = brain or Brain.create()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if run_scheduler:
            async def loop():
                while True:  # daily freshness check
                    await asyncio.sleep(b.settings.sync_interval_h * 3600)
                    try:
                        await run_sync(b)
                    except Exception as e:  # never die; try again next cycle
                        print("sync failed:", e)
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()

    app = FastAPI(title="AI Tech Consultant - Knowledge Brain", version="0.1.0", lifespan=lifespan,
                  description="Ask questions, search, manage expert tasks. Tasks 2 and 3 call this API.")

    def auth(x_api_key: str | None = Header(default=None)) -> None:
        if b.settings.api_key and x_api_key != b.settings.api_key:
            raise HTTPException(401, "bad or missing X-API-Key")

    @app.get("/v1/health")
    def health():
        return {"ok": True, **b.index.stats()}

    @app.post("/v1/ask", dependencies=[Depends(auth)])
    async def ask(body: AskIn):
        """Answer with cited sources. If unknown: answered=false and a human task is created."""
        return dataclasses.asdict(await qa.ask(b, body.question, body.k))

    @app.get("/v1/search", dependencies=[Depends(auth)])
    def search(q: str = Query(min_length=2), k: int = Query(6, ge=1, le=20)):
        """Raw retrieval, no LLM. Cheap and fast."""
        return [dataclasses.asdict(h) for h in b.index.search(q, k)]

    @app.get("/v1/tasks", dependencies=[Depends(auth)])
    def list_tasks(status: str = "open"):
        return tasks.list_tasks(b, status)

    @app.post("/v1/tasks/{task_id}/resolve", dependencies=[Depends(auth)])
    def resolve(task_id: int, body: ResolveIn):
        """Expert answer is stored AND indexed, so the next similar question is answered with it."""
        try:
            return tasks.resolve_task(b, task_id, body.answer, body.expert)
        except KeyError:
            raise HTTPException(404, "no such task")

    @app.post("/v1/feedback", dependencies=[Depends(auth)])
    def feedback(body: FeedbackIn):
        b.db.execute("INSERT INTO feedback(question,answer,helpful,comment) VALUES(?,?,?,?)",
                     (body.question, body.answer, int(body.helpful), body.comment))
        tid = None if body.helpful else tasks.create_task(b, body.question, "user marked answer unhelpful")
        return {"ok": True, "task_id": tid}

    @app.post("/v1/admin/crawl", dependencies=[Depends(auth)])
    async def crawl(limit: int | None = None, retry_failed: bool = False):
        rep = await first_crawl(b, limit) if not retry_failed else await process_queue(b, limit, True)
        return dataclasses.asdict(rep)

    @app.post("/v1/admin/sync", dependencies=[Depends(auth)])
    async def sync():
        return await run_sync(b)

    @app.get("/v1/admin/usage", dependencies=[Depends(auth)])
    def usage():
        rows = b.db.query("SELECT purpose,model,count(*) n,sum(input_tokens) i,sum(output_tokens) o,"
                          "round(sum(usd),4) usd,round(avg(ms)) avg_ms FROM usage GROUP BY purpose,model")
        return [dict(r) for r in rows]

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(STATIC / "index.html")

    return app
