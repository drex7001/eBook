"""Runtime settings, read from environment variables / the project's .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v.strip() if v is not None and v.strip() != "" else default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float_or_none(name: str) -> float | None:
    v = _env(name)
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT / "data"))))
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    # ---- LLM (translation + understanding) ----
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "gemini").lower())  # gemini | ollama | mock

    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_base_url: str = field(default_factory=lambda: _env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.8-flash"))
    # Cheaper model for pass 1 (summaries + glossary), word lookups and practice questions.
    gemini_understand_model: str = field(default_factory=lambda: _env("GEMINI_UNDERSTAND_MODEL", "gemini-3.5-flash-lite"))
    gemini_light_thinking: str = field(default_factory=lambda: _env("GEMINI_LIGHT_THINKING_LEVEL", "minimal"))
    gemini_thinking_level: str = field(default_factory=lambda: _env("GEMINI_THINKING_LEVEL", "low"))  # "" to omit
    gemini_temperature: float | None = field(default_factory=lambda: _float_or_none("GEMINI_TEMPERATURE"))

    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "gemma3:12b"))
    ollama_num_ctx: int = field(default_factory=lambda: _int("OLLAMA_NUM_CTX", 16384))
    ollama_temperature: float = field(default_factory=lambda: _float_or_none("OLLAMA_TEMPERATURE") or 0.2)

    # Batch sizes are characters of source text per LLM call.
    translate_batch_chars: int = field(default_factory=lambda: _int("TRANSLATE_BATCH_CHARS", 0))
    understand_chunk_chars: int = field(default_factory=lambda: _int("UNDERSTAND_CHUNK_CHARS", 0))
    concurrency: int = field(default_factory=lambda: _int("CONCURRENCY", 0))

    # ---- TTS ----
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "gemini").lower())  # gemini | none
    gemini_tts_model: str = field(default_factory=lambda: _env("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts"))
    # "interactions" (current docs) or "generate_content" (older *-preview-tts models)
    gemini_tts_api: str = field(default_factory=lambda: _env("GEMINI_TTS_API", "interactions"))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "Kore"))
    tts_style: str = field(default_factory=lambda: _env("TTS_STYLE", "warm, calm Sri Lankan storyteller reading a book aloud"))
    batch_poll_seconds: int = field(default_factory=lambda: _int("BATCH_POLL_SECONDS", 60))

    def __post_init__(self) -> None:
        local = self.llm_provider == "ollama"
        if not self.translate_batch_chars:
            self.translate_batch_chars = 2500 if local else 8000
        if not self.understand_chunk_chars:
            self.understand_chunk_chars = 6000 if local else 24000
        if not self.concurrency:
            self.concurrency = 1 if local else 3
        if not self.gemini_understand_model:
            self.gemini_understand_model = self.gemini_model
        if self.llm_provider != "gemini":
            self.gemini_light_thinking = ""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_label(self) -> str:
        if self.llm_provider == "gemini":
            return self.gemini_model
        if self.llm_provider == "ollama":
            return self.ollama_model
        return "mock"


settings = Settings()


# USD per 1M tokens on the paid tier: (input, output incl. thinking, cached input). From
# ai.google.dev/gemini-api/docs/pricing (October 2026). gemini-3.8-flash doubles from 2027-01-01.
# Batch jobs cost half of these. On the free tier the real cost is 0; the app then shows what it *would* cost.
PRICES = {
    "gemini-3.8-flash-tts": (0.50, 9.00, 0.0),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
}


def price_for(model: str) -> tuple[float, float, float] | None:
    import datetime
    p = PRICES.get(model)
    if p and model in ("gemini-3.8-flash", "gemini-3.8-flash-tts") and datetime.date.today() >= datetime.date(2027, 1, 1):
        p = tuple(x * 2 for x in p)
    return p
