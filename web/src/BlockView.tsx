import { memo } from "react";
import { assetUrl } from "./api";
import type { Block } from "./types";

interface Props {
  b: Block;
  docId: string;
  hl: string | null;
  hasNote: boolean;
  selected: boolean;
  playing: boolean;
  bilingual: boolean;
}

function Img({ b, docId, eq }: { b: Block; docId: string; eq?: boolean }) {
  const r = b.regions[0];
  const w = r ? r.x1 - r.x0 + 6 : 400;
  const h = r ? r.y1 - r.y0 + 6 : 300;
  const px = Math.round(w * (eq ? 1.15 : 1.3));
  return (
    <figure>
      <img
        src={assetUrl(docId, b.image!)}
        loading="lazy"
        alt={eq ? b.source : "Figure from the original page"}
        data-zoom="1"
        style={{ width: `min(100%, ${px}px)`, aspectRatio: `${w} / ${h}` }}
      />
    </figure>
  );
}

function BlockViewInner({ b, docId, hl, hasNote, selected, playing, bilingual }: Props) {
  const cls = ["blk", `blk-${b.type}`];
  if (b.status === "pending") cls.push("pending");
  if (b.status === "failed") cls.push("failed");
  if (selected) cls.push("sel");
  if (playing) cls.push("playing");
  if (hl) cls.push(`hl-${hl}`);
  const text = b.translated || b.source;

  let body;
  switch (b.type) {
    case "heading": {
      const L = Math.min(4, Math.max(1, b.level || 2));
      body = (
        <>
          <div className={`h h${L}`} role="heading" aria-level={L + 1}>{text}</div>
          {bilingual && b.translated && <p className="orig">{b.source}</p>}
        </>
      );
      break;
    }
    case "figure":
      body = <Img b={b} docId={docId} />;
      break;
    case "equation":
      body = <Img b={b} docId={docId} eq />;
      break;
    case "table":
      if (b.table_mode === "html" && b.table) {
        const cells = b.table_si || b.table;
        body = (
          <div className="tablewrap">
            <table><tbody>
              {cells.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{c}</td>)}</tr>)}
            </tbody></table>
          </div>
        );
      } else body = <Img b={b} docId={docId} />;
      break;
    case "reference":
      body = <p>{b.source}</p>;
      break;
    default:
      body = (
        <>
          <p>{text}</p>
          {bilingual && b.translated && <p className="orig">{b.source}</p>}
        </>
      );
  }
  return (
    <div className={cls.join(" ")} data-seq={b.seq}>
      {body}
      {hasNote && <span className="note-mark" aria-label="Has a note" />}
    </div>
  );
}

export default memo(BlockViewInner);
