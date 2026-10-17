from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages(
  url TEXT PRIMARY KEY, title TEXT, section TEXT, lastmod TEXT, content_hash TEXT,
  status TEXT NOT NULL DEFAULT 'active',      -- active | removed
  kind TEXT NOT NULL DEFAULT 'web',           -- web | expert
  fetched_at TEXT);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL,
  kind TEXT NOT NULL,                         -- text | image | expert
  text TEXT NOT NULL, image_url TEXT);
CREATE INDEX IF NOT EXISTS chunks_url ON chunks(url);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS images(sha TEXT PRIMARY KEY, caption TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS queue(
  url TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, lastmod TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, norm TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',        -- open | answered
  reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  answer TEXT, expert TEXT, answered_at TEXT);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT, helpful INTEGER,
  comment TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT, purpose TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, usd REAL, ms INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


class DB:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur

    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()
