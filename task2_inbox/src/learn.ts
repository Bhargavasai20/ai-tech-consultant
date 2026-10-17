import { config } from './config.ts';
import { type Llm } from './llm.ts';
import { PROMPTS } from './prompts.ts';
import { isUnchanged, similarity } from './similarity.ts';
import type { Store } from './store.ts';
import type { Category, Draft, KindState, Outcome } from './types.ts';

export function getKind(store: Store, kind: string): KindState {
  return (store.state.kinds[kind] ??= {
    kind, category: kind.split(':')[0] as Category, streak: 0, total: 0, autoSend: false,
    autoSentCount: 0, audits: [], demotions: 0, history: [], lastEvent: 'created',
  });
}

export function outcomeOf(sim: number): Outcome {
  return isUnchanged(sim) ? 'unchanged' : sim < 0.5 ? 'rewritten' : 'edited';
}

export function promote(store: Store, k: KindState): void {
  if (!k.autoSend && k.streak >= config.minStreak && !config.blockedCategories.includes(k.category)) {
    k.autoSend = true;
    k.lastEvent = `promoted to auto-send after ${k.streak} unchanged in a row`;
  }
}

export function demote(k: KindState, why: string): void {
  if (k.autoSend) k.demotions++;
  k.autoSend = false;
  k.streak = 0;           // must earn all 20 again
  k.audits = [];
  k.lastEvent = `demoted: ${why}`;
}

/** A human sent (or edited, or rewrote) a draft that was waiting for review. */
export async function recordHumanOutcome(store: Store, llm: Llm | null, draft: Draft, finalBody: string): Promise<Outcome> {
  const sim = similarity(draft.body, finalBody);
  const outcome = outcomeOf(sim);
  draft.final = finalBody;
  draft.similarity = Number(sim.toFixed(3));
  const wasAudit = draft.status === 'audit_pending';
  draft.status = outcome === 'unchanged' ? 'sent_unchanged' : outcome === 'edited' ? 'sent_edited' : 'rewritten';

  const k = getKind(store, draft.kind);
  k.total++;
  k.history = [...k.history, outcome === 'unchanged' ? 'u' as const : outcome === 'edited' ? 'e' as const : 'r' as const].slice(-200);
  store.state.outbox.push({ draftId: draft.id, to: store.state.emails[draft.emailId]?.from ?? '', subject: draft.subject, body: finalBody, auto: false, at: new Date().toISOString() });

  if (wasAudit) {
    k.audits = [...k.audits, outcome !== 'unchanged'].slice(-config.auditWindow);
    if (k.audits.filter(Boolean).length >= config.auditFailLimit) demote(k, `${config.auditFailLimit} of last ${k.audits.length} audited drafts needed edits`);
  }
  // Only drafts that were clean (no guard fired) count toward earning auto-send. A "we're checking" holding
  // reply approved unchanged proves nothing about answer quality.
  const flagged = draft.reasons.some((r) => !r.startsWith('held as quality audit'));
  if (outcome === 'unchanged') {
    if (!flagged) {
      k.streak++;
      if (!wasAudit) promote(store, k);
    }
  } else {
    k.streak = 0;
    if (k.autoSend && !wasAudit) demote(k, 'human edited a draft of an auto-send kind');
    store.state.exemplars.push({ kind: draft.kind, subject: draft.subject, reply: finalBody, at: new Date().toISOString() });
    if (llm) await learnRule(store, llm, draft, finalBody);
  }
  store.save();
  return outcome;
}

async function learnRule(store: Store, llm: Llm, draft: Draft, finalBody: string): Promise<void> {
  try {
    const r = await llm.complete({ system: PROMPTS.distill.system, model: config.classifyModel, maxTokens: 80,
      user: `AI DRAFT:\n${draft.body}\n\nHUMAN VERSION:\n${finalBody}` });
    const text = r.text.trim();
    if (!text || text === 'NONE' || text.length > 200) return;
    const mine = store.state.rules.filter((x) => x.kind === draft.kind && x.active);
    if (mine.some((x) => x.text.toLowerCase() === text.toLowerCase())) return;
    store.state.rules.push({ id: `r_${Date.now().toString(36)}_${store.state.rules.length}`, kind: draft.kind, text, active: true, addedAt: new Date().toISOString(), fromDraft: draft.id });
    const active = store.state.rules.filter((x) => x.kind === draft.kind && x.active);
    for (const old of active.slice(0, Math.max(0, active.length - config.maxActiveRules))) old.active = false;
  } catch { /* learning is best-effort; never block the human's send */ }
}

/** Undo: switch a learned rule off. Next drafts use the previous prompt version. */
export function revertRule(store: Store, id: string): boolean {
  const r = store.state.rules.find((x) => x.id === id);
  if (!r) return false;
  r.active = false;
  store.save();
  return true;
}

/** Customer replied angrily / asked to escalate after an auto-sent reply -> immediate demotion. */
export function recordCustomerSignal(store: Store, draftId: string, negative: boolean): void {
  const d = store.state.drafts[draftId];
  if (!d || !negative) return;
  demote(getKind(store, d.kind), 'customer reacted badly to an auto-sent reply');
  store.save();
}

/** First half vs second half unchanged-rate: the "are we getting better, not worse" number. */
export function trend(k: KindState): { early: number | null; late: number | null } {
  const h = k.history;
  if (h.length < 6) return { early: null, late: null };
  const mid = Math.floor(h.length / 2);
  const rate = (a: string[]) => a.filter((x) => x === 'u').length / a.length;
  return { early: Number(rate(h.slice(0, mid)).toFixed(2)), late: Number(rate(h.slice(mid)).toFixed(2)) };
}
