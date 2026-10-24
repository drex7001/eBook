"""Local models through Ollama's /api/chat with structured (JSON-schema) output."""
from __future__ import annotations

import time

import httpx

from .base import LLMError, LLMResult, parse_json_loose


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings, model: str | None = None):
        self.base = settings.ollama_url.rstrip("/")
        self.model = model or settings.ollama_model
        self.num_ctx = settings.ollama_num_ctx
        self.temperature = settings.ollama_temperature
        self._schema_format = True
        # local generation can be slow on CPU; allow long requests
        self.client = httpx.Client(timeout=httpx.Timeout(1800.0, connect=10.0))

    def generate_json(self, system: str, prompt: str, schema: dict, purpose: str = "") -> LLMResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False,
            "format": schema if (self._schema_format and schema) else "json",
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
            "keep_alive": "30m",
        }
        last = ""
        for attempt in range(4):
            try:
                r = self.client.post(f"{self.base}/api/chat", json=body)
            except httpx.ConnectError:
                raise LLMError(f"Cannot reach Ollama at {self.base}. Is `ollama serve` running?", retryable=True)
            except httpx.HTTPError as e:
                last = str(e)
                time.sleep(2 + attempt * 3)
                continue
            if r.status_code == 404:
                raise LLMError(f'Ollama model "{self.model}" is not installed. Run: ollama pull {self.model}')
            if r.status_code == 400 and self._schema_format and "format" in r.text.lower():
                self._schema_format = False      # older Ollama: plain JSON mode
                body["format"] = "json"
                continue
            if r.status_code != 200:
                last = f"{r.status_code}: {r.text[:300]}"
                time.sleep(2 + attempt * 3)
                continue
            j = r.json()
            text = (j.get("message") or {}).get("content", "")
            try:
                data = parse_json_loose(text)
            except ValueError:
                last = f"invalid JSON: {text[:200]}"
                continue
            return LLMResult(data, int(j.get("prompt_eval_count") or 0), int(j.get("eval_count") or 0), text)
        raise LLMError(f"Ollama kept failing: {last}", retryable=True)
