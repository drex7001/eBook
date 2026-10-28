"""Pass 2: translate blocks section by section, with summaries + neighbouring passages as context."""
from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .. import db
from ..llm import LLMError
from . import prompts, qa
from .common import Paused, TRANSLATABLE_TEXT
from .understand import merge_terms

log = logging.getLogger(__name__)
MAX_ITEMS = 40


@dataclass
class Unit:
    id: str
    seq: int
    type: str
    text: str
    cell: tuple[int, int] | None = None


def units_for_row(r) -> list[Unit]:
    if r["type"] == "table":
        if r["table_mode"] != "html" or not r["source_table"]:
            return []
        cells = json.loads(r["source_table"])
        out = []
        for i, row in enumerate(cells):
            for j, txt in enumerate(row):
                if txt and sum(ch.isalpha() for ch in txt) >= 2:
                    out.append(Unit(f"{r['seq']}.{i}.{j}", r["seq"], "table_cell", txt, (i, j)))
        return out
    if r["type"] in TRANSLATABLE_TEXT and (r["source"] or "").strip():
        return [Unit(str(r["seq"]), r["seq"], r["type"], r["source"])]
    return []


def batches(units: list[Unit], max_chars: int) -> list[list[Unit]]:
    out: list[list[Unit]] = []
    cur: list[Unit] = []
    size = 0
    for u in units:
        n = len(u.text)
        # keep all cells of one table in the same batch when possible
        if cur and (size + n > max_chars or len(cur) >= MAX_ITEMS) and not (u.cell and cur[-1].seq == u.seq and size + n < 2 * max_chars):
            out.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += n
    if cur:
        out.append(cur)
    return out


class Translator:
    def __init__(self, doc_id: str, llm, settings, should_stop=lambda: False):
        self.doc_id = doc_id
        self.llm = llm
        self.settings = settings
        self.should_stop = should_stop
        doc = db.get_doc(doc_id)
        self.title = doc["title"]
        self.brief = prompts.format_brief(json.loads(doc["brief"] or "{}"), doc["title"])
        self.chunks = [dict(r) for r in db.q("SELECT idx, start_seq, end_seq, summary FROM chunks WHERE doc_id=? ORDER BY idx", doc_id)]
        self._gloss_lock = threading.Lock()
        self._load_glossary()
        self._table_parts: dict[int, dict[tuple[int, int], str]] = {}
        self._table_lock = threading.Lock()

    # ------------------------------------------------------------------ context

    def _load_glossary(self) -> None:
        with self._gloss_lock:
            self.glossary = [dict(r) for r in db.q(
                "SELECT term, rendering, policy, count FROM glossary WHERE doc_id=? ORDER BY locked DESC, count DESC LIMIT 600",
                self.doc_id)]
            self._gloss_res = [(re.compile(r"(?<!\w)" + re.escape(g["term"]) + r"(?!\w)", re.I), g) for g in self.glossary]

    def glossary_for(self, text: str) -> list[dict]:
        with self._gloss_lock:
            hits = [g for rx, g in self._gloss_res if rx.search(text)]
        return hits[:60]

    def summaries_for(self, seq: int) -> list[str]:
        before = [c for c in self.chunks if c["end_seq"] < seq and c["summary"]][-2:]
        cur = [c for c in self.chunks if c["start_seq"] <= seq <= c["end_seq"] and c["summary"]]
        out = [f"- {c['summary']}" for c in before]
        out += [f"- (this part) {c['summary']}" for c in cur]
        return out

    def previous_for(self, seq: int, n: int = 3, english_only: bool = False) -> list[tuple[str, str]]:
        if english_only:   # batch jobs are built before anything is translated
            rows = db.q("SELECT source FROM blocks WHERE doc_id=? AND seq<? AND type IN ('paragraph','list_item','heading') "
                        "ORDER BY seq DESC LIMIT ?", self.doc_id, seq, n)
            return [(r["source"][:700], "") for r in reversed(rows)]
        rows = db.q("SELECT source, translated FROM blocks WHERE doc_id=? AND seq<? AND status='done' "
                    "AND type IN ('paragraph','list_item','heading') AND translated IS NOT NULL ORDER BY seq DESC LIMIT ?",
                    self.doc_id, seq, n)
        return [(r["source"][:700], r["translated"][:1200]) for r in reversed(rows)]

    def following_for(self, seq: int, n: int = 2) -> list[str]:
        rows = db.q("SELECT source FROM blocks WHERE doc_id=? AND seq>? AND type IN ('paragraph','list_item','heading') "
                    "ORDER BY seq LIMIT ?", self.doc_id, seq, n)
        return [r["source"][:500] for r in rows]

    # ------------------------------------------------------------------ core

    def build_prompt(self, units: list[Unit], extra: str = "", english_context: bool = False) -> str:
        text = "\n".join(u.text for u in units)
        items = [{"id": u.id, "type": u.type, "text": u.text} for u in units]
        return prompts.translate_prompt(
            brief=self.brief,
            glossary=prompts.format_glossary(self.glossary_for(text)),
            summaries=self.summaries_for(units[0].seq),
            previous=self.previous_for(units[0].seq, english_only=english_context),
            items=items,
            following=self.following_for(units[-1].seq),
            extra_instruction=extra,
        )

    def parse(self, res) -> dict[str, str]:
        if res.data.get("new_terms"):
            merge_terms(self.doc_id, res.data["new_terms"])
            self._load_glossary()
        out: dict[str, str] = {}
        for t in res.data.get("translations") or []:
            if isinstance(t, dict) and "id" in t:
                out[str(t["id"]).strip()] = str(t.get("text") or t.get("si") or "").strip()
        return out

    def call(self, units: list[Unit], extra: str = "") -> dict[str, str]:
        res = self.llm.generate_json(prompts.system_for("translate", self.settings), self.build_prompt(units, extra), prompts.translation_schema(),
                                     purpose="translate")
        db.add_usage(self.doc_id, res, "translate")
        return self.parse(res)

    def accept_batch(self, units: list[Unit], got: dict[str, str]) -> int:
        """Batch results: keep clean answers; anything doubtful stays pending for the normal pass (which retries)."""
        ok = []
        for u in units:
            si = got.get(u.id, "")
            issues = qa.check(u.text, si, u.type, getattr(self.settings, "target_language", "si"))
            if not qa.wants_retry(issues):
                ok.append((u, si, issues))
        return self._save(ok)

    def translate_units(self, units: list[Unit], extra: str = "", attempt: int = 0) -> int:
        """Translate, check, retry once, save. Returns number of blocks completed."""
        if self.should_stop():
            raise Paused()
        try:
            got = self.call(units, extra)
        except LLMError as e:
            if e.retryable:
                raise
            if len(units) > 1:      # isolate the item the model refuses
                mid = len(units) // 2
                return self.translate_units(units[:mid], extra, attempt) + self.translate_units(units[mid:], extra, attempt)
            self._fail(units[0], [f"error:{e}"])
            return 0

        accepted: list[tuple[Unit, str, list[str]]] = []
        retry: list[tuple[Unit, list[str]]] = []
        for u in units:
            si = got.get(u.id, "")
            issues = qa.check(u.text, si, u.type, getattr(self.settings, "target_language", "si"))
            if attempt == 0 and qa.wants_retry(issues):
                retry.append((u, issues))
            elif "empty" in issues:
                self._fail(u, issues)
            else:
                # a second answer without Sinhala is usually right (names, affiliations, e-mails): keep it, flagged
                accepted.append((u, si, issues))
        done = self._save(accepted)
        if retry:
            notes = "; ".join(f"id {u.id}: {', '.join(i)}" for u, i in retry)
            msg = ("Your previous answer for these items had problems (" + notes + "). Translate them again completely; "
                   "keep every number and citation marker exactly as in the source.")
            if extra:
                msg = extra + "\n" + msg
            done += self.translate_units([u for u, _ in retry], msg, attempt=1)
        return done

    def _fail(self, u: Unit, issues: list[str]) -> None:
        if u.cell:
            self._table_cell(u, u.text)   # keep the English cell rather than lose the table
            return
        db.ex("UPDATE blocks SET status='failed', qa=?, rev=? WHERE doc_id=? AND seq=?",
              json.dumps(issues), db.next_rev(), self.doc_id, u.seq)

    def _table_cell(self, u: Unit, si: str) -> bool:
        """Collect cells; when the table is complete write it. Returns True when the table got saved."""
        with self._table_lock:
            parts = self._table_parts.setdefault(u.seq, {})
            parts[u.cell] = si
            row = db.q1("SELECT * FROM blocks WHERE doc_id=? AND seq=?", self.doc_id, u.seq)
            needed = {x.cell for x in units_for_row(row)}
            if not needed.issubset(parts):
                return False
            cells = json.loads(row["source_table"])
            out = [[parts.get((i, j), c) for j, c in enumerate(r)] for i, r in enumerate(cells)]
            db.ex("UPDATE blocks SET translated_table=?, status='done', rev=? WHERE doc_id=? AND seq=?",
                  json.dumps(out, ensure_ascii=False), db.next_rev(), self.doc_id, u.seq)
            self._table_parts.pop(u.seq, None)
            return True

    def _save(self, accepted: list[tuple[Unit, str, list[str]]]) -> int:
        n = 0
        for u, si, issues in accepted:
            if u.cell:
                n += 1 if self._table_cell(u, si) else 0
                continue
            db.ex("UPDATE blocks SET translated=?, status='done', qa=?, rev=? WHERE doc_id=? AND seq=?",
                  si, json.dumps(issues) if issues else None, db.next_rev(), self.doc_id, u.seq)
            n += 1
        return n

    # ------------------------------------------------------------------ sections

    def pending_units(self, start: int, end: int) -> list[Unit]:
        rows = db.q("SELECT * FROM blocks WHERE doc_id=? AND seq BETWEEN ? AND ? AND status='pending' ORDER BY seq",
                    self.doc_id, start, end)
        return [u for r in rows for u in units_for_row(r)]

    def run_section(self, start: int, end: int, on_progress) -> None:
        for b in batches(self.pending_units(start, end), self.settings.translate_batch_chars):
            n = self.translate_units(b)
            on_progress(n)


def work_units(doc_id: str, min_chars: int) -> list[tuple[int, int]]:
    """Sections merged until each holds at least one full batch of pending text, so short sections
    (common in papers) don't each cost a separate, mostly-overhead LLM call."""
    secs = db.q("SELECT idx, start_seq, end_seq FROM sections WHERE doc_id=? ORDER BY idx", doc_id)
    sizes = {r["section"]: r["n"] for r in db.q(
        "SELECT section, SUM(LENGTH(COALESCE(source,''))) AS n FROM blocks WHERE doc_id=? AND status='pending' GROUP BY section",
        doc_id)}
    groups: list[list[int]] = []
    cur: list[int] | None = None
    for s in secs:
        if cur is None:
            cur = [s["start_seq"], s["end_seq"], 0]
        cur[1] = s["end_seq"]
        cur[2] += sizes.get(s["idx"], 0) or 0
        if cur[2] >= min_chars:
            groups.append(cur)
            cur = None
    if cur is not None:
        if groups and cur[2] < min_chars / 3:
            groups[-1][1] = cur[1]          # tiny tail: fold into the previous group
        else:
            groups.append(cur)
    return [(g[0], g[1]) for g in groups]


def refresh_counts(doc_id: str) -> None:
    r = db.q1("SELECT SUM(status='done') AS d, SUM(status='failed') AS f, SUM(status IN ('done','failed','pending')) AS t "
              "FROM blocks WHERE doc_id=?", doc_id)
    db.update_doc(doc_id, translated=r["d"] or 0, failed=r["f"] or 0, translatable=r["t"] or 0)


def run(doc_id: str, llm, settings, should_stop) -> None:
    tr = Translator(doc_id, llm, settings, should_stop)
    groups = list(enumerate(work_units(doc_id, settings.translate_batch_chars)))
    pos = db.q1("SELECT seq FROM positions WHERE doc_id=?", doc_id)
    here = pos["seq"] if pos else 0
    cur = next((i for i, (a, b) in groups if a <= here <= b), 0)
    # reader's current part first, then what follows, then what came before
    order = [g for _, g in sorted(groups, key=lambda x: (x[0] < cur, x[0] if x[0] >= cur else -x[0]))]

    refresh_counts(doc_id)
    lock = threading.Lock()

    def progress(n: int) -> None:
        with lock:
            refresh_counts(doc_id)
            d = db.get_doc(doc_id)
            db.update_doc(doc_id, stage_done=d["translated"] + d["failed"], stage_total=d["translatable"])

    d = db.get_doc(doc_id)
    db.update_doc(doc_id, stage="translate", stage_done=d["translated"] + d["failed"], stage_total=d["translatable"])
    with ThreadPoolExecutor(max_workers=max(1, settings.concurrency)) as pool:
        futs = [pool.submit(tr.run_section, a, b, progress) for a, b in order]
        err = None
        for f in as_completed(futs):
            try:
                f.result()
            except Paused as e:
                err = err or e
            except Exception as e:  # stop scheduling more work, surface the first real error
                err = e
                for g in futs:
                    g.cancel()
        if err:
            raise err
    progress(0)


def retranslate(doc_id: str, seq: int, instruction: str, llm, settings) -> dict:
    row = db.q1("SELECT * FROM blocks WHERE doc_id=? AND seq=?", doc_id, seq)
    if row is None:
        raise KeyError(seq)
    units = units_for_row(row)
    if not units:
        raise ValueError("This block has nothing to translate.")
    db.ex("UPDATE blocks SET status='pending' WHERE doc_id=? AND seq=?", doc_id, seq)
    tr = Translator(doc_id, llm, settings)
    extra = instruction.strip()
    if extra:
        extra = f"The reader asked: \"{extra}\" — apply this to these items."
    tr.translate_units(units, extra)
    refresh_counts(doc_id)
    return db.block_row_to_api(db.q1("SELECT * FROM blocks WHERE doc_id=? AND seq=?", doc_id, seq))


# ----------------------------------------------------------------------------- Batch API

def batch_requests(doc_id: str, llm, settings) -> tuple[list[tuple[str, str, str, dict]], dict[str, list[str]]]:
    """All pending translation calls as Batch API requests. Context uses English for the previous
    passages because nothing is translated yet when the job is built."""
    tr = Translator(doc_id, llm, settings)
    reqs, keymap = [], {}
    for a, b in work_units(doc_id, settings.translate_batch_chars):
        for units in batches(tr.pending_units(a, b), settings.translate_batch_chars):
            key = f"t{len(reqs)}"
            reqs.append((key, prompts.system_for("translate", settings), tr.build_prompt(units, english_context=True), prompts.translation_schema()))
            keymap[key] = [u.id for u in units]
    return reqs, keymap


def ingest_batch(doc_id: str, results, keymap: dict[str, list[str]], llm, settings, model: str) -> int:
    tr = Translator(doc_id, llm, settings)
    units = {u.id: u for u in tr.pending_units(0, 10 ** 9)}
    n = 0
    for key, res, _err in results:
        if res is None or key not in keymap:
            continue
        res.model = model
        db.add_usage(doc_id, res, "translate")
        got = tr.parse(res)
        n += tr.accept_batch([units[i] for i in keymap[key] if i in units], got)
    refresh_counts(doc_id)
    return n
