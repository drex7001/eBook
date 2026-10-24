"""Offline stand-in for development: fake 'translations' so the whole app can be exercised without a key."""
from __future__ import annotations

import json
import re
import threading
import time

from .base import LLMResult

_BATCHES: dict[str, list] = {}
_LOCK = threading.Lock()


class MockProvider:
    name = "mock"

    def __init__(self, settings=None, model: str | None = None, delay: float = 0.05):
        self.model = model or "mock"
        self.delay = delay

    def generate_json(self, system: str, prompt: str, schema: dict, purpose: str = "") -> LLMResult:
        from ..pipeline.prompts import extract_items

        time.sleep(self.delay)
        if purpose == "understand":
            body = prompt.split("--- BEGIN PORTION ---")[-1].split("--- END PORTION ---")[0]
            words = re.findall(r"\b[A-Z][a-zA-Z\-]{3,}\b", body)
            seen = []
            for w in words:
                if w not in seen:
                    seen.append(w)
            terms = [{"term": w, "policy": "keep_en", "rendering": w, "kind": "concept"} for w in seen[:8]]
            return self._r({"summary": body.strip()[:300], "terms": terms}, prompt, 200)
        if purpose == "brief":
            return self._r({"doc_type": "other", "domain": "general", "audience": "general", "tone": "neutral",
                            "summary": "Mock summary.", "style_notes": "Mock notes.", "title_si": "Mock පොත"}, prompt, 80)
        if purpose == "lookup":
            w = re.search(r'Word: "([^"]+)"', prompt).group(1)
            return self._r({"lemma": w.lower(), "pos": "noun", "ipa": "ˈmɒk", "meaning_en": f"mock meaning of {w}",
                            "meaning_si": f"{w} එකේ තේරුම", "in_context_si": "මෙතන තේරුම මේකයි.",
                            "examples": [{"en": f"I use {w} every day.", "si": f"මම හැමදාම {w} පාවිච්චි කරනවා."},
                                         {"en": f"This {w} is new.", "si": f"මේ {w} එක අලුත්."}],
                            "synonyms": ["sample"], "level": "B2"}, prompt, 120)
        if purpose == "quiz":
            items = []
            for wid, word in re.findall(r'word_id (\d+): "([^"]+)"', prompt):
                for kind in ("meaning", "cloze", "usage", "listen"):
                    items.append({"word_id": int(wid), "kind": kind, "question": f"{kind} question for {word}",
                                  "options": [word, f"{word}x", f"{word}y", f"{word}z"],
                                  "explain_si": f"{word} තමයි හරි උත්තරය.",
                                  "audio_text": f"I heard the word {word} today." if kind == "listen" else ""})
            return self._r({"items": items}, prompt, 300)
        items = extract_items(prompt)
        out = [{"id": it["id"], "si": "සිං: " + it["text"]} for it in items]
        return self._r({"translations": out, "new_terms": []}, prompt, sum(len(i["text"]) for i in items) // 2)

    def _r(self, data: dict, prompt: str, out: int) -> LLMResult:
        return LLMResult(data, len(prompt) // 4, out, json.dumps(data, ensure_ascii=False), 0, 0, self.model)

    # Batch API stand-in: jobs finish on the first status check.
    def batch_create(self, requests: list, display_name: str) -> str:
        with _LOCK:
            name = f"batches/mock{len(_BATCHES) + 1}"
            _BATCHES[name] = requests
        return name

    def batch_get(self, name: str) -> dict:
        responses = []
        for key, system, prompt, schema in _BATCHES.get(name, []):
            purpose = "understand" if "--- BEGIN PORTION ---" in prompt else "translate"
            res = self.generate_json(system, prompt, schema, purpose)
            responses.append({"metadata": {"key": key}, "response": {
                "candidates": [{"content": {"parts": [{"text": res.raw}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": res.prompt_tokens, "candidatesTokenCount": res.output_tokens}}})
        return {"name": name, "done": True, "metadata": {"state": "BATCH_STATE_SUCCEEDED"},
                "response": {"inlinedResponses": {"inlinedResponses": responses}}}
