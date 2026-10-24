import { useCallback, useEffect, useRef, useState } from "react";
import { api, upload } from "./api";
import { go } from "./App";
import { IconMore, IconPlus } from "./icons";
import { CostLine } from "./Panels";
import Sheet, { Toast } from "./Sheet";
import { isActive, jobLine, pct } from "./status";
import type { Doc } from "./types";

export default function Library() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [model, setModel] = useState("");
  const [up, setUp] = useState<number | null>(null);
  const [menu, setMenu] = useState<Doc | null>(null);
  const [toast, setToast] = useState("");
  const [picked, setPicked] = useState<File | null>(null);
  const [due, setDue] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.docs().then(setDocs).catch((e) => setToast(e.message)), []);

  useEffect(() => {
    load();
    api.health().then((h) => setModel(h.model)).catch(() => {});
    api.words().then((r) => setDue(r.stats.total ? r.stats.due : null)).catch(() => {});
  }, [load]);

  useEffect(() => {
    if (!docs?.some(isActive)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [docs, load]);

  const onFile = async (f: File | undefined, mode: "standard" | "batch") => {
    if (!f) return;
    setPicked(null);
    setUp(0);
    try {
      await upload(f, setUp, mode);
      await load();
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setUp(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <main className="library">
      <header className="lib-head">
        <h1>මගේ පොත්</h1>
        <button className="act" onClick={() => go("/words")}>
          මගේ වචන{due ? <span className="badge">{due}</span> : null}
        </button>
      </header>
      {model && <p className="small" style={{ margin: "-14px 4px 16px" }}>Translate කරන්නේ {model}</p>}

      <button className="leaf add" onClick={() => fileRef.current?.click()} disabled={up !== null}>
        <span className="plus"><IconPlus width={18} height={18} /></span>
        {up === null ? "PDF එකක් දාන්න" : `Upload කරනවා ${Math.round(up * 100)}%`}
      </button>
      <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => setPicked(e.target.files?.[0] ?? null)} />
      {up !== null && <div className="uploading"><div style={{ width: `${up * 100}%` }} /></div>}

      {docs && docs.length === 0 && (
        <p className="empty">
          තාම පොත් නෑ. පොතක් හරි research paper එකක් හරි PDF එකක් විදියට දාන්න.
          Translate වෙන ගමන්ම කියවන්න පටන් ගන්න පුළුවන්.
        </p>
      )}

      {docs?.map((d) => {
        const read = d.position != null && d.blocks ? pct(d.position + 1, d.blocks) : 0;
        return (
          <div key={d.id} style={{ position: "relative" }}>
            <button className="leaf" onClick={() => go(`/read/${d.id}`)}>
              <p className="leaf-title">{d.title}</p>
              {d.title_si && d.title_si !== d.title && <p className="leaf-title-si">{d.title_si}</p>}
              <div className="leaf-meta">
                <span className={d.status === "error" ? "err" : ""}>{jobLine(d)}</span>
                <span>පිටු {d.page_count}</span>
                {read > 0 && <span>කියෙව්වේ {read}%</span>}
              </div>
              {read > 0 && <div className="leaf-progress" style={{ width: `calc((100% - 64px) * ${read / 100})` }} />}
            </button>
            <button className="icon-btn leaf-more" aria-label="More" onClick={() => setMenu(d)}><IconMore /></button>
          </div>
        );
      })}

      {picked && (
        <Sheet onClose={() => { setPicked(null); if (fileRef.current) fileRef.current.value = ""; }} label="Translation mode">
          <h3>{picked.name}</h3>
          <button className="mode-opt" onClick={() => onFile(picked, "standard")}>
            <b>සාමාන්‍ය විදියට</b>
            <span>Translate වෙන ගමන්ම කියවන්න පුළුවන්. විනාඩි කිහිපයයි.</span>
          </button>
          <button className="mode-opt" onClick={() => onFile(picked, "batch")}>
            <b>Batch mode: 50% ලාභයි</b>
            <span>Google එකේ Batch API එක. පැය කිහිපයක් (උපරිම පැය 24) යන්න පුළුවන්. Free tier එකේ වැඩ කරන්නේ නෑ, එහෙම වුණොත් ඉබේම සාමාන්‍ය විදියට යනවා.</span>
          </button>
        </Sheet>
      )}

      {menu && <DocMenu doc={menu} onClose={() => setMenu(null)} onChanged={() => { setMenu(null); load(); }} onError={setToast} />}
      {toast && <Toast msg={toast} onDone={() => setToast("")} />}
    </main>
  );
}

function DocMenu({ doc, onClose, onChanged, onError }: {
  doc: Doc; onClose: () => void; onChanged: () => void; onError: (m: string) => void;
}) {
  const [title, setTitle] = useState(doc.title);
  const [confirm, setConfirm] = useState(false);
  const [redo, setRedo] = useState(false);
  const run = (p: Promise<unknown>) => p.then(onChanged).catch((e) => onError(e.message));
  return (
    <Sheet onClose={onClose} label="Document options">
      <h3>{doc.title}</h3>
      {doc.error && <p className="small">{doc.error}</p>}
      <div className="row">
        <input className="field" style={{ minHeight: 0 }} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
        <button className="act" onClick={() => run(api.rename(doc.id, title))}>නම save කරන්න</button>
      </div>
      <div className="actions" style={{ marginTop: 14 }}>
        {isActive(doc) && <button className="act" onClick={() => run(api.pause(doc.id))}>Translate එක pause කරන්න</button>}
        {(doc.status === "paused" || doc.status === "error") && (
          <button className="act primary" onClick={() => run(api.resume(doc.id))}>නැවත පටන් ගන්න</button>
        )}
        {doc.failed > 0 && !isActive(doc) && (
          <button className="act" onClick={() => run(api.retryFailed(doc.id))}>Fail වුණ blocks ආයෙ translate කරන්න</button>
        )}
        {!isActive(doc) && (redo
          ? <button className="act primary" onClick={() => run(api.retranslateAll(doc.id))}>ඔව්, glossary එකත් අලුතින් හදලා ආයෙ translate කරන්න</button>
          : <button className="act" onClick={() => setRedo(true)}>මුළු පොතම ආයෙ translate කරන්න</button>)}
        <button className="act" onClick={() => run(api.setMode(doc.id, doc.mode === "batch" ? "standard" : "batch"))}>
          {doc.mode === "batch" ? "Batch mode off කරන්න" : "Batch mode on කරන්න (50% ලාභයි)"}
        </button>
        {!confirm ? (
          <button className="act" onClick={() => setConfirm(true)}>Delete කරන්න</button>
        ) : (
          <button className="act primary" onClick={() => run(api.remove(doc.id))}>ඔව්, notes එක්කම delete කරන්න</button>
        )}
      </div>
      {redo && <p className="small">ඔයා Glossary එකේ අතින් වෙනස් කරපු terms තියාගන්නවා. Notes සහ highlights නැති වෙන්නේ නෑ.</p>}
      {Object.entries(doc.batch || {}).map(([k, b]) => (
        <p key={k} className="small">Batch {k}: {b.state}{b.last_state ? ` (${b.last_state})` : ""}{b.note ? `: ${b.note}` : ""}</p>
      ))}
      <CostLine doc={doc} />
    </Sheet>
  );
}
