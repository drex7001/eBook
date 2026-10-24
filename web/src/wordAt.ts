/** The English word under a tap, using the browser's caret-from-point API. Null if the tap wasn't on a Latin word. */
const WORD = /[A-Za-z][A-Za-z'’-]*/;

function caretAt(x: number, y: number): { node: Node; offset: number } | null {
  const d = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  if (d.caretPositionFromPoint) {
    const p = d.caretPositionFromPoint(x, y);
    return p ? { node: p.offsetNode, offset: p.offset } : null;
  }
  if (d.caretRangeFromPoint) {
    const r = d.caretRangeFromPoint(x, y);
    return r ? { node: r.startContainer, offset: r.startOffset } : null;
  }
  return null;
}

export function wordAt(x: number, y: number): string | null {
  const c = caretAt(x, y);
  if (!c || c.node.nodeType !== Node.TEXT_NODE) return null;
  const text = c.node.textContent || "";
  let a = c.offset, b = c.offset;
  const isW = (ch: string) => /[A-Za-z'’-]/.test(ch);
  while (a > 0 && isW(text[a - 1])) a--;
  while (b < text.length && isW(text[b])) b++;
  const m = text.slice(a, b).match(WORD);
  if (!m) return null;
  const word = m[0].replace(/['’-]+$/, "");
  if (word.length < 2) return null;
  // make sure the finger was actually on the word, not in the gap next to it
  const range = document.createRange();
  range.setStart(c.node, a);
  range.setEnd(c.node, b);
  const rects = Array.from(range.getClientRects());
  const hit = rects.some((r) => x >= r.left - 4 && x <= r.right + 4 && y >= r.top - 4 && y <= r.bottom + 4);
  return hit ? word : null;
}
