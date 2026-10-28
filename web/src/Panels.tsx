import { useEffect, useState } from "react";
import { api } from "./api";
import { usePrefs, useText } from "./prefs";
import Sheet from "./Sheet";
import type { Block, Doc, GlossaryTerm, Note } from "./types";

export function TocSheet({ blocks, current, onJump, onClose }: {
  blocks: Block[]; current: number; onJump: (seq: number) => void; onClose: () => void;
}) {
  const p=usePrefs(),t=useText();
  const heads = blocks.filter((b) => b.type === "heading" && b.level <= 3);
  const cur = [...heads].reverse().find((h) => h.seq <= current)?.seq;
  return (
    <Sheet onClose={onClose} label="Contents">
      <h3>{t("Contents","පටුන")}</h3>
      {heads.length === 0 && <p className="small">{t("No headings were found in this document.","මේ document එකේ headings හොයාගන්න බැරි වුණා.")}</p>}
      {heads.map((h) => (
        <button key={h.seq} className={"list-btn" + (h.seq === cur ? " cur" : "")}
          style={{ paddingLeft: 6 + (h.level - 1) * 16 }} onClick={() => onJump(h.seq)}>
          <span className="pg">{h.page + 1}</span>
          {p.displayMode==="original"?h.source:h.translated || h.source}
        </button>
      ))}
    </Sheet>
  );
}

export function NotesSheet({ notes, blocks, onJump, onClose }: {
  notes: Note[]; blocks: Block[]; onJump: (seq: number) => void; onClose: () => void;
}) {
  const p=usePrefs(),t=useText();
  const sorted = [...notes].sort((a, b) => a.seq - b.seq || a.id - b.id);
  return (
    <Sheet onClose={onClose} label="Notes and highlights">
      <h3>Notes <small>{notes.length}</small></h3>
      {sorted.length === 0 && (
        <p className="small">{t("Tap a paragraph to add a note or highlight.","තාම notes නෑ. Paragraph එකක් tap කරලා note එකක් හරි highlight එකක් හරි දාන්න.")}</p>
      )}
      {sorted.map((n) => {
        const b = blocks[n.seq];
        const excerpt = (p.displayMode==="original"?b?.source||"":b?.translated || b?.source || "").slice(0, 110);
        return (
          <button key={n.id} className="list-btn" onClick={() => onJump(n.seq)}>
            <span className="pg">{(b?.page ?? 0) + 1}</span>
            <span className="small" style={{ display: "block" }}>
              {n.color && <span className={`swatch ${n.color}`} style={{ display: "inline-block", width: 10, height: 10, marginRight: 6 }} />}
              {excerpt}{excerpt.length >= 110 ? "…" : ""}
            </span>
            {n.body && <span style={{ fontFamily: "var(--f-read)" }}>{n.body}</span>}
          </button>
        );
      })}
    </Sheet>
  );
}

export function Glossary({ docId, onToast }: { docId: string; onToast: (m: string) => void }) {
  const tr=useText();
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null);
  useEffect(() => { api.glossary(docId).then(setTerms).catch((e) => onToast(e.message)); }, [docId, onToast]);
  if (!terms) return <p className="small">Load වෙනවා...</p>;
  const save = (t: GlossaryTerm, patch: Partial<GlossaryTerm>) => {
    const n = { ...t, ...patch };
    setTerms(terms.map((x) => (x.term === t.term ? { ...n, locked: 1 } : x)));
    api.editTerm(docId, { term: n.term, rendering: n.policy === "keep_en" ? n.term : n.rendering, policy: n.policy })
      .catch((e) => onToast(e.message));
  };
  return (
    <>
      <p className="small">{tr("Edits apply to this translation version. Retranslate a passage explicitly to apply changes to already translated text.","මේ වෙනස්කම් මේ translation version එකට අදාළයි. දැනට translate වුණු paragraph එකකට වෙනස්කම් දාන්න ඒක ආයෙ translate කරන්න.")}</p>
      <table className="gloss"><tbody>
        {terms.slice(0, 300).map((t) => (
          <tr key={t.term}>
            <td style={{ width: "36%" }}>{t.term}</td>
            <td>
              <input defaultValue={t.rendering} disabled={t.policy === "keep_en"} aria-label={`Rendering for ${t.term}`}
                onBlur={(e) => e.target.value !== t.rendering && save(t, { rendering: e.target.value })} />
            </td>
            <td style={{ width: 96 }}>
              <select value={t.policy} aria-label={`Policy for ${t.term}`} onChange={(e) => save(t, { policy: e.target.value as GlossaryTerm["policy"] })}>
                <option value="keep_en">{tr("Source","Original")}</option>
                <option value="translate">{tr("Translate","Translate")}</option>
                <option value="transliterate">{tr("Transliterate","අකුරු මාරු කරන්න")}</option>
              </select>
            </td>
          </tr>
        ))}
      </tbody></table>
    </>
  );
}

export function CostLine({ doc }: { doc: Doc }) {
  return (
    <p className="small">
      {doc.model}{doc.mode === "batch" ? " (batch)" : ""}: calls {doc.llm_calls}, input {doc.prompt_tokens.toLocaleString()}
      {doc.cached_tokens ? ` (cache ${doc.cached_tokens.toLocaleString()})` : ""}, output {doc.output_tokens.toLocaleString()}
      {doc.thought_tokens ? ` (thinking ${doc.thought_tokens.toLocaleString()})` : ""}
      {doc.cost_usd ? `. Paid tier එකේ නම් ≈ $${doc.cost_usd.toFixed(3)}` : ""}
    </p>
  );
}
