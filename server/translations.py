"""Versioned translation workspaces over immutable source block IDs."""
from __future__ import annotations

import json
import time
import uuid

from fastapi import HTTPException

from . import app_settings, db


def capture(doc_id: str):
    doc = db.get_doc(doc_id)
    if not doc or not doc.get("active_run"):
        return
    fields = ("translated", "translated_table", "status", "qa")
    snapshot = {
        "blocks": [{"seq": r["seq"], **{k: r[k] for k in fields}} for r in db.q("SELECT * FROM blocks WHERE doc_id=?", doc_id)],
        "document": {k: doc[k] for k in ("brief", "title_si", "stage", "stage_done", "stage_total", "translated", "failed", "status", "error", "batch_jobs")},
        "glossary": [dict(r) for r in db.q("SELECT * FROM glossary WHERE doc_id=?", doc_id)],
        "chunks": [dict(r) for r in db.q("SELECT * FROM chunks WHERE doc_id=?", doc_id)],
    }
    db.ex("UPDATE translation_runs SET snapshot=?,status=?,error=? WHERE id=?",
          json.dumps(snapshot, ensure_ascii=False), doc["status"], doc["error"], doc["active_run"])


def initial(doc_id: str, run_profile: dict | None = None):
    rid = uuid.uuid4().hex
    db.ex("INSERT INTO translation_runs(id,doc_id,profile,status,created_at) VALUES(?,?,?,?,?)",
          rid, doc_id, json.dumps(run_profile or app_settings.profile()), "queued", time.time())
    db.update_doc(doc_id, active_run=rid)
    return rid


def ensure_idle(doc_id: str):
    from .pipeline.jobs import worker
    doc = db.get_doc(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if worker.active == doc_id or doc["status"] in ("queued", "running", "waiting"):
        raise HTTPException(409, "Pause the active translation and wait until it stops before changing versions.")
    for job in json.loads(doc.get("batch_jobs") or "{}").values():
        if job.get("state") in ("submitted", "running"):
            raise HTTPException(409, "Wait for the submitted batch job before changing versions.")
    return doc


def new(doc_id: str):
    ensure_idle(doc_id)
    with db.tx():
        capture(doc_id)
        rid = initial(doc_id)
        db.ex("UPDATE blocks SET translated=NULL,translated_table=NULL,qa=NULL,status=CASE WHEN status='skip' THEN 'skip' ELSE 'pending' END,rev=? WHERE doc_id=?",
              db.next_rev(), doc_id)
        db.ex("DELETE FROM glossary WHERE doc_id=?", doc_id)
        db.ex("DELETE FROM chunks WHERE doc_id=?", doc_id)
        has_blocks = db.q1("SELECT 1 FROM blocks WHERE doc_id=?", doc_id)
        db.update_doc(doc_id, brief=None, title_si=None, translated=0, failed=0, batch_jobs=None, auto_translate=1,
                      stage="understand" if has_blocks else "parse", status="queued", stage_done=0, error=None)
    from .pipeline.jobs import worker
    worker.enqueue(doc_id)
    return rid


def activate(doc_id: str, run_id: str):
    doc = ensure_idle(doc_id)
    if doc["active_run"] == run_id:
        return
    r = db.q1("SELECT * FROM translation_runs WHERE id=? AND doc_id=?", run_id, doc_id)
    if not r or not r["snapshot"]:
        raise HTTPException(404, "Saved translation version not found")
    data = json.loads(r["snapshot"])
    with db.tx():
        capture(doc_id)
        for b in data["blocks"]:
            db.ex("UPDATE blocks SET translated=?,translated_table=?,status=?,qa=?,rev=? WHERE doc_id=? AND seq=?",
                  b["translated"], b["translated_table"], b["status"], b["qa"], db.next_rev(), doc_id, b["seq"])
        for table in ("glossary", "chunks"):
            db.ex(f"DELETE FROM {table} WHERE doc_id=?", doc_id)
            for row in data[table]:
                columns = list(row)
                db.ex(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", *row.values())
        patch = data["document"]
        patch["status"] = "paused" if patch["status"] in ("running", "queued", "waiting") else patch["status"]
        db.update_doc(doc_id, active_run=run_id, **patch)


def list_runs(doc_id: str):
    rows = db.q("SELECT id,profile,status,created_at,error FROM translation_runs WHERE doc_id=? ORDER BY created_at DESC", doc_id)
    return [dict(r) | {"profile": json.loads(r["profile"])} for r in rows]
