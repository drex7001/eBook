"""Parser output model. Every later stage (translation, reader, notes, audio) keys off Block.seq."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

# Block types
HEADING = "heading"
PARAGRAPH = "paragraph"
LIST_ITEM = "list_item"
CAPTION = "caption"
FOOTNOTE = "footnote"
FIGURE = "figure"
TABLE = "table"
EQUATION = "equation"
REFERENCE = "reference"  # bibliography entry: kept in English

TEXT_TYPES = {HEADING, PARAGRAPH, LIST_ITEM, CAPTION, FOOTNOTE}


@dataclass
class Region:
    page: int  # 0-based
    x0: float
    y0: float
    x1: float
    y1: float

    def as_dict(self) -> dict:
        return {"page": self.page, "x0": round(self.x0, 1), "y0": round(self.y0, 1),
                "x1": round(self.x1, 1), "y1": round(self.y1, 1)}


@dataclass
class Block:
    type: str
    text: str = ""
    level: int = 0
    regions: list[Region] = field(default_factory=list)
    image: str | None = None          # asset filename for figure / table / equation crops
    table: list[list[str]] | None = None
    table_mode: str | None = None     # "html" = translate cells, "image" = show original crop
    seq: int = -1

    @property
    def page(self) -> int:
        return self.regions[0].page if self.regions else 0

    @property
    def translatable(self) -> bool:
        if self.type in TEXT_TYPES:
            return bool(self.text.strip())
        return self.type == TABLE and self.table_mode == "html"


@dataclass
class Section:
    title: str
    start_seq: int


@dataclass
class ParsedDoc:
    title: str
    page_count: int
    page_sizes: list[tuple[float, float]]
    blocks: list[Block]
    sections: list[Section]


ProgressCb = Callable[[int, int], None]


class Parser(Protocol):
    def parse(self, pdf_path: str, asset_dir: str, progress: ProgressCb | None = None) -> ParsedDoc: ...
