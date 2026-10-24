"""Background worker: parse -> understand -> translate, one document at a time, resumable."""
from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
import time
from pathlib import Path

from .. import db
from ..config import settings
from ..llm import LLMError, get_llm
from ..llm.gemini import batch_results, batch_state
from ..parser import get_parser
from . import translate, understand
from .common import Paused, TRANSLATABLE_TEXT

log = logging.getLogger(__name__)


def doc_dir(doc_id: str) -> Path:
    return Path(settings.data_dir) / "docs" / doc_id


def parse_stage(doc_id: str) -> None:
    d = doc_dir(doc_id)
    assets = d / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    parser = get_parser()
    db.update_doc(doc_id, stage="parse", stage_done=0, parser=parser.name)
    parsed = parser.parse(str(d / "source.pdf"), str(assets),
                          progress=lambda done, total: db.update_doc(doc_id, stage_done=done, stage_total=total))
    starts = [s.start_seq for s in parsed.sections] + [len(parsed.blocks)]
    rev = db.next_rev()
    with db.tx() as c:
        for t in ("blocks", "sections", "chunks", "glossary"):
            c.execute(f"DELETE FROM {t} WHERE doc_id=?", (doc_id,))
        for i, s in enumerate(parsed.sections):
            c.execute("INSERT INTO sections(doc_id, idx, title, start_seq, end_seq) VALUES(?,?,?,?,?)",
                      (doc_id, i, s.title, s.start_seq, starts[i + 1] - 1))
        sec = 0
        for b in parsed.blocks:
            while sec + 1 < len(parsed.sections) and b.seq >= starts[sec + 1]:
                sec += 1
            c.execute(
                "INSERT INTO blocks(doc_id, seq, type, level, page, regions, image, source, source_table, table_mode, "
                "status, section, rev) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, b.seq, b.type, b.level, b.page, json.dumps([r.as_dict() for r in b.regions]), b.image,
                 b.text, json.dumps(b.table, ensure_ascii=False) if b.table else None, b.table_mode,
                 "pending" if b.translatable else "skip", sec, rev))
    doc = db.get_doc(doc_id)
    renamed = doc["title"] and doc["title"] != Path(doc["filename"]).stem
    title = doc["title"] if renamed else (parsed.title or doc["title"])
    db.update_doc(doc_id, title=title, page_count=parsed.page_count, page_sizes=json.dumps(parsed.page_sizes),
                  translatable=sum(1 for b in parsed.blocks if b.translatable))


class Worker:
    def __init__(self) -> None:
        self.q: "queue.Queue[str]" = queue.Queue()
        self.stop_flags: set[str] = set()
        self.active: str | None = None
        self.thread = threading.Thread(target=self._loop, daemon=True, name="pipeline")

    def start(self) -> None:
        self.thread.start()
        threading.Thread(target=self._poll_loop, daemon=True, name="batch-poller").start()
        for r in db.q("SELECT id FROM documents WHERE status IN ('queued','running') ORDER BY created_at"):
            db.update_doc(r["id"], status="queued")
            self.q.put(r["id"])

    def enqueue(self, doc_id: str) -> None:
        self.stop_flags.discard(doc_id)
        db.update_doc(doc_id, status="queued", error=None)
        self.q.put(doc_id)

    def pause(self, doc_id: str) -> None:
        self.stop_flags.add(doc_id)
        if self.active != doc_id:
            db.update_doc(doc_id, status="paused")

    def _loop(self) -> None:
        while True:
            doc_id = self.q.get()
            doc = db.get_doc(doc_id)
            if not doc or doc["status"] not in ("queued",) or doc_id in self.stop_flags:
                continue
            self.active = doc_id
            try:
                self._run(doc_id)
            except Paused:
                db.update_doc(doc_id, status="paused")
            except Exception as e:  # noqa: BLE001
                log.exception("job failed for %s", doc_id)
                db.update_doc(doc_id, status="error", error=str(e)[:1000])
            finally:
                self.active = None

    def _run(self, doc_id: str) -> None:
        stop = lambda: doc_id in self.stop_flags  # noqa: E731
        db.update_doc(doc_id, status="running", error=None)
        doc = db.get_doc(doc_id)
        stage = doc["stage"] or "parse"
        batch = (doc["mode"] or "standard") == "batch"
        if stage == "parse":
            t = time.time()
            parse_stage(doc_id)
            log.info("parsed %s in %.1fs", doc_id, time.time() - t)
            stage = "understand"
            db.update_doc(doc_id, stage=stage)
        if stop():
            raise Paused()
        if stage == "understand":
            if batch and self._submit_batch(doc_id, "understand"):
                return
            understand.run(doc_id, get_llm(settings, "understand"), settings, stop)
            stage = "translate"
            db.update_doc(doc_id, stage=stage)
        if stage in ("translate", "done"):
            if batch and self._submit_batch(doc_id, "translate"):
                return
            translate.run(doc_id, get_llm(settings, "translate"), settings, stop)
            db.update_doc(doc_id, stage="done", status="done")

    # ------------------------------------------------------------------ Batch API mode

    @staticmethod
    def _jobs(doc_id: str) -> dict:
        return json.loads(db.get_doc(doc_id)["batch_jobs"] or "{}")

    @staticmethod
    def _save_jobs(doc_id: str, jobs: dict) -> None:
        db.update_doc(doc_id, batch_jobs=json.dumps(jobs, ensure_ascii=False))

    def _submit_batch(self, doc_id: str, stage: str) -> bool:
        """Send this stage's calls as one Batch API job. True = job is out, the doc now waits for the poller.
        False = carry on normally (stage already batched, too small, or batch mode unavailable)."""
        jobs = self._jobs(doc_id)
        j = jobs.get(stage)
        if j and j.get("state") == "submitted":
            db.update_doc(doc_id, status="waiting", stage=stage)
            return True
        if j:
            return False                       # done or failed earlier: leftovers go through the normal path
        llm = get_llm(settings, "understand" if stage == "understand" else "translate")
        if not hasattr(llm, "batch_create"):
            jobs[stage] = {"state": "failed", "note": f"{settings.llm_provider} has no batch mode"}
            self._save_jobs(doc_id, jobs)
            return False
        if stage == "understand":
            reqs, keymap = understand.batch_requests(doc_id, settings), None
        else:
            reqs, keymap = translate.batch_requests(doc_id, llm, settings)
        size = sum(len(p.encode()) for _k, _s, p, _sc in reqs)
        if len(reqs) < 2 or size > 18_000_000:
            jobs[stage] = {"state": "failed", "note": "too small for a batch job" if len(reqs) < 2 else "too large for one job"}
            self._save_jobs(doc_id, jobs)
            return False
        title = db.get_doc(doc_id)["title"] or doc_id
        try:
            name = llm.batch_create(reqs, f"{title[:60]} ({stage})")
        except LLMError as e:
            log.warning("batch submit failed for %s: %s", doc_id, e)
            jobs[stage] = {"state": "failed", "note": str(e)[:300]}
            self._save_jobs(doc_id, jobs)
            return False
        jobs[stage] = {"state": "submitted", "name": name, "submitted_at": time.time(), "requests": len(reqs),
                       "model": llm.model, "keys": keymap}
        self._save_jobs(doc_id, jobs)
        db.update_doc(doc_id, status="waiting", stage=stage)
        log.info("batch job %s submitted for %s (%d requests)", name, doc_id, len(reqs))
        return True

    def _poll_loop(self) -> None:
        while True:
            time.sleep(max(10, settings.batch_poll_seconds))
            for r in db.q("SELECT id FROM documents WHERE status='waiting'"):
                try:
                    self.poll(r["id"])
                except Exception:  # noqa: BLE001
                    log.exception("batch poll failed for %s", r["id"])

    def poll(self, doc_id: str) -> None:
        jobs = self._jobs(doc_id)
        for stage, j in jobs.items():
            if j.get("state") != "submitted":
                continue
            llm = get_llm(settings, "understand" if stage == "understand" else "translate")
            st = llm.batch_get(j["name"])
            state = batch_state(st)
            j["last_state"], j["checked_at"] = state, time.time()
            if state in ("PENDING", "RUNNING", "UNSPECIFIED"):
                continue
            if state == "SUCCEEDED":
                results = batch_results(st)
                if stage == "understand":
                    n = understand.ingest_batch(doc_id, results, j["model"])
                else:
                    n = translate.ingest_batch(doc_id, results, j["keys"] or {}, llm, settings, j["model"])
                j.update(state="done", ingested=n, errors=sum(1 for _k, res, _e in results if res is None))
            else:
                j.update(state="failed", note=f"batch job ended as {state}")
        self._save_jobs(doc_id, jobs)
        if not any(j.get("state") == "submitted" for j in jobs.values()):
            self.enqueue(doc_id)               # continue: leftovers, brief, retries go through the normal path


worker = Worker()

__all__ = ["worker", "doc_dir", "TRANSLATABLE_TEXT"]
