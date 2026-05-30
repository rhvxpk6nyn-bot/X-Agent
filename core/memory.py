"""Memory system — SQLite FTS5 + file-based, zero heavy deps."""

import json
import sqlite3
import threading
import time
from pathlib import Path

import yaml

from core.config import AGENT_HOME, config

MEMORY_DIR = AGENT_HOME / "memory"
HOT_DIR = MEMORY_DIR / "hot"
WARM_DIR = MEMORY_DIR / "warm"
COLD_DIR = MEMORY_DIR / "cold"
FTS_DB_PATH = AGENT_HOME / "fts.db"


_fts_local = threading.local()
_fts_write_lock = threading.Lock()

def _get_fts() -> sqlite3.Connection:
    db = getattr(_fts_local, "db", None)
    if db is None:
        db = sqlite3.connect(str(FTS_DB_PATH))
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(id, title, content, tags, tokenize='unicode61')")
        _fts_local.db = db
    return db


class Memory:
    def __init__(self, memory_id="", mtype="note", title="", content="",
                 tags=None, importance=0.5, created_at=None):
        self.id = memory_id or f"mem-{time.time_ns()}"
        self.type = mtype
        self.title = title
        self.content = content
        self.tags = tags or []
        self.importance = importance
        self.created_at = created_at or time.time()

    @property
    def score(self):
        mc = config.memory
        half_life = mc.decay_half_life_days * self.importance * 86400
        elapsed = time.time() - self.created_at
        return max(self.importance * (0.5 ** (elapsed / max(half_life, 1))), mc.decay_floor)

    def to_dict(self):
        return {"id": self.id, "type": self.type, "title": self.title,
                "content": self.content, "score": round(self.score, 3)}

    @classmethod
    def from_file(cls, path: Path):
        text = path.read_text()
        fm, body = {}, text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
        return cls(
            memory_id=fm.get("id", path.stem), mtype=fm.get("type", "note"),
            title=fm.get("title", path.stem), content=body,
            tags=fm.get("tags", []), importance=fm.get("importance", 0.5),
            created_at=fm.get("created_at", path.stat().st_mtime),
        )


class MemoryStore:
    def __init__(self):
        for d in [HOT_DIR, WARM_DIR, COLD_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def add(self, mem: Memory, tier="warm"):
        dest = {"hot": HOT_DIR, "warm": WARM_DIR, "cold": COLD_DIR}[tier]
        path = dest / f"{mem.id}.md"
        path.write_text(f"---\n{yaml.dump({'id':mem.id,'type':mem.type,'title':mem.title,'tags':mem.tags,'importance':mem.importance,'created_at':mem.created_at})}---\n\n{mem.content}")
        with _fts_write_lock:
            db = _get_fts()
            # FTS5 has no UNIQUE constraint, so INSERT OR REPLACE would duplicate.
            # Delete any existing row for this id first to keep it idempotent.
            db.execute("DELETE FROM mem_fts WHERE id = ?", (mem.id,))
            db.execute("INSERT INTO mem_fts(id, title, content, tags) VALUES(?,?,?,?)",
                       (mem.id, mem.title, mem.content, " ".join(mem.tags)))
            db.commit()

    def get_hot(self) -> list[Memory]:
        return sorted([Memory.from_file(p) for p in HOT_DIR.glob("*.md")],
                      key=lambda m: m.importance, reverse=True)[:5]

    def search(self, query: str, top_k: int = 5) -> list[Memory]:
        db = _get_fts()
        # Build prefix query: each word gets a * suffix for partial matching
        # e.g. "python progr" -> "python* progr*"
        words = query.strip().split()
        safe_words = []
        for w in words:
            # Strip non-alphanumeric (keep only FTS5-safe chars)
            clean = "".join(c for c in w if c.isalnum() or c in "-_")
            if clean:
                safe_words.append(f"{clean}*")
        if not safe_words:
            return []
        fts_query = " ".join(safe_words)
        try:
            rows = db.execute(
                "SELECT id, rank FROM mem_fts WHERE mem_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, top_k * 2)
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback: un-prefixed OR query
            try:
                simple_query = " OR ".join(safe_words).replace("*", "")
                rows = db.execute(
                    "SELECT id, rank FROM mem_fts WHERE mem_fts MATCH ? ORDER BY rank LIMIT ?",
                    (simple_query, top_k * 2)
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        scored = []
        for mid, rank in rows:
            for root in [HOT_DIR, WARM_DIR, COLD_DIR]:
                p = Path(root) / f"{mid}.md"
                if p.exists():
                    mem = Memory.from_file(p)
                    # FTS5 rank is negative; more negative = more relevant.
                    # Combine relevance with decay score and a small tag boost.
                    relevance = -rank if rank is not None else 1.0
                    final = relevance * mem.score * (1 + 0.1 * len(mem.tags))
                    scored.append((final, mem))
                    break
        scored.sort(key=lambda t: t[0], reverse=True)
        return [m for _, m in scored[:top_k]]


store = MemoryStore()
