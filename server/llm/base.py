"""Provider-neutral LLM interface. Every provider returns parsed JSON plus token counts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False, result: LLMResult | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.result = result


@dataclass
class LLMResult:
    data: dict
    prompt_tokens: int = 0
    output_tokens: int = 0      # includes thinking tokens (billed as output)
    raw: str = ""
    cached_tokens: int = 0      # part of prompt_tokens served from cache (billed at the cache rate)
    thought_tokens: int = 0     # part of output_tokens spent on thinking
    model: str = ""
    batch: bool = False         # came from a Batch API job (half price)


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, system: str, prompt: str, schema: dict, purpose: str = "") -> LLMResult: ...


def parse_json_loose(text: str) -> dict:
    """Parse model output that should be a JSON object, tolerating ``` fences and leading chatter."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        v = json.loads(t[start:end + 1])
        if isinstance(v, dict):
            return v
    raise ValueError("model output is not a JSON object")
