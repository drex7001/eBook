"""Text-to-speech. Only a Gemini adapter for now; the reader UI talks to /api/.../tts and doesn't care which."""
from __future__ import annotations

import base64
import io
import re
import time
import wave

import httpx

# Prebuilt Gemini voices (from the Gemini speech-generation docs).
GEMINI_VOICES = ["Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
                 "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
                 "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
                 "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"]


class TTSError(Exception):
    pass


def pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def speech_text(text: str) -> str:
    """What we send to TTS: drop citation markers, URLs and stray symbols that sound bad read aloud."""
    t = re.sub(r"\[\d+(?:\s*[,–\-]\s*\d+)*\]", "", text)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[∗†‡*#|]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _find_audio(obj) -> tuple[str, str] | None:
    """Walk an Interactions API response for the last {type: audio, data: base64} item."""
    found = None
    if isinstance(obj, dict):
        if obj.get("type") == "audio" and isinstance(obj.get("data"), str):
            found = (obj["data"], str(obj.get("mime_type") or obj.get("mimeType") or ""))
        for v in obj.values():
            f = _find_audio(v)
            if f:
                found = f
    elif isinstance(obj, list):
        for v in obj:
            f = _find_audio(v)
            if f:
                found = f
    return found


class GeminiTTS:
    def __init__(self, settings):
        self.key = settings.gemini_api_key
        self.base = settings.gemini_base_url.rstrip("/")
        self.model = settings.gemini_tts_model
        self.api = settings.gemini_tts_api
        self.client = httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0))

    def synthesize(self, text: str, voice: str, style: str = "") -> bytes:
        if not self.key:
            raise TTSError("GEMINI_API_KEY is not set in .env")
        text = speech_text(text)
        if not text:
            raise TTSError("Nothing to read in this block.")
        last = ""
        for attempt in range(4):
            try:
                if self.api == "generate_content":
                    return self._generate_content(text, voice, style)
                return self._interactions(text, voice, style)
            except httpx.HTTPError as e:
                last = str(e)
            except TTSError as e:
                if "429" not in str(e) and "503" not in str(e):
                    raise
                last = str(e)
            time.sleep(2 * (attempt + 1))
        raise TTSError(f"TTS failed after retries: {last}")

    def _check(self, r: httpx.Response) -> dict:
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", r.text[:300])
            except ValueError:
                msg = r.text[:300]
            raise TTSError(f"Gemini TTS {r.status_code}: {msg}")
        return r.json()

    def _interactions(self, text: str, voice: str, style: str) -> bytes:
        item: dict = {"type": "text", "text": text}
        if style:
            item["annotations"] = [{"type": "speech_metadata", "style": style}]
        body = {
            "model": self.model,
            "input": [{"type": "user_input", "content": [item]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": voice}]},
        }
        r = self.client.post(f"{self.base}/v1beta/interactions", json=body,
                             headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
        j = self._check(r)
        found = _find_audio(j)
        if not found:
            raise TTSError("Gemini TTS response had no audio: " + str(j)[:300])
        data, mime = found
        raw = base64.b64decode(data)
        if raw[:4] == b"RIFF":
            return raw
        rate = int(m.group(1)) if (m := re.search(r"rate=(\d+)", mime)) else 24000
        return pcm_to_wav(raw, rate)

    def _generate_content(self, text: str, voice: str, style: str) -> bytes:
        prompt = f"Read this aloud in a {style} voice:\n{text}" if style else text
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        r = self.client.post(f"{self.base}/v1beta/models/{self.model}:generateContent", json=body,
                             headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
        j = self._check(r)
        try:
            part = j["candidates"][0]["content"]["parts"][0]["inlineData"]
        except (KeyError, IndexError):
            raise TTSError("Gemini TTS response had no audio: " + str(j)[:300])
        raw = base64.b64decode(part["data"])
        rate = int(m.group(1)) if (m := re.search(r"rate=(\d+)", part.get("mimeType", ""))) else 24000
        return raw if raw[:4] == b"RIFF" else pcm_to_wav(raw, rate)


def get_tts(settings):
    if settings.tts_provider == "gemini":
        return GeminiTTS(settings)
    raise TTSError(f"TTS_PROVIDER '{settings.tts_provider}' is not available.")


__all__ = ["get_tts", "GEMINI_VOICES", "TTSError", "speech_text", "pcm_to_wav"]
