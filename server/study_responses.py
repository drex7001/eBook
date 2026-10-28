"""Durable quiz responses and conservative, offline validation/recovery.

Store paid output BEFORE checking it. Normalization repairs representations, never
invents an answer or substitutes a translated/paraphrased quote for source evidence.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import random
import re
import time
import unicodedata
import uuid

from . import db
from .ai_safety import LOCK
from .llm.base import parse_json_loose

REASONS = {
    "invalid_response": "The response does not contain a questions array.",
    "empty_response": "The provider returned no questions.",
    "invalid_question": "A question must be an object with question text.",
    "invalid_options": "Four non-empty, distinct options are required.",
    "invalid_answer": "The correct answer must identify exactly one option (0–3 or A–D).",
    "invalid_source_seq": "The question refers to a source ID that was not supplied.",
    "missing_source_quote": "A supporting quote from the original source is missing.",
    "source_quote_mismatch": "The quote does not match the original source. Quotes must stay in the source language; PDF spacing and typography are normalized locally.",
    "missing_explanation": "The answer explanation is missing.",
    "invalid_option_explanations": "Option explanations could not be matched to the four options.",
    "duplicate_question": "The response repeats a question already saved in this paper.",
    "extra_questions": "The response contains more questions than requested; the extra output is retained in the saved response.",
    "incomplete_response": "The response did not supply all requested valid questions. Generation stopped without an automatic retry.",
    "provider_error": "The provider request failed. It was not automatically repeated.",
    "malformed_json": "The provider returned output that could not be parsed as JSON. The output was saved without another generation request.",
}


def save_response(paper_id: str, batch_index: int, payload: dict, result, error: str | None = None, model: str = "", response_id: str | None = None) -> str:
    rid = response_id or uuid.uuid4().hex
    usage = {"response_received": result is not None,
             "input_tokens": result.prompt_tokens if result else None,
             "output_tokens": result.output_tokens if result else None,
             "cached_tokens": result.cached_tokens if result else None,
             "thinking_tokens": result.thought_tokens if result else None,
             "cost_usd": db.cost_of(result) if result else None,
             "estimate_known": bool(result and (result.model == "mock" or db.price_for_model(result.model)))}
    diagnostics = [{"code": error, "message": REASONS.get(error, REASONS["provider_error"])}] if error else []
    values = (result.model if result else model, json.dumps(payload, ensure_ascii=False),
              result.raw if result else None, json.dumps(result.data, ensure_ascii=False) if result else None,
              json.dumps(usage), "saved" if not error else "provider_error", json.dumps(diagnostics))
    if response_id:
        db.ex("UPDATE quiz_generation_responses SET model=?,request=?,raw=?,parsed=?,usage=?,outcome=?,diagnostics=? WHERE id=?", *values, rid)
    else:
        db.ex("INSERT INTO quiz_generation_responses(id,paper_id,batch_index,model,request,raw,parsed,usage,outcome,diagnostics,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              rid, paper_id, batch_index, *values, time.time())
    return rid


def reserve_response(paper_id, batch_index, payload, model):
    # Verify writable storage before making a potentially billable request.
    rid = save_response(paper_id, batch_index, payload, None, model=model)
    db.ex("UPDATE quiz_generation_responses SET outcome='requesting' WHERE id=?", rid)
    return rid


def _integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value)
    return None


def _ordered(value):
    if not isinstance(value, dict):
        return value
    upper = {str(k).strip().upper(): v for k, v in value.items()}
    for keys in (("A", "B", "C", "D"), ("0", "1", "2", "3")):
        if set(upper) == set(keys):
            return [upper[k] for k in keys]
    return value


def normalize_question(item):
    if not isinstance(item, dict):
        return item
    q = dict(item)
    options = _ordered(q.get("options"))
    if isinstance(options, list):
        options = [o.get("text", o.get("option")) if isinstance(o, dict) else o for o in options]
        options = [o.strip() if isinstance(o, str) else o for o in options]
    q["options"] = options
    answer = q.get("answer", q.get("correct_answer", q.get("correct_option")))
    index = _integer(answer)
    if index is None and isinstance(answer, str):
        match = re.fullmatch(r"\s*([A-Da-d])[).:]?\s*", answer)
        if match:
            index = ord(match[1].upper()) - ord("A")
        elif isinstance(options, list):
            matches = [i for i, o in enumerate(options) if isinstance(o, str) and o == answer.strip()]
            if len(matches) == 1:
                index = matches[0]
    q["answer"] = index
    q["source_seq"] = _integer(q.get("source_seq"))
    for key in ("question", "explanation", "source_quote"):
        if isinstance(q.get(key), str):
            q[key] = q[key].strip()
    reasons = _ordered(q.get("option_explanations", q.get("distractors")))
    # "Distractors" conventionally means only the three WRONG options. The old
    # contract used that name for four explanations, incorrectly rejecting this case.
    if "option_explanations" not in q and type(index) is int and 0 <= index < 4:
        if isinstance(reasons, list) and len(reasons) == 3:
            reasons = reasons.copy()
            reasons.insert(index, q.get("explanation"))
        elif isinstance(reasons, dict):
            upper = {str(k).strip().upper(): v for k, v in reasons.items()}
            expected = {chr(65 + i) for i in range(4) if i != index}
            if set(upper) == expected:
                reasons = [q.get("explanation") if i == index else upper[chr(65 + i)] for i in range(4)]
    q["distractors"] = reasons
    return q


def _evidence(text: str, join_hyphens: bool = True) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                                       "\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-",
                                       "\u00ad": "", "\u200b": "", "\ufeff": ""}))
    text = re.sub(r"(?<=\w)-[ \t]*\r?\n\s*(?=\w)", "" if join_hyphens else "-", text)
    return " ".join(text.split())


def validate(item, source_map):
    q = normalize_question(item)
    if not isinstance(q, dict) or not isinstance(q.get("question"), str) or not q["question"]:
        return None, ["invalid_question"]
    issues = []
    options = q.get("options")
    if (not isinstance(options, list) or len(options) != 4
        or not all(isinstance(o, str) and o for o in options)
        or len({_evidence(o).casefold() for o in options if isinstance(o, str)}) != 4):
        issues.append("invalid_options")
    answer, seq = q.get("answer"), q.get("source_seq")
    if type(answer) is not int or not 0 <= answer < 4:
        issues.append("invalid_answer")
    if type(seq) is not int or seq not in source_map:
        issues.append("invalid_source_seq")
    quote = q.get("source_quote")
    if not isinstance(quote, str) or len(quote) < 12:
        issues.append("missing_source_quote")
    elif seq in source_map:
        source = source_map[seq].get("source", source_map[seq].get("text", ""))
        if not any(_evidence(quote, a) in _evidence(source, b) for a in (True, False) for b in (True, False)):
            issues.append("source_quote_mismatch")
    if not isinstance(q.get("explanation"), str) or not q["explanation"]:
        issues.append("missing_explanation")
    reasons = q.get("distractors")
    if not isinstance(reasons, list) or len(reasons) != 4 or not all(isinstance(r, str) and r.strip() for r in reasons):
        issues.append("invalid_option_explanations")
    return (None if issues else q), issues


def response_questions(row):
    try:
        data = json.loads(row["parsed"]) if row["parsed"] else None
    except (TypeError, ValueError):
        data = None
    if not data or not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raw = row["raw"] or ""
        try:
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            value = json.loads(clean)
            data = {"questions": value} if isinstance(value, list) else value
        except (TypeError, ValueError):
            try:
                data = parse_json_loose(raw)
            except (TypeError, ValueError):
                return None
    return data.get("questions") if isinstance(data, dict) and isinstance(data.get("questions"), list) else None


def fingerprint(doc_id, q):
    return hashlib.sha256((doc_id + json.dumps(sorted(q["options"]), ensure_ascii=False) + q["question"].casefold()).encode()).hexdigest()


def accept_response(response_id: str, *, recovery: bool = False):
    """Re-use the archived source/response; never calls a model."""
    with LOCK:
        row = db.q1("SELECT * FROM quiz_generation_responses WHERE id=?", response_id)
        p = db.q1("SELECT * FROM quiz_papers WHERE id=?", row["paper_id"])
        payload = json.loads(row["request"])
        sources = {int(s["seq"]): {"source": s["text"], "section": s.get("section", 0)} for s in payload["sources"]}
        questions = response_questions(row)
        reports = []
        accepted = 0
        if questions is None:
            reports.append({"code": "invalid_response", "message": REASONS["invalid_response"]})
        elif not questions:
            reports.append({"code": "empty_response", "message": REASONS["empty_response"]})
        existing = {q["fingerprint"] for q in db.q("SELECT fingerprint FROM subject_questions WHERE paper_id=?", p["id"])}
        seen = set()
        for index, item in enumerate(questions or []):
            q, issues = validate(item, sources)
            if q:
                key = fingerprint(p["doc_id"], q)
                if key in seen or (key in existing and not recovery):
                    issues = ["duplicate_question"]
                else:
                    seen.add(key)
                    if key in existing:
                        accepted += 1
                        continue
                    n = db.q1("SELECT COUNT(*) n FROM subject_questions WHERE paper_id=?", p["id"])["n"]
                    if n >= p["count"]:
                        issues = ["extra_questions"]
                    else:
                        order = list(range(4))
                        random.shuffle(order)
                        db.ex("INSERT INTO subject_questions(id,paper_id,fingerprint,question,options,answer,explanation,distractors,source_seq,source_quote,section) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                              uuid.uuid4().hex, p["id"], key, q["question"],
                              json.dumps([q["options"][i] for i in order], ensure_ascii=False), order.index(q["answer"]),
                              q["explanation"], json.dumps([q["distractors"][i] for i in order], ensure_ascii=False),
                              q["source_seq"], q["source_quote"], sources[q["source_seq"]]["section"])
                        existing.add(key)
                        accepted += 1
            if issues:
                reports.append({"question_index": index, "codes": issues,
                                "messages": [REASONS[code] for code in issues]})
        if accepted < payload["count"]:
            reports.append({"code": "incomplete_response", "message": REASONS["incomplete_response"]})
        outcome = "accepted" if not reports else "partial" if accepted else "rejected"
        db.ex("UPDATE quiz_generation_responses SET outcome=?,diagnostics=? WHERE id=?", outcome,
              json.dumps(reports, ensure_ascii=False), response_id)
        return accepted, reports


def summary(paper_id: str):
    records = db.q("SELECT * FROM quiz_generation_responses WHERE paper_id=? ORDER BY created_at", paper_id)
    counts = Counter()
    returned = 0
    for row in records:
        returned += len(response_questions(row) or [])
        for entry in json.loads(row["diagnostics"]):
            counts.update(entry.get("codes", [entry["code"]] if "code" in entry else []))
    usage = [json.loads(row["usage"]) for row in records]
    return {"requests": len(records), "responses_saved": sum(u["response_received"] for u in usage),
            "returned_questions": returned if records else None,
            "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
            "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
            "estimated_cost_usd": sum(u.get("cost_usd") or 0 for u in usage),
            "estimate_known": bool(usage) and all(u.get("estimate_known") for u in usage),
            "diagnostics": [{"code": code, "count": count, "message": REASONS.get(code, code)} for code, count in counts.items()],
            "response_ids": [r["id"] for r in records]}
