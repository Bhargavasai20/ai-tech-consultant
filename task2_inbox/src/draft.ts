import { config } from './config.ts';
import { type Llm, parseJson } from './llm.ts';
import { PROMPTS } from './prompts.ts';
import type { Store } from './store.ts';
import type { Classification, InboundEmail, KbAnswer } from './types.ts';

export function activeRules(store: Store, kind: string) {
  return store.state.rules.filter((r) => r.kind === kind && r.active);
}

export function promptVersion(store: Store, kind: string): string {
  const n = activeRules(store, kind).length;
  return `${PROMPTS.draft.version}${n ? `+r${n}` : ''}`;
}

export function buildDraftPrompt(store: Store, kind: string, email: InboundEmail, kb: KbAnswer | null): string {
  const rules = activeRules(store, kind).map((r) => `- ${r.text}`).join('\n') || '(none yet)';
  const examples = store.state.exemplars.filter((e) => e.kind === kind).slice(-config.maxExemplarsPerKind)
    .map((e) => `Subject: ${e.subject}\n${e.reply}`).join('\n---\n') || '(none yet)';
  const facts = kb?.answered
    ? `${kb.answer}\nSources: ${kb.sources.map((s) => s.url).join(', ')}`
    : '(none - the knowledge base had no answer)';
  return `<style_rules>\n${rules}\n</style_rules>\n<approved_examples>\n${examples}\n</approved_examples>\n` +
    `<knowledge_base>\n${facts}\n</knowledge_base>\n<email>\nFrom: ${email.from}\nSubject: ${email.subject}\n\n${email.body.slice(0, 6000)}\n</email>`;
}

export async function writeDraft(llm: Llm, store: Store, kind: string, email: InboundEmail, c: Classification, kb: KbAnswer | null) {
  const system = PROMPTS.draft.system.replace('${company}', config.companyName);
  const r = await llm.complete({ system, user: buildDraftPrompt(store, kind, email, kb), model: config.draftModel, maxTokens: 700 });
  const j = parseJson<{ subject?: string; body?: string }>(r.text);
  if (!j.body) throw new Error('draft had no body');
  return { subject: j.subject ?? `Re: ${email.subject}`, body: j.body, tokens: r.inputTokens + r.outputTokens, _c: c };
}

/** Deterministic checks on the draft itself. Anything returned forces human review. */
export function checkDraft(body: string, email: InboundEmail, kb: KbAnswer | null): string[] {
  const reasons: string[] = [];
  const allowed = new Set([...(kb?.sources.map((s) => s.url) ?? [])]);
  for (const raw of body.match(/https?:\/\/[^\s)>\]]+/g) ?? []) {
    const url = raw.replace(/[.,;:!?]+$/, '');
    const host = new URL(url).hostname;
    if (!allowed.has(url) && !config.companyDomains.some((d) => host === d || host.endsWith(`.${d}`))) reasons.push(`link not from knowledge base: ${url}`);
  }
  const grounded = `${kb?.answer ?? ''} ${email.body}`;
  for (const amt of body.match(/[$₹€£]\s?\d[\d,]*(?:\.\d+)?/g) ?? []) {
    if (!grounded.includes(amt)) reasons.push(`amount not in knowledge base: ${amt}`);
  }
  return reasons;
}
