import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { State } from './types.ts';

const empty = (): State => ({ emails: {}, drafts: {}, kinds: {}, rules: [], exemplars: [], topics: {}, outbox: [] });

/** Tiny JSON-file store. path=null keeps everything in memory (tests). Writes are atomic (temp + rename). */
export class Store {
  state: State;
  private path: string | null;
  constructor(path: string | null) {
    this.path = path;
    this.state = path && existsSync(path) ? { ...empty(), ...(JSON.parse(readFileSync(path, 'utf8')) as State) } : empty();
  }
  save(): void {
    if (!this.path) return;
    mkdirSync(dirname(this.path), { recursive: true });
    const tmp = `${this.path}.tmp`;
    writeFileSync(tmp, JSON.stringify(this.state, null, 2));
    renameSync(tmp, this.path);
  }
}
