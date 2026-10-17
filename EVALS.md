# EVALS

> Status: harnesses and 60+ test cases are built and run. **Real-model numbers are not filled in yet** - run the
> commands below with `ANTHROPIC_API_KEY` set and paste the output. Do not paste MOCK numbers.

## What exists now

| Check | Where | Result |
|---|---|---|
| Unit/integration tests, offline | `make test` | Task 1: 10 pass - Task 2: 12 pass - Task 3: 10 pass |
| Task 1 cases (12 answerable, 8 not) | `evals/task1_cases.json` | harness runs |
| Task 2 cases (54 emails, 11 categories) | `task2_inbox/evals/seed_emails.json` | harness runs |
| Task 3 cases (15 extraction/settings, 5 follow-up) | `evals/task3_cases.json` | harness runs |

Mock-mode results are circular for Tasks 2-3 (the mock was written against the same cases) and prove wiring only.
One genuine finding came out of Task 1 even in mock mode: **"Does the platform support blockchain payments?" was
answered from the Stripe article** (retrieval coverage check too weak). That is a real failure to show in the demo.

## How to produce the real tables
```
export ANTHROPIC_API_KEY=...
export BRAIN_PRICES='{"claude-haiku-5-5":[IN,OUT],"claude-sonnet-5-5":[IN,OUT]}'   # USD per 1M tokens, from the pricing page
BRAIN_ANSWER_MODEL=claude-haiku-5-5  python3 evals/run_task1.py --real
BRAIN_ANSWER_MODEL=claude-sonnet-5-5 python3 evals/run_task1.py --real
PRICES="$BRAIN_PRICES" EVAL_MODELS=claude-haiku-5-5,claude-sonnet-5-5 (cd task2_inbox && node evals/run.ts)
SCOPE_CHEAP_MODEL=claude-haiku-5-5 python3 evals/run_task3.py --real     # then again with the other model
```
For Task 1 against the **real** help center: after `make crawl`, write 20+ questions from real articles in the same
JSON shape (including unanswerable ones and one about a removed article) and run with `--real`.

## Tables to fill (one per task; keep numbers, not adjectives)

**Task 1 - Knowledge Brain** (model decision: answer model)
| Model | Correct+cited | Abstained correctly | Avg seconds | Cost per answer |
|---|---|---|---|---|
| haiku | TBD | TBD | TBD | TBD |
| sonnet | TBD | TBD | TBD | TBD |

Also measure: first-crawl pages/minute and requests/second; vision cost for N images; sync run with 1 added, 1 updated, 1 removed page (tests already cover correctness).

**Task 2 - Inbox** (model decision: classifier, drafter)
| Model | Category accuracy (54) | Avg ms/email | Cost / 1000 emails |
|---|---|---|---|
| haiku | TBD | TBD | TBD |
| sonnet | TBD | TBD | TBD |

Learning: emails until first auto-send (harness: 20), unchanged-rate early vs late on 30 simulated emails, demotion after 2 changed audits (tested).

**Task 3 - Scope**
| Model (extract) | Requirement recall | Existing-setting correct | Follow-up classified | Seconds | Cost |
|---|---|---|---|---|---|
| haiku | TBD | TBD | TBD | TBD | TBD |
| sonnet | TBD | TBD | TBD | TBD | TBD |

## Reliability and safety (tested, see test names)
Retry then flag on invalid model JSON - Brain down -> flagged, never invented - junk transcript window flagged - citation to a
non-retrieved source refused - injection email -> spam, no reply - links/amounts not in the knowledge base force review -
approval gate returns 403 - broken sitemap cannot delete memory.

## Failures I have seen
1. Blockchain-payments false positive (Task 1, above). Fix to try: require the rarest question term to appear, or add embeddings.
2. Holding replies inflated the auto-send streak (Task 2). Fixed; test added.
3. Link check treated "…/a," and "$10." as different from "…/a" and "$10". Fixed; test added.
