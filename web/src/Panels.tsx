import { useEffect, useState } from "react";
import { api } from "./api";
import { setPrefs, usePrefs, type Theme } from "./prefs";
import Sheet from "./Sheet";
import { isActive, jobLine } from "./status";
import type { Block, Doc, GlossaryTerm, Note } from "./types";

export function TocSheet({ blocks, current, onJump, onClose }: {
  blocks: Block[]; current: number; onJump: (seq: number) => void; onClose: () => void;
}) {
  const heads = blocks.filter((b) => b.type === "heading" && b.level <= 3);
  const cur = [...heads].reverse().find((h) => h.seq <= current)?.seq;
  return (
    <Sheet onClose={onClose} label="Contents">
      <h3>පටුන</h3>
      {heads.length === 0 && <p className="small">මේ document එකේ headings හොයාගන්න බැරි වුණා.</p>}
      {heads.map((h) => (
        <button key={h.seq} className={"list-btn" + (h.seq === cur ? " cur" : "")}
          style={{ paddingLeft: 6 + (h.level - 1) * 16 }} onClick={() => onJump(h.seq)}>
          <span className="pg">{h.page + 1}</span>
          {h.translated || h.source}
        </button>
      ))}
    </Sheet>
  );
}

export function NotesSheet({ notes, blocks, onJump, onClose }: {
  notes: Note[]; blocks: Block[]; onJump: (seq: number) => void; onClose: () => void;
}) {
  const sorted = [...notes].sort((a, b) => a.seq - b.seq || a.id - b.id);
  return (
    <Sheet onClose={onClose} label="Notes and highlights">
      <h3>Notes <small>{notes.length}</small></h3>
      {sorted.length === 0 && (
        <p className="small">තාම notes නෑ. Paragraph එකක් tap කරලා note එකක් හරි highlight එකක් හරි දාන්න.</p>
      )}
      {sorted.map((n) => {
        const b = blocks[n.seq];
        const excerpt = (b?.translated || b?.source || "").slice(0, 110);
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

const THEMES: [Theme, string][] = [["paper", "සුදු"], ["leaf", "පුස්කොළ"], ["night", "රෑ"]];
const RATES = [0.9, 1, 1.15, 1.3];

export function SettingsSheet({ doc, onClose, onDoc, onToast }: {
  doc: Doc; onClose: () => void; onDoc: (d: Doc) => void; onToast: (m: string) => void;
}) {
  const p = usePrefs();
  const [voices, setVoices] = useState<string[]>([]);
  const [showGloss, setShowGloss] = useState(false);
  useEffect(() => {
    api.voices().then((v) => {
      setVoices(v.voices);
      if (!p.voice) setPrefs({ voice: v.default });
    }).catch(() => {});
  }, [p.voice]);

  const act = (f: Promise<Doc>) => f.then(onDoc).catch((e) => onToast(e.message));

  return (
    <Sheet onClose={onClose} label="Reading settings">
      <h3>කියවන විදිය</h3>
      <div className="row">
        <label>Theme</label>
        <div className="seg">
          {THEMES.map(([t, n]) => <button key={t} className={p.theme === t ? "on" : ""} onClick={() => setPrefs({ theme: t })}>{n}</button>)}
        </div>
      </div>
      <div className="row">
        <label htmlFor="fs">අකුරු ප්‍රමාණය</label>
        <input id="fs" type="range" min={15} max={28} step={1} value={p.fontSize} onChange={(e) => setPrefs({ fontSize: +e.target.value })} />
      </div>
      <div className="row">
        <label htmlFor="lh">පේළි අතර ඉඩ</label>
        <input id="lh" type="range" min={1.4} max={2.2} step={0.05} value={p.lineHeight} onChange={(e) => setPrefs({ lineHeight: +e.target.value })} />
      </div>
      <div className="row">
        <label>English original එකත් පෙන්නන්න</label>
        <button className={"toggle" + (p.bilingual ? " on" : "")} role="switch" aria-checked={p.bilingual}
          aria-label="Show English original" onClick={() => setPrefs({ bilingual: !p.bilingual })} />
      </div>
      <div className="row">
        <label>English වචනයක් tap කළාම තේරුම පෙන්නන්න</label>
        <button className={"toggle" + (p.wordTap ? " on" : "")} role="switch" aria-checked={p.wordTap}
          aria-label="Tap an English word to see its meaning" onClick={() => setPrefs({ wordTap: !p.wordTap })} />
      </div>
      <div className="row">
        <label htmlFor="voice">Voice එක</label>
        <select id="voice" value={p.voice} onChange={(e) => setPrefs({ voice: e.target.value })}>
          {voices.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>
      <div className="row">
        <label>කියවන වේගය</label>
        <div className="seg">
          {RATES.map((r) => <button key={r} className={p.rate === r ? "on" : ""} onClick={() => setPrefs({ rate: r })}>{r}×</button>)}
        </div>
      </div>

      <h3 style={{ marginTop: 22 }}>මේ පොත</h3>
      <p className="small">{jobLine(doc)}{doc.error ? `: ${doc.error}` : ""}</p>
      {doc.brief?.summary && <p style={{ fontFamily: "var(--f-read)", lineHeight: 1.6, margin: "6px 0 10px" }}>{doc.brief.summary}</p>}
      <CostLine doc={doc} />
      <div className="actions">
        {isActive(doc) && <button className="act" onClick={() => act(api.pause(doc.id))}>Translate එක pause කරන්න</button>}
        {(doc.status === "paused" || doc.status === "error") && <button className="act primary" onClick={() => act(api.resume(doc.id))}>නැවත පටන් ගන්න</button>}
        {doc.failed > 0 && !isActive(doc) && <button className="act" onClick={() => act(api.retryFailed(doc.id))}>Fail වුණ {doc.failed} ආයෙ translate කරන්න</button>}
        <button className="act" onClick={() => setShowGloss(!showGloss)}>Glossary</button>
      </div>
      {showGloss && <Glossary docId={doc.id} onToast={onToast} />}
    </Sheet>
  );
}

function Glossary({ docId, onToast }: { docId: string; onToast: (m: string) => void }) {
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
      <p className="small">මෙතන වෙනස් කරන දේ ඊළඟට translate වෙන කොටස් වලට අදාළ වෙනවා. දැනටමත් translate වුණ paragraph එකක් වෙනස් කරන්න ඒක tap කරලා "ආයෙ translate" දෙන්න.</p>
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
                <option value="keep_en">English</option>
                <option value="translate">සිංහල</option>
                <option value="transliterate">සිංහල අකුරෙන්</option>
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
