"""Cheap automatic checks on each translation. Hard issues trigger a retry; soft ones are stored for the reader."""
from __future__ import annotations

import re
from collections import Counter

SINHALA_RE = re.compile(r"[඀-෿]")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
CITE_RE = re.compile(r"\[\d+(?:\s*[,–\-]\s*\d+)*\]")

HARD = {"empty", "no_sinhala", "target_script_missing"}


def _nums(s: str) -> Counter:
    return Counter(n.replace(",", "") for n in NUM_RE.findall(s))


def check(source: str, target: str, kind: str = "paragraph", language: str = "si") -> list[str]:
    language = language.split("-")[0]
    t = (target or "").strip()
    if not t:
        return ["empty"]
    issues: list[str] = []
    english_words = len(re.findall(r"[A-Za-z]{3,}", source))
    prose = english_words >= 5 or (not re.search(r"[A-Za-z]", source) and sum(c.isalpha() for c in source) >= 25)
    if language == "si" and kind != "table_cell" and prose and not SINHALA_RE.search(t):
        issues.append("no_sinhala")
    scripts = {"ta": r"[\u0b80-\u0bff]", "ar": r"[\u0600-\u06ff]", "he": r"[\u0590-\u05ff]"}
    if language in scripts and kind != "table_cell" and prose and not re.search(scripts[language], t):
        issues.append("target_script_missing")
    missing = [n for n in _nums(CITE_RE.sub(" ", source)) if n not in _nums(CITE_RE.sub(" ", t))]
    if missing:
        issues.append("missing_numbers:" + ",".join(missing[:6]))
    cites = [c for c in CITE_RE.findall(source) if c.replace(" ", "") not in t.replace(" ", "")]
    if cites:
        issues.append("missing_citations:" + ",".join(cites[:6]))
    if len(source) > 250 and len(t) < 0.35 * len(source):
        issues.append("much_shorter")
    return issues


def is_hard(issues: list[str]) -> bool:
    return any(i.split(":")[0] in HARD for i in issues)


def wants_retry(issues: list[str]) -> bool:
    return any(i.split(":")[0] in HARD | {"missing_numbers", "missing_citations", "much_shorter"} for i in issues)
