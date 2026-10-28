"""PDF -> ordered Blocks, using PyMuPDF 2.x Layout (ONNX layout model) for box classes and reading order.

Layout gives us classified boxes (text, section-header, picture, table, formula, caption, footnote,
list-item, page-header/footer) in reading order, including two-column pages. We then:
  * re-extract each box's text from MuPDF's own line extraction (proper spacing),
  * glue figure labels onto pictures and merge side-by-side pictures into one figure,
  * crop figures / tables / equations from the page as images (pixel-identical to the original),
  * merge paragraphs that continue across columns / pages,
  * derive sections (from the PDF outline when present) for translation grouping and the TOC.
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf

from .base import (CAPTION, EQUATION, FIGURE, FOOTNOTE, HEADING, LIST_ITEM, PARAGRAPH, REFERENCE, TABLE,
                   Block, ParsedDoc, ProgressCb, Region, Section)

log = logging.getLogger(__name__)

_CAP = r"^\s*(fig(?:ure)?|table|tab|plate|chart|scheme|algorithm|listing|exhibit)\.?\s*([0-9]+|[IVXLC]+)"
CAPTION_LOOSE_RE = re.compile(_CAP + r"\b", re.I)
CAPTION_RE = re.compile(_CAP + r"(\s*[:.\-\u2013\u2014|]|\s*$)", re.I)
REF_HEAD_RE = re.compile(r"^\s*([0-9]+\.?\s*)?(references|bibliography|works cited|literature cited|sources)\s*$", re.I)
REF_ITEM_RE = re.compile(r"^\s*\[[0-9]{1,3}\]\s+\S")
YEAR_RE = re.compile(r"\b(1[89][0-9]{2}|20[0-9]{2})\b")
LIST_MARK_RE = re.compile(r"^\s*([\u2022\u25cf\u25aa\u2013\u2014\-*]\s|\(?[0-9]{1,3}[.)]\s|\(?[a-z][.)]\s|\[[0-9]{1,3}\]\s)")
URL_TAIL_RE = re.compile(r"(https?://|www\.)\S*[/\-._=?&#]$")
CHAPTER_LABEL_RE = re.compile(
    r"^\s*(chapter|part|book|lesson|unit)\s+([0-9]+|[IVXLC]+|[A-Za-z]+)\s*[:.\-–—]?\s*$", re.I)
PAGE_NUM_RE = re.compile(r"^\s*(page\s*)?([0-9]+|[ivxlc]+)\s*$", re.I)
TERMINAL_CHARS = ".!?:;\"”’')]…"

FLOAT_TYPES = {FIGURE, TABLE, FOOTNOTE, CAPTION}
BATCH_PAGES = 25


@dataclass
class _Item:
    cls: str
    rect: pymupdf.Rect
    text: str
    box: object = None
    absorbed: bool = False
    members: list = field(default_factory=list)


# ----------------------------------------------------------------------------- text helpers

def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("­", "").replace("�", "")
    s = re.sub(r"[ \t   ]+", " ", s)
    return s.strip()


def join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = clean_text(ln)
        if not ln:
            continue
        if not out:
            out = ln
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and ln[:1].islower():
            out = out[:-1] + ln          # de-hyphenate "manipula-" + "tion"
        elif URL_TAIL_RE.search(out) and not ln[:1].isupper():
            out += ln                    # URL broken across lines
        else:
            out += " " + ln
    return out


def join_paragraph_parts(a: str, b: str) -> str:
    return join_lines([a, b])


def _norm_title(s: str) -> str:
    s = re.sub(r"^\s*([0-9]+(\.[0-9]+)*\.?|[IVXLC]+\.)\s*", "", s)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# ----------------------------------------------------------------------------- page text

def _page_lines(page: pymupdf.Page) -> list[dict]:
    d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
    out = []
    for b in d["blocks"]:
        if b.get("type", 0) != 0:
            continue
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"]]
            if not spans:
                continue
            txt, prev = "", None
            for s in spans:
                t = s["text"]
                if prev is not None and txt and not txt.endswith(" ") and not t.startswith(" "):
                    if s["bbox"][0] - prev["bbox"][2] > 0.15 * max(s["size"], 1):
                        txt += " "
                txt += t
                prev = s
            if not txt.strip():
                continue
            out.append({"rect": pymupdf.Rect(ln["bbox"]), "text": txt, "size": max(s["size"] for s in spans)})
    return out


def _rows(lines: list[dict]) -> list[dict]:
    """Order a box's lines top-to-bottom, left-to-right (lines sharing a baseline form one row)."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (l["rect"].y0 + l["rect"].y1) / 2)
    rows: list[list[dict]] = [[lines[0]]]
    for ln in lines[1:]:
        last = rows[-1][-1]
        yc, lyc = (ln["rect"].y0 + ln["rect"].y1) / 2, (last["rect"].y0 + last["rect"].y1) / 2
        tol = 0.45 * min(ln["rect"].height, last["rect"].height)
        if abs(yc - lyc) <= tol:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    out = []
    for r in rows:
        r = sorted(r, key=lambda l: l["rect"].x0)
        rect = pymupdf.Rect(r[0]["rect"])
        for l in r[1:]:
            rect |= l["rect"]
        out.append({"text": " ".join(l["text"].strip() for l in r), "rect": rect,
                    "size": max(l["size"] for l in r)})
    return out


def _split_groups(rows: list[dict]) -> list[list[dict]]:
    """Split one layout box into paragraphs where it clearly holds more than one
    (blank-line gap, font-size jump, or a new [n] reference / bullet starting a row)."""
    if len(rows) < 2:
        return [rows]
    heights = sorted(r["rect"].height for r in rows)
    med_h = heights[len(heights) // 2]
    groups = [[rows[0]]]
    for prev, cur in zip(rows, rows[1:]):
        gap = cur["rect"].y0 - prev["rect"].y1
        new = (gap > max(4.0, 0.6 * med_h)
               or abs(cur["size"] - prev["size"]) > 1.2
               or REF_ITEM_RE.match(cur["text"]) is not None
               or re.match(r"^\s*[\u2022\u25cf\u25aa\u2013]\s", cur["text"]) is not None)
        if new:
            groups.append([cur])
        else:
            groups[-1].append(cur)
    return groups


def _assign_lines(lines: list[dict], rects: list[pymupdf.Rect]) -> list[list[dict]]:
    out: list[list[dict]] = [[] for _ in rects]
    grown = [pymupdf.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2) for r in rects]
    for ln in lines:
        c = pymupdf.Point((ln["rect"].x0 + ln["rect"].x1) / 2, (ln["rect"].y0 + ln["rect"].y1) / 2)
        best, best_area = None, float("inf")
        for i, r in enumerate(grown):
            if r.contains(c):
                a = r.width * r.height
                if a < best_area:
                    best, best_area = i, a
        if best is not None:
            out[best].append(ln)
    return out


def _box_fallback_text(box) -> str:
    tl = getattr(box, "textlines", None) or []
    return join_lines([" ".join(s.get("text", "") for s in l.get("spans", [])) for l in tl])


# ----------------------------------------------------------------------------- figures

def _crop(page: pymupdf.Page, rect: pymupdf.Rect, path: str, dpi: int = 200, max_px: int = 1800) -> str:
    r = pymupdf.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3) & page.rect
    zoom = dpi / 72
    if max(r.width, r.height) * zoom > max_px:
        zoom = max_px / max(r.width, r.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=r, alpha=False)
    if pix.width * pix.height > 700_000:
        path = os.path.splitext(path)[0] + ".jpg"
        pix.save(path, jpg_quality=85)
    else:
        pix.save(path)
    return os.path.basename(path)


def _assemble_figures(items: list[_Item], page_area: float, page_w: float, text_chars: int) -> list[_Item]:
    pics = [it for it in items if it.cls == "picture"]
    if not pics:
        return items
    scanned = text_chars < 40
    for p in pics:
        tiny = p.rect.width < 40 or p.rect.height < 30 or p.rect.width * p.rect.height < 0.012 * page_area
        if tiny and not scanned:
            p.absorbed = True  # decorative (logos, badges): drop
    live = [p for p in pics if not p.absorbed]

    # Glue short labels that sit on / right next to a picture into the picture (they're part of the drawing).
    for it in items:
        if it.cls in ("picture", "table", "formula") or it.absorbed:
            continue
        t = it.text.strip()
        if not t or len(t) > 80 or CAPTION_LOOSE_RE.match(t) or re.match(r"^\s*[0-9]+(\.[0-9]+)+\s", t):
            continue
        cx, cy = (it.rect.x0 + it.rect.x1) / 2, (it.rect.y0 + it.rect.y1) / 2
        for p in live:
            near = pymupdf.Rect(p.rect.x0 - 25, p.rect.y0 - 25, p.rect.x1 + 25, p.rect.y1 + 25)
            if not near.intersects(it.rect):
                continue
            inside_h = p.rect.x0 - 30 <= cx <= p.rect.x1 + 30 and it.rect.width < p.rect.width + 140
            inside_v = p.rect.y0 - 5 <= cy <= p.rect.y1 + 5
            if inside_h or inside_v:
                p.rect |= it.rect
                it.absorbed = True
                break

    # Merge pictures that sit side by side (sub-figures) or overlap.
    live.sort(key=lambda p: (p.rect.y0, p.rect.x0))
    merged = True
    while merged:
        merged = False
        for i in range(len(live)):
            for j in range(i + 1, len(live)):
                a, b = live[i], live[j]
                if a.absorbed or b.absorbed:
                    continue
                ov = min(a.rect.y1, b.rect.y1) - max(a.rect.y0, b.rect.y0)
                same_row = ov > 0.4 * min(a.rect.height, b.rect.height)
                gap = max(a.rect.x0, b.rect.x0) - min(a.rect.x1, b.rect.x1)
                if a.rect.intersects(b.rect) or (same_row and gap < 0.25 * page_w):
                    a.rect |= b.rect
                    b.absorbed = True
                    merged = True
    return [it for it in items if not it.absorbed]


def _reorder_columns(items: list[_Item], page_w: float) -> list[_Item]:
    """Two-column pages: read the whole left column, then the right one, band by band.
    Bands are separated by anything that crosses the gutter (full-width figures, titles, abstracts)."""
    mid = page_w / 2
    crosses = [it.rect.x0 < mid - 10 and it.rect.x1 > mid + 10 for it in items]
    left = [it for it, c in zip(items, crosses) if not c and (it.rect.x0 + it.rect.x1) / 2 < mid]
    right = [it for it, c in zip(items, crosses) if not c and (it.rect.x0 + it.rect.x1) / 2 >= mid]
    if len(left) < 2 or len(right) < 2 or (len(left) + len(right)) < 0.5 * len(items):
        return items
    seps = sorted([it for it, c in zip(items, crosses) if c], key=lambda it: it.rect.y0)
    bounds = [s.rect.y0 for s in seps] + [float("inf")]

    def band(it: _Item) -> int:
        yc = (it.rect.y0 + it.rect.y1) / 2
        return next(i for i, b in enumerate(bounds) if yc < b)

    out: list[_Item] = []
    for i in range(len(bounds)):
        out += sorted((it for it in left if band(it) == i), key=lambda it: it.rect.y0)
        out += sorted((it for it in right if band(it) == i), key=lambda it: it.rect.y0)
        if i < len(seps):
            out.append(seps[i])
    return out


# ----------------------------------------------------------------------------- parser

class LayoutParser:
    """Default parser: PyMuPDF Layout. Swap in another class with the same parse() signature."""

    name = "pymupdf-layout"

    def parse(self, pdf_path: str, asset_dir: str, progress: ProgressCb | None = None) -> ParsedDoc:
        from pymupdf4llm.helpers import document_layout as dl

        os.makedirs(asset_dir, exist_ok=True)
        doc = pymupdf.open(pdf_path)
        n = doc.page_count
        blocks: list[Block] = []

        for start in range(0, n, BATCH_PAGES):
            pages = list(range(start, min(n, start + BATCH_PAGES)))
            with contextlib.redirect_stdout(io.StringIO()):
                parsed = dl.parse_document(doc, pages=pages, use_ocr=False, force_text=True)
            for pg in parsed.pages:
                blocks.extend(self._page_blocks(doc[pg.page_number - 1], pg, asset_dir))
            if progress:
                progress(min(n, start + BATCH_PAGES), n)

        toc = doc.get_toc()
        blocks = _merge_chapter_labels(blocks)
        _normalize_heading_levels(blocks, toc)
        blocks = _merge_continuations(blocks)
        _mark_references(blocks)
        blocks = [b for b in blocks if b.type in (FIGURE, TABLE, EQUATION) or b.text.strip()]
        for i, b in enumerate(blocks):
            b.seq = i
        sections = _sections(blocks, toc, n)
        title = _doc_title(doc, blocks, pdf_path)
        sizes = [(doc[i].rect.width, doc[i].rect.height) for i in range(n)]
        doc.close()
        return ParsedDoc(title=title, page_count=n, page_sizes=sizes, blocks=blocks, sections=sections)

    # .........................................................................

    def _page_blocks(self, page: pymupdf.Page, pg, asset_dir: str) -> list[Block]:
        pno = page.number
        W, H = page.rect.width, page.rect.height
        boxes = [b for b in pg.boxes if b.boxclass not in ("page-header", "page-footer")]
        rects = [pymupdf.Rect(b.x0, b.y0, b.x1, b.y1) for b in boxes]
        lines = _page_lines(page)
        assigned = _assign_lines(lines, rects)
        text_chars = sum(len(l["text"].strip()) for l in lines)

        sizes = sorted(l["size"] for l in lines for _ in range(max(1, len(l["text"]) // 20)))
        body = sizes[len(sizes) // 2] if sizes else 10.0

        items: list[_Item] = []
        for b, r, lns in zip(boxes, rects, assigned):
            if not lns:
                items.append(_Item(cls=b.boxclass, rect=r, text=_box_fallback_text(b), box=b))
                continue
            rows = _rows(lns)
            groups = _split_groups(rows) if b.boxclass in ("text", "list-item", "footnote") else [rows]
            for g in groups:
                text = join_lines([row["text"] for row in g])
                if len(groups) == 1:
                    items.append(_Item(cls=b.boxclass, rect=r, text=text, box=b))
                    continue
                gr = pymupdf.Rect(g[0]["rect"])
                for row in g[1:]:
                    gr |= row["rect"]
                gcls = b.boxclass
                if len(g) == 1 and g[0]["size"] > body + 1.2 and len(text) < 120:
                    gcls = "section-header"
                items.append(_Item(cls=gcls, rect=gr, text=text, box=None))
        items = _assemble_figures(items, W * H, W, text_chars)
        items = _reorder_columns(items, W)

        out: list[Block] = []
        k = 0
        for idx, it in enumerate(items):
            reg = [Region(pno, it.rect.x0, it.rect.y0, it.rect.x1, it.rect.y1)]
            cls, text = it.cls, it.text
            if cls == "picture":
                k += 1
                img = _crop(page, it.rect, os.path.join(asset_dir, f"p{pno + 1:04d}_fig{k}.png"))
                out.append(Block(FIGURE, text="", regions=reg, image=img))
            elif cls == "table":
                k += 1
                img = _crop(page, it.rect, os.path.join(asset_dir, f"p{pno + 1:04d}_tab{k}.png"))
                cells = _table_cells(it.box)
                if cells:
                    out.append(Block(TABLE, text=_table_text(cells), regions=reg, image=img, table=cells,
                                     table_mode=_table_mode(cells)))
                else:
                    out.append(Block(FIGURE, text="", regions=reg, image=img))
            elif cls == "formula":
                k += 1
                img = _crop(page, it.rect, os.path.join(asset_dir, f"p{pno + 1:04d}_eq{k}.png"), dpi=220)
                out.append(Block(EQUATION, text=text, regions=reg, image=img))
            elif not text:
                continue
            elif PAGE_NUM_RE.match(text):
                continue
            elif CAPTION_RE.match(text):
                out.append(Block(CAPTION, text=text, regions=reg))
            elif cls in ("section-header", "title"):
                lvl = int(getattr(it.box, "header_level", 0) or 0) or 2
                if len(text) > 200:
                    out.append(Block(PARAGRAPH, text=text, regions=reg))
                else:
                    out.append(Block(HEADING, text=text, level=lvl, regions=reg))
            elif cls == "caption":
                out.append(Block(CAPTION, text=text, regions=reg))
            elif cls == "list-item":
                out.append(Block(LIST_ITEM, text=text, regions=reg))
            elif cls == "footnote":
                out.append(Block(FOOTNOTE, text=text, regions=reg))
            else:
                out.append(Block(PARAGRAPH, text=text, regions=reg))

        # "Table 2" alone + its title line right below -> one caption; a caption split in two -> one
        res: list[Block] = []
        for b in out:
            prev = res[-1] if res else None
            gap = b.regions[0].y0 - prev.regions[-1].y1 if prev else 99
            if prev and prev.type == CAPTION and (
                    (b.type == PARAGRAPH and len(prev.text) < 16 and gap < 15)
                    or (b.type == CAPTION and not CAPTION_RE.match(b.text) and gap < 8)):
                res[-1].text = res[-1].text + " " + b.text
                res[-1].regions.extend(b.regions)
                continue
            res.append(b)
        return res


# ----------------------------------------------------------------------------- tables

def _table_cells(box) -> list[list[str]] | None:
    t = getattr(box, "table", None)
    if not isinstance(t, dict):
        return None
    rows = t.get("extract") or []
    cells = [[join_lines((c or "").split("\n")) for c in r] for r in rows]
    cells = [r for r in cells if any(c for c in r)]
    if len(cells) < 2 or max(len(r) for r in cells) < 2:
        return None
    return cells


def _table_mode(cells: list[list[str]]) -> str:
    non_empty = [c for r in cells for c in r if c]
    wordy = [c for c in non_empty if len(re.findall(r"[^\W\d_]{2,}", c, re.UNICODE)) >= 3
             or (any(ord(ch) > 127 and ch.isalpha() for ch in c) and sum(ch.isalpha() for ch in c) >= 8)]
    return "html" if non_empty and len(wordy) / len(non_empty) >= 0.3 else "image"


def _table_text(cells: list[list[str]]) -> str:
    return "\n".join(" | ".join(r) for r in cells)


# ----------------------------------------------------------------------------- doc-level passes

def _merge_chapter_labels(blocks: list[Block]) -> list[Block]:
    """'Chapter 1' heading immediately followed by 'The MU-puzzle' heading -> one heading."""
    out: list[Block] = []
    for b in blocks:
        prev = out[-1] if out else None
        if (prev and prev.type == HEADING and b.type == HEADING and CHAPTER_LABEL_RE.match(prev.text)
                and prev.page == b.page):
            prev.text = f"{prev.text.strip()} · {b.text.strip()}"
            prev.level = min(prev.level, b.level)
            prev.regions.extend(b.regions)
            continue
        out.append(b)
    return out


def _normalize_heading_levels(blocks: list[Block], toc: list) -> None:
    toc_levels = {}
    for lvl, title, _page in toc or []:
        toc_levels.setdefault(_norm_title(title), lvl)
    min_toc = min(toc_levels.values()) if toc_levels else 1
    heads = [b for b in blocks if b.type == HEADING]
    ranks = sorted({b.level for b in heads})
    for b in heads:
        key = _norm_title(b.text)
        if key in toc_levels:
            b.level = toc_levels[key] - min_toc + 1
        else:
            b.level = ranks.index(b.level) + 1 if b.level in ranks else 2
        b.level = max(1, min(4, b.level))


def _mark_references(blocks: list[Block]) -> None:
    """Bibliography entries stay in English (they are citations, not prose)."""
    in_refs, ref_level = False, 0
    for b in blocks:
        if b.type == HEADING:
            if REF_HEAD_RE.match(b.text):
                in_refs, ref_level = True, b.level
                continue
            if in_refs and b.level <= ref_level:
                in_refs = False
        if b.type in (PARAGRAPH, LIST_ITEM) and (
                in_refs or (REF_ITEM_RE.match(b.text) and YEAR_RE.search(b.text))):
            b.type = REFERENCE


def _ends_open(text: str) -> bool:
    t = text.rstrip()
    if not t:
        return False
    if t.endswith("-") and len(t) > 1 and t[-2].isalpha():
        return True
    return t[-1] not in TERMINAL_CHARS


def _merge_continuations(blocks: list[Block]) -> list[Block]:
    """Join a paragraph that was split by a column/page break (possibly with figures/footnotes between)."""
    out: list[Block] = []
    last_flow = -1  # index in out of the last paragraph/list item, if only floats follow it
    for b in blocks:
        stray_head = b.type == HEADING and b.text.lstrip()[:1].islower() and len(b.text) < 40
        if (b.type in (PARAGRAPH, LIST_ITEM) or stray_head) and last_flow >= 0 and not LIST_MARK_RE.match(b.text):
            prev = out[last_flow]
            t = b.text.lstrip()
            first = t[:1]
            ptail = prev.text.rstrip()[-1:]
            cont = first.islower() or ptail in "-,(\u2013" or (first in ")]},.;:" and first != "")
            if _ends_open(prev.text) and first and cont:
                prev.text = join_paragraph_parts(prev.text, b.text)
                prev.regions.extend(b.regions)
                continue
        out.append(b)
        if b.type in (PARAGRAPH, LIST_ITEM):
            last_flow = len(out) - 1
        elif b.type not in FLOAT_TYPES:
            last_flow = -1
    return out


def _sections(blocks: list[Block], toc: list, page_count: int) -> list[Section]:
    starts: list[Section] = []
    heads = [b for b in blocks if b.type == HEADING]
    if toc:
        counts: dict[int, int] = {}
        for lvl, _t, _p in toc:
            counts[lvl] = counts.get(lvl, 0) + 1
        level = min((l for l, c in counts.items() if c >= 2), default=None)
        if level is not None:
            for lvl, title, page in toc:
                if lvl != level:
                    continue
                key = _norm_title(title)
                hit = next((b for b in heads if _norm_title(b.text) == key and b.page >= page - 2), None)
                if hit is None:
                    hit = next((b for b in blocks if b.page >= max(0, page - 1)), None)
                if hit is not None:
                    starts.append(Section(title=title.strip(), start_seq=hit.seq))
    if len(starts) < 2 and heads:
        for lvl in (1, 2):
            cand = [b for b in heads if b.level == lvl]
            if 2 <= len(cand) <= max(2, len(blocks) // 4):
                starts = [Section(title=b.text, start_seq=b.seq) for b in cand]
                break
    if len(starts) < 2:
        step = 15
        starts = []
        for p in range(0, page_count, step):
            hit = next((b for b in blocks if b.page >= p), None)
            if hit is not None:
                starts.append(Section(title=f"Pages {p + 1}–{min(page_count, p + step)}", start_seq=hit.seq))

    # dedupe, sort, make sure the first section starts at 0
    seen, uniq = set(), []
    for s in sorted(starts, key=lambda s: s.start_seq):
        if s.start_seq not in seen:
            seen.add(s.start_seq)
            uniq.append(s)
    if not uniq or uniq[0].start_seq != 0:
        uniq.insert(0, Section(title="Front matter", start_seq=0))

    # fold very small sections into the next one so each LLM context has some substance
    sizes = []
    for i, s in enumerate(uniq):
        end = uniq[i + 1].start_seq if i + 1 < len(uniq) else len(blocks)
        sizes.append(sum(len(b.text) for b in blocks[s.start_seq:end] if b.translatable))
    merged: list[Section] = []
    pending: int | None = None
    for i, (s, size) in enumerate(zip(uniq, sizes)):
        start = pending if pending is not None else s.start_seq
        if size < 800 and i < len(uniq) - 1:
            if pending is None:
                pending = s.start_seq
            continue
        merged.append(Section(title=s.title, start_seq=start))
        pending = None
    return merged


def _doc_title(doc: pymupdf.Document, blocks: list[Block], pdf_path: str) -> str:
    t = (doc.metadata or {}).get("title") or ""
    t = t.strip()
    if t and not re.search(r"[\\/]|\.(obd|docx?|pdf|tex)$", t, re.I) and len(t) > 3:
        return t
    skip = {"contents", "table of contents", "overview", "preface", "abstract", "foreword", "introduction"}
    for b in blocks:
        if b.page > 1:
            break
        if b.type == HEADING and b.level == 1 and len(b.text) > 3 and b.text.strip().lower() not in skip:
            return b.text
    return ""  # caller falls back to the uploaded file name
