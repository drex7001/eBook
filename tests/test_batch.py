"""Batch API: response parsing, and the whole pipeline in batch mode against the mock provider."""
import json
import shutil

import httpx
import pytest

from conftest import SAMPLE
from server.config import settings
from server.llm.gemini import GeminiProvider, batch_results, batch_state


def test_batch_state_and_results_shapes():
    op = {"name": "batches/1", "metadata": {"@type": "x", "state": "BATCH_STATE_RUNNING"}}
    assert batch_state(op) == "RUNNING"
    assert batch_state({"name": "batches/1", "state": "JOB_STATE_SUCCEEDED"}) == "SUCCEEDED"
    done = {"name": "batches/1", "done": True, "metadata": {"state": "BATCH_STATE_SUCCEEDED"},
            "response": {"@type": "t", "inlinedResponses": {"inlinedResponses": [
                {"metadata": {"key": "t0"}, "response": {"candidates": [{"content": {"parts": [{"text": '{"translations": []}'}]}}],
                                                       "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}},
                {"metadata": {"key": "t1"}, "error": {"code": 400, "message": "bad"}}]}}}
    res = batch_results(done)
    assert res[0][0] == "t0" and res[0][1].prompt_tokens == 10 and res[0][1].batch
    assert res[1] == ("t1", None, "bad")


def test_batch_create_request_shape():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"name": "batches/abc", "metadata": {"state": "BATCH_STATE_PENDING"}})

    settings.gemini_api_key = "k"
    p = GeminiProvider(settings, model="gemini-test")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    name = p.batch_create([("t0", "SYS", "PROMPT", {"type": "object"})], "doc (translate)")
    assert name == "batches/abc"
    assert seen["url"].endswith("/v1beta/models/gemini-test:batchGenerateContent")
    r = seen["body"]["batch"]["input_config"]["requests"]["requests"][0]
    assert r["metadata"] == {"key": "t0"} and r["request"]["systemInstruction"]["parts"][0]["text"] == "SYS"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample PDF missing")
def test_pipeline_in_batch_mode():
    from server import db
    from server.pipeline import jobs

    db.init()
    doc_id = "batchdoc1"
    d = jobs.doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLE, d / "source.pdf")
    db.ex("INSERT INTO documents(id, title, filename, status, stage, mode, created_at, updated_at) VALUES(?,?,?,?,?,?,0,0)",
          doc_id, "1706.03762v7", "1706.03762v7.pdf", "queued", "parse", "batch")
    w = jobs.Worker()
    w._run(doc_id)                                    # parse, then submit pass 1 as a batch job
    doc = db.get_doc(doc_id)
    assert doc["status"] == "waiting" and json.loads(doc["batch_jobs"])["understand"]["state"] == "submitted"
    w.poll(doc_id)                                    # job done -> summaries stored, doc re-queued
    assert db.get_doc(doc_id)["status"] == "queued"
    w._run(doc_id)                                    # brief, then pass 2 as a batch job
    assert json.loads(db.get_doc(doc_id)["batch_jobs"])["translate"]["state"] == "submitted"
    w.poll(doc_id)
    w._run(doc_id)                                    # leftovers through the normal path
    doc = db.get_doc(doc_id)
    assert doc["status"] == "done" and doc["translated"] == doc["translatable"] > 80
    n_batch = db.q1("SELECT COUNT(*) AS n FROM usage_log WHERE doc_id=? AND batch=1", doc_id)["n"]
    assert n_batch >= 3


def test_work_units_merge_small_sections():
    from server import db
    from server.pipeline.translate import work_units

    db.init()
    doc_id = "wu1"
    with db.tx() as c:
        for i, (a, b) in enumerate([(0, 1), (2, 3), (4, 5), (6, 7)]):
            c.execute("INSERT INTO sections(doc_id, idx, title, start_seq, end_seq) VALUES(?,?,?,?,?)", (doc_id, i, f"s{i}", a, b))
        for seq in range(8):
            c.execute("INSERT INTO blocks(doc_id, seq, type, source, status, section) VALUES(?,?,?,?,?,?)",
                      (doc_id, seq, "paragraph", "x" * 1000, "pending", seq // 2))
    assert work_units(doc_id, 8000) == [(0, 7)]
    assert work_units(doc_id, 4000) == [(0, 3), (4, 7)]
    assert work_units(doc_id, 2000) == [(0, 1), (2, 3), (4, 5), (6, 7)]
    assert work_units(doc_id, 5000) == [(0, 5), (6, 7)]
    assert work_units(doc_id, 7000) == [(0, 7)]          # 2000-char tail folds into the previous group
