"""SQLite storage (one file, WAL mode). One connection per thread."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import settings

DB_PATH = Path(settings.data_dir) / "ebook.sqlite3"
_local = threading.local()
_rev_lock = threading.Lock()
_last_rev = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, title TEXT, title_si TEXT, filename TEXT, page_count INT DEFAULT 0,
  status TEXT, stage TEXT, stage_done INT DEFAULT 0, stage_total INT DEFAULT 0,
  error TEXT, brief TEXT, page_sizes TEXT, parser TEXT,
  provider TEXT, model TEXT, prompt_tokens INT DEFAULT 0, output_tokens INT DEFAULT 0, llm_calls INT DEFAULT 0,
  translatable INT DEFAULT 0, translated INT DEFAULT 0, failed INT DEFAULT 0,
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS blocks(
  doc_id TEXT, seq INT, type TEXT, level INT, page INT, regions TEXT, image TEXT,
  source TEXT, source_table TEXT, table_mode TEXT,
  translated TEXT, translated_table TEXT, status TEXT, qa TEXT, section INT, rev INT DEFAULT 0,
  PRIMARY KEY(doc_id, seq)
);
CREATE INDEX IF NOT EXISTS blocks_rev ON blocks(doc_id, rev);
CREATE TABLE IF NOT EXISTS sections(
  doc_id TEXT, idx INT, title TEXT, start_seq INT, end_seq INT, PRIMARY KEY(doc_id, idx)
);
CREATE TABLE IF NOT EXISTS chunks(
  doc_id TEXT, idx INT, start_seq INT, end_seq INT, summary TEXT, PRIMARY KEY(doc_id, idx)
);
CREATE TABLE IF NOT EXISTS glossary(
  doc_id TEXT, key TEXT, term TEXT, rendering TEXT, policy TEXT, kind TEXT,
  count INT DEFAULT 1, locked INT DEFAULT 0, PRIMARY KEY(doc_id, key)
);
CREATE TABLE IF NOT EXISTS positions(doc_id TEXT PRIMARY KEY, seq INT, updated_at REAL);
CREATE TABLE IF NOT EXISTS notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, seq INT, color TEXT, quote TEXT, body TEXT,
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS notes_doc ON notes(doc_id, seq);
CREATE TABLE IF NOT EXISTS audio(
  doc_id TEXT, seq INT, voice TEXT, hash TEXT, file TEXT, created_at REAL, PRIMARY KEY(doc_id, seq, voice)
);
CREATE TABLE IF NOT EXISTS lookups(key TEXT PRIMARY KEY, data TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS words(
  id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT, lemma TEXT UNIQUE, pos TEXT, ipa TEXT,
  meaning_en TEXT, meaning_si TEXT, in_context_si TEXT, examples TEXT, synonyms TEXT, level TEXT,
  context TEXT, doc_id TEXT, seq INT, created_at REAL,
  due_at REAL, interval_days REAL DEFAULT 0, ease REAL DEFAULT 2.5, reps INT DEFAULT 0, lapses INT DEFAULT 0,
  last_review REAL, audio_file TEXT, audio_hash TEXT
);
CREATE TABLE IF NOT EXISTS quiz_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, word_id INT, kind TEXT, question TEXT, options TEXT,
  explain_si TEXT, audio_text TEXT, uses INT DEFAULT 0, last_used REAL, created_at REAL
);
CREATE INDEX IF NOT EXISTS quiz_word ON quiz_items(word_id);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, word_id INT, kind TEXT, correct INT, at REAL);
CREATE TABLE IF NOT EXISTS usage_log(
  at REAL, doc_id TEXT, purpose TEXT, model TEXT, prompt_tokens INT, output_tokens INT,
  cached_tokens INT, thought_tokens INT, batch INT, cost REAL
);
"""

# columns added after the first release: (table, column, type)
MIGRATIONS = [
    ("documents", "active_run", "TEXT"),
    ("documents", "auto_translate", "INT DEFAULT 1"),
    ("usage_log", "audio_seconds", "REAL DEFAULT 0"),
    ("usage_log", "estimate_known", "INT DEFAULT 1"),
    ("words", "source_language", "TEXT DEFAULT 'en'"),
    ("words", "target_language", "TEXT DEFAULT 'si'"),
    ("documents", "cached_tokens", "INT DEFAULT 0"),
    ("documents", "thought_tokens", "INT DEFAULT 0"),
    ("documents", "cost_usd", "REAL DEFAULT 0"),
    ("documents", "mode", "TEXT DEFAULT 'standard'"),
    ("documents", "batch_jobs", "TEXT"),
]


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


def init() -> None:
    c = conn()
    c.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    from .beta_storage import init_beta
    init_beta(c)
    from .config import PRICES
    known = ["mock", *PRICES]
    c.execute(f"UPDATE usage_log SET estimate_known=CASE WHEN model IN ({','.join('?' for _ in known)}) THEN 1 ELSE 0 END", known)


def next_rev() -> int:
    """Monotonic change counter; the reader polls for blocks with rev > last seen."""
    global _last_rev
    with _rev_lock:
        _last_rev = max(_last_rev + 1, int(time.time() * 1000))
        return _last_rev


def q(sql: str, *args) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, *args) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def ex(sql: str, *args) -> sqlite3.Cursor:
    return conn().execute(sql, args)


def tx():
    """Usage: with db.tx(): ..."""
    return _Tx()


class _Tx:
    def __enter__(self):
        conn().execute("BEGIN IMMEDIATE")
        return conn()

    def __exit__(self, et, ev, tb):
        conn().execute("ROLLBACK" if et else "COMMIT")
        return False


def update_doc(doc_id: str, **fields) -> None:
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    ex(f"UPDATE documents SET {cols} WHERE id=?", *fields.values(), doc_id)


def cost_of(res) -> float:
    from .config import price_for
    p = price_for(res.model or "")
    if not p:
        return 0.0
    pin, pout, pcache = p
    cached = min(res.cached_tokens, res.prompt_tokens)
    usd = ((res.prompt_tokens - cached) * pin + cached * pcache + res.output_tokens * pout) / 1e6
    return usd * (0.5 if res.batch else 1.0)


def add_usage(doc_id: str | None, res, purpose: str = "") -> None:
    """Record one LLM call (an LLMResult) against a document and in the usage log."""
    cost = cost_of(res)
    if doc_id:
        ex("UPDATE documents SET prompt_tokens=prompt_tokens+?, output_tokens=output_tokens+?, llm_calls=llm_calls+1, "
           "cached_tokens=cached_tokens+?, thought_tokens=thought_tokens+?, cost_usd=cost_usd+? WHERE id=?",
           res.prompt_tokens, res.output_tokens, res.cached_tokens, res.thought_tokens, cost, doc_id)
    ex("INSERT INTO usage_log(at,doc_id,purpose,model,prompt_tokens,output_tokens,cached_tokens,thought_tokens,batch,cost,estimate_known) "
       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", time.time(), doc_id, purpose, res.model,
       res.prompt_tokens, res.output_tokens, res.cached_tokens, res.thought_tokens, 1 if res.batch else 0, cost,
       int(res.model == 'mock' or price_for_model(res.model)))


def price_for_model(model: str) -> bool:
    from .config import price_for
    return price_for(model) is not None


def get_doc(doc_id: str) -> dict | None:
    r = q1("SELECT * FROM documents WHERE id=?", doc_id)
    return dict(r) if r else None


def block_row_to_api(r: sqlite3.Row) -> dict:
    d = {
        "seq": r["seq"], "type": r["type"], "level": r["level"], "page": r["page"],
        "regions": json.loads(r["regions"] or "[]"), "image": r["image"],
        "source": r["source"], "status": r["status"], "rev": r["rev"],
        "translated": r["translated"], "table_mode": r["table_mode"],
    }
    if r["source_table"]:
        d["table"] = json.loads(r["source_table"])
    if r["translated_table"]:
        d["table_si"] = json.loads(r["translated_table"])
        d["translated_table"] = d["table_si"]
    if r["qa"]:
        d["qa"] = json.loads(r["qa"])
    return d
