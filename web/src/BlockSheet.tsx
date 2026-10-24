import { useLayoutEffect, useRef, useState } from "react";
import { api, pageUrl } from "./api";
import { IconCopy, IconNote, IconRetry, IconSpeaker } from "./icons";
import Sheet from "./Sheet";
import type { Block, Doc, Note, Region } from "./types";
import { isSpeakable } from "./useAudio";
import { wordAt } from "./wordAt";

const COLORS = ["turmeric", "green", "lotus", "sky"] as const;

function PageCrop({ docId, r, size, onZoom }: { docId: string; r: Region; size: [number, number]; onZoom: (u: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => setW(ref.current?.clientWidth ?? 0), []);
  const [pw, ph] = size;
  const cx0 = Math.max(0, r.x0 - 14), cx1 = Math.min(pw, r.x1 + 14);
  const cy0 = Math.max(0, r.y0 - 22), cy1 = Math.min(ph, r.y1 + 22);
  const s = w ? w / (cx1 - cx0) : 0;
  const inner = (cy1 - cy0) * s;
  return (
    <div className="crop" ref={ref} onClick={() => onZoom(pageUrl(docId, r.page))} style={{ height: Math.min(inner || 120, 340), overflowY: inner > 340 ? "auto" : "hidden" }}>
      {s > 0 && (
        <div style={{ position: "relative", height: inner }}>
          <img src={pageUrl(docId, r.page)} alt={`Original page ${r.page + 1}`}
            style={{ width: pw * s, left: -cx0 * s, top: -cy0 * s }} />
          <div className="mark" style={{
            left: (r.x0 - cx0) * s - 3, top: (r.y0 - cy0) * s - 3,
            width: (r.x1 - r.x0) * s + 6, height: (r.y1 - r.y0) * s + 6,
          }} />
        </div>
      )}
    </div>
  );
}

function qaText(q: string): string {
  const [k, v] = q.split(":");
  if (k === "missing_numbers") return `Translation එකේ මේ අංක නෑ: ${v}`;
  if (k === "missing_citations") return `Citation markers අඩුයි: ${v}`;
  if (k === "much_shorter") return "Translation එක original එකට වඩා ගොඩක් කෙටියි, මොනවා හරි මගඇරිලා වෙන්න පුළුවන්";
  if (k === "no_sinhala") return "Output එකේ සිංහල නෑ";
  if (k === "empty") return "Model එකෙන් translation එකක් ආවේ නෑ";
  if (k === "error") return `Error: ${q.slice(6)}`;
  return q;
}

export default function BlockSheet({ doc, block, notes, onClose, onListen, onNotes, onBlock, onToast, onZoom, onWord }: {
  doc: Doc; block: Block; notes: Note[]; onZoom: (url: string) => void; onWord: (w: string) => void;
  onClose: () => void; onListen: (seq: number) => void;
  onNotes: (n: Note[]) => void; onBlock: (b: Block) => void; onToast: (m: string) => void;
}) {
  const [mode, setMode] = useState<"" | "note" | "retranslate">("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const mine = notes.filter((n) => n.seq === block.seq);
  const hlNote = mine.find((n) => n.color && !n.body);
  const textual = !["figure", "equation"].includes(block.type) && !(block.type === "table" && block.table_mode !== "html");
  const canTranslate = ["heading", "paragraph", "list_item", "caption", "footnote"].includes(block.type) ||
    (block.type === "table" && block.table_mode === "html");

  const setHighlight = async (c: string | null) => {
    try {
      if (hlNote && !c) {
        await api.deleteNote(doc.id, hlNote.id);
        onNotes(notes.filter((n) => n.id !== hlNote.id));
      } else if (hlNote && c) {
        const u = await api.editNote(doc.id, hlNote.id, { color: c, quote: hlNote.quote, body: null });
        onNotes(notes.map((n) => (n.id === u.id ? u : n)));
      } else if (c) {
        const n = await api.addNote(doc.id, { seq: block.seq, color: c });
        onNotes([...notes, n]);
      }
    } catch (e) { onToast((e as Error).message); }
  };

  const saveNote = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const n = await api.addNote(doc.id, { seq: block.seq, body: text.trim(), quote: (block.translated || block.source).slice(0, 140) });
      onNotes([...notes, n]);
      setText(""); setMode("");
    } catch (e) { onToast((e as Error).message); } finally { setBusy(false); }
  };

  const retranslate = async () => {
    setBusy(true);
    try {
      const b = await api.retranslate(doc.id, block.seq, text.trim());
      onBlock(b);
      setText(""); setMode("");
      onToast("අලුත් translation එක දැම්මා");
    } catch (e) { onToast((e as Error).message); } finally { setBusy(false); }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(block.translated || block.source);
      onToast("Copy කළා");
    } catch { onToast("Copy කරන්න බැරි වුණා"); }
  };

  const size = (r: Region): [number, number] => doc.page_sizes[r.page] ?? [612, 792];

  return (
    <Sheet onClose={onClose} leafy label="Original text">
      <h3>Original එක <small>පිටුව {block.page + 1}</small></h3>
      {textual && block.type !== "table" && (
        <p className="original" onClick={(e) => { const w = wordAt(e.clientX, e.clientY); if (w) onWord(w); }}>{block.source}</p>
      )}
      {textual && block.type !== "table" && <p className="small" style={{ marginTop: -6 }}>English වචනයක් tap කරලා තේරුම බලන්න.</p>}
      {block.regions.map((r, i) => <PageCrop key={i} docId={doc.id} r={r} size={size(r)} onZoom={onZoom} />)}
      {block.qa?.map((q) => <p className="qa" key={q}>{qaText(q)}</p>)}

      <div className="actions">
        {isSpeakable(block) && (
          <button className="act primary" onClick={() => onListen(block.seq)}><IconSpeaker width={19} height={19} />මෙතන ඉඳන් අහන්න</button>
        )}
        <button className="act" onClick={() => { setMode(mode === "note" ? "" : "note"); setText(""); }}><IconNote width={19} height={19} />Note එකක්</button>
        {canTranslate && (
          <button className="act" onClick={() => { setMode(mode === "retranslate" ? "" : "retranslate"); setText(""); }}>
            <IconRetry width={19} height={19} />ආයෙ translate
          </button>
        )}
        {textual && <button className="act" onClick={copy}><IconCopy width={19} height={19} />Copy</button>}
      </div>

      <div className="swatches" role="group" aria-label="Highlight">
        {COLORS.map((c) => (
          <button key={c} className={`swatch ${c}` + (hlNote?.color === c ? " on" : "")} aria-label={`Highlight ${c}`}
            onClick={() => setHighlight(c)} />
        ))}
        {hlNote && <button className="swatch none" aria-label="Remove highlight" onClick={() => setHighlight(null)}>×</button>}
      </div>

      {mode === "note" && (
        <div>
          <textarea className="field" autoFocus value={text} onChange={(e) => setText(e.target.value)}
            placeholder="මේ කොටස ගැන ඔයාගේ note එක" />
          <div className="actions"><button className="act primary" disabled={busy || !text.trim()} onClick={saveNote}>Save කරන්න</button></div>
        </div>
      )}
      {mode === "retranslate" && (
        <div>
          <textarea className="field" autoFocus value={text} onChange={(e) => setText(e.target.value)}
            placeholder="මොකක්ද වෙනස් කරන්න ඕන? (නැතත් කමක් නෑ) උදා: 'gradient' එක English වලින්ම තියන්න" />
          <div className="actions">
            <button className="act primary" disabled={busy} onClick={retranslate}>{busy ? "Translate කරනවා..." : "ආයෙ translate කරන්න"}</button>
          </div>
        </div>
      )}

      {mine.filter((n) => n.body).map((n) => (
        <div className="note-item" key={n.id}>
          <div className="body">{n.body}</div>
          <button className="act" onClick={async () => {
            await api.deleteNote(doc.id, n.id).catch(() => {});
            onNotes(notes.filter((x) => x.id !== n.id));
          }}>Delete</button>
        </div>
      ))}
    </Sheet>
  );
}
