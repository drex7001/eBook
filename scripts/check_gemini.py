"""Live check of your Gemini setup: model names, one small translation, one TTS clip.

    python scripts/check_gemini.py

Uses GEMINI_API_KEY / GEMINI_MODEL / GEMINI_TTS_MODEL from .env. Costs a few hundred tokens.
"""
import sys
import time
import wave
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.config import settings  # noqa: E402
from server.llm.gemini import GeminiProvider  # noqa: E402
from server.pipeline import prompts  # noqa: E402
from server.tts import GeminiTTS  # noqa: E402

ok = True


def step(name):
    print(f"\n== {name}")


step("API key")
if not settings.gemini_api_key:
    print("GEMINI_API_KEY is missing from .env")
    sys.exit(1)
print("found (" + settings.gemini_api_key[:4] + "…)")

step("Models available to this key")
try:
    r = httpx.get(f"{settings.gemini_base_url}/v1beta/models", params={"pageSize": 1000},
                  headers={"x-goog-api-key": settings.gemini_api_key}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])]
    for n in names:
        if "flash" in n or "tts" in n or "pro" in n:
            print("  ", n)
    for want in (settings.gemini_model, settings.gemini_understand_model, settings.gemini_tts_model):
        print(f"{'OK ' if want in names else 'MISSING'}  {want}")
        ok &= want in names
except Exception as e:  # noqa: BLE001
    ok = False
    print("could not list models:", e)

step(f"Translate with {settings.gemini_model}")
items = [
    {"id": "1", "type": "paragraph", "text": "The encoder is composed of a stack of N = 6 identical layers [11]."},
    {"id": "2", "type": "paragraph", "text": "It was raining heavily when we finally reached the village."},
]
prompt = prompts.translate_prompt(brief="title: test", glossary="(none yet)", summaries=[], previous=[],
                                  items=items, following=[])
try:
    t = time.time()
    res = GeminiProvider(settings).generate_json(prompts.TRANSLATE_SYSTEM, prompt, prompts.TRANSLATE_SCHEMA, "translate")
    for tr in res.data.get("translations", []):
        print(f"  [{tr['id']}] {tr['si']}")
    print(f"tokens in/out: {res.prompt_tokens}/{res.output_tokens}, {time.time() - t:.1f}s")
except Exception as e:  # noqa: BLE001
    ok = False
    print("FAILED:", e)

step(f"TTS with {settings.gemini_tts_model} ({settings.gemini_tts_api} API), voice {settings.tts_voice}")
try:
    t = time.time()
    wav = GeminiTTS(settings).synthesize("මේ paper එකෙන් අපි අලුත් model එකක් propose කරනවා.", settings.tts_voice,
                                         settings.tts_style)
    out = Path(__file__).resolve().parent / "check_tts.wav"
    out.write_bytes(wav)
    with wave.open(str(out)) as w:
        secs = w.getnframes() / w.getframerate()
    print(f"saved {out} ({secs:.1f}s of audio, {time.time() - t:.1f}s to generate). Play it and listen to the Sinhala.")
except Exception as e:  # noqa: BLE001
    ok = False
    print("FAILED:", e)

if "--batch" in sys.argv:
    from server.llm.gemini import batch_state
    step("Batch API (submits a 2-request job; results can take minutes to hours)")
    try:
        p = GeminiProvider(settings)
        name = p.batch_create([("t0", prompts.TRANSLATE_SYSTEM, prompt, prompts.TRANSLATE_SCHEMA),
                               ("t1", prompts.TRANSLATE_SYSTEM, prompt, prompts.TRANSLATE_SCHEMA)], "check_gemini")
        print(f"submitted {name}, state {batch_state(p.batch_get(name))}")
        print(f"later: python scripts/check_gemini.py --batch-status {name}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print("FAILED:", e)

if "--batch-status" in sys.argv:
    from server.llm.gemini import batch_results, batch_state
    name = sys.argv[sys.argv.index("--batch-status") + 1]
    j = GeminiProvider(settings).batch_get(name)
    print(name, batch_state(j))
    for key, res, err in batch_results(j):
        print(" ", key, "OK" if res else f"error: {err}", (res.data.get("translations") if res else ""))

print("\nAll good." if ok else "\nSomething needs attention (see above).")
sys.exit(0 if ok else 1)
