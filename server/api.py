"""HTTP API + static hosting of the reader app."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import uuid
from typing import Literal
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import db, vocab
from .config import ROOT, settings
from .llm import LLMError, get_llm
from .pipeline import translate
from .pipeline.jobs import doc_dir, worker
from .tts import GEMINI_VOICES, TTSError, get_tts
from . import app_settings, translations
from .ai_safety import confirmed, once
from .beta_api import router as beta_router, check_audio

log = logging.getLogger("ebook")
WEB_DIST = ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    db.ex("UPDATE quiz_papers SET status=CASE WHEN status='stopping' THEN 'paused' ELSE 'error' END,error='Generation interrupted. Any saved output is retained; use the free saved-response check before generating again.' WHERE status IN ('queued','running','stopping')")
    worker.start()
    yield


app = FastAPI(title="eBook translator", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.include_router(beta_router)


@app.middleware("http")
async def same_origin_changes(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin changes are not allowed"}, status_code=403)
    return await call_next(request)


def _doc_or_404(doc_id: str) -> dict:
    d = db.get_doc(doc_id)
    if not d:
        raise HTTPException(404, "document not found")
    return d


def _doc_api(d: dict) -> dict:
    pos = db.q1("SELECT seq FROM positions WHERE doc_id=?", d["id"])
    nblocks = db.q1("SELECT COUNT(*) AS n FROM blocks WHERE doc_id=?", d["id"])["n"]
    return {
        "id": d["id"], "title": d["title"], "title_si": d["title_si"], "filename": d["filename"],
        "translated_title": d["title_si"], "active_run": d.get("active_run"),
        "translation_profile": next((r["profile"] for r in translations.list_runs(d["id"]) if r["id"] == d.get("active_run")), None),
        "page_count": d["page_count"], "status": d["status"], "stage": d["stage"],
        "stage_done": d["stage_done"], "stage_total": d["stage_total"], "error": d["error"],
        "translatable": d["translatable"], "translated": d["translated"], "failed": d["failed"],
        "prompt_tokens": d["prompt_tokens"], "output_tokens": d["output_tokens"], "llm_calls": d["llm_calls"],
        "provider": d["provider"], "model": d["model"], "blocks": nblocks,
        "position": pos["seq"] if pos else None, "created_at": d["created_at"], "updated_at": d["updated_at"],
        "brief": json.loads(d["brief"]) if d["brief"] else None,
        "page_sizes": json.loads(d["page_sizes"]) if d["page_sizes"] else [],
        "cached_tokens": d.get("cached_tokens") or 0, "thought_tokens": d.get("thought_tokens") or 0,
        "cost_usd": round(d.get("cost_usd") or 0, 4), "mode": d.get("mode") or "standard",
        "batch": {k: {x: v.get(x) for x in ("state", "requests", "submitted_at", "last_state", "note", "ingested")}
                  for k, v in json.loads(d.get("batch_jobs") or "{}").items()},
    }


# ----------------------------------------------------------------------------- meta

@app.get("/api/health")
def health() -> dict:
    settings = app_settings.runtime()
    return {
        "llm_provider": settings.llm_provider, "model": settings.model_label,
        "gemini_key": bool(settings.gemini_api_key), "tts_provider": settings.tts_provider,
        "tts_model": settings.gemini_tts_model, "tts_voice": settings.tts_voice,
    }


@app.get("/api/tts/voices")
def voices() -> dict:
    settings = app_settings.runtime()
    return {"voices": GEMINI_VOICES, "default": settings.tts_voice}


# ----------------------------------------------------------------------------- documents

@app.get("/api/documents")
def list_docs() -> list[dict]:
    return [_doc_api(dict(r)) for r in db.q("SELECT * FROM documents ORDER BY updated_at DESC")]


@app.post("/api/documents")
async def upload(file: UploadFile = File(...), mode: str = Form("standard"), translation_confirmed: bool = Form(False), request_key: str = Form(...)) -> dict:
    if len(request_key) < 8 or len(request_key) > 150:
        raise HTTPException(400, "A request key is required")
    prefs = app_settings.get()
    if prefs.auto_translate:
        confirmed(translation_confirmed)
    settings = app_settings.runtime()
    previous = db.q1("SELECT result,kind FROM ai_actions WHERE key=?", request_key)
    if previous and previous["kind"] != "upload":
        raise HTTPException(409, "Request key belongs to another action")
    if previous and previous["result"]:
        await file.close()
        existing = db.get_doc(json.loads(previous["result"])["id"])
        if not existing:
            raise HTTPException(409, "This upload was already deleted. Select the PDF again.")
        return _doc_api(existing)
    if previous:
        raise HTTPException(409, "This upload is already in progress or was interrupted. Check the library before trying again.")
    name = Path(file.filename or "document.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")
    db.ex("INSERT INTO ai_actions(key,kind,fingerprint,created_at) VALUES(?,?,?,?)", request_key, "upload", name, time.time())
    doc_id = uuid.uuid4().hex[:10]
    d = doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / "source.pdf"
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    try:
        with pymupdf.open(dest) as pdf:
            pages = pdf.page_count
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "That file could not be opened as a PDF.")
    now = time.time()
    db.ex("INSERT INTO documents(id, title, filename, page_count, status, stage, provider, model, mode, created_at, updated_at) "
          "VALUES(?,?,?,?,?,?,?,?,?,?,?)", doc_id, Path(name).stem, name, pages, "queued", "parse",
          settings.llm_provider, settings.model_label, "batch" if mode == "batch" else "standard", now, now)
    translations.initial(doc_id, app_settings.profile(prefs))
    db.update_doc(doc_id, auto_translate=int(prefs.auto_translate))
    db.ex("UPDATE ai_actions SET result=? WHERE key=?", json.dumps({"id": doc_id}), request_key)
    worker.enqueue(doc_id)
    return _doc_api(db.get_doc(doc_id))


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str) -> dict:
    d = _doc_api(_doc_or_404(doc_id))
    d["sections"] = [dict(r) for r in db.q("SELECT idx, title, start_seq, end_seq FROM sections WHERE doc_id=? ORDER BY idx", doc_id)]
    return d


class DocPatch(BaseModel):
    title: str | None = None
    mode: str | None = None


@app.patch("/api/documents/{doc_id}")
def patch_document(doc_id: str, body: DocPatch) -> dict:
    _doc_or_404(doc_id)
    if body.title is not None and body.title.strip():
        db.update_doc(doc_id, title=body.title.strip()[:300])
    if body.mode in ("standard", "batch"):
        db.update_doc(doc_id, mode=body.mode)
    return _doc_api(db.get_doc(doc_id))


class RetranslateAll(BaseModel):
    rebuild_glossary: bool = True
    confirmed: bool = False
    request_key: str = ""


@app.post("/api/documents/{doc_id}/retranslate-all")
def retranslate_all(doc_id: str, body: RetranslateAll) -> dict:
    """Translate the whole document again (e.g. after prompt or glossary changes). Locked glossary edits are kept."""
    confirmed(body.confirmed)
    once(body.request_key, "translation", {"doc_id": doc_id, "profile": app_settings.profile()}, lambda: {"run_id": translations.new(doc_id)})
    return _doc_api(db.get_doc(doc_id))


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    _doc_or_404(doc_id)
    worker.pause(doc_id)
    with db.tx() as c:
        c.execute("DELETE FROM subject_reviews WHERE question_id IN (SELECT q.id FROM subject_questions q JOIN quiz_papers p ON p.id=q.paper_id WHERE p.doc_id=?)", (doc_id,))
        c.execute("DELETE FROM quiz_generation_responses WHERE paper_id IN (SELECT id FROM quiz_papers WHERE doc_id=?)", (doc_id,))
        c.execute("DELETE FROM subject_questions WHERE paper_id IN (SELECT id FROM quiz_papers WHERE doc_id=?)", (doc_id,))
        c.execute("DELETE FROM quiz_attempts WHERE paper_id IN (SELECT id FROM quiz_papers WHERE doc_id=?)", (doc_id,))
        for table in ("quiz_papers", "translation_runs", "audio_grants"):
            c.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))
        for t in ("blocks", "sections", "chunks", "glossary", "positions", "notes", "audio"):
            c.execute(f"DELETE FROM {t} WHERE doc_id=?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    shutil.rmtree(doc_dir(doc_id), ignore_errors=True)
    return {"ok": True}


@app.post("/api/documents/{doc_id}/resume")
def resume(doc_id: str) -> dict:
    _doc_or_404(doc_id)
    worker.enqueue(doc_id)
    return _doc_api(db.get_doc(doc_id))


@app.post("/api/documents/{doc_id}/pause")
def pause(doc_id: str) -> dict:
    _doc_or_404(doc_id)
    worker.pause(doc_id)
    return _doc_api(db.get_doc(doc_id))


@app.post("/api/documents/{doc_id}/retry-failed")
def retry_failed(doc_id: str) -> dict:
    _doc_or_404(doc_id)
    db.ex("UPDATE blocks SET status='pending' WHERE doc_id=? AND status='failed'", doc_id)
    db.update_doc(doc_id, stage="translate")
    worker.enqueue(doc_id)
    return _doc_api(db.get_doc(doc_id))


@app.get("/api/documents/{doc_id}/blocks")
def blocks(doc_id: str, since: int = 0) -> JSONResponse:
    _doc_or_404(doc_id)
    rows = db.q("SELECT * FROM blocks WHERE doc_id=? AND rev>? ORDER BY seq", doc_id, since)
    mx = db.q1("SELECT MAX(rev) AS m FROM blocks WHERE doc_id=?", doc_id)["m"] or 0
    return JSONResponse({"rev": mx, "blocks": [db.block_row_to_api(r) for r in rows]})


@app.get("/api/documents/{doc_id}/glossary")
def glossary(doc_id: str) -> list[dict]:
    _doc_or_404(doc_id)
    return [dict(r) for r in db.q("SELECT term, rendering, policy, kind, count, locked FROM glossary WHERE doc_id=? "
                                  "ORDER BY count DESC, term", doc_id)]


class GlossaryEdit(BaseModel):
    term: str
    rendering: str
    policy: str


@app.put("/api/documents/{doc_id}/glossary")
def edit_glossary(doc_id: str, body: GlossaryEdit) -> dict:
    _doc_or_404(doc_id)
    if body.policy not in ("keep_en", "translate", "transliterate"):
        raise HTTPException(400, "bad policy")
    key = body.term.strip().lower()
    db.ex("INSERT INTO glossary(doc_id, key, term, rendering, policy, kind, count, locked) VALUES(?,?,?,?,?,'',1,1) "
          "ON CONFLICT(doc_id, key) DO UPDATE SET rendering=excluded.rendering, policy=excluded.policy, locked=1",
          doc_id, key, body.term.strip(), body.rendering.strip() or body.term.strip(), body.policy)
    return {"ok": True}


# ----------------------------------------------------------------------------- files

@app.get("/api/documents/{doc_id}/assets/{name}")
def asset(doc_id: str, name: str) -> FileResponse:
    p = doc_dir(doc_id) / "assets" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/documents/{doc_id}/pages/{page}.png")
def page_image(doc_id: str, page: int, zoom: float = 1.6) -> FileResponse:
    _doc_or_404(doc_id)
    zoom = max(0.2, min(3.0, zoom))
    out = doc_dir(doc_id) / "pages" / f"{page}_{zoom:.2f}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(doc_dir(doc_id) / "source.pdf") as pdf:
            if not 0 <= page < pdf.page_count:
                raise HTTPException(404)
            pdf[page].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(out)
    return FileResponse(out, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/documents/{doc_id}/source.pdf")
def source_pdf(doc_id: str) -> FileResponse:
    _doc_or_404(doc_id)
    return FileResponse(doc_dir(doc_id) / "source.pdf", media_type="application/pdf")


# ----------------------------------------------------------------------------- reading state

class Position(BaseModel):
    seq: int


@app.put("/api/documents/{doc_id}/position")
def set_position(doc_id: str, body: Position) -> dict:
    db.ex("INSERT INTO positions(doc_id, seq, updated_at) VALUES(?,?,?) "
          "ON CONFLICT(doc_id) DO UPDATE SET seq=excluded.seq, updated_at=excluded.updated_at",
          doc_id, body.seq, time.time())
    db.ex("UPDATE documents SET updated_at=? WHERE id=?", time.time(), doc_id)
    return {"ok": True}


class NoteIn(BaseModel):
    seq: int
    color: str | None = None
    quote: str | None = None
    body: str | None = None


@app.get("/api/documents/{doc_id}/notes")
def list_notes(doc_id: str) -> list[dict]:
    return [dict(r) for r in db.q("SELECT * FROM notes WHERE doc_id=? ORDER BY seq, id", doc_id)]


@app.post("/api/documents/{doc_id}/notes")
def add_note(doc_id: str, n: NoteIn) -> dict:
    _doc_or_404(doc_id)
    now = time.time()
    cur = db.ex("INSERT INTO notes(doc_id, seq, color, quote, body, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                doc_id, n.seq, n.color, n.quote, n.body, now, now)
    return dict(db.q1("SELECT * FROM notes WHERE id=?", cur.lastrowid))


@app.patch("/api/documents/{doc_id}/notes/{note_id}")
def edit_note(doc_id: str, note_id: int, n: NoteIn) -> dict:
    db.ex("UPDATE notes SET color=?, quote=?, body=?, updated_at=? WHERE id=? AND doc_id=?",
          n.color, n.quote, n.body, time.time(), note_id, doc_id)
    r = db.q1("SELECT * FROM notes WHERE id=?", note_id)
    if not r:
        raise HTTPException(404)
    return dict(r)


@app.delete("/api/documents/{doc_id}/notes/{note_id}")
def delete_note(doc_id: str, note_id: int) -> dict:
    db.ex("DELETE FROM notes WHERE id=? AND doc_id=?", note_id, doc_id)
    return {"ok": True}


# ----------------------------------------------------------------------------- per-block actions

class Retranslate(BaseModel):
    instruction: str = ""
    confirmed: bool = False
    request_key: str = ""


@app.post("/api/documents/{doc_id}/blocks/{seq}/retranslate")
def retranslate_block(doc_id: str, seq: int, body: Retranslate) -> dict:
    _doc_or_404(doc_id)
    confirmed(body.confirmed)
    try:
        settings = app_settings.runtime(doc_id)
        def perform():
            result = translate.retranslate(doc_id, seq, body.instruction, get_llm(settings, "translate"), settings)
            translations.capture(doc_id)
            return result
        return once(body.request_key, "retranslate-block", [doc_id, seq, body.instruction], perform)
    except KeyError:
        raise HTTPException(404, "block not found")
    except (ValueError, LLMError) as e:
        raise HTTPException(400, str(e))


class TTSRequest(BaseModel):
    voice: str | None = None
    grant_id: str = ""
    side: Literal["original", "translated"] = "translated"
    confirmed: bool = False
    request_key: str = ""


def _speakable(r) -> str:
    if r["type"] in ("figure", "equation", "table", "reference"):
        return ""
    return (r["translated"] or r["source"] or "").strip()


@app.post("/api/documents/{doc_id}/blocks/{seq}/tts")
def block_tts(doc_id: str, seq: int, body: TTSRequest) -> dict:
    settings = app_settings.runtime(doc_id)
    voice = body.voice if body.voice in GEMINI_VOICES else settings.tts_voice
    check_audio(doc_id, seq, body.grant_id, body.side, voice)
    return once(body.request_key, "tts", [doc_id, seq, voice, body.side, db.get_doc(doc_id)["active_run"], settings.gemini_tts_model],
                lambda: _block_tts(doc_id, seq, body, settings, voice))


def _block_tts(doc_id, seq, body, settings, voice):
    # Recheck after admission: this request may have waited behind another generation.
    check_audio(doc_id, seq, body.grant_id, body.side, voice)
    _doc_or_404(doc_id)
    r = db.q1("SELECT * FROM blocks WHERE doc_id=? AND seq=?", doc_id, seq)
    if not r:
        raise HTTPException(404, "block not found")
    text = (r["source"] if body.side == "original" else r["translated"] or r["source"]) if _speakable(r) else ""
    if not text:
        return {"skip": True}
    voice = body.voice if body.voice in GEMINI_VOICES else settings.tts_voice
    h = hashlib.sha1(f"{settings.gemini_tts_model}|{voice}|{settings.tts_style}|{text}".encode()).hexdigest()[:16]
    row = db.q1("SELECT file, hash FROM audio WHERE doc_id=? AND seq=? AND voice=?", doc_id, seq, voice)
    adir = doc_dir(doc_id) / "audio"
    if row and row["hash"] == h and (adir / row["file"]).exists():
        return {"url": f"/api/documents/{doc_id}/audio/{row['file']}", "cached": True}
    try:
        wav = get_tts(settings).synthesize(text, voice, settings.tts_style)
        log_audio_usage(doc_id, settings.gemini_tts_model, text, wav)
    except TTSError as e:
        raise HTTPException(502, str(e))
    adir.mkdir(parents=True, exist_ok=True)
    name = f"{seq:05d}_{voice}_{h}.wav"
    (adir / name).write_bytes(wav)
    db.ex("INSERT INTO audio(doc_id, seq, voice, hash, file, created_at) VALUES(?,?,?,?,?,?) "
          "ON CONFLICT(doc_id, seq, voice) DO UPDATE SET hash=excluded.hash, file=excluded.file, created_at=excluded.created_at",
          doc_id, seq, voice, h, name, time.time())
    return {"url": f"/api/documents/{doc_id}/audio/{name}", "cached": False}


@app.get("/api/documents/{doc_id}/audio/{name}")
def audio_file(doc_id: str, name: str) -> FileResponse:
    p = doc_dir(doc_id) / "audio" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ----------------------------------------------------------------------------- English learning

class LookupIn(BaseModel):
    word: str
    doc_id: str | None = None
    seq: int | None = None
    confirmed: bool = False
    request_key: str = ""


@app.post("/api/lookup")
def lookup_word(body: LookupIn) -> dict:
    confirmed(body.confirmed)
    try:
        cfg = app_settings.runtime()
        cfg.source_language = "auto"  # A tapped word may be code-mixed or belong to an older source-language profile.
        return once(body.request_key, "lookup", [body.word, body.doc_id, body.seq, app_settings.profile()],
                    lambda: vocab.lookup(body.word, body.doc_id, body.seq, get_llm(cfg, "understand"), cfg))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LLMError as e:
        raise HTTPException(502, str(e))


@app.get("/api/words")
def list_words(q: str = "") -> dict:
    rows = db.q("SELECT * FROM words WHERE word LIKE ? OR meaning_si LIKE ? OR meaning_en LIKE ? ORDER BY created_at DESC",
                f"%{q}%", f"%{q}%", f"%{q}%")
    return {"stats": vocab.stats(), "words": [vocab.word_api(r) for r in rows]}


@app.post("/api/words")
def add_word(body: dict) -> dict:
    try:
        return vocab.save_word(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/words/{word_id}")
def delete_word(word_id: int) -> dict:
    db.ex("DELETE FROM quiz_items WHERE word_id=?", word_id)
    db.ex("DELETE FROM words WHERE id=?", word_id)
    return {"ok": True}


@app.get("/api/practice")
def practice(limit: int = 10) -> dict:
    try:
        qs = vocab.practice_set(max(1, min(30, limit)))
        for q in qs:
            q.pop("answer", None)
    except LLMError as e:
        raise HTTPException(502, str(e))
    return {"stats": vocab.stats(), "questions": qs}


class AnswerIn(BaseModel):
    word_id: int
    kind: str
    correct: bool | None = None
    choice_token: str = ""
    choice: int | None = Field(None, ge=0, le=3)


@app.post("/api/practice/answer")
def practice_answer(body: AnswerIn) -> dict:
    try:
        row = db.q1("SELECT * FROM quiz_choices WHERE token=? AND word_id=? AND kind=?", body.choice_token, body.word_id, body.kind)
        if not row:
            raise HTTPException(400, "Reload practice before answering")
        item = db.q1("SELECT explain_si FROM quiz_items WHERE id=?", row["item_id"]) if row["item_id"] else None
        correct = bool(body.correct) if body.kind == "recall" else body.choice == row["answer"]
        from .ai_safety import LOCK
        with LOCK:
            if not db.q1("SELECT used FROM quiz_choices WHERE token=?", body.choice_token)["used"]:
                vocab.record_answer(body.word_id, body.kind, correct)
                from . import progress
                progress.record(f"vocab-answer-{body.choice_token}", "answer", subject=f"vocab-{row['item_id'] or body.word_id}")
                if correct and body.kind != "recall":
                    progress.record(f"vocab-correct-{body.choice_token}", "correct", subject=f"vocab-{row['item_id']}")
                db.ex("UPDATE quiz_choices SET used=1 WHERE token=?", body.choice_token)
        return {"answer": row["answer"], "correct": correct, "explanation": item["explain_si"] if item else ""}
    except KeyError:
        raise HTTPException(404, "word not found")


@app.post("/api/words/{word_id}/audio")
def word_audio(word_id: int, body: TTSRequest) -> dict:
    if app_settings.get().audio_mode != "cloud":
        raise HTTPException(403, "Cloud voice is disabled")
    confirmed(body.confirmed)
    return once(body.request_key, "word-audio", [word_id, body.voice], lambda: _word_audio(word_id, body))


def _word_audio(word_id: int, body: TTSRequest) -> dict:
    if app_settings.get().audio_mode != "cloud":
        raise HTTPException(403, "Cloud voice is disabled")
    settings = app_settings.runtime()
    r = db.q1("SELECT * FROM words WHERE id=?", word_id)
    if not r:
        raise HTTPException(404)
    w = vocab.word_api(r)
    voice = body.voice if body.voice in GEMINI_VOICES else settings.tts_voice
    text = vocab.audio_script(w)
    style = (f"Clear, friendly language teacher. Read the word in its own language, followed by its meaning in "
             f"{app_settings.language_name(w.get('target_language') or 'si')}. Read each example faithfully.")
    h = hashlib.sha1(f"{settings.gemini_tts_model}|{voice}|{style}|{text}".encode()).hexdigest()[:16]
    adir = Path(settings.data_dir) / "vocab_audio"
    name = f"w{word_id}_{h}.wav"
    if not (adir / name).exists():
        try:
            wav = get_tts(settings).synthesize(text, voice, style)
            log_audio_usage(None, settings.gemini_tts_model, text, wav)
        except TTSError as e:
            raise HTTPException(502, str(e))
        adir.mkdir(parents=True, exist_ok=True)
        (adir / name).write_bytes(wav)
    return {"url": f"/api/vocab-audio/{name}"}


@app.get("/api/vocab-audio/{name}")
def vocab_audio_file(name: str) -> FileResponse:
    p = Path(settings.data_dir) / "vocab_audio" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/usage")
def usage() -> dict:
    """Spend so far, split by what it was for."""
    rows = db.q("SELECT purpose, model, batch, COUNT(*) AS calls, SUM(prompt_tokens) AS input, SUM(output_tokens) AS output, "
                "SUM(cached_tokens) AS cached, SUM(thought_tokens) AS thinking, SUM(cost) AS cost, SUM(audio_seconds) AS audio_seconds, MIN(estimate_known) AS estimate_known "
                "FROM usage_log GROUP BY purpose, model, batch ORDER BY cost DESC")
    return {"rows": [dict(r) for r in rows], "total_usd": round(sum((r["cost"] or 0) for r in rows), 4),
            "pricing_date": "2026-10-28", "unknown_estimates": any(not r["estimate_known"] for r in rows)}


def log_audio_usage(doc_id, model, text, wav):
    import io
    import wave
    from .llm.base import LLMResult
    with wave.open(io.BytesIO(wav)) as f:
        duration = f.getnframes() / f.getframerate()
    db.add_usage(doc_id, LLMResult({}, len(text) // 4, round(duration * 25), model=model), "audio")
    db.ex("UPDATE usage_log SET audio_seconds=? WHERE rowid=last_insert_rowid()", duration)


# ----------------------------------------------------------------------------- reader app (built React files)

@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    f = (WEB_DIST / path).resolve()
    if path and f.is_file() and WEB_DIST.resolve() in f.parents:
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f.as_posix() else {}
        return FileResponse(f, headers=headers)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"error": "web app not built. Run: cd web && npm install && npm run build"}, status_code=404)
