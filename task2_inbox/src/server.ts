import { readFileSync } from 'node:fs';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { fileURLToPath } from 'node:url';
import { processEmail, type Deps } from './agent.ts';
import { HttpBrain } from './brainClient.ts';
import { config } from './config.ts';
import { getKind, recordCustomerSignal, recordHumanOutcome, revertRule, trend, demote } from './learn.ts';
import { makeLlm } from './llm.ts';
import { Store } from './store.ts';
import type { InboundEmail } from './types.ts';

const UI = fileURLToPath(new URL('../public/index.html', import.meta.url));

async function json(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const c of req) { size += (c as Buffer).length; if (size > 1_000_000) throw new Error('body too large'); chunks.push(c as Buffer); }
  return chunks.length ? (JSON.parse(Buffer.concat(chunks).toString()) as Record<string, unknown>) : {};
}
const send = (res: ServerResponse, code: number, body: unknown) => {
  res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(body));
};

export function makeServer(d: Deps) {
  const { store } = d;
  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? '/', 'http://x');
      const route = `${req.method} ${url.pathname}`;
      if (route === 'GET /') { res.writeHead(200, { 'content-type': 'text/html' }); return void res.end(readFileSync(UI)); }

      if (route === 'POST /api/emails') {
        const b = await json(req);
        if (typeof b.body !== 'string' || typeof b.from !== 'string') return send(res, 400, { error: 'from and body are required strings' });
        const email: InboundEmail = { id: String(b.id ?? `e${Date.now()}`), from: b.from, subject: String(b.subject ?? '(no subject)'), body: b.body, receivedAt: new Date().toISOString() };
        return send(res, 200, await processEmail(d, email));
      }
      if (route === 'GET /api/drafts') {
        const want = url.searchParams.get('status') ?? 'pending_review';
        return send(res, 200, Object.values(store.state.drafts).filter((x) => x.status === want || (want === 'pending_review' && x.status === 'audit_pending'))
          .map((x) => ({ ...x, email: store.state.emails[x.emailId] })));
      }
      if (route === 'POST /api/drafts/feedback') {
        const b = await json(req);
        const draft = store.state.drafts[String(b.draftId)];
        if (!draft || (draft.status !== 'pending_review' && draft.status !== 'audit_pending')) return send(res, 404, { error: 'no pending draft with that id' });
        const finalBody = typeof b.finalBody === 'string' && b.finalBody.trim() ? b.finalBody : draft.body; // one-click send = body unchanged
        const outcome = await recordHumanOutcome(store, d.llm, draft, finalBody);
        return send(res, 200, { outcome, similarity: draft.similarity, kind: getKind(store, draft.kind) });
      }
      if (route === 'POST /api/customer-signal') {
        const b = await json(req); recordCustomerSignal(store, String(b.draftId), Boolean(b.negative)); return send(res, 200, { ok: true });
      }
      if (route === 'GET /api/kinds') {
        return send(res, 200, Object.values(store.state.kinds).map((k) => ({ ...k, trend: trend(k), rules: store.state.rules.filter((r) => r.kind === k.kind) })));
      }
      if (route === 'POST /api/kinds/demote') {
        const b = await json(req); demote(getKind(store, String(b.kind)), 'manual demotion'); store.save(); return send(res, 200, { ok: true });
      }
      if (route === 'POST /api/rules/revert') {
        const b = await json(req); return send(res, 200, { reverted: revertRule(store, String(b.id)) });
      }
      if (route === 'GET /api/health') return send(res, 200, { ok: true, mock: config.mock });
      send(res, 404, { error: 'not found' });
    } catch (e) {
      send(res, 500, { error: e instanceof Error ? e.message : 'error' });
    }
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const deps: Deps = { llm: makeLlm(), brain: new HttpBrain(), store: new Store(config.dataFile) };
  makeServer(deps).listen(config.port, () => console.log(`Inbox Agent on :${config.port} (mock llm: ${config.mock})`));
}
