import { config } from './config.ts';

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

export function levenshteinRatio(a: string, b: string): number {
  if (a === b) return 1;
  if (!a.length || !b.length) return 0;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min((prev[j] ?? 0) + 1, (cur[j - 1] ?? 0) + 1, (prev[j - 1] ?? 0) + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return 1 - (prev[b.length] ?? 0) / Math.max(a.length, b.length);
}

/** Similarity of draft vs what the human actually sent, ignoring case, punctuation and whitespace. */
export function similarity(draft: string, final: string): number {
  return levenshteinRatio(norm(draft), norm(final));
}

export function isUnchanged(sim: number): boolean { return sim >= config.unchangedSimilarity; }
