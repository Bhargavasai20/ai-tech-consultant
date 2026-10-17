/**
 * Task 2 evals. Usage:
 *   ANTHROPIC_API_KEY=... EVAL_MODELS=claude-haiku-5-5,claude-sonnet-5-5 node evals/run.ts
 * Without a key it runs on the MockLlm: that proves the harness works, NOT model quality.
 * Set PRICES='{"model":[inPerMTok,outPerMTok]}' from the Anthropic pricing page to get cost.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { processEmail } from '../src/agent.ts';
import { FakeBrain } from '../src/brainClient.ts';
import { classify } from '../src/classify.ts';
import { getKind, recordHumanOutcome } from '../src/learn.ts';
import { makeLlm, type Llm } from '../src/llm.ts';
import { Store } from '../src/store.ts';
import type { InboundEmail } from '../src/types.ts';

const seeds = JSON.parse(readFileSync(new URL('./seed_emails.json', import.meta.url), 'utf8')) as (InboundEmail & { expected: string })[];
const prices = JSON.parse(process.env.PRICES ?? '{}') as Record<string, [number, number]>;
const models = (process.env.EVAL_MODELS ?? 'claude-haiku-5-5').split(',');
const base = makeLlm();
const mock = !process.env.ANTHROPIC_API_KEY;

const out: Record<string, unknown> = { mock, cases: seeds.length, classification: [] as unknown[] };
for (const model of models) {
  let ok = 0, inTok = 0, outTok = 0, ms = 0;
  const wrong: string[] = [];
  const llm: Llm = { complete: async (r) => { const t = performance.now(); const x = await base.complete({ ...r, model }); ms += performance.now() - t; inTok += x.inputTokens; outTok += x.outputTokens; return x; } };
  const store = new Store(null);
  for (const e of seeds) {
    const c = await classify(llm, store, e);
    if (c.category === e.expected) ok++; else wrong.push(`${e.id}: expected ${e.expected}, got ${c.category}`);
  }
  const p = prices[model];
  (out.classification as unknown[]).push({ model, accuracy: Number((ok / seeds.length).toFixed(3)), avgMsPerEmail: Math.round(ms / seeds.length), inTok, outTok, usd: p ? Number(((inTok * p[0] + outTok * p[1]) / 1e6).toFixed(4)) : 'set PRICES', wrong });
}

// Learning curve: 30 how-to emails, human approves unchanged. When does it earn auto-send?
const d = { llm: base, brain: new FakeBrain(), store: new Store(null) };
let promotedAt = -1;
for (let i = 0; i < 30; i++) {
  const dr = await processEmail(d, { id: `lc${i}`, from: 'a@b.c', subject: 's', body: 'How do I change the price of my plan?', receivedAt: '' });
  if (dr.status === 'pending_review') await recordHumanOutcome(d.store, base, dr, dr.body);
  if (promotedAt < 0 && getKind(d.store, 'how_to:how-to-setting').autoSend) promotedAt = i + 1;
}
out.learning = { promotedAfterEmails: promotedAt };

const file = new URL(`./results/${mock ? 'mock' : 'real'}-${Date.now()}.json`, import.meta.url);
writeFileSync(file, JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
