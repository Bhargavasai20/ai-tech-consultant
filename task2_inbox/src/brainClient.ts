import { config } from './config.ts';
import { withRetry } from './llm.ts';
import type { KbAnswer } from './types.ts';

export interface Brain { ask(question: string): Promise<KbAnswer> }

/** Calls Task 1 over HTTP only. If the Brain is down we degrade (flagged) instead of inventing facts. */
export class HttpBrain implements Brain {
  async ask(question: string): Promise<KbAnswer> {
    try {
      return await withRetry(async () => {
        const res = await fetch(`${config.brainUrl}/v1/ask`, {
          method: 'POST',
          signal: AbortSignal.timeout(20_000),
          headers: { 'content-type': 'application/json', ...(config.brainKey ? { 'x-api-key': config.brainKey } : {}) },
          body: JSON.stringify({ question }),
        });
        if (!res.ok) throw new Error(`brain ${res.status}`);
        const j = (await res.json()) as { answered: boolean; answer: string; sources: { url: string; title: string }[] };
        return { answered: j.answered, answer: j.answer, sources: j.sources.map((s) => ({ url: s.url, title: s.title })) };
      }, 2);
    } catch {
      return { answered: false, answer: '', sources: [], unavailable: true };
    }
  }
}

/** Test double. */
export class FakeBrain implements Brain {
  private reply: KbAnswer;
  constructor(reply?: KbAnswer) {
    this.reply = reply ?? { answered: true, answer: 'Open Admin > Plans and edit the price.', sources: [{ url: 'https://help.example.com/a', title: 'Change pricing' }] };
  }
  async ask(): Promise<KbAnswer> { return this.reply; }
}
