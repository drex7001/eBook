"""Validated app preferences and Windows user-scoped encrypted credentials."""
from __future__ import annotations

import ctypes
import json
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db
from .config import settings

LANGUAGES = {"en": "English", "si": "සිංහල", "ta": "தமிழ்", "hi": "हिन्दी", "ar": "العربية",
             "es": "Español", "fr": "Français", "de": "Deutsch", "it": "Italiano", "pt": "Português",
             "ja": "日本語", "ko": "한국어", "zh": "中文", "ru": "Русский", "bn": "বাংলা",
             "ur": "اردو", "ne": "नेपाली", "th": "ไทย", "vi": "Tiếng Việt", "id": "Indonesia",
             "tr": "Türkçe", "nl": "Nederlands", "pl": "Polski", "he": "עברית", "fa": "فارسی",
             "ml": "മലയാളം", "te": "తెలుగు", "kn": "ಕನ್ನಡ", "mr": "मराठी", "sw": "Kiswahili"}


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface_language: Literal["si", "en"] = "si"
    display_mode: Literal["translated", "original", "both"] = "translated"
    font_size: int = Field(19, ge=15, le=32)
    line_height: float = Field(1.8, ge=1.3, le=2.5)
    theme: Literal["paper", "leaf", "night"] = "night"
    word_tap: bool = True
    source_language: str = "auto"
    target_language: str = "si"
    purpose: Literal["reading", "language", "study"] = "reading"
    translation_style: Literal["conversational", "formal"] = "conversational"
    keep_terms: bool = True
    auto_translate: bool = True
    provider: Literal["gemini", "ollama", "mock"] = "gemini"
    model: str = ""
    light_model: str = ""
    tts_model: str = ""
    audio_mode: Literal["off", "device", "cloud"] = "off"
    voice: str = "Kore"
    rate: float = Field(1, ge=0.5, le=2)
    quiz_count: int = Field(10, ge=1, le=40)
    exam_count: int = Field(20, ge=1, le=60)
    exam_minutes: int = Field(30, ge=1, le=180)
    reading_goal: int = Field(10, ge=1, le=120)
    question_goal: int = Field(5, ge=1, le=100)
    gamification: bool = True
    timezone: str = "Asia/Colombo"

    @field_validator("source_language", "target_language")
    @classmethod
    def language(cls, value, info):
        if info.field_name == "source_language" and value == "auto":
            return value
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value):
            raise ValueError("Use a language code such as si, ta, en or pt-BR")
        return value

    @field_validator("model", "light_model", "tts_model")
    @classmethod
    def model_name(cls, value):
        if len(value) > 120 or (value and not re.fullmatch(r"[\w.:/-]+", value)):
            raise ValueError("Invalid model name")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone")
        return value

    @field_validator("voice")
    @classmethod
    def valid_voice(cls, value):
        from .tts import GEMINI_VOICES
        if value not in GEMINI_VOICES:
            raise ValueError("Choose a supported cloud voice")
        return value


def get() -> AppSettings:
    r = db.q1("SELECT data FROM app_settings WHERE id=1")
    if r:
        return AppSettings.model_validate_json(r["data"])
    return AppSettings(provider=settings.llm_provider)


def update(patch: dict) -> AppSettings:
    with db.tx() as c:
        current = get().model_dump()
        value = AppSettings.model_validate(current | patch)
        c.execute("INSERT INTO app_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                  (value.model_dump_json(),))
        if value.timezone != current["timezone"]:
            import datetime as dt
            for row in c.execute("SELECT id,at FROM progress_events").fetchall():
                event_day = dt.datetime.fromtimestamp(row["at"], ZoneInfo(value.timezone)).date().isoformat()
                c.execute("UPDATE progress_events SET day=? WHERE id=?", (event_day, row["id"]))
    return value


def profile(p: AppSettings | None = None) -> dict:
    p = p or get()
    return {k: getattr(p, k) for k in ("source_language", "target_language", "purpose", "translation_style", "keep_terms")} | {
        "provider": p.provider, "model": p.model, "light_model": p.light_model, "prompt_version": "multilingual-v2"}


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


def runtime(doc_id: str | None = None):
    p = get()
    values = profile(p)
    if doc_id:
        r = db.q1("SELECT r.profile FROM translation_runs r JOIN documents d ON d.active_run=r.id WHERE d.id=?", doc_id)
        if r:
            values.update(json.loads(r["profile"]))
    result = replace(settings)
    result.llm_provider = values.get("provider", p.provider)
    try:
        result.gemini_api_key = read_key()
    except ValueError:
        if result.llm_provider == "gemini" or p.audio_mode == "cloud":
            raise
        result.gemini_api_key = ""
    result.gemini_model = values.get("model") or settings.gemini_model
    result.gemini_understand_model = values.get("light_model") or settings.gemini_understand_model
    result.gemini_tts_model = p.tts_model or settings.gemini_tts_model
    result.ollama_model = values.get("model") or settings.ollama_model
    result.tts_voice = p.voice
    for k, v in values.items():
        setattr(result, k, v)
    return result


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise ValueError("Secure key storage requires Windows. Use GEMINI_API_KEY in the environment on this OS.")
    buf = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError("Windows could not unlock the API key. Enter it again using this Windows account.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def _key_path() -> Path:
    return Path(settings.data_dir) / "credentials.dpapi"


def read_key() -> str:
    path = _key_path()
    if not path.exists():
        return settings.gemini_api_key
    raw = path.read_bytes()
    return _crypt(raw, True).decode() if raw else ""


def save_key(value: str | None):
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if value is not None and (not value.strip() or len(value) > 500):
        raise ValueError("Enter a valid API key")
    raw = _crypt(value.strip().encode()) if value else b""
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def key_status() -> dict:
    try:
        value = read_key()
        return {"configured": bool(value), "masked": "••••" + value[-4:] if value else "",
                "source": "saved" if _key_path().exists() else "environment", "error": None}
    except ValueError as e:
        return {"configured": False, "masked": "", "source": "saved", "error": str(e)}
