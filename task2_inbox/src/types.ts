export const CATEGORIES = [
  'how_to', 'new_project', 'refund', 'complaint', 'quote', 'follow_up',
  'billing', 'account_access', 'feature_request', 'spam', 'other',
] as const;
export type Category = (typeof CATEGORIES)[number];
export type Sentiment = 'positive' | 'neutral' | 'negative' | 'angry';

export interface InboundEmail {
  id: string;
  from: string;
  subject: string;
  body: string;
  receivedAt: string;
}

export interface Classification {
  category: Category;
  topic: string;          // canonical short slug, e.g. "change-plan-price"
  confidence: number;     // 0..1
  sentiment: Sentiment;
  question: string;       // the core ask, rewritten as one question for the Knowledge Brain
  containsSensitive: boolean; // card numbers, passwords, ID numbers...
}

export interface KbSource { url: string; title: string }
export interface KbAnswer { answered: boolean; answer: string; sources: KbSource[]; unavailable?: boolean }

export type DraftStatus =
  | 'pending_review'   // waiting for a human
  | 'audit_pending'    // would have auto-sent, held as a quality sample
  | 'auto_sent'        // went out without a human
  | 'sent_unchanged' | 'sent_edited' | 'rewritten'
  | 'no_reply_needed'; // spam

export interface Draft {
  id: string;
  emailId: string;
  kind: string;          // "category:topic" - what "same kind" means
  subject: string;
  body: string;
  sources: KbSource[];
  promptVersion: string; // e.g. draft@1+r2  (prompt version + active learned rules)
  status: DraftStatus;
  reasons: string[];     // why a human must look (guards that fired)
  createdAt: string;
  final?: string;
  similarity?: number;
}

export type Outcome = 'unchanged' | 'edited' | 'rewritten';

export interface KindState {
  kind: string;
  category: Category;
  streak: number;          // consecutive unchanged sends
  total: number;
  autoSend: boolean;
  autoSentCount: number;
  audits: boolean[];       // last audits, true = human changed it
  demotions: number;
  history: ('u' | 'e' | 'r')[]; // outcome log (capped) for the "is it improving" metric
  lastEvent: string;
}

export interface Rule { id: string; kind: string; text: string; active: boolean; addedAt: string; fromDraft: string }
export interface Exemplar { kind: string; subject: string; reply: string; at: string }

export interface State {
  emails: Record<string, InboundEmail>;
  drafts: Record<string, Draft>;
  kinds: Record<string, KindState>;
  rules: Rule[];
  exemplars: Exemplar[];
  topics: Record<string, string[]>;
  outbox: { draftId: string; to: string; subject: string; body: string; auto: boolean; at: string }[];
}
