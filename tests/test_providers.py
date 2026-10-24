"""Gemini / Ollama / TTS adapters against canned HTTP responses (no network)."""
import base64
import io
import json
import wave

import httpx
import pytest

from server.config import settings
from server.llm.base import LLMError, parse_json_loose
from server.llm.gemini import GeminiProvider
from server.llm.ollama import OllamaProvider
from server.tts import GeminiTTS, pcm_to_wav, speech_text

SCHEMA = {"type": "object", "properties": {"translations": {"type": "array"}}}


def gemini(handler):
    settings.gemini_api_key = "test-key"
    p = GeminiProvider(settings, model="gemini-test")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


def ok_body(text, thought=False):
    parts = ([{"text": "thinking...", "thought": True}] if thought else []) + [{"text": text}]
    return {"candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 40, "thoughtsTokenCount": 10}}


def test_gemini_request_and_parse():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["key"] = req.headers["x-goog-api-key"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=ok_body('```json\n{"translations": [{"id": "1", "si": "හරි"}]}\n```', thought=True))

    r = gemini(handler).generate_json("SYS", "PROMPT", SCHEMA)
    assert seen["url"].endswith("/v1beta/models/gemini-test:generateContent")
    assert seen["key"] == "test-key"
    gc = seen["body"]["generationConfig"]
    assert gc["responseMimeType"] == "application/json" and gc["responseJsonSchema"] == SCHEMA
    assert gc["thinkingConfig"] == {"thinkingLevel": settings.gemini_thinking_level}
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert r.data["translations"][0]["si"] == "හරි"
    assert (r.prompt_tokens, r.output_tokens) == (120, 50)


def test_gemini_drops_thinking_config_when_rejected():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body["generationConfig"])
        if "thinkingConfig" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"code": 400, "message": "Thinking level is not supported for this model."}})
        return httpx.Response(200, json=ok_body('{"translations": []}'))

    gemini(handler).generate_json("S", "P", SCHEMA)
    assert "thinkingConfig" in calls[0] and "thinkingConfig" not in calls[1]


def test_gemini_retries_429_with_retry_delay(monkeypatch):
    sleeps = []
    monkeypatch.setattr("server.llm.gemini.time.sleep", lambda s: sleeps.append(s))
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        if n["i"] == 1:
            return httpx.Response(429, json={"error": {"code": 429, "message": "quota", "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]}})
        return httpx.Response(200, json=ok_body('{"translations": []}'))

    gemini(handler).generate_json("S", "P", SCHEMA)
    assert sleeps == [7.0]


def test_gemini_model_not_found_message():
    p = gemini(lambda req: httpx.Response(404, json={"error": {"message": "models/x is not found"}}))
    with pytest.raises(LLMError, match="GEMINI_MODEL"):
        p.generate_json("S", "P", SCHEMA)


def test_gemini_safety_block_is_not_retried():
    body = {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
    with pytest.raises(LLMError, match="blocked") as e:
        gemini(lambda req: httpx.Response(200, json=body)).generate_json("S", "P", SCHEMA)
    assert not e.value.retryable


def test_ollama_request_and_parse():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"translations": [{"id": "3", "si": "ok"}]}'},
                                         "prompt_eval_count": 50, "eval_count": 9})

    p = OllamaProvider(settings)
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    r = p.generate_json("SYS", "PROMPT", SCHEMA)
    assert seen["format"] == SCHEMA and seen["stream"] is False
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    assert r.data["translations"][0]["id"] == "3" and r.prompt_tokens == 50


def test_ollama_missing_model():
    p = OllamaProvider(settings)
    p.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404, json={"error": "model not found"})))
    with pytest.raises(LLMError, match="ollama pull"):
        p.generate_json("S", "P", SCHEMA)


def _tts(handler, api="interactions"):
    settings.gemini_api_key = "k"
    settings.gemini_tts_api = api
    t = GeminiTTS(settings)
    t.client = httpx.Client(transport=httpx.MockTransport(handler))
    return t


def test_tts_interactions_wav():
    wav = pcm_to_wav(b"\x00\x01" * 2400)
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "int_1", "status": "completed", "steps": [
            {"type": "user_input", "content": [{"type": "text", "text": "x"}]},
            {"type": "model_output", "content": [{"type": "audio", "mime_type": "audio/wav",
                                                   "data": base64.b64encode(wav).decode()}]}]})

    out = _tts(handler).synthesize("ආයුබෝවන් [12] world", "Kore", "calm")
    assert seen["url"].endswith("/v1beta/interactions")
    b = seen["body"]
    assert b["response_format"] == {"type": "audio"}
    assert b["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert b["input"][0]["content"][0]["text"] == "ආයුබෝවන් world"
    assert out == wav


def test_tts_raw_pcm_gets_wav_header():
    pcm = b"\x00\x00" * 24000
    handler = lambda req: httpx.Response(200, json={"steps": [{"type": "model_output", "content": [
        {"type": "audio", "mime_type": "audio/l16; rate=24000", "data": base64.b64encode(pcm).decode()}]}]})
    out = _tts(handler).synthesize("hello", "Puck")
    with wave.open(io.BytesIO(out)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 24000


def test_tts_generate_content_mode():
    pcm = b"\x01\x00" * 100
    handler = lambda req: httpx.Response(200, json={"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]})
    out = _tts(handler, api="generate_content").synthesize("hello", "Puck")
    assert out[:4] == b"RIFF"
    settings.gemini_tts_api = "interactions"


def test_parse_json_loose():
    assert parse_json_loose('Sure! {"a": 1} thanks') == {"a": 1}
    assert speech_text("See https://x.com/a and [3, 4]. ∗") == "See and ."
