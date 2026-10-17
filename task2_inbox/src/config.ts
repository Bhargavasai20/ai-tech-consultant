import type { Category } from './types.ts';

const env = process.env;
export const config = {
  brainUrl: env.BRAIN_URL ?? 'http://localhost:8001',
  brainKey: env.BRAIN_API_KEY ?? '',
  anthropicKey: env.ANTHROPIC_API_KEY ?? '',
  classifyModel: env.INBOX_CLASSIFY_MODEL ?? 'claude-haiku-5-5',
  draftModel: env.INBOX_DRAFT_MODEL ?? 'claude-sonnet-5-5',
  mock: env.INBOX_MOCK === '1' || !env.ANTHROPIC_API_KEY,
  dataFile: env.INBOX_DATA ?? 'data/state.json',
  companyName: env.COMPANY_NAME ?? 'Acme Software',
  companyDomains: (env.COMPANY_DOMAINS ?? 'acme.example').split(','),
  /** "unchanged" = normalised text is the same, or >= this similarity (typo / whitespace fixes only). */
  unchangedSimilarity: Number(env.INBOX_UNCHANGED_SIM ?? 0.98),
  /** drafts of one kind sent with no change, in a row, before it may go out alone. */
  minStreak: Number(env.INBOX_MIN_STREAK ?? 20),
  minConfidence: 0.8,
  /** money / commitments / feelings: always a human. */
  blockedCategories: (env.INBOX_BLOCKED ?? 'complaint,refund,quote,new_project,spam').split(',') as Category[],
  /** share of would-be auto-sends held back as a quality sample (deterministic by draft id). */
  auditRate: Number(env.INBOX_AUDIT_RATE ?? 0.1),
  /** demote when this many of the last `auditWindow` audits were changed by a human. */
  auditWindow: 10,
  auditFailLimit: 2,
  maxActiveRules: 5,
  maxExemplarsPerKind: 3,
  port: Number(env.PORT ?? 8002),
} as const;
