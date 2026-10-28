"""Local learning history and idempotent, bounded XP awards."""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

from . import app_settings, db


def day(at: float | None = None) -> str:
    return dt.datetime.fromtimestamp(at if at is not None else time.time(), ZoneInfo(app_settings.get().timezone)).date().isoformat()


def record(event_id: str, kind: str, doc_id=None, subject="", amount=1, difficulty="easy"):
    p = app_settings.get()
    today, now = day(), time.time()
    with db.tx():
        if db.q1("SELECT 1 FROM progress_events WHERE id=?", event_id):
            return
        xp = 0
        if p.gamification:
            if kind == "reading":
                earned = db.q1("SELECT COALESCE(SUM(xp),0) n FROM progress_events WHERE day=? AND kind='reading'", today)["n"]
                xp = max(0, min(1, 30 - earned))
            elif kind == "correct" and not db.q1("SELECT 1 FROM progress_events WHERE kind='correct' AND subject=?", subject):
                xp = {"easy": 5, "medium": 10, "hard": 15}[difficulty]
        db.ex("INSERT INTO progress_events VALUES(?,?,?,?,?,?,?,?)", event_id, kind, doc_id, subject, amount, today, now, xp)
        read = db.q1("SELECT COUNT(*) n FROM progress_events WHERE day=? AND kind='reading'", today)["n"]
        answered = db.q1("SELECT COUNT(*) n FROM progress_events WHERE day=? AND kind='answer'", today)["n"]
        if p.gamification and read >= p.reading_goal and answered >= p.question_goal:
            db.ex("INSERT OR IGNORE INTO progress_events VALUES(?,?,?,?,?,?,?,?)", "challenge-" + today, "challenge", None, "daily", 1, today, now, 20)


def reading(event_id: str, doc_id: str, seq: int):
    if not db.q1("SELECT 1 FROM blocks WHERE doc_id=? AND seq=?", doc_id, seq):
        raise ValueError("Reading block not found")
    from .ai_safety import LOCK
    with LOCK:
        latest = db.q1("SELECT MAX(at) at FROM progress_events WHERE kind='reading'")
        if latest["at"] and time.time() - latest["at"] < 55:
            return
        record(event_id, "reading", doc_id, str(seq))
        section = db.q1("SELECT idx FROM sections WHERE doc_id=? AND end_seq=?", doc_id, seq)
        if section:
            record(f"chapter-{doc_id}-{section['idx']}", "chapter", doc_id, str(section["idx"]))


def summary():
    p, today = app_settings.get(), day()
    totals = {r["kind"]: r["n"] for r in db.q("SELECT kind,COUNT(*) n FROM progress_events WHERE day=? GROUP BY kind", today)}
    xp = db.q1("SELECT COALESCE(SUM(xp),0) n FROM progress_events")["n"]
    days = {r["day"] for r in db.q("SELECT day FROM progress_events WHERE kind IN ('reading','answer') GROUP BY day HAVING SUM(CASE WHEN kind='reading' THEN 1 ELSE 0 END)>=? OR SUM(CASE WHEN kind='answer' THEN 1 ELSE 0 END)>=?", p.reading_goal, p.question_goal)}
    date = dt.date.fromisoformat(today)
    if today not in days:
        date -= dt.timedelta(days=1)
    streak = 0
    while date.isoformat() in days:
        streak += 1
        date -= dt.timedelta(days=1)
    badges = ["Chapter explorer"] if db.q1("SELECT 1 FROM progress_events WHERE kind='chapter'") else []
    if streak >= 7:
        badges.append("Seven day streak")
    return {"xp": xp, "level": 1 + xp // 100, "streak": streak, "reading_minutes": totals.get("reading", 0),
            "answers": totals.get("answer", 0), "reading_goal": p.reading_goal, "question_goal": p.question_goal,
            "challenge_complete": bool(totals.get("challenge")), "badges": badges, "enabled": p.gamification,
            "history": [dict(r) for r in db.q("SELECT day,SUM(CASE WHEN kind='reading' THEN 1 ELSE 0 END) reading_minutes,SUM(CASE WHEN kind='answer' THEN 1 ELSE 0 END) answers,SUM(xp) xp FROM progress_events GROUP BY day ORDER BY day DESC LIMIT 30")]}
