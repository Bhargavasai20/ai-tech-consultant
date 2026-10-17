import { config } from './config.ts';
import { type Llm, parseJson } from './llm.ts';
import { PROMPTS } from './prompts.ts';
import type { Store } from './store.ts';
import { CATEGORIES, type Category, type Classification, type InboundEmail, type Sentiment } from './types.ts';

const SENTIMENTS: Sentiment[] = ['positive', 'neutral', 'negative', 'angry'];
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').split('-').slice(0, 4).join('-') || 'general';

/** "Same kind" = same category AND a near-identical topic (word overlap >= 0.5 with a known topic). */
export function canonicalTopic(store: Store, category: Category, topic: string): string {
  const t = slug(topic);
  const known = (store.state.topics[category] ??= []);
  const words = new Set(t.split('-'));
  for (const k of known) {
    const kw = new Set(k.split('-'));
    const inter = [...words].filter((w) => kw.has(w)).length;
    if (inter / new Set([...words, ...kw]).size >= 0.5) return k;
  }
  known.push(t);
  return t;
}

export function validate(raw: unknown): Omit<Classification, 'topic'> & { topic: string } {
  const o = raw as Record<string, unknown>;
  if (!CATEGORIES.includes(o.category as Category)) throw new Error('bad category');
  const confidence = Number(o.confidence);
  if (!(confidence >= 0 && confidence <= 1)) throw new Error('bad confidence');
  return {
    category: o.category as Category,
    topic: String(o.topic ?? 'general'),
    confidence,
    sentiment: SENTIMENTS.includes(o.sentiment as Sentiment) ? (o.sentiment as Sentiment) : 'neutral',
    question: String(o.question ?? '').slice(0, 500),
    containsSensitive: Boolean(o.containsSensitive),
  };
}

export async function classify(llm: Llm, store: Store, email: InboundEmail): Promise<Classification> {
  const user = `<email>\nFrom: ${email.from}\nSubject: ${email.subject}\n\n${email.body.slice(0, 6000)}\n</email>`;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await llm.complete({ system: PROMPTS.classify.system, user: attempt ? `${user}\n\nReply with valid JSON only.` : user, model: config.classifyModel, maxTokens: 300 });
      const v = validate(parseJson(r.text));
      return { ...v, topic: canonicalTopic(store, v.category, v.topic) };
    } catch { /* retry once, then fall through */ }
  }
  // Safe fallback: confidence 0 means a human always reviews it.
  return { category: 'other', topic: 'unclassified', confidence: 0, sentiment: 'neutral', question: '', containsSensitive: false };
}
