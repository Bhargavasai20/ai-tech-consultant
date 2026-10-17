"""Long transcripts: overlapping windows on speaker-turn boundaries (never cut a sentence in half)."""
from __future__ import annotations


def windows(transcript: str, max_words: int = 2500, overlap_words: int = 200) -> list[str]:
    turns = [t for t in transcript.splitlines() if t.strip()]
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for t in turns:
        w = len(t.split())
        if cur and n + w > max_words:
            out.append("\n".join(cur))
            keep: list[str] = []
            k = 0
            for prev in reversed(cur):          # carry the last ~overlap_words into the next window
                k += len(prev.split())
                if k > overlap_words:
                    break
                keep.insert(0, prev)
            cur, n = keep, sum(len(x.split()) for x in keep)
        cur.append(t)
        n += w
    if cur:
        out.append("\n".join(cur))
    return out or [""]
