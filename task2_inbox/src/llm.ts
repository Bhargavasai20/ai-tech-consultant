import { config } from './config.ts';

export interface LlmRequest { system: string; user: string; model: string; maxTokens?: number }
export interface LlmResponse { text: string; inputTokens: number; outputTokens: number }
export interface Llm { complete(req: LlmRequest): Promise<LlmResponse> }

export async function withRetry<T>(fn: () => Promise<T>, tries = 3, baseMs = 500): Promise<T> {
  let last: unknown;
  for (let i = 0; i < tries; i++) {
    try { return await fn(); } catch (e) {
      last = e;
      if (i < tries - 1) await new Promise((r) => setTimeout(r, baseMs * 2 ** i));
    }
  }
  throw last;
}

export class AnthropicLlm implements Llm {
  async complete(req: LlmRequest): Promise<LlmResponse> {
    return withRetry(async () => {
      const res = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        signal: AbortSignal.timeout(60_000),
        headers: {
          'content-type': 'application/json',
          'x-api-key': config.anthropicKey,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({
          model: req.model, max_tokens: req.maxTokens ?? 700, system: req.system,
          messages: [{ role: 'user', content: req.user }],
        }),
      });
      if (!res.ok) throw new Error(`anthropic ${res.status}`);
      const j = (await res.json()) as {
        content: { type: string; text?: string }[]; usage: { input_tokens: number; output_tokens: number };
      };
      return {
        text: j.content.filter((b) => b.type === 'text').map((b) => b.text ?? '').join(''),
        inputTokens: j.usage.input_tokens, outputTokens: j.usage.output_tokens,
      };
    });
  }
}

/** Offline stand-in so the whole app, tests and demo run without a key. NOT used for real eval numbers. */
export class MockLlm implements Llm {
  calls = 0;
  async complete(req: LlmRequest): Promise<LlmResponse> {
    this.calls++;
    let text: string;
    if (req.system.startsWith('CLASSIFY')) text = JSON.stringify(mockClassify(req.user));
    else if (req.system.startsWith('DISTILL')) text = 'Always link the relevant help article.';
    else text = JSON.stringify(mockDraft(req.user));
    return { text, inputTokens: Math.ceil(req.user.length / 4), outputTokens: Math.ceil(text.length / 4) };
  }
}

const RULES: [RegExp, string, string][] = [
  [/ignore (all |previous )?instructions|viagra|crypto giveaway|you have won/i, 'spam', 'spam'],
  [/refund|money back|charged twice|chargeback/i, 'refund', 'refund-request'],
  [/unacceptable|terrible|worst|furious|cancel everything|disappointed/i, 'complaint', 'service-complaint'],
  [/quote|how much would|estimate|pricing for a custom/i, 'quote', 'custom-quote'],
  [/new (website|project|app)|build (us|me) a|redesign/i, 'new_project', 'new-project'],
  [/any update|following up|checking in|still waiting|status of/i, 'follow_up', 'status-follow-up'],
  [/invoice|billing|receipt|payment method/i, 'billing', 'invoice-request'],
  [/password|log ?in|locked out|2fa|can't access/i, 'account_access', 'login-help'],
  [/would be great if|feature request|can you add|wish/i, 'feature_request', 'feature-idea'],
  [/how (do|can) i|where (do|can) i|how to|is it possible to/i, 'how_to', 'how-to-setting'],
];

function mockClassify(user: string) {
  const body = user.replace(/<[^>]+>/g, ' ');
  for (const [re, category, topic] of RULES) {
    if (re.test(body)) {
      return {
        category, topic, confidence: 0.9,
        sentiment: category === 'complaint' ? 'angry' : 'neutral',
        question: category === 'how_to' ? body.trim().split(/[.?!]/)[0] + '?' : '',
        containsSensitive: /\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b/.test(body),
      };
    }
  }
  return { category: 'other', topic: 'general', confidence: 0.5, sentiment: 'neutral', question: '', containsSensitive: false };
}

function mockDraft(user: string) {
  const kb = /<knowledge_base>([\s\S]*?)<\/knowledge_base>/.exec(user)?.[1]?.trim() ?? '';
  const answer = kb && !kb.startsWith('(none') ? kb.split('\n')[0] : "I'm checking this with the team and will come back to you shortly.";
  return { subject: 'Re: your message', body: `Hi,\n\nThanks for getting in touch. ${answer}\n\nThe team` };
}

export function makeLlm(): Llm { return config.mock ? new MockLlm() : new AnthropicLlm(); }

export function parseJson<T>(text: string): T {
  const m = /\{[\s\S]*\}/.exec(text);
  if (!m) throw new Error('no JSON in model reply');
  return JSON.parse(m[0]) as T;
}
