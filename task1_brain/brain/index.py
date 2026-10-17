"""Memory: chunks in SQLite + FTS5 (BM25). Removal is a hard delete, so removed pages cannot leak."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .db import DB

STOP = set("a an the and or of to in on for with is are was were be do does did how what when where why which "
           "can could should would i my me we our you your it its this that these those at by from as if "
           "there any about into not no yes get set make use using".split())


def terms(q: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", q.lower()) if t not in STOP and len(t) > 1]


def chunk_text(text: str, max_words: int = 160) -> list[str]:
    """Paragraph-aware chunks; a short heading is glued to the paragraph after it."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    n = 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > max_words:
            chunks.append("\n".join(cur))
            cur, n = (cur[-1:] if len(cur[-1].split()) < 12 else []), 0  # carry heading over
            n = sum(len(c.split()) for c in cur)
        cur.append(p)
        n += w
    if cur:
        chunks.append("\n".join(cur))
    return chunks


@dataclass
class Hit:
    chunk_id: int
    url: str
    title: str
    kind: str
    text: str
    image_url: str | None
    score: float


class Index:
    def __init__(self, db: DB) -> None:
        self.db = db

    def replace_page(self, *, url: str, title: str, section: str, lastmod: str | None, content_hash: str,
                     kind: str, text_chunks: list[str], image_chunks: list[tuple[str, str]]) -> int:
        """Atomically swap a page's chunks. image_chunks = [(image_url, caption_text)]."""
        c = self.db.conn
        try:
            self._delete_chunks(url)
            c.execute("""INSERT INTO pages(url,title,section,lastmod,content_hash,status,kind,fetched_at)
                         VALUES(?,?,?,?,?,'active',?,datetime('now'))
                         ON CONFLICT(url) DO UPDATE SET title=excluded.title, section=excluded.section,
                           lastmod=excluded.lastmod, content_hash=excluded.content_hash, status='active',
                           kind=excluded.kind, fetched_at=excluded.fetched_at""",
                      (url, title, section, lastmod, content_hash, kind))
            n = 0
            for t in text_chunks:
                self._add_chunk(url, "expert" if kind == "expert" else "text", f"{title}\n{t}", None)
                n += 1
            for img_url, cap in image_chunks:
                self._add_chunk(url, "image", f"{title} (screenshot)\n{cap}", img_url)
                n += 1
            c.commit()
            return n
        except Exception:
            c.rollback()
            raise

    def _add_chunk(self, url: str, kind: str, text: str, image_url: str | None) -> None:
        cur = self.db.conn.execute("INSERT INTO chunks(url,kind,text,image_url) VALUES(?,?,?,?)",
                                   (url, kind, text, image_url))
        self.db.conn.execute("INSERT INTO chunks_fts(rowid,text) VALUES(?,?)", (cur.lastrowid, text))

    def _delete_chunks(self, url: str) -> None:
        ids = [r["id"] for r in self.db.conn.execute("SELECT id FROM chunks WHERE url=?", (url,))]
        for i in ids:
            self.db.conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
        self.db.conn.execute("DELETE FROM chunks WHERE url=?", (url,))

    def remove_page(self, url: str) -> None:
        self._delete_chunks(url)
        self.db.conn.execute("UPDATE pages SET status='removed' WHERE url=?", (url,))
        self.db.conn.commit()

    def search(self, query: str, k: int = 6) -> list[Hit]:
        ts = terms(query)
        if not ts:
            return []
        match = " OR ".join(f'"{t}"' for t in ts)
        rows = self.db.query(
            """SELECT c.id,c.url,c.kind,c.text,c.image_url,p.title,bm25(chunks_fts) AS s
               FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid JOIN pages p ON p.url=c.url
               WHERE chunks_fts MATCH ? AND p.status='active' ORDER BY s LIMIT ?""", (match, k))
        return [Hit(r["id"], r["url"], r["title"], r["kind"], r["text"], r["image_url"], -r["s"]) for r in rows]

    def stats(self) -> dict:
        q = lambda s: self.db.query(s)[0][0]  # noqa: E731
        return {"pages_active": q("SELECT count(*) FROM pages WHERE status='active'"),
                "pages_removed": q("SELECT count(*) FROM pages WHERE status='removed'"),
                "chunks": q("SELECT count(*) FROM chunks"),
                "images_captioned": q("SELECT count(*) FROM images"),
                "open_tasks": q("SELECT count(*) FROM tasks WHERE status='open'")}
