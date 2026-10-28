import { useCallback, useEffect, useRef, useState } from "react";
import { api, upload } from "./api";
import { go, openSettings } from "./App";
import { IconMore, IconPlus } from "./icons";
import { CostLine } from "./Panels";
import Sheet, { Toast } from "./Sheet";
import { isActive, jobLine, pct } from "./status";
import type { Doc, Progress } from "./types";
import { catalog, useSettings, useText } from "./prefs";
import { ProgressCard } from "./Progress";

export default function Library() {
  const prefs=useSettings(),t=useText();
  const [progress,setProgress]=useState<Progress|null>(null);
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
    api.progress().then(setProgress).catch(()=>{});
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
        <h1>{t("My library","මගේ පොත්")}</h1>
        <button className="act" onClick={() => go("/words")}>
          {t("My words","මගේ වචන")}{due ? <span className="badge">{due}</span> : null}
        </button>
        <button className="act" onClick={openSettings}>{t("Settings","Settings")}</button>
        <button className="act" onClick={()=>go("/progress")}>{t("Progress","ප්‍රගතිය")}</button>
      </header>
      <p className="small" style={{ margin: "-14px 4px 16px" }}>{catalog.languages[prefs.target_language]||prefs.target_language} · {prefs.translation_style} · {model}</p>
      {progress&&<ProgressCard value={progress}/>}

      <button className="leaf add" aria-label={t("Add a PDF","PDF එකක් දාන්න")} onClick={() => fileRef.current?.click()} disabled={up !== null}>
        <span className="plus"><IconPlus width={18} height={18} /></span>
        <span>{up === null ? t("Add a PDF","PDF එකක් දාන්න") : `${t("Uploading","Upload කරනවා")} ${Math.round(up * 100)}%`}</span>
      </button>
      <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => setPicked(e.target.files?.[0] ?? null)} />
      {up !== null && <div className="uploading"><div style={{ width: `${up * 100}%` }} /></div>}

      {docs && docs.length === 0 && (
        <p className="empty">
          {t("Add a book, textbook or research paper as a PDF. You can start reading while it translates.","තාම පොත් නෑ. පොතක් හරි research paper එකක් හරි PDF එකක් දාන්න. Translate වෙන ගමන්ම කියවන්න පුළුවන්.")}
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
                <span>{d.page_count} {t("pages","පිටු")}</span>
                {read > 0 && <span>{read}% {t("read","කියවලා")}</span>}
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
          <p className="generation-summary">{prefs.auto_translate?t("Whole-book translation","මුළු පොතේ translation එක"):t("Original text only · translation paused","Original එක පමණයි · translation pause වෙනවා")} → {catalog.languages[prefs.target_language]||prefs.target_language} · {prefs.translation_style}</p>
          <button className="mode-opt" onClick={() => onFile(picked, "standard")}>
            <b>{prefs.auto_translate?t("Upload & translate","Upload & translate කරන්න"):t("Upload original","Original එක upload කරන්න")}</b>
            <span>{t("Uses the current app settings. AI translation may incur provider charges; you can pause the job.","දැනට app settings අනුව හදනවා. AI translation එකට වියදමක් යන්න පුළුවන්; අතරමඟ pause කරන්න පුළුවන්.")}</span>
          </button>
          {prefs.auto_translate&&<button className="mode-opt" onClick={() => onFile(picked, "batch")}>
            <b>{t("Upload & translate · batch mode","Upload & translate · batch mode")}</b>
            <span>{t("Discounted batch processing can take hours. If unavailable, this job may fall back to standard pricing.","Batch processing එකට පැය කිහිපයක් යන්න පුළුවන්. Batch නැත්නම් standard pricing වලට මාරු වෙන්න පුළුවන්.")}</span>
          </button>}
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
  const t=useText();
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
        <button className="act" onClick={() => run(api.rename(doc.id, title))}>{t("Save title","නම save කරන්න")}</button>
      </div>
      <div className="actions" style={{ marginTop: 14 }}>
        {isActive(doc) && <button className="act" onClick={() => run(api.pause(doc.id))}>{t("Pause translation","Translate එක pause කරන්න")}</button>}
        {(doc.status === "paused" || doc.status === "error") && (
          <button className="act primary" onClick={() => run(api.resume(doc.id))}>{t("Resume translation","නැවත පටන් ගන්න")}</button>
        )}
        {doc.failed > 0 && !isActive(doc) && (
          <button className="act" onClick={() => run(api.retryFailed(doc.id))}>{t("Retry failed passages · AI","Fail වුණ blocks ආයෙ translate කරන්න · AI")}</button>
        )}
        {!isActive(doc) && (redo
          ? <button className="act primary" onClick={() => run(api.retranslateAll(doc.id))}>{t("Confirm new version · AI","අලුත් version එක හදන්න · AI")}</button>
          : <button className="act" onClick={() => setRedo(true)}>{t("Translate a new version","අලුත් translation version එකක්")}</button>)}
        <button className="act" onClick={() => run(api.setMode(doc.id, doc.mode === "batch" ? "standard" : "batch"))}>
          {doc.mode === "batch" ? t("Use standard mode","Batch mode Off කරන්න") : t("Use batch mode","Batch mode On කරන්න")}
        </button>
        {!confirm ? (
          <button className="act" onClick={() => setConfirm(true)}>{t("Delete book","Delete කරන්න")}</button>
        ) : (
          <button className="act primary" onClick={() => run(api.remove(doc.id))}>{t("Confirm deletion with notes","ඔව්, notes එක්කම delete කරන්න")}</button>
        )}
      </div>
      {redo && <p className="small">{t("Uses current app language/style settings. Saved translation versions, notes and highlights are preserved.","දැනට app language/style settings අනුව හදනවා. පරණ versions, notes සහ highlights තියෙනවා.")}</p>}
      {Object.entries(doc.batch || {}).map(([k, b]) => (
        <p key={k} className="small">Batch {k}: {b.state}{b.last_state ? ` (${b.last_state})` : ""}{b.note ? `: ${b.note}` : ""}</p>
      ))}
      <CostLine doc={doc} />
    </Sheet>
  );
}
