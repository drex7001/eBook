"""Quiz regression cases using real provider adapters with recorded HTTP shapes.

No API keys or real provider calls. Covers output preservation and fail-fast cost
behaviour, rather than relying only on the always-conforming MockProvider.
"""
from dataclasses import replace
import json
import sqlite3
import time
import uuid
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from server import app_settings, db, study, study_generation, study_responses
from server.api import app
from server.config import settings
from server.llm.base import LLMResult
from server.llm.gemini import GeminiProvider


@pytest.fixture
def paper_data():
    db.init()
    did, pid = uuid.uuid4().hex, uuid.uuid4().hex
    db.ex("INSERT INTO documents(id,title,status) VALUES(?,?,'done')", did, "Offline quiz regression")
    db.ex("INSERT INTO quiz_papers(id,doc_id,difficulty,version,language,scope,count,status,created_at,request_key,profile) VALUES(?,?,?,1,'si','{}',50,'queued',?,?,?)",
          pid, did, "hard", time.time(), uuid.uuid4().hex, json.dumps({"quiz_generation_version": "durable-v2"}))
    rows = [{"seq": i + 10, "section": i, "page": i,
             "source": f"Chapter {i}. Photosynthesis converts light energy into chemical energy. Plants combine water and carbon dioxide to produce sugars. Oxygen is released. " * 4}
            for i in range(20)]
    for row in rows:
        db.ex("INSERT INTO blocks(doc_id,seq,type,page,source,section,status) VALUES(?,?,'paragraph',?,?,?,'done')",
              did, row["seq"], row["page"], row["source"], row["section"])
    return pid, did, rows


def candidate(source, number=0):
    return {"question": f"ප්‍රශ්නය {number}: ආලෝක ශක්තිය ගැන source එකේ කියන්නේ මොකක්ද?",
            "options": ["අඩු වෙනවා", "රසායනික ශක්තිය බවට හරවනවා", "වෙනස් වෙන්නේ නෑ", "සෑම විටම නැති වෙනවා"],
            "answer": 1, "explanation": "ශක්තිය වෙනත් ආකාරයකට හරවනවා.",
            "option_explanations": ["Source එකේ මේක නෑ.", "Source එකෙන් සහාය ලැබෙනවා.", "Source එකට විරුද්ධයි.", "Source එකේ මේක නෑ."],
            "source_seq": source["seq"], "source_quote": source["text"][:110]}


def provider(handler):
    cfg = replace(settings, gemini_api_key="offline-test-key")
    client = GeminiProvider(cfg, model="gemini-3.5-flash-lite", thinking="")
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def http_body(data):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(data, ensure_ascii=False)}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 150, "candidatesTokenCount": 200}}


def request_payload(request):
    body = json.loads(request.content)
    return json.loads(body["contents"][0]["parts"][0]["text"].split("<QUIZ_INPUT>")[1].split("</QUIZ_INPUT>")[0])


def test_invalid_first_response_is_saved_and_stops_all_remaining_calls(paper_data):
    pid, did, rows = paper_data
    seen = []
    def handler(request):
        payload = request_payload(request)
        item = candidate(payload["sources"][0])
        item["source_quote"] = "මෙය original English source එකේ නැති සිංහල quote එකක්."
        seen.append({"questions": [item]})
        return httpx.Response(200, json=http_body(seen[-1]))
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    p = study.paper(pid)
    assert p["status"] == "error" and not p["questions"]
    assert len(seen) == 1  # Previously: 40 requests for a 50-question / 20-section paper.
    archive = db.q1("SELECT * FROM quiz_generation_responses WHERE paper_id=?", pid)
    assert json.loads(archive["raw"]) == seen[0]
    assert json.loads(archive["parsed"]) == seen[0]
    assert json.loads(archive["usage"])["output_tokens"] == 200
    assert db.q1("SELECT COUNT(*) n FROM usage_log WHERE doc_id=? AND purpose='subject_quiz'", did)["n"] == 1
    assert {d["code"] for d in p["generation"]["diagnostics"]} == {"source_quote_mismatch", "incomplete_response"}
    assert p["generation"]["returned_questions"] == 1 and p["generation"]["responses_saved"] == 1
    assert len(p["error"]) < 250


def test_valid_questions_survive_a_partially_invalid_response(paper_data):
    pid, _, rows = paper_data
    calls = []
    def handler(request):
        payload = request_payload(request)
        good = candidate(payload["sources"][0], 1)
        bad = candidate(payload["sources"][1], 2)
        bad["answer"] = 99
        calls.append(1)
        return httpx.Response(200, json=http_body({"questions": [good, bad]}))
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    p = study.paper(pid)
    assert len(calls) == 1 and p["status"] == "partial" and len(p["questions"]) == 1
    assert p["generation"]["returned_questions"] == 2
    client = TestClient(app)
    try:
        saved = client.get(f"/api/papers/{pid}/responses").json()["responses"]
        assert len(saved[0]["questions"]) == 2
    finally:
        client.close()


def test_small_sections_are_batched_into_13_responses_for_50_questions(paper_data):
    pid, _, rows = paper_data
    calls = []
    def handler(request):
        payload = request_payload(request)
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]["properties"]["questions"]["items"]
        assert schema["properties"]["source_seq"]["enum"] == [s["seq"] for s in payload["sources"]]
        assert "option_explanations" in schema["required"]
        assert "NEVER translate" in schema["properties"]["source_quote"]["description"]
        number = len(calls) * 4
        calls.append(payload)
        return httpx.Response(200, json=http_body({"questions": [candidate(payload["sources"][i % len(payload["sources"])], number+i) for i in range(payload["count"])]}))
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    p = study.paper(pid)
    assert p["status"] == "ready" and len(p["questions"]) == 50
    assert len(calls) == p["generation"]["requests"] == p["generation"]["max_requests"] == 13
    assert p["generation"]["responses_saved"] == 13
    assert len({r["section"] for r in db.q("SELECT section FROM subject_questions WHERE paper_id=?", pid)}) == 20


def test_three_wrong_option_explanations_and_letter_answer_are_repaired_locally(paper_data):
    pid, _, rows = paper_data
    db.ex("UPDATE quiz_papers SET count=1 WHERE id=?", pid)
    calls = []
    def handler(request):
        payload = request_payload(request)
        item = candidate(payload["sources"][0])
        item["distractors"] = [item["option_explanations"][i] for i in (0,2,3)]
        del item["option_explanations"]
        item["answer"] = "B"
        item["source_seq"] = str(item["source_seq"])
        calls.append(item)
        return httpx.Response(200, json=http_body({"questions": [item]}))
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    q = db.q1("SELECT * FROM subject_questions WHERE paper_id=?", pid)
    assert study.paper(pid)["status"] == "ready" and len(calls) == 1
    assert json.loads(q["options"])[q["answer"]] == calls[0]["options"][1]
    assert json.loads(q["distractors"])[q["answer"]] == calls[0]["explanation"]


def test_pdf_typography_is_normalized_but_translated_or_changed_evidence_is_rejected():
    source = "The ofﬁce’s inter-\nnational team uses\u00a0light energy. The measured value is 42."
    item = candidate({"seq": 7, "text": source})
    item["source_quote"] = "The office's international team uses light energy."
    assert study.validate_question(item, {7: {"source": source}})
    item["source_quote"] = "The measured value is 43."
    assert not study.validate_question(item, {7: {"source": source}})
    item["source_quote"] = "මනින ලද අගය හතළිස් දෙකයි කියලා කියනවා."
    assert not study.validate_question(item, {7: {"source": source}})


def test_output_is_committed_before_validation_and_available_after_validation_crash(paper_data, monkeypatch):
    pid, _, rows = paper_data
    def handler(request):
        p = request_payload(request)
        return httpx.Response(200, json=http_body({"questions": [candidate(p["sources"][0])]}))
    def crash(*args, **kwargs):
        archive = db.q1("SELECT raw FROM quiz_generation_responses WHERE paper_id=?", pid)
        assert archive and json.loads(archive["raw"])["questions"]
        raise RuntimeError("simulated validator failure")
    monkeypatch.setattr(study_responses, "accept_response", crash)
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    assert db.q1("SELECT raw FROM quiz_generation_responses WHERE paper_id=?", pid)["raw"]
    assert study.paper(pid)["status"] == "error"


def test_storage_failure_prevents_a_provider_call(paper_data, monkeypatch):
    pid, _, rows = paper_data
    model = Mock(model="test-model")
    monkeypatch.setattr(study_responses, "reserve_response", Mock(side_effect=sqlite3.OperationalError("disk full")))
    study_generation.generate(pid, rows, settings, lambda *_: model)
    assert not model.generate_json.called
    assert study.paper(pid)["status"] == "error"


def test_saved_output_can_be_rechecked_without_any_provider_call(paper_data, monkeypatch):
    pid, _, rows = paper_data
    db.ex("UPDATE quiz_papers SET count=1,status='error' WHERE id=?", pid)
    payload = next(study_generation.request_groups(rows, 1))
    item = candidate(payload["sources"][0])
    item["distractors"] = [item["option_explanations"][i] for i in (0,2,3)]
    item.pop("option_explanations")
    data = {"questions": [item]}
    rid = study_responses.save_response(pid, 0, payload, LLMResult(data, 120, 200, json.dumps(data), model="gemini-3.5-flash-lite"))
    factory = Mock(side_effect=AssertionError("Local recovery must not construct a provider"))
    monkeypatch.setattr(study, "get_llm", factory)
    client = TestClient(app)
    try:
        result = client.post(f"/api/papers/{pid}/recheck")
        assert result.status_code == 200 and len(result.json()["questions"]) == 1
        question_id = result.json()["questions"][0]["id"]
        assert client.post(f"/api/papers/{pid}/recheck").json()["questions"][0]["id"] == question_id
        saved = client.get(f"/api/papers/{pid}/responses").json()["responses"]
        assert len(saved) == 1 and saved[0]["id"] == rid and json.loads(saved[0]["raw"]) == data
        attempt = client.post(f"/api/papers/{pid}/attempts", json={"mode":"exam","request_key":uuid.uuid4().hex}).json()
        assert client.get(f"/api/papers/{pid}/responses").status_code == 403
        assert client.post(f"/api/papers/{pid}/recheck").status_code == 409
        assert "answer" not in attempt["questions"][0]
        assert not factory.called
    finally:
        client.close()


@pytest.mark.parametrize("kind", ["json", "wrapper", "429", "timeout"])
def test_subject_provider_failures_are_not_retried_and_received_bytes_are_retained(paper_data, kind):
    pid, did, rows = paper_data
    calls = []
    raw = '```json\n{"questions": [unfinished response'
    def handler(request):
        calls.append(1)
        if kind == "timeout":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        if kind == "429":
            return httpx.Response(429, json={"error": {"message":"quota"}})
        if kind == "wrapper":
            return httpx.Response(200, text=raw)
        return httpx.Response(200, json={"candidates":[{"content":{"parts":[{"text":raw}]},"finishReason":"MAX_TOKENS"}],
                                       "usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":20}})
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    assert len(calls) == 1
    archive = db.q1("SELECT * FROM quiz_generation_responses WHERE paper_id=?", pid)
    assert archive
    if kind in ("json", "wrapper"):
        assert archive["raw"] == raw
        assert json.loads(archive["usage"])["response_received"]
        assert db.q1("SELECT COUNT(*) n FROM usage_log WHERE doc_id=?", did)["n"] == 1
    else:
        assert archive["raw"] is None
        assert not json.loads(archive["usage"])["response_received"]


def test_stop_saves_inflight_output_without_starting_another_batch(paper_data):
    pid, _, rows = paper_data
    calls = []
    def handler(request):
        p = request_payload(request)
        calls.append(1)
        study_generation.stop(pid)
        return httpx.Response(200, json=http_body({"questions": [candidate(p["sources"][i], i) for i in range(p["count"])]}))
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    p = study.paper(pid)
    assert len(calls) == 1 and p["status"] == "paused"
    assert len(p["questions"]) == 4 and p["generation"]["responses_saved"] == 1


def test_stopping_cannot_start_an_attempt_while_output_is_still_inflight(paper_data):
    from fastapi import HTTPException
    pid, _, rows = paper_data
    calls = []
    def handler(request):
        payload = request_payload(request)
        offset = len(calls)*4
        calls.append(1)
        if len(calls) == 2:
            study_generation.stop(pid)
            assert study.paper(pid)["status"] == "stopping"
            with pytest.raises(HTTPException):
                study.start(pid, "study", 30, uuid.uuid4().hex)
            with pytest.raises(HTTPException):
                study_generation.recover(pid)
        return httpx.Response(200, json=http_body({"questions": [candidate(payload["sources"][i], offset+i) for i in range(payload["count"])]}))
    study_generation.generate(pid, rows, settings, lambda *_: provider(handler))
    assert len(calls) == 2 and study.paper(pid)["status"] == "paused"
    assert len(study.start(pid,"study",30,uuid.uuid4().hex)["questions"]) == 8


def test_legacy_failures_report_unrecoverable_output_without_repeated_errors(paper_data, monkeypatch):
    pid, _, _ = paper_data
    db.ex("UPDATE quiz_papers SET status='error',profile='{}',error=? WHERE id=?",
          "Some generated questions did not pass source/format checks. " * 20, pid)
    model = Mock(side_effect=AssertionError("No generation"))
    monkeypatch.setattr(study, "get_llm", model)
    p = study.paper(pid)
    assert p["generation"]["legacy_unarchived"] and p["generation"]["responses_saved"] == 0
    assert p["error"].count("Some generated") == 1
    client = TestClient(app)
    try:
        assert client.post(f"/api/papers/{pid}/recheck").status_code == 409
        assert not model.called
    finally:
        client.close()
