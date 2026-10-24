import time

from server import db, vocab
from server.config import settings
from server.llm import get_llm


def setup_module():
    db.init()


def test_schedule_progression():
    w = {"ease": 2.5, "reps": 0, "interval_days": 0, "lapses": 0}
    now = 1_000_000.0
    a = vocab.schedule(w, True, now)
    assert a["interval_days"] == 1 and a["reps"] == 1
    b = vocab.schedule({**w, **a}, True, now)
    assert b["interval_days"] == 3
    c = vocab.schedule({**w, **b}, True, now)
    assert c["interval_days"] == round(3 * b["ease"], 1)
    d = vocab.schedule({**w, **c}, False, now)
    assert d["reps"] == 0 and d["lapses"] == 1 and d["due_at"] == now + 600 and d["ease"] < c["ease"]


def test_lookup_save_practice_flow():
    llm = get_llm(settings, "understand")
    card = vocab.lookup("Interoperability,", None, None, llm)
    assert card["word"] == "Interoperability" and card["meaning_si"] and card["saved_id"] is None
    n_calls = db.q1("SELECT COUNT(*) AS n FROM usage_log WHERE purpose='lookup'")["n"]
    vocab.lookup("Interoperability", None, None, llm)          # cached
    assert db.q1("SELECT COUNT(*) AS n FROM usage_log WHERE purpose='lookup'")["n"] == n_calls

    w = vocab.save_word(card)
    assert w["lemma"] == "interoperability" and w["examples"]
    assert vocab.lookup("interoperability", None, None, llm)["saved_id"] == w["id"]

    qs = vocab.practice_set(10, llm)
    q = next(q for q in qs if q["word"]["id"] == w["id"])
    assert q["kind"] in vocab.KINDS and len(q["options"]) == 4
    assert q["options"][q["answer"]] == w["word"]   # mock puts the word as the right answer
    upd = vocab.record_answer(w["id"], q["kind"], True)
    assert upd["due_at"] > time.time() + 3600
    s = vocab.stats()
    assert s["total"] >= 1 and s["reviewed_today"] >= 1 and s["streak"] == 1
    # the word is no longer due, so the next set is empty of it
    assert all(x["word"]["id"] != w["id"] for x in vocab.practice_set(10, llm))
