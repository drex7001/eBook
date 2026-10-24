"""Debug helper: show how the parser splits a PDF into blocks.

    python scripts/parse_preview.py path/to/file.pdf [max_blocks]
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.parser import get_parser  # noqa: E402

pdf = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 120
out = tempfile.mkdtemp(prefix="parse-")
t = time.time()
doc = get_parser().parse(pdf, out, progress=lambda d, n: print(f"  pages {d}/{n}", end="\r"))
print(f"\n{doc.title}: {doc.page_count} pages -> {len(doc.blocks)} blocks in {time.time() - t:.1f}s (images in {out})")
print("sections:", ", ".join(f"{s.title} @{s.start_seq}" for s in doc.sections[:30]))
for b in doc.blocks[:limit]:
    extra = f" [{b.image}]" if b.image else ""
    if b.table:
        extra += f" table {len(b.table)}x{len(b.table[0])} ({b.table_mode})"
    print(f"{b.seq:5d} p{b.page + 1:<4d}{b.type:10s}{b.text[:100]!r}{extra}")
