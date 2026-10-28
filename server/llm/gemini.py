"""Gemini via the REST generateContent endpoint (still fully supported alongside the Interactions API).

Defensive by design: if the model rejects `thinkingConfig` or the JSON schema field, we drop that
field and retry, so older/newer model names keep working without code changes.
"""
from __future__ import annotations

import logging
import random
import re
import time

import httpx

from .base import LLMError, LLMResult, parse_json_loose

log = logging.getLogger(__name__)

BLOCK_REASONS = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "LANGUAGE"}


def _retry_delay(err: dict) -> float | None:
    for d in (err.get("error", {}) or {}).get("details", []) or []:
        if str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.match(r"([0-9.]+)s", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    return None


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings, model: str | None = None, thinking: str | None = None, fallback_model: str | None = None):
        self.key = settings.gemini_api_key
        self.base = settings.gemini_base_url.rstrip("/")
        self.model = model or settings.gemini_model
        self.fallback_model = fallback_model if fallback_model != self.model else None
        self.thinking = settings.gemini_thinking_level if thinking is None else thinking
        self.temperature = settings.gemini_temperature
        self._use_thinking = bool(self.thinking)
        self._use_schema = True
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0))

    @property
    def headers(self) -> dict:
        return {"x-goog-api-key": self.key, "Content-Type": "application/json"}

    @staticmethod
    def usage(j: dict) -> tuple[int, int, int, int]:
        """(prompt, output incl. thinking, cached, thinking) from usageMetadata."""
        u = j.get("usageMetadata") or {}
        thought = int(u.get("thoughtsTokenCount") or 0)
        return (int(u.get("promptTokenCount") or 0), int(u.get("candidatesTokenCount") or 0) + thought,
                int(u.get("cachedContentTokenCount") or 0), thought)

    def _body(self, system: str, prompt: str, schema: dict) -> dict:
        gen: dict = {"responseMimeType": "application/json"}
        if self._use_schema and schema:
            gen["responseJsonSchema"] = schema
        if self._use_thinking:
            gen["thinkingConfig"] = {"thinkingLevel": self.thinking}
        if self.temperature is not None:
            gen["temperature"] = self.temperature
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen,
        }

    @staticmethod
    def _text(j: dict) -> tuple[str, str]:
        cands = j.get("candidates") or []
        if not cands:
            reason = (j.get("promptFeedback") or {}).get("blockReason", "NO_CANDIDATES")
            return "", reason
        c = cands[0]
        parts = (c.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text, c.get("finishReason", "")

    def generate_json(self, system: str, prompt: str, schema: dict, purpose: str = "") -> LLMResult:
        if not self.key:
            raise LLMError("GEMINI_API_KEY is not set. Add it to the .env file in the project folder.")
        headers = self.headers
        last = ""
        for attempt in range(8):
            url = f"{self.base}/v1beta/models/{self.model}:generateContent"
            try:
                r = self.client.post(url, headers=headers, json=self._body(system, prompt, schema))
            except httpx.HTTPError as e:
                if purpose == "subject_quiz":
                    raise LLMError("Quiz request was interrupted. It was not repeated because it may already have been processed.", retryable=True) from e
                last = f"network error: {e}"
                time.sleep(min(60, 2 ** attempt + random.random()))
                continue

            if r.status_code == 200:
                try:
                    j = r.json()
                    text, finish = self._text(j)
                    ptok, otok, ctok, ttok = self.usage(j)
                except (ValueError, TypeError, AttributeError) as e:
                    if purpose == "subject_quiz":
                        raise LLMError("Quiz response could not be decoded; received bytes retained without retry.",
                                       result=LLMResult({}, raw=r.text, model=self.model)) from e
                    raise
                if not text:
                    if purpose == "subject_quiz":
                        raise LLMError(f"Quiz response had no text ({finish}); no automatic retry.",
                                       result=LLMResult({}, ptok, otok, text, ctok, ttok, self.model))
                    if finish in BLOCK_REASONS:
                        raise LLMError(f"Gemini blocked this request ({finish}).")
                    last = f"empty response ({finish})"
                    continue
                try:
                    return LLMResult(parse_json_loose(text), ptok, otok, text, ctok, ttok, self.model)
                except ValueError as e:
                    if purpose == "subject_quiz":
                        raise LLMError("Quiz response was not valid JSON; output retained without a new request.",
                                       result=LLMResult({}, ptok, otok, text, ctok, ttok, self.model)) from e
                    last = f"invalid JSON (finish={finish}): {text[:200]}"
                    if finish == "MAX_TOKENS":
                        raise LLMError("Gemini output hit the token limit; use a smaller batch size.", retryable=True)
                    continue

            try:
                err = r.json()
            except ValueError:
                err = {}
            msg = (err.get("error") or {}).get("message") or r.text[:300]
            low = msg.lower()
            if r.status_code == 400:
                if self._use_thinking and "think" in low:
                    log.warning("Gemini: model rejected thinkingConfig, retrying without it (%s)", msg)
                    self._use_thinking = False
                    continue
                if self._use_schema and ("schema" in low or "response_json" in low or "responsejson" in low):
                    log.warning("Gemini: model rejected responseJsonSchema, retrying without it (%s)", msg)
                    self._use_schema = False
                    continue
                if "api key" in low:
                    raise LLMError("Gemini rejected the API key. Check GEMINI_API_KEY in .env.")
                raise LLMError(f"Gemini 400: {msg}")
            if r.status_code in (401, 403):
                raise LLMError(f"Gemini refused the request ({r.status_code}): {msg}")
            if r.status_code == 404:
                if purpose == "subject_quiz":
                    raise LLMError("The selected quiz model was not found. Select an available model before generating; no automatic model fallback.")
                if self.fallback_model:
                    log.warning("Gemini model %s not found, using %s", self.model, self.fallback_model)
                    self.model, self.fallback_model = self.fallback_model, None
                    continue
                raise LLMError(f'Gemini model "{self.model}" was not found. Set GEMINI_MODEL in .env. ({msg})')
            if r.status_code in (429, 500, 502, 503, 504):
                if purpose == "subject_quiz":
                    raise LLMError(f"Quiz provider returned HTTP {r.status_code}; request not automatically repeated.", retryable=True)
                wait = _retry_delay(err) or min(90, 2 ** (attempt + 1) + random.random() * 2)
                log.info("Gemini %s, waiting %.0fs: %s", r.status_code, wait, msg[:120])
                last = f"{r.status_code}: {msg}"
                time.sleep(wait)
                continue
            raise LLMError(f"Gemini {r.status_code}: {msg}")
        raise LLMError(f"Gemini kept failing: {last}", retryable=True)

    # ------------------------------------------------------------------ Batch API (half price, async)

    def batch_create(self, requests: list[tuple[str, str, str, dict]], display_name: str) -> str:
        """requests: (key, system, prompt, schema). Returns the batch name ("batches/…")."""
        if not self.key:
            raise LLMError("GEMINI_API_KEY is not set.")
        body = {"batch": {"display_name": display_name[:120], "input_config": {"requests": {"requests": [
            {"request": self._body(system, prompt, schema), "metadata": {"key": key}}
            for key, system, prompt, schema in requests]}}}}
        r = self.client.post(f"{self.base}/v1beta/models/{self.model}:batchGenerateContent", headers=self.headers,
                             json=body, timeout=httpx.Timeout(600.0, connect=20.0))
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", r.text[:300])
            except ValueError:
                msg = r.text[:300]
            raise LLMError(f"Batch job could not be created ({r.status_code}): {msg}")
        j = r.json()
        name = j.get("name") or (j.get("metadata") or {}).get("name")
        if not name:
            raise LLMError("Batch API returned no job name: " + str(j)[:300])
        return name

    def batch_get(self, name: str) -> dict:
        r = self.client.get(f"{self.base}/v1beta/{name}", headers=self.headers)
        if r.status_code != 200:
            raise LLMError(f"Batch status {r.status_code}: {r.text[:300]}", retryable=r.status_code >= 500)
        return r.json()


def _walk(obj, key):
    """Yield every value stored under `key` anywhere in a JSON tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)


def batch_state(j: dict) -> str:
    """SUCCEEDED / FAILED / CANCELLED / EXPIRED / PENDING / RUNNING (the docs disagree on where `state` lives)."""
    for v in _walk(j, "state"):
        if isinstance(v, str) and ("BATCH_STATE_" in v or "JOB_STATE_" in v):
            return v.split("_STATE_")[-1]
    if j.get("done"):
        return "FAILED" if j.get("error") else "SUCCEEDED"
    return "PENDING"


def batch_results(j: dict) -> list[tuple[str, LLMResult | None, str]]:
    """[(key, result or None, error message)] from inline responses."""
    out = []
    for block in _walk(j, "inlinedResponses"):
        items = block.get("inlinedResponses") if isinstance(block, dict) else block
        if not isinstance(items, list):
            continue
        for it in items:
            key = str((it.get("metadata") or {}).get("key", ""))
            if it.get("error"):
                out.append((key, None, str(it["error"].get("message", it["error"]))[:300]))
                continue
            resp = it.get("response") or {}
            text, finish = GeminiProvider._text(resp)
            ptok, otok, ctok, ttok = GeminiProvider.usage(resp)
            try:
                res = LLMResult(parse_json_loose(text), ptok, otok, text, ctok, ttok, batch=True)
                out.append((key, res, ""))
            except ValueError:
                out.append((key, None, f"bad JSON ({finish})"))
        if out:
            break
    return out
