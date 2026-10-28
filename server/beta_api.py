"""Private-beta settings, translation versions, subject learning and progress routes."""
from __future__ import annotations

import time
import uuid
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import app_settings, db, progress, study, translations
from .ai_safety import confirmed, once
from .tts import GEMINI_VOICES

router = APIRouter(prefix="/api")


class AIAction(BaseModel):
    confirmed: bool = False
    request_key: str = Field(min_length=8, max_length=150)


def local_only(request: Request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Manage API keys from this computer's localhost address.")


@router.get("/settings")
def get_settings():
    return {"settings": app_settings.get().model_dump(), "key": app_settings.key_status(),
            "languages": app_settings.LANGUAGES, "voices": GEMINI_VOICES,
            "initialized": bool(db.q1("SELECT 1 FROM app_settings")), "pricing_date": "2026-10-28"}


@router.patch("/settings")
def patch_settings(body: dict):
    try:
        value = app_settings.update(body)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if any(k in body for k in ("audio_mode", "voice", "tts_model", "display_mode", "target_language")):
        db.ex("UPDATE audio_grants SET revoked=1")
    return value.model_dump()


class KeyIn(BaseModel):
    key: str = Field(min_length=1, max_length=500)


@router.put("/providers/gemini/key")
def put_key(body: KeyIn, request: Request):
    local_only(request)
    try:
        app_settings.save_key(body.key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return app_settings.key_status()


@router.delete("/providers/gemini/key")
def delete_key(request: Request):
    local_only(request)
    app_settings.save_key(None)
    db.ex("UPDATE audio_grants SET revoked=1")
    return app_settings.key_status()


@router.post("/providers/gemini/test")
def test_key(request: Request):
    local_only(request)
    try:
        cfg = app_settings.runtime()
        if not cfg.gemini_api_key:
            raise HTTPException(400, "Configure an API key first")
        r = httpx.get(cfg.gemini_base_url.rstrip("/") + "/v1beta/models", headers={"x-goog-api-key": cfg.gemini_api_key}, timeout=20)
        if not r.is_success:
            raise HTTPException(400, "The provider rejected the key or could not list models.")
        return {"ok": True, "models": [m["name"].removeprefix("models/") for m in r.json().get("models", [])]}
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach the provider. No content was generated.")


@router.get("/documents/{doc_id}/translations")
def runs(doc_id: str):
    doc = db.get_doc(doc_id)
    if not doc:
        raise HTTPException(404)
    return {"active_run": doc["active_run"], "runs": translations.list_runs(doc_id), "current_profile": app_settings.profile()}


@router.post("/documents/{doc_id}/translations")
def new_run(doc_id: str, body: AIAction):
    confirmed(body.confirmed)
    return once(body.request_key, "translation", {"doc_id": doc_id, "profile": app_settings.profile()},
                lambda: {"run_id": translations.new(doc_id)})


@router.post("/documents/{doc_id}/translations/{run_id}/activate")
def activate_run(doc_id: str, run_id: str):
    translations.activate(doc_id, run_id)
    return {"ok": True}


class AudioGrantIn(BaseModel):
    confirmed: bool = False
    doc_id: str
    seq: int = Field(ge=0)
    scope: Literal["paragraph", "chapter"] = "paragraph"
    side: Literal["original", "translated"] = "translated"
    voice: str = "Kore"


@router.post("/audio/authorize")
def audio_authorize(body: AudioGrantIn):
    confirmed(body.confirmed)
    if app_settings.get().audio_mode != "cloud":
        raise HTTPException(403, "Cloud voice is disabled in app settings")
    doc = db.get_doc(body.doc_id)
    block = db.q1("SELECT section FROM blocks WHERE doc_id=? AND seq=?", body.doc_id, body.seq)
    if not doc or not block:
        raise HTTPException(404)
    end = body.seq
    if body.scope == "chapter":
        row = db.q1("SELECT end_seq FROM sections WHERE doc_id=? AND idx=?", body.doc_id, block["section"])
        end = row["end_seq"] if row else body.seq
    gid = uuid.uuid4().hex
    db.ex("INSERT INTO audio_grants(id,doc_id,start_seq,end_seq,run_id,side,voice,expires) VALUES(?,?,?,?,?,?,?,?)",
          gid, body.doc_id, body.seq, end, doc["active_run"], body.side, body.voice, time.time() + 3600)
    return {"grant_id": gid, "end_seq": end}


@router.delete("/audio/authorizations/{grant_id}")
def revoke_audio(grant_id: str):
    db.ex("UPDATE audio_grants SET revoked=1 WHERE id=?", grant_id)
    return {"ok": True}


def check_audio(doc_id: str, seq: int, grant_id: str, side: str, voice: str):
    if app_settings.get().audio_mode != "cloud":
        raise HTTPException(403, "Cloud voice is disabled")
    grant = db.q1("SELECT * FROM audio_grants WHERE id=?", grant_id)
    doc = db.get_doc(doc_id)
    if (not grant or not doc or grant["revoked"] or grant["expires"] < time.time() or grant["doc_id"] != doc_id
        or not grant["start_seq"] <= seq <= grant["end_seq"] or grant["run_id"] != doc["active_run"]
        or grant["side"] != side or grant["voice"] != voice):
        raise HTTPException(403, "Confirm the paragraph or chapter before generating cloud audio")


class PaperIn(AIAction):
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    count: int = Field(10, ge=1, le=60)
    sections: list[int] = Field(default_factory=list, max_length=200)
    sequences: list[int] = Field(default_factory=list, max_length=1000)
    start_seq: int | None = Field(None, ge=0)
    end_seq: int | None = Field(None, ge=0)


@router.post("/documents/{doc_id}/papers")
def create_paper(doc_id: str, body: PaperIn):
    confirmed(body.confirmed)
    return study.create(doc_id, body.difficulty, body.count,
                        {k: getattr(body, k) for k in ("sections", "sequences", "start_seq", "end_seq")}, body.request_key)


@router.get("/documents/{doc_id}/study")
def get_study(doc_id: str):
    if not db.get_doc(doc_id):
        raise HTTPException(404)
    return study.dashboard(doc_id)


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str):
    return study.paper(paper_id)


@router.post("/papers/{paper_id}/recheck")
def recheck_paper(paper_id: str):
    from .study_generation import recover
    recover(paper_id)
    return study.paper(paper_id)


@router.post("/papers/{paper_id}/stop")
def stop_paper(paper_id: str):
    from .study_generation import stop
    stop(paper_id)
    return study.paper(paper_id)


@router.get("/papers/{paper_id}/responses")
def saved_paper_responses(paper_id: str):
    from .study_responses import response_questions
    import json
    if not db.q1("SELECT 1 FROM quiz_papers WHERE id=?", paper_id):
        raise HTTPException(404, "Paper not found")
    if db.q1("SELECT 1 FROM quiz_attempts WHERE paper_id=? AND submitted_at IS NULL", paper_id):
        raise HTTPException(403, "Saved response details are hidden while an attempt is in progress.")
    return {"responses": [{"id": r["id"], "batch_index": r["batch_index"], "model": r["model"],
                            "raw": r["raw"], "questions": response_questions(r),
                            "sources": json.loads(r["request"])["sources"], "usage": json.loads(r["usage"]),
                            "outcome": r["outcome"], "diagnostics": json.loads(r["diagnostics"])}
                           for r in db.q("SELECT * FROM quiz_generation_responses WHERE paper_id=? ORDER BY created_at", paper_id)]}


class AttemptIn(BaseModel):
    mode: Literal["study", "exam"] = "study"
    minutes: int = Field(30, ge=1, le=180)
    request_key: str = Field(min_length=8, max_length=150)


@router.post("/papers/{paper_id}/attempts")
def start_attempt(paper_id: str, body: AttemptIn):
    return study.start(paper_id, body.mode, body.minutes, body.request_key)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str):
    return study.attempt(attempt_id)


class AnswerIn(BaseModel):
    question_id: str
    choice: int = Field(ge=0, le=3)


@router.post("/attempts/{attempt_id}/answers")
def answer(attempt_id: str, body: AnswerIn):
    return study.answer(attempt_id, body.question_id, body.choice)


@router.post("/attempts/{attempt_id}/submit")
def submit(attempt_id: str):
    study.submit(attempt_id)
    return study.attempt(attempt_id)


class ReadingIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=150)
    doc_id: str
    seq: int = Field(ge=0)


@router.post("/progress/reading")
def reading(body: ReadingIn):
    try:
        progress.reading(body.event_id, body.doc_id, body.seq)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/progress")
def get_progress():
    return progress.summary()


@router.post("/practice/generate")
def generate_practice(body: AIAction):
    confirmed(body.confirmed)
    from . import vocab
    from .llm import get_llm
    def perform():
        cfg = app_settings.runtime()
        words = [vocab.word_api(r) for r in db.q("SELECT * FROM words WHERE due_at<=? ORDER BY due_at LIMIT 30", time.time())]
        vocab.ensure_questions(words, get_llm(cfg, "understand"))
        return {"ok": True}
    return once(body.request_key, "vocab-questions", {}, perform)
