"""English learning: word lookups, saved words, spaced-repetition practice with generated MCQs."""
from __future__ import annotations

import hashlib
import json
import random
import re
import time

from . import db
from .llm import LLMError
from .pipeline import prompts

DAY = 86400.0
KINDS = ("meaning", "cloze", "usage", "listen")


# ----------------------------------------------------------------------------- lookup

def context_sentence(doc_id: str | None, seq: int | None, word: str) -> str:
    """The sentence the word came from: English original first, else the translated text."""
    if not doc_id or seq is None:
        return ""
    r = db.q1("SELECT source, translated FROM blocks WHERE doc_id=? AND seq=?", doc_id, seq)
    if not r:
        return ""
    rx = re.compile(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", re.I)
    for text in (r["source"] or "", r["translated"] or ""):
        for sent in re.split(r"(?<=[.!?;:])\s+", text):
            if rx.search(sent):
                return sent.strip()[:400]
    return (r["source"] or "")[:300]


def lookup(word: str, doc_id: str | None, seq: int | None, llm) -> dict:
    word = word.strip(" \t\n'\"’‘“”.,;:()[]")[:60]
    if not re.search(r"[A-Za-z]", word):
        raise ValueError("Not an English word.")
    sentence = context_sentence(doc_id, seq, word)
    key = hashlib.sha1(f"{word.lower()}|{sentence}".encode()).hexdigest()
    hit = db.q1("SELECT data FROM lookups WHERE key=?", key)
    if hit:
        data = json.loads(hit["data"])
    else:
        res = llm.generate_json(prompts.LOOKUP_SYSTEM, prompts.lookup_prompt(word, sentence or word),
                                prompts.LOOKUP_SCHEMA, purpose="lookup")
        db.add_usage(None, res, "lookup")
        data = res.data
        db.ex("INSERT OR REPLACE INTO lookups(key, data, created_at) VALUES(?,?,?)",
              key, json.dumps(data, ensure_ascii=False), time.time())
    data = dict(data)
    data.update(word=word, context=sentence, doc_id=doc_id, seq=seq)
    lemma = (data.get("lemma") or word).strip().lower()
    saved = db.q1("SELECT id FROM words WHERE lemma=?", lemma)
    data["saved_id"] = saved["id"] if saved else None
    return data


# ----------------------------------------------------------------------------- saved words

def word_api(r) -> dict:
    d = dict(r)
    for k in ("examples", "synonyms"):
        d[k] = json.loads(d[k] or "[]")
    return d


def save_word(data: dict) -> dict:
    lemma = (data.get("lemma") or data.get("word") or "").strip().lower()
    if not lemma:
        raise ValueError("No word given.")
    now = time.time()
    row = db.q1("SELECT id FROM words WHERE lemma=?", lemma)
    fields = dict(word=data.get("word") or lemma, pos=data.get("pos"), ipa=data.get("ipa"),
                  meaning_en=data.get("meaning_en"), meaning_si=data.get("meaning_si"),
                  in_context_si=data.get("in_context_si"),
                  examples=json.dumps(data.get("examples") or [], ensure_ascii=False),
                  synonyms=json.dumps(data.get("synonyms") or [], ensure_ascii=False),
                  level=data.get("level"), context=data.get("context"), doc_id=data.get("doc_id"), seq=data.get("seq"))
    if row:
        db.ex("UPDATE words SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?", *fields.values(), row["id"])
        wid = row["id"]
    else:
        cur = db.ex("INSERT INTO words(lemma, created_at, due_at, " + ", ".join(fields) + ") VALUES(?,?,?," +
                    ",".join("?" * len(fields)) + ")", lemma, now, now, *fields.values())
        wid = cur.lastrowid
    return word_api(db.q1("SELECT * FROM words WHERE id=?", wid))


def stats() -> dict:
    now = time.time()
    r = db.q1("SELECT COUNT(*) AS total, SUM(due_at<=?) AS due, SUM(interval_days>=21) AS known FROM words", now)
    day = lambda t: int((t + 19800) // DAY)  # noqa: E731  (Sri Lanka time, UTC+5:30)
    days = {day(x["at"]) for x in db.q("SELECT at FROM reviews")}
    today = day(now)
    d = today if today in days else today - 1
    streak = 0
    while d in days:
        streak += 1
        d -= 1
    reviewed_today = db.q1("SELECT COUNT(*) AS n FROM reviews WHERE at>=?", today * DAY - 19800)["n"]
    return {"total": r["total"] or 0, "due": r["due"] or 0, "known": r["known"] or 0,
            "streak": streak, "reviewed_today": reviewed_today}


# ----------------------------------------------------------------------------- spaced repetition

def schedule(w: dict, correct: bool, now: float | None = None) -> dict:
    """SM-2 style. Returns updated interval_days, ease, reps, lapses, due_at."""
    now = now or time.time()
    ease, reps, interval, lapses = w.get("ease") or 2.5, w.get("reps") or 0, w.get("interval_days") or 0, w.get("lapses") or 0
    if correct:
        reps += 1
        interval = 1 if reps == 1 else 3 if reps == 2 else round(interval * ease, 1)
        ease = min(3.0, ease + 0.05)
        due = now + interval * DAY
    else:
        reps, lapses = 0, lapses + 1
        interval = 0
        ease = max(1.3, ease - 0.2)
        due = now + 10 * 60          # see it again in ten minutes
    return {"interval_days": interval, "ease": round(ease, 2), "reps": reps, "lapses": lapses, "due_at": due}


def record_answer(word_id: int, kind: str, correct: bool) -> dict:
    w = db.q1("SELECT * FROM words WHERE id=?", word_id)
    if not w:
        raise KeyError(word_id)
    upd = schedule(dict(w), correct)
    db.ex("UPDATE words SET interval_days=?, ease=?, reps=?, lapses=?, due_at=?, last_review=? WHERE id=?",
          upd["interval_days"], upd["ease"], upd["reps"], upd["lapses"], upd["due_at"], time.time(), word_id)
    db.ex("INSERT INTO reviews(word_id, kind, correct, at) VALUES(?,?,?,?)", word_id, kind, 1 if correct else 0, time.time())
    return upd


# ----------------------------------------------------------------------------- questions

def ensure_questions(words: list[dict], llm) -> None:
    need = [w for w in words if db.q1("SELECT COUNT(*) AS n FROM quiz_items WHERE word_id=?", w["id"])["n"] < len(KINDS)]
    for i in range(0, len(need), 8):
        group = need[i:i + 8]
        try:
            res = llm.generate_json(prompts.QUIZ_SYSTEM, prompts.quiz_prompt(group), prompts.QUIZ_SCHEMA, purpose="quiz")
        except LLMError:
            continue                       # practice still works with the meaning card for these words
        db.add_usage(None, res, "quiz")
        ids = {w["id"] for w in group}
        for it in res.data.get("items") or []:
            opts = [str(o).strip() for o in (it.get("options") or []) if str(o).strip()]
            if it.get("word_id") not in ids or it.get("kind") not in KINDS or len(opts) < 3 or len(set(opts)) != len(opts):
                continue
            db.ex("INSERT INTO quiz_items(word_id, kind, question, options, explain_si, audio_text, created_at) "
                  "VALUES(?,?,?,?,?,?,?)", it["word_id"], it["kind"], str(it.get("question") or ""),
                  json.dumps(opts[:4], ensure_ascii=False), str(it.get("explain_si") or ""),
                  str(it.get("audio_text") or ""), time.time())


def practice_set(limit: int, llm) -> list[dict]:
    now = time.time()
    rows = db.q("SELECT * FROM words WHERE due_at<=? ORDER BY reps>0 DESC, due_at LIMIT ?", now, limit)
    words = [word_api(r) for r in rows]
    if not words:
        return []
    ensure_questions(words, llm)
    out = []
    for w in words:
        items = db.q("SELECT * FROM quiz_items WHERE word_id=? ORDER BY uses, COALESCE(last_used,0)", w["id"])
        if items:
            it = items[0]
            opts = json.loads(it["options"])
            order = list(range(len(opts)))
            random.shuffle(order)
            q = {"item_id": it["id"], "kind": it["kind"], "question": it["question"],
                 "options": [opts[i] for i in order], "answer": order.index(0),
                 "explain_si": it["explain_si"], "audio_text": it["audio_text"]}
            db.ex("UPDATE quiz_items SET uses=uses+1, last_used=? WHERE id=?", now, it["id"])
        else:   # no generated question yet: plain recall card
            q = {"item_id": None, "kind": "recall", "question": f"'{w['word']}' කියන්නේ මොකක්ද?", "options": [],
                 "answer": -1, "explain_si": w.get("meaning_si") or "", "audio_text": ""}
        q["word"] = w
        out.append(q)
    return out


def audio_script(w: dict) -> str:
    ex = (w.get("examples") or [{}])[0] if w.get("examples") else {}
    parts = [w["word"] + ".", (w.get("meaning_si") or "") + ".", ex.get("en", ""), ex.get("si", "")]
    return " ".join(p for p in parts if p and p != ".")
