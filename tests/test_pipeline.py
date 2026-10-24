"""End-to-end on the Attention paper with the mock provider: parse -> understand -> translate."""
import json
import shutil

import pytest

from conftest import SAMPLE

pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample/1706.03762v7.pdf not present")


def test_parse_attention_paper(tmp_path):
    from server.parser import get_parser
    doc = get_parser().parse(str(SAMPLE), str(tmp_path))
    types = [b.type for b in doc.blocks]
    assert doc.title == "Attention Is All You Need"
    assert types.count("figure") >= 4
    assert types.count("equation") >= 4
    assert types.count("reference") >= 30
    heads = [b.text for b in doc.blocks if b.type == "heading"]
    assert "3.2.1 Scaled Dot-Product Attention" in heads
    assert not any(h == "Scaled Dot-Product Attention" for h in heads)  # figure label glued into the figure
    caps = [b.text for b in doc.blocks if b.type == "caption"]
    assert any(c.startswith("Figure 2:") for c in caps)
    assert not any(c.startswith("Table 2 summarizes") for c in caps)
    assert [s.title for s in doc.sections][:3] == ["Front matter", "Introduction", "Background"]
    for b in doc.blocks:
        if b.image:
            assert (tmp_path / b.image).exists()


def test_full_pipeline_with_mock():
    from server import db
    from server.config import settings
    from server.llm import get_llm
    from server.pipeline import jobs, translate, understand

    db.init()
    doc_id = "testdoc01"
    d = jobs.doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLE, d / "source.pdf")
    db.ex("INSERT INTO documents(id, title, filename, status, stage, created_at, updated_at) VALUES(?,?,?,?,?,0,0)",
          doc_id, "1706.03762v7", "1706.03762v7.pdf", "running", "parse")
    jobs.parse_stage(doc_id)
    understand.run(doc_id, get_llm(settings, "understand"), settings, lambda: False)
    translate.run(doc_id, get_llm(settings), settings, lambda: False)
    doc = db.get_doc(doc_id)
    assert doc["translatable"] > 80 and doc["translated"] == doc["translatable"] and doc["failed"] == 0
    assert json.loads(doc["brief"])["title_si"]
    tbl = db.q1("SELECT translated_table FROM blocks WHERE doc_id=? AND type='table' AND table_mode='html'", doc_id)
    assert tbl and json.loads(tbl["translated_table"])
    refs = db.q("SELECT status FROM blocks WHERE doc_id=? AND type='reference'", doc_id)
    assert refs and all(r["status"] == "skip" for r in refs)
