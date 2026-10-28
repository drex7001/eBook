"""Explicit generation admission and durable duplicate-action suppression."""
import hashlib
import json
import threading
import time

from fastapi import HTTPException

from . import db

LOCK = threading.RLock()


def confirmed(value: bool):
    if not value:
        raise HTTPException(409, "Confirm this AI action before generating new content.")


def once(key: str, kind: str, payload, operation):
    if not key or len(key) > 150:
        raise HTTPException(400, "A request key is required")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with LOCK:
        row = db.q1("SELECT * FROM ai_actions WHERE key=?", key)
        if row:
            if row["kind"] != kind or row["fingerprint"] != fingerprint:
                raise HTTPException(409, "This request key belongs to a different action")
            if not row["result"]:
                raise HTTPException(409, "This action was interrupted. Check its status before explicitly retrying with a new request key.")
            return json.loads(row["result"])
        db.ex("INSERT INTO ai_actions(key,kind,fingerprint,created_at) VALUES(?,?,?,?)", key, kind, fingerprint, time.time())
        result = operation()
        db.ex("UPDATE ai_actions SET result=? WHERE key=?", json.dumps(result, ensure_ascii=False), key)
        return result
