"""Source-grounded subject papers, persisted exams and server-side grading."""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException

from . import app_settings, db, progress
from .ai_safety import LOCK
from .llm import get_llm

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="subject-quiz")
def _sources(doc_id, scope):
    rows = [dict(r) for r in db.q("SELECT seq,source,page,section FROM blocks WHERE doc_id=? AND type IN ('paragraph','list_item','heading','caption','footnote') ORDER BY seq", doc_id)]
    if scope.get("sections"):
        rows = [r for r in rows if r["section"] in scope["sections"]]
    if scope.get("sequences"):
        rows = [r for r in rows if r["seq"] in scope["sequences"]]
    if scope.get("start_seq") is not None:
        rows = [r for r in rows if r["seq"] >= scope["start_seq"]]
    if scope.get("end_seq") is not None:
        rows = [r for r in rows if r["seq"] <= scope["end_seq"]]
    return [r for r in rows if len((r["source"] or "").strip()) >= 40]


def create(doc_id: str, difficulty: str, count: int, scope: dict, request_key: str):
    if not db.get_doc(doc_id):
        raise HTTPException(404, "Document not found")
    with LOCK:
        prior = db.q1("SELECT * FROM quiz_papers WHERE request_key=?", request_key)
        normalized = json.dumps(scope, sort_keys=True)
        if prior:
            if (prior["doc_id"], prior["difficulty"], prior["count"], prior["scope"]) != (doc_id, difficulty, count, normalized):
                raise HTTPException(409, "Request key belongs to another paper")
            return paper(prior["id"])
        rows = _sources(doc_id, scope)
        maximum = min(60, sum(len(r["source"]) for r in rows) // 100)
        if maximum < count:
            raise HTTPException(422, {"message": "Not enough source material. Select more text or fewer questions.", "suggested_count": maximum})
        runtime = app_settings.runtime()
        pid = uuid.uuid4().hex
        version = db.q1("SELECT COALESCE(MAX(version),0)+1 n FROM quiz_papers WHERE doc_id=? AND difficulty=?", doc_id, difficulty)["n"]
        prefs = app_settings.get()
        db.ex("INSERT INTO quiz_papers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", pid, doc_id, difficulty, version,
              prefs.target_language, normalized, count, "queued", None, time.time(), request_key,
              json.dumps(app_settings.profile(prefs) | {"quiz_generation_version": "durable-v2"}),)
        POOL.submit(generate, pid, rows, runtime)
    return paper(pid)


def generate(pid: str, rows: list[dict], runtime):
    from .study_generation import generate as run
    run(pid, rows, runtime, get_llm)


def validate_question(item, source_map):
    from .study_responses import validate
    return validate(item, source_map)[0]


def paper(pid: str):
    r = db.q1("SELECT * FROM quiz_papers WHERE id=?", pid)
    if not r:
        raise HTTPException(404, "Paper not found")
    p = dict(r)
    p["scope"] = json.loads(p["scope"])
    p["profile"] = json.loads(p["profile"])
    p["questions"] = [question_public(dict(q)) for q in db.q("SELECT * FROM subject_questions WHERE paper_id=? ORDER BY rowid", pid)]
    from .study_responses import summary
    from .study_generation import call_limit
    p["generation"] = summary(pid)
    p["generation"]["max_requests"] = call_limit(p["count"])
    p["generation"]["can_recover"] = bool(p["generation"]["responses_saved"]) and p["status"] not in ("queued", "running", "stopping", "ready") and not db.q1("SELECT 1 FROM quiz_attempts WHERE paper_id=?", pid)
    p["generation"]["legacy_unarchived"] = (not p["generation"]["requests"] and p["status"] in ("error", "partial")
                                           and not p["profile"].get("quiz_generation_version"))
    if p["error"]:
        # Old jobs concatenated the same generic error once per batch.
        repeated = "Some generated questions did not pass source/format checks."
        if repeated in p["error"]:
            p["error"] = repeated
    return p


def question_public(q, reveal=False):
    out = {k: q[k] for k in ("id", "question")}
    out["options"] = json.loads(q["options"])
    if reveal:
        out.update(answer=q["answer"], explanation=q["explanation"], distractors=json.loads(q["distractors"]),
                   source_seq=q["source_seq"], source_quote=q["source_quote"])
    return out


def start(pid: str, mode: str, minutes: int, request_key: str):
    with LOCK:
        old = db.q1("SELECT id,paper_id,mode FROM quiz_attempts WHERE request_key=?", request_key)
        if old:
            if old["paper_id"] != pid or old["mode"] != mode:
                raise HTTPException(409, "Request key belongs to another attempt")
            return attempt(old["id"])
        p = paper(pid)
        if p["status"] not in ("ready", "partial", "error", "paused") or not p["questions"]:
            raise HTTPException(409, "This paper has no ready questions yet")
        aid, now = uuid.uuid4().hex, time.time()
        db.ex("INSERT INTO quiz_attempts(id,paper_id,mode,started_at,deadline,request_key) VALUES(?,?,?,?,?,?)",
              aid, pid, mode, now, now + minutes * 60 if mode == "exam" else None, request_key)
    return attempt(aid)


def _grade_event(a, q, chosen):
    difficulty = db.q1("SELECT difficulty,doc_id FROM quiz_papers WHERE id=?", a["paper_id"])
    if chosen is not None:
        progress.record(f"answer-{a['id']}-{q['id']}", "answer", difficulty["doc_id"], q["fingerprint"])
    correct = chosen == q["answer"]
    if correct:
        progress.record(f"correct-{a['id']}-{q['id']}", "correct", difficulty["doc_id"], q["fingerprint"], difficulty=difficulty["difficulty"])
    previous = db.q1("SELECT * FROM subject_reviews WHERE question_id=?", q["id"])
    reps = (previous["reps"] if previous else 0) + 1 if correct else 0
    interval = (1 if reps == 1 else 3 if reps == 2 else round((previous["interval_days"] or 3) * 2.5, 1)) if correct else 0
    db.ex("INSERT OR REPLACE INTO subject_reviews VALUES(?,?,?,?)", q["id"], time.time() + (interval * 86400 if correct else 600), interval, reps)


def submit(aid: str):
    with LOCK:
        a = db.q1("SELECT * FROM quiz_attempts WHERE id=?", aid)
        if not a:
            raise HTTPException(404, "Attempt not found")
        if a["submitted_at"]:
            return
        answers = json.loads(a["answers"])
        score = 0
        for q in db.q("SELECT * FROM subject_questions WHERE paper_id=?", a["paper_id"]):
            chosen = answers.get(q["id"])
            score += int(chosen == q["answer"])
            if a["mode"] == "exam" or chosen is None:
                _grade_event(a, q, chosen)
        db.ex("UPDATE quiz_attempts SET submitted_at=?,score=? WHERE id=?", time.time(), score, aid)


def attempt(aid: str):
    a = db.q1("SELECT * FROM quiz_attempts WHERE id=?", aid)
    if not a:
        raise HTTPException(404, "Attempt not found")
    if not a["submitted_at"] and a["deadline"] and time.time() >= a["deadline"]:
        submit(aid)
        a = db.q1("SELECT * FROM quiz_attempts WHERE id=?", aid)
    out = dict(a)
    out["answers"] = json.loads(out["answers"])
    p = paper(a["paper_id"])
    out["paper"] = p
    out["server_time"] = time.time()
    out["questions"] = [question_public(dict(q), bool(a["submitted_at"]) or (a["mode"] == "study" and q["id"] in out["answers"]))
                        for q in db.q("SELECT * FROM subject_questions WHERE paper_id=? ORDER BY rowid", a["paper_id"])]
    return out


def answer(aid: str, qid: str, choice: int):
    with LOCK:
        current = attempt(aid)
        if current["submitted_at"]:
            raise HTTPException(409, "This attempt is already submitted or its time has expired")
        q = db.q1("SELECT * FROM subject_questions WHERE id=? AND paper_id=?", qid, current["paper_id"])
        if not q:
            raise HTTPException(404, "Question not in this paper")
        if current["mode"] == "study" and qid in current["answers"]:
            return current
        answers = current["answers"] | {qid: choice}
        db.ex("UPDATE quiz_attempts SET answers=? WHERE id=?", json.dumps(answers), aid)
        if current["mode"] == "study":
            _grade_event(current, q, choice)
        return attempt(aid)


def dashboard(doc_id: str):
    return {
        "generation_contract": "durable-v2",
        "papers": [paper(r["id"]) for r in db.q("SELECT id FROM quiz_papers WHERE doc_id=? ORDER BY created_at DESC", doc_id)],
        "attempts": [dict(r) for r in db.q("SELECT a.id,a.paper_id,a.mode,a.started_at,a.submitted_at,a.score,p.difficulty,p.version,(SELECT COUNT(*) FROM subject_questions q WHERE q.paper_id=p.id) total FROM quiz_attempts a JOIN quiz_papers p ON p.id=a.paper_id WHERE p.doc_id=? ORDER BY a.started_at DESC", doc_id)],
        "review": [dict(r) for r in db.q("SELECT q.id,q.paper_id,q.question,q.section,r.due_at FROM subject_reviews r JOIN subject_questions q ON q.id=r.question_id JOIN quiz_papers p ON p.id=q.paper_id WHERE p.doc_id=? AND r.due_at<=? ORDER BY r.due_at", doc_id, time.time())],
        "weak_sections": [dict(r) for r in db.q("SELECT q.section,COUNT(*) mistakes FROM subject_reviews r JOIN subject_questions q ON q.id=r.question_id JOIN quiz_papers p ON p.id=q.paper_id WHERE p.doc_id=? AND r.reps=0 GROUP BY q.section ORDER BY mistakes DESC", doc_id)],
    }
