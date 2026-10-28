"""Run an isolated, synthetic, mock-only beta demo for browser verification.

Never reads the user's library or enables an external AI provider.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATA_DIR"] = str(ROOT / "output" / "beta-smoke")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["GEMINI_API_KEY"] = ""
os.environ["TTS_PROVIDER"] = "none"
os.environ["HOST"] = "127.0.0.1"

from server import app_settings, db, translations  # noqa: E402
from server.pipeline.jobs import doc_dir  # noqa: E402


def seed():
    import pymupdf
    db.init()
    app_settings.update({"provider": "mock", "interface_language": "en", "audio_mode": "off"})
    did = "beta-demo"
    if db.get_doc(did):
        return
    folder = doc_dir(did)
    folder.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open()
    rows = []
    seq = 0
    for section, title in enumerate(("1. Energy and living systems", "2. Cells and adaptation", "3. Evidence and understanding")):
        page = pdf.new_page()
        page.insert_text((52, 58), title, fontsize=18)
        rows.append((seq, "heading", 1, section, title, f"සිංහල: {title}", [dict(page=section,x0=50,y0=35,x1=550,y1=65)]))
        seq += 1
        for i in range(4):
            source = (f"Passage {section+1}.{i+1}. Plants convert sunlight into chemical energy through photosynthesis. "
                      "Chlorophyll absorbs light and the plant combines water with carbon dioxide to produce sugars. "
                      "Oxygen is released as a by-product. These sugars support growth and the work performed inside cells. "
                      "Scientists compare controlled observations to distinguish evidence from an unsupported claim. "
                      "A useful explanation connects the observations to a mechanism and predicts what a new experiment might show.")
            y = 90 + i * 165
            page.insert_textbox(pymupdf.Rect(52,y,550,y+150),source,fontsize=10)
            translated = (f"කොටස {section+1}.{i+1}. පැළෑටි photosynthesis මඟින් හිරු එළිය chemical energy බවට හරවනවා. "
                          "Chlorophyll එකෙන් ආලෝකය අවශෝෂණය කරගෙන, water සහ carbon dioxide භාවිතා කර sugars හදනවා. "
                          "මේ ක්‍රියාවලියෙන් oxygen පිටවෙනවා. මේක තේරුම් ගන්න evidence සහ explanation අතර සම්බන්ධය බලන්න.")
            rows.append((seq,"paragraph",0,section,source,translated,[dict(page=section,x0=50,y0=y,x1=552,y1=y+145)]))
            seq += 1
    pdf.save(folder / "source.pdf")
    pdf.close()
    now = time.time()
    db.ex("INSERT INTO documents(id,title,title_si,filename,page_count,status,stage,stage_done,stage_total,provider,model,page_sizes,created_at,updated_at) VALUES(?,?,?,?,?,'done','done',15,15,'mock','mock',?,?,?)",
          did,"Understanding living systems","ජීව පද්ධති තේරුම් ගනිමු","beta-demo.pdf",3,json.dumps([[595,842]]*3),now,now)
    for seq,kind,level,section,source,translated,regions in rows:
        db.ex("INSERT INTO blocks(doc_id,seq,type,level,page,regions,source,translated,status,section,rev) VALUES(?,?,?,?,?,?,?,?,'done',?,?)",
              did,seq,kind,level,section,json.dumps(regions),source,translated,section,db.next_rev())
    for s,title in enumerate(("Energy and living systems","Cells and adaptation","Evidence and understanding")):
        db.ex("INSERT INTO sections VALUES(?,?,?,?,?)",did,s,title,s*5,s*5+4)
    translations.initial(did)
    translations.capture(did)


def seed_quiz_failures():
    """Synthetic saved/unsaved failures for UI recovery checks; never calls a model."""
    from server import study_responses
    from server.llm.base import LLMResult
    source = dict(db.q1("SELECT seq,source,section,page FROM blocks WHERE doc_id='beta-demo' AND type='paragraph' ORDER BY seq LIMIT 1"))
    payload = {"count": 1, "sources": [{"seq": source["seq"], "text": source["source"], "section": source["section"], "page": source["page"]}]}
    for pid, difficulty, version in (("demo-old-failure", "easy", 901), ("demo-saved-failure", "hard", 902), ("demo-recoverable", "medium", 903)):
        if db.q1("SELECT 1 FROM quiz_papers WHERE id=?", pid):
            continue
        old = pid == "demo-old-failure"
        db.ex("INSERT INTO quiz_papers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", pid, "beta-demo", difficulty, version, "si", "{}", 1, "error",
              "Some generated questions did not pass source/format checks. " * (20 if old else 1), time.time(), pid,
              json.dumps({} if old else {"quiz_generation_version": "durable-v2"}))
        if old:
            continue
        item = {"question": "ආලෝක ශක්තිය ගැන source එකේ කියන්නේ මොකක්ද?", "options": ["අඩු වෙනවා", "රසායනික ශක්තියට හරවනවා", "වෙනස් වෙන්නේ නැහැ", "නැති වෙනවා"],
                "answer": "B", "source_seq": str(source["seq"]), "source_quote": source["source"][:120],
                "explanation": "එය රසායනික ශක්තිය බවට හරවනවා.", "distractors": ["Source එකට ගැළපෙන්නේ නැහැ."] * 3}
        if pid == "demo-saved-failure":
            item["source_quote"] = "මේ සිංහල quote එක English original එකේ නැති නිසා reject වෙනවා."
        data = {"questions": [item]}
        rid = study_responses.save_response(pid, 0, payload, LLMResult(data, raw=json.dumps(data, ensure_ascii=False), model="mock"))
        if pid == "demo-saved-failure":
            study_responses.accept_response(rid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--quiz-failure-demo", action="store_true")
    args = parser.parse_args()
    seed()
    if args.quiz_failure_demo:
        seed_quiz_failures()
    import uvicorn
    uvicorn.run("server.api:app",host="127.0.0.1",port=args.port,log_level="warning")
