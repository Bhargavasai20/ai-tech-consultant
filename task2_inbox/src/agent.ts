import { createHash } from 'node:crypto';
import type { Brain } from './brainClient.ts';
import { classify } from './classify.ts';
import { config } from './config.ts';
import { checkDraft, promptVersion, writeDraft } from './draft.ts';
import { getKind } from './learn.ts';
import type { Llm } from './llm.ts';
import type { Store } from './store.ts';
import type { Classification, Draft, InboundEmail, KbAnswer } from './types.ts';

export interface Deps { llm: Llm; brain: Brain; store: Store }

/** Deterministic: ~auditRate of drafts are held for review even if the kind may auto-send. */
export function isAuditSample(draftId: string): boolean {
  const n = parseInt(createHash('sha1').update(draftId).digest('hex').slice(0, 6), 16) % 100;
  return n < config.auditRate * 100;
}

/** Why must a human look at this one? Empty list = safe to auto-send (if the kind earned it). */
export function guardReasons(c: Classification, kb: KbAnswer | null, bodyChecks: string[]): string[] {
  const r = [...bodyChecks];
  if (c.confidence < config.minConfidence) r.push(`low classifier confidence (${c.confidence})`);
  if (c.sentiment === 'angry' || c.sentiment === 'negative') r.push(`customer sentiment is ${c.sentiment}`);
  if (c.containsSensitive) r.push('email contains sensitive data');
  if (kb?.unavailable) r.push('knowledge brain unavailable');
  if (c.category === 'how_to' && !kb?.answered) r.push('knowledge base could not answer');
  if (config.blockedCategories.includes(c.category)) r.push(`category ${c.category} always needs a human`);
  return r;
}

export async function processEmail(d: Deps, email: InboundEmail): Promise<Draft> {
  const { store } = d;
  store.state.emails[email.id] = email;
  const c = await classify(d.llm, store, email);
  const kind = `${c.category}:${c.topic}`;
  const id = `d_${email.id}`;
  const base = { id, emailId: email.id, kind, sources: [] as Draft['sources'], createdAt: new Date().toISOString() };

  if (c.category === 'spam') {
    const draft: Draft = { ...base, subject: '', body: '', promptVersion: '-', status: 'no_reply_needed', reasons: ['classified as spam'] };
    store.state.drafts[id] = draft; store.save();
    return draft;
  }

  const kb = c.question ? await d.brain.ask(c.question) : null;
  let subject = `Re: ${email.subject}`, body = '', reasons: string[] = [];
  try {
    const w = await writeDraft(d.llm, store, kind, email, c, kb);
    subject = w.subject; body = w.body;
    reasons = guardReasons(c, kb, checkDraft(body, email, kb));
  } catch {
    reasons = ['draft generation failed - write manually'];
  }

  const k = getKind(store, kind);
  const canAuto = k.autoSend && reasons.length === 0 && body !== '';
  let status: Draft['status'] = 'pending_review';
  if (canAuto) {
    if (isAuditSample(id)) { status = 'audit_pending'; reasons.push('held as quality audit sample'); }
    else {
      status = 'auto_sent'; k.autoSentCount++;
      store.state.outbox.push({ draftId: id, to: email.from, subject, body, auto: true, at: new Date().toISOString() });
    }
  }
  const draft: Draft = { ...base, subject, body, sources: kb?.sources ?? [], promptVersion: promptVersion(store, kind), status, reasons };
  store.state.drafts[id] = draft;
  store.save();
  return draft;
}
