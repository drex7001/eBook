"""HTTP API + static hosting of the reader app."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import db, vocab
from .config import ROOT, settings
from .llm import LLMError, get_llm
from .pipeline import translate
from .pipeline.jobs import doc_dir, worker
from .tts import GEMINI_VOICES, TTSError, get_tts

log = logging.getLogger("ebook")
WEB_DIST = ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    worker.start()
    yield


app = FastAPI(title="eBook translator", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2000)


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
    return {
        "llm_provider": settings.llm_provider, "model": settings.model_label,
        "gemini_key": bool(settings.gemini_api_key), "tts_provider": settings.tts_provider,
        "tts_model": settings.gemini_tts_model, "tts_voice": settings.tts_voice,
    }


@app.get("/api/tts/voices")
def voices() -> dict:
    return {"voices": GEMINI_VOICES, "default": settings.tts_voice}


# ----------------------------------------------------------------------------- documents

@app.get("/api/documents")
def list_docs() -> list[dict]:
    return [_doc_api(dict(r)) for r in db.q("SELECT * FROM documents ORDER BY updated_at DESC")]


@app.post("/api/documents")
async def upload(file: UploadFile = File(...), mode: str = Form("standard")) -> dict:
    name = Path(file.filename or "document.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")
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


@app.post("/api/documents/{doc_id}/retranslate-all")
def retranslate_all(doc_id: str, body: RetranslateAll) -> dict:
    """Translate the whole document again (e.g. after prompt or glossary changes). Locked glossary edits are kept."""
    _doc_or_404(doc_id)
    if worker.active == doc_id:
        raise HTTPException(409, "මේ පොත දැන් translate වෙනවා. මුලින් Pause කරලා, නැවතුණාම ආයෙ try කරන්න.")
    with db.tx() as c:
        if body.rebuild_glossary:
            c.execute("DELETE FROM glossary WHERE doc_id=? AND locked=0", (doc_id,))
            c.execute("UPDATE chunks SET summary=NULL WHERE doc_id=?", (doc_id,))
        c.execute("UPDATE blocks SET translated=NULL, translated_table=NULL, qa=NULL, status='pending', rev=? "
                  "WHERE doc_id=? AND status IN ('done','failed','pending')", (db.next_rev(), doc_id))
    db.update_doc(doc_id, stage="understand" if body.rebuild_glossary else "translate",
                  brief=None if body.rebuild_glossary else db.get_doc(doc_id)["brief"], batch_jobs=None)
    translate.refresh_counts(doc_id)
    worker.enqueue(doc_id)
    return _doc_api(db.get_doc(doc_id))


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    _doc_or_404(doc_id)
    worker.pause(doc_id)
    with db.tx() as c:
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


@app.post("/api/documents/{doc_id}/blocks/{seq}/retranslate")
def retranslate_block(doc_id: str, seq: int, body: Retranslate) -> dict:
    _doc_or_404(doc_id)
    try:
        return translate.retranslate(doc_id, seq, body.instruction, get_llm(settings, "translate"), settings)
    except KeyError:
        raise HTTPException(404, "block not found")
    except (ValueError, LLMError) as e:
        raise HTTPException(400, str(e))


class TTSRequest(BaseModel):
    voice: str | None = None


def _speakable(r) -> str:
    if r["type"] in ("figure", "equation", "table", "reference"):
        return ""
    return (r["translated"] or r["source"] or "").strip()


@app.post("/api/documents/{doc_id}/blocks/{seq}/tts")
def block_tts(doc_id: str, seq: int, body: TTSRequest) -> dict:
    _doc_or_404(doc_id)
    r = db.q1("SELECT * FROM blocks WHERE doc_id=? AND seq=?", doc_id, seq)
    if not r:
        raise HTTPException(404, "block not found")
    text = _speakable(r)
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


@app.post("/api/lookup")
def lookup_word(body: LookupIn) -> dict:
    try:
        return vocab.lookup(body.word, body.doc_id, body.seq, get_llm(settings, "understand"))
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
        qs = vocab.practice_set(max(1, min(30, limit)), get_llm(settings, "understand"))
    except LLMError as e:
        raise HTTPException(502, str(e))
    return {"stats": vocab.stats(), "questions": qs}


class AnswerIn(BaseModel):
    word_id: int
    kind: str
    correct: bool


@app.post("/api/practice/answer")
def practice_answer(body: AnswerIn) -> dict:
    try:
        return vocab.record_answer(body.word_id, body.kind, body.correct)
    except KeyError:
        raise HTTPException(404, "word not found")


@app.post("/api/words/{word_id}/audio")
def word_audio(word_id: int, body: TTSRequest) -> dict:
    r = db.q1("SELECT * FROM words WHERE id=?", word_id)
    if not r:
        raise HTTPException(404)
    w = vocab.word_api(r)
    voice = body.voice if body.voice in GEMINI_VOICES else settings.tts_voice
    text = vocab.audio_script(w)
    style = "clear, friendly English teacher; say the English slowly"
    h = hashlib.sha1(f"{settings.gemini_tts_model}|{voice}|{style}|{text}".encode()).hexdigest()[:16]
    adir = Path(settings.data_dir) / "vocab_audio"
    name = f"w{word_id}_{h}.wav"
    if not (adir / name).exists():
        try:
            wav = get_tts(settings).synthesize(text, voice, style)
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
                "SUM(cached_tokens) AS cached, SUM(thought_tokens) AS thinking, SUM(cost) AS cost "
                "FROM usage_log GROUP BY purpose, model, batch ORDER BY cost DESC")
    return {"rows": [dict(r) for r in rows], "total_usd": round(sum((r["cost"] or 0) for r in rows), 4)}


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
