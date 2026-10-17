# AI Tech Consultant

One system for a software or service business: **it knows the product, handles the inbox, and turns meetings into a scope of work.**

| Task | What it does | Lang | Port |
|---|---|---|---|
| 1 `task1_brain` | Polite crawl of a help center (text + screenshots), daily sync, cited answers, "I don't know" becomes a task for a human expert whose answer is learned | Python | 8001 |
| 2 `task2_inbox` | Reads customer emails, drafts replies from Task 1's facts, learns from every human edit, earns auto-send per kind of email | TypeScript | 8002 |
| 3 `task3_scope` | Transcripts to scope, hour estimates and proposal; follow-up meeting shows what changed and what to quote extra; human approval gate | Python | 8003 |

Tasks 2 and 3 call Task 1 **only over HTTP** (`POST /v1/ask`).

## Run it
```
make install     # Python 3.11+, Node 22.18+
make run         # no API key needed: runs in MOCK mode with demo data
make test        # 32 tests, offline
```
Windows (no `make`): `.\run.ps1` from the project root starts all three tasks (create the `.venv` and `pip install -e task1_brain -e task3_scope` first). Open `http://127.0.0.1:8001`, not `0.0.0.0`.

Real mode: `export ANTHROPIC_API_KEY=...`, then `make crawl` (first full read, ~1 request/second, resumable), then `make run`.
Screens: open the three ports above. API docs for Task 1: `localhost:8001/docs`.

## Read next
`DESIGN.md` (why), `EVALS.md` (numbers and failures), `AI_LOG.md` (how it was built).
