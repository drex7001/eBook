"""Pass 1: read the document in English -> chunk summaries, glossary, document brief."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import db
from ..llm import LLMError
from . import prompts
from .common import Paused, TRANSLATABLE_TEXT

log = logging.getLogger(__name__)


def build_chunks(doc_id: str, max_chars: int) -> None:
    rows = db.q("SELECT seq, type, source, table_mode FROM blocks WHERE doc_id=? ORDER BY seq", doc_id)
    starts = {r["start_seq"] for r in db.q("SELECT start_seq FROM sections WHERE doc_id=?", doc_id)}
    chunks: list[list[int]] = []
    cur_len = 0
    for r in rows:
        textual = r["type"] in TRANSLATABLE_TEXT or (r["type"] == "table" and r["table_mode"] == "html")
        if not textual:
            continue
        n = min(len(r["source"] or ""), 1500)
        if chunks and (cur_len + n > max_chars or (r["seq"] in starts and cur_len > 0.4 * max_chars)):
            chunks.append([r["seq"], r["seq"]])
            cur_len = 0
        elif not chunks:
            chunks.append([r["seq"], r["seq"]])
        chunks[-1][1] = r["seq"]
        cur_len += n
    if not chunks:
        return
    last_seq = rows[-1]["seq"]
    with db.tx() as c:
        c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        for i, (s, _e) in enumerate(chunks):
            end = chunks[i + 1][0] - 1 if i + 1 < len(chunks) else last_seq
            c.execute("INSERT INTO chunks(doc_id, idx, start_seq, end_seq) VALUES(?,?,?,?)", (doc_id, i, s if i else 0, end))


def chunk_text(doc_id: str, start: int, end: int) -> str:
    rows = db.q("SELECT type, source, table_mode FROM blocks WHERE doc_id=? AND seq BETWEEN ? AND ? ORDER BY seq",
                doc_id, start, end)
    out = []
    for r in rows:
        if r["type"] in TRANSLATABLE_TEXT:
            out.append(("# " if r["type"] == "heading" else "") + (r["source"] or ""))
        elif r["type"] == "table" and r["source"]:
            out.append("[table] " + r["source"][:800])
    return "\n\n".join(out)


def merge_terms(doc_id: str, terms: list) -> None:
    for t in terms or []:
        if not isinstance(t, dict):
            continue
        term = str(t.get("term", "")).strip()
        if not term or len(term) > 80:
            continue
        policy = t.get("policy") if t.get("policy") in prompts.POLICIES else "keep_en"
        rendering = str(t.get("rendering") or term).strip() or term
        if policy == "keep_en":
            rendering = term
        key = term.lower()
        row = db.q1("SELECT key FROM glossary WHERE doc_id=? AND key=?", doc_id, key)
        if row:
            db.ex("UPDATE glossary SET count=count+1 WHERE doc_id=? AND key=?", doc_id, key)
        else:
            db.ex("INSERT INTO glossary(doc_id, key, term, rendering, policy, kind, count) VALUES(?,?,?,?,?,?,1)",
                  doc_id, key, term, rendering, policy, str(t.get("kind") or ""))


def _ensure_chunks(doc_id: str, settings) -> list:
    if not db.q1("SELECT 1 FROM chunks WHERE doc_id=?", doc_id):
        build_chunks(doc_id, settings.understand_chunk_chars)
    return db.q("SELECT idx, start_seq, end_seq, summary FROM chunks WHERE doc_id=? ORDER BY idx", doc_id)


def _chunk_prompt(doc: dict, c, total: int) -> str:
    return prompts.understand_prompt(doc["title"], c["idx"] + 1, total, chunk_text(doc["id"], c["start_seq"], c["end_seq"]))


def save_chunk(doc_id: str, idx: int, res) -> None:
    db.add_usage(doc_id, res, "understand")
    summary = str(res.data.get("summary") or "").strip() or "(no summary)"
    db.ex("UPDATE chunks SET summary=? WHERE doc_id=? AND idx=?", summary, doc_id, idx)
    merge_terms(doc_id, res.data.get("terms"))


def batch_requests(doc_id: str, settings) -> list[tuple[str, str, str, dict]]:
    """Pass-1 requests for the Batch API: key u<idx> per chunk that still needs a summary."""
    doc = db.get_doc(doc_id)
    chunks = _ensure_chunks(doc_id, settings)
    out = []
    for c in chunks:
        if c["summary"]:
            continue
        if not chunk_text(doc_id, c["start_seq"], c["end_seq"]).strip():
            db.ex("UPDATE chunks SET summary=? WHERE doc_id=? AND idx=?", "(no text)", doc_id, c["idx"])
            continue
        out.append((f"u{c['idx']}", prompts.system_for("understand", settings), _chunk_prompt(doc, c, len(chunks)), prompts.UNDERSTAND_SCHEMA))
    return out


def ingest_batch(doc_id: str, results, model: str) -> int:
    n = 0
    for key, res, _err in results:
        if res is None or not key.startswith("u"):
            continue
        res.model = model
        save_chunk(doc_id, int(key[1:]), res)
        n += 1
    return n


def run(doc_id: str, llm, settings, should_stop) -> None:
    doc = db.get_doc(doc_id)
    chunks = _ensure_chunks(doc_id, settings)
    total = len(chunks) + 1
    done = sum(1 for c in chunks if c["summary"])
    db.update_doc(doc_id, stage="understand", stage_done=done, stage_total=total)

    def work(c) -> None:
        if should_stop():
            raise Paused()
        if not chunk_text(doc_id, c["start_seq"], c["end_seq"]).strip():
            db.ex("UPDATE chunks SET summary=? WHERE doc_id=? AND idx=?", "(no text)", doc_id, c["idx"])
            return
        res = llm.generate_json(prompts.system_for("understand", settings), _chunk_prompt(doc, c, len(chunks)),
                                prompts.UNDERSTAND_SCHEMA, purpose="understand")
        save_chunk(doc_id, c["idx"], res)

    pending = [c for c in chunks if not c["summary"]]
    with ThreadPoolExecutor(max_workers=max(1, settings.concurrency)) as pool:
        futs = [pool.submit(work, c) for c in pending]
        for f in as_completed(futs):
            f.result()  # re-raise Paused / LLMError
            done += 1
            db.update_doc(doc_id, stage_done=done)

    if should_stop():
        raise Paused()
    if not doc.get("brief"):
        summaries = [c["summary"] for c in db.q("SELECT summary FROM chunks WHERE doc_id=? ORDER BY idx", doc_id)]
        budget = 14000 if settings.llm_provider == "gemini" else 4000
        if sum(len(s) for s in summaries) > budget:   # sample evenly across the document
            step = max(1, len(summaries) // max(1, budget // 400))
            summaries = summaries[::step]
        terms = [r["term"] for r in db.q("SELECT term FROM glossary WHERE doc_id=? ORDER BY count DESC LIMIT 80", doc_id)]
        try:
            res = llm.generate_json(prompts.system_for("brief", settings), prompts.brief_prompt(doc["title"], summaries, terms),
                                    prompts.brief_schema(), purpose="brief")
            db.add_usage(doc_id, res, "brief")
            brief = res.data
        except LLMError as e:
            if e.retryable:
                raise
            log.warning("brief failed, continuing without it: %s", e)
            brief = {}
        db.update_doc(doc_id, brief=json.dumps(brief, ensure_ascii=False),
                      title_si=str(brief.get("translated_title") or brief.get("title_si") or "") or None, stage_done=total)
