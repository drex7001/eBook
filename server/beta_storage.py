"""Additive beta schema. Original blocks remain the stable anchors for notes and positions."""
import json
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS translation_runs(
 id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, profile TEXT NOT NULL, status TEXT NOT NULL,
 created_at REAL NOT NULL, snapshot TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS runs_doc ON translation_runs(doc_id,created_at);
CREATE TABLE IF NOT EXISTS quiz_generation_responses(
 id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, batch_index INT NOT NULL,
 model TEXT, request TEXT NOT NULL, raw TEXT, parsed TEXT, usage TEXT NOT NULL,
 outcome TEXT NOT NULL, diagnostics TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS quiz_responses_paper ON quiz_generation_responses(paper_id,created_at);
CREATE TABLE IF NOT EXISTS ai_actions(
 key TEXT PRIMARY KEY, kind TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audio_grants(
 id TEXT PRIMARY KEY, doc_id TEXT, start_seq INT, end_seq INT, run_id TEXT, side TEXT,
 voice TEXT, expires REAL, revoked INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS quiz_papers(
 id TEXT PRIMARY KEY, doc_id TEXT, difficulty TEXT, version INT, language TEXT, scope TEXT,
 count INT, status TEXT, error TEXT, created_at REAL, request_key TEXT UNIQUE, profile TEXT);
CREATE TABLE IF NOT EXISTS subject_questions(
 id TEXT PRIMARY KEY, paper_id TEXT, fingerprint TEXT, question TEXT, options TEXT,
 answer INT, explanation TEXT, distractors TEXT, source_seq INT, source_quote TEXT, section INT);
CREATE TABLE IF NOT EXISTS quiz_attempts(
 id TEXT PRIMARY KEY, paper_id TEXT, mode TEXT, started_at REAL, deadline REAL,
 submitted_at REAL, answers TEXT DEFAULT '{}', score INT, request_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS subject_reviews(
 question_id TEXT PRIMARY KEY, due_at REAL, interval_days REAL DEFAULT 0, reps INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS progress_events(
 id TEXT PRIMARY KEY, kind TEXT, doc_id TEXT, subject TEXT, amount INT, day TEXT, at REAL, xp INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS progress_day ON progress_events(day,kind);
CREATE TABLE IF NOT EXISTS quiz_choices(
 token TEXT PRIMARY KEY, word_id INT, item_id INT, kind TEXT, answer INT, used INT DEFAULT 0);
"""


def init_beta(c):
    c.executescript(SCHEMA)
    # Existing single-language documents become an immutable first translation version.
    from .config import settings
    base_profile = {"source_language": "en", "target_language": "si", "purpose": "reading",
                    "translation_style": "conversational", "keep_terms": True,
                    "prompt_version": "legacy-v1", "light_model": settings.gemini_understand_model}
    for row in c.execute("SELECT id,provider,model FROM documents WHERE active_run IS NULL").fetchall():
        profile = json.dumps(base_profile | {"provider": row["provider"] or settings.llm_provider,
                                            "model": row["model"] or settings.model_label})
        rid = "legacy-" + row["id"]
        c.execute("INSERT OR IGNORE INTO translation_runs(id,doc_id,profile,status,created_at) VALUES(?,?,?,?,?)",
                  (rid, row["id"], profile, "legacy", time.time()))
        c.execute("UPDATE documents SET active_run=? WHERE id=?", (rid, row["id"]))
