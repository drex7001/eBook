"""Cheap automatic checks on each translation. Hard issues trigger a retry; soft ones are stored for the reader."""
from __future__ import annotations

import re
from collections import Counter

SINHALA_RE = re.compile(r"[඀-෿]")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
CITE_RE = re.compile(r"\[\d+(?:\s*[,–\-]\s*\d+)*\]")

HARD = {"empty", "no_sinhala"}


def _nums(s: str) -> Counter:
    return Counter(n.replace(",", "") for n in NUM_RE.findall(s))


def check(source: str, target: str, kind: str = "paragraph") -> list[str]:
    t = (target or "").strip()
    if not t:
        return ["empty"]
    issues: list[str] = []
    english_words = len(re.findall(r"[A-Za-z]{3,}", source))
    if kind != "table_cell" and english_words >= 5 and not SINHALA_RE.search(t):
        issues.append("no_sinhala")
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
