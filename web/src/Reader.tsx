import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "./api";
import { go, openSettings } from "./App";
import BlockSheet from "./BlockSheet";
import BlockView from "./BlockView";
import { IconBack, IconClose, IconNext, IconNote, IconPause, IconPlay, IconPrev, IconSpeaker, IconToc, IconType } from "./icons";
import { NotesSheet, TocSheet } from "./Panels";
import { catalog, setPrefs, usePrefs, useSettings, useText } from "./prefs";
import Sheet, { Toast } from "./Sheet";
import { isActive, jobFraction, jobLine } from "./status";
import type { Block, Doc, Note, WordCardData } from "./types";
import { TranslationVersions } from "./Versions";
import { isSpeakable, useAudio } from "./useAudio";
import WordCard from "./WordCard";
import { wordAt } from "./wordAt";

const POS_KEY = (id: string) => `ebook.pos.${id}`;

function mergeBlocks(prev: Block[], incoming: Block[]): Block[] {
  if (!prev.length) return incoming;
  const out = prev.slice();
  for (const b of incoming) out[b.seq] = b;
  return out.filter(Boolean);
}

export default function Reader({ docId }: { docId: string }) {
  const prefs = usePrefs();
  const t=useText();
  const appSettings=useSettings();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const [panel, setPanel] = useState<"" | "toc" | "notes" | "versions">("");
  const [zoom, setZoom] = useState<string | null>(null);
  const [lookup, setLookup] = useState<{ word: string; seq: number; card: WordCardData | null } | null>(null);
  const [wordPrompt,setWordPrompt]=useState<{word:string;seq:number}|null>(null);
  const [listenPrompt,setListenPrompt]=useState<number|null>(null);
  const [listenScope,setListenScope]=useState<"paragraph"|"chapter">("paragraph");
  const [listenSide,setListenSide]=useState<"original"|"translated">("translated");
  const lookupToken=useRef(0), topRef=useRef(0);
  const [toast, setToast] = useState("");
  const [hidden, setHidden] = useState(false);
  const [top, setTop] = useState(0);
  const rev = useRef(0);
  const restored = useRef(false);
  const lastY = useRef(0);
  const saveT = useRef<number | undefined>(undefined);

  const onToast = useCallback((m: string) => setToast(m), []);
  const audio = useAudio(docId, blocks, prefs.voice || "Kore", prefs.rate, doc?.title ?? "", onToast,doc?.translation_profile);

  // ---------------------------------------------------------------- data
  useEffect(() => {
    Promise.all([api.doc(docId), api.blocks(docId, 0), api.notes(docId)])
      .then(([d, b, n]) => {
        setDoc(d);
        setBlocks(b.blocks);
        rev.current = b.rev;
        setNotes(n);
      })
      .catch((e) => setErr(e.message));
  }, [docId]);

  useEffect(() => {
    if (!doc || !isActive(doc)) return;
    const t = setInterval(async () => {
      try {
        const [d, b] = await Promise.all([api.doc(docId), api.blocks(docId, rev.current)]);
        setDoc(d);
        if (b.blocks.length) setBlocks((prev) => mergeBlocks(prev, b.blocks));
        rev.current = Math.max(rev.current, b.rev);
      } catch { /* server restarting; try again next tick */ }
    }, 3000);
    return () => clearInterval(t);
  }, [doc?.status, docId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- position
  const scrollTo = useCallback((seq: number, smooth = false) => {
    const el = document.querySelector(`[data-seq="${seq}"]`);
    el?.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
  }, []);

  useEffect(() => {
    if (restored.current || !doc || !blocks.length) return;
    restored.current = true;
    const requested=new URLSearchParams(location.hash.split("?")[1]).get("seq");
    let seq = requested!==null ? Number(requested) : doc.position ?? 0;
    try {
      const local = localStorage.getItem(POS_KEY(docId));
      if (requested===null && doc.position == null && local) seq = +local;
    } catch { /* ignore */ }
    if (seq > 0) requestAnimationFrame(() => scrollTo(Math.min(seq, blocks.length - 1)));
  }, [doc, blocks.length, docId, scrollTo]);

  useEffect(() => {
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const y = window.scrollY;
        if (y > lastY.current + 10 && y > 120) setHidden(true);
        else if (y < lastY.current - 10) setHidden(false);
        lastY.current = y;
        let seq: number | null = null;
        for (const probe of [80, 110, 150, 200]) {
          const rect=document.querySelector(".reader")?.getBoundingClientRect();
          const el = document.elementFromPoint(rect ? rect.left+rect.width/2 : window.innerWidth/2, probe)?.closest("[data-seq]");
          if (el) { seq = +(el as HTMLElement).dataset.seq!; break; }
        }
        if (seq == null || !restored.current) return;
        setTop(seq);
        topRef.current=seq;
        window.clearTimeout(saveT.current);
        const s = seq;
        saveT.current = window.setTimeout(() => {
          try { localStorage.setItem(POS_KEY(docId), String(s)); } catch { /* ignore */ }
          api.setPosition(docId, s).catch(() => {});
        }, 1200);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [docId]);

  useEffect(()=>{
    let active=0,last=Date.now();
    const activity=()=>{last=Date.now();};
    window.addEventListener("pointerdown",activity,{passive:true});window.addEventListener("keydown",activity);window.addEventListener("scroll",activity,{passive:true});
    const timer=setInterval(()=>{if(document.visibilityState!=="visible"||!document.hasFocus()||Date.now()-last>60000)return;active+=5;if(active>=60){active=0;void api.reading(docId,topRef.current).catch(()=>{});}},5000);
    return()=>{clearInterval(timer);window.removeEventListener("pointerdown",activity);window.removeEventListener("keydown",activity);window.removeEventListener("scroll",activity);};
  },[docId]);

  // follow the voice
  useEffect(() => {
    if (audio.seq == null) return;
    const el = document.querySelector(`[data-seq="${audio.seq}"]`);
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 60 || r.top > window.innerHeight * 0.6) el.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [audio.seq]);

  // ---------------------------------------------------------------- derived
  const noteInfo = useMemo(() => {
    const m = new Map<number, { color: string | null; body: boolean }>();
    for (const n of notes) {
      const cur = m.get(n.seq) ?? { color: null, body: false };
      if (n.color && !n.body) cur.color = n.color;
      if (n.body) cur.body = true;
      m.set(n.seq, cur);
    }
    return m;
  }, [notes]);

  const heading = useMemo(() => {
    for (let i = Math.min(top, blocks.length - 1); i >= 0; i--) {
      const b = blocks[i];
      if (b.type === "heading" && b.level <= 2) return prefs.displayMode==="original"?b.source:b.translated || b.source;
    }
    return doc?.title ?? "";
  }, [top, blocks, doc?.title,prefs.displayMode]);

  const onTap = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.dataset.zoom) { setZoom((t as HTMLImageElement).src); return; }
    if (window.getSelection()?.toString()) return;
    const el = t.closest("[data-seq]") as HTMLElement | null;
    if (!el) return;
    const seq = +el.dataset.seq!;
    const b = blocks[seq];
    if (prefs.wordTap && b && b.type !== "reference") {
      const w = wordAt(e.clientX, e.clientY);
      if (w) { setWordPrompt({ word: w, seq }); return; }
    }
    setSel(seq);
  };

  const listenHere = () => {
    let s = top;
    while (s < blocks.length && !isSpeakable(blocks[s])) s++;
    if (s < blocks.length) requestListen(s);
  };
  const requestListen=(s:number)=>{
    if(prefs.audioMode==="off"){setToast(t("Voice is Off. Enable it in App settings.","Voice Off. App settings වලින් enable කරන්න."));return;}
    const side=prefs.displayMode==="original"?"original":"translated";
    if(prefs.audioMode==="device"){void audio.playAt(s,"paragraph",side);return;}
    setListenSide(side);setListenScope("paragraph");setListenPrompt(s);
  };
  const translateWord=async()=>{
    if(!wordPrompt)return;const choice=wordPrompt,my=++lookupToken.current;
    setWordPrompt(null);setLookup({...choice,card:null});
    try{const card=await api.lookup(choice.word,docId,choice.seq);if(my===lookupToken.current)setLookup({...choice,card});}
    catch(e){if(my===lookupToken.current){setLookup(null);setToast((e as Error).message);}}
  };

  if (err) return <p className="center-msg">{err}<br /><button className="act" onClick={() => go("/")}>{t("Library","Library එකට")}</button></p>;
  if (!doc) return <p className="center-msg">{t("Loading…","Load වෙනවා...")}</p>;

  const style = { "--fs": `${prefs.fontSize}px`, "--lh": prefs.lineHeight } as CSSProperties;
  const selBlock = sel != null ? blocks[sel] : null;

  return (
    <div style={style}>
      <header className={"topbar" + (hidden && !panel && sel == null ? " hidden" : "")}>
        <button className="icon-btn" aria-label="Back to library" onClick={() => go("/")}><IconBack /></button>
        <div className="where">{heading}</div>
        <button className="icon-btn" aria-label="Listen from here" onClick={listenHere} aria-disabled={prefs.audioMode==="off"}><IconSpeaker /></button>
        <button className="icon-btn" aria-label="Contents" onClick={() => setPanel("toc")}><IconToc /></button>
        <button className="icon-btn" aria-label="Notes" onClick={() => setPanel("notes")}><IconNote /></button>
        <button className="icon-btn" aria-label="App settings" onClick={openSettings}><IconType /></button>
      </header>

      <main className="reader" onClick={onTap}>
        <div className="reader-tools" onClick={(e)=>e.stopPropagation()}><div className="seg" aria-label="Reading view">{(["translated","original","both"] as const).map((m)=><button key={m} className={prefs.displayMode===m?"on":""} onClick={()=>setPrefs({displayMode:m})}>{m==="translated"?t("Translation","Translation"):m==="original"?t("Original","Original"):t("Both","දෙකම")}</button>)}</div><div className="actions"><button className="act" onClick={()=>setPanel("versions")}>{t("Versions","Versions")}</button><button className="act" onClick={()=>go(`/study/${docId}`)}>{t("Study / exam","Study / exam")}</button></div></div>
        {prefs.displayMode!=="original"&&doc.translation_profile&&(doc.translation_profile.target_language!==appSettings.target_language||doc.translation_profile.translation_style!==appSettings.translation_style||doc.translation_profile.purpose!==appSettings.purpose)&&<div className="version-create" onClick={(e)=>e.stopPropagation()}><p className="small">{t("Showing a saved translation version:","පෙන්වන්නේ save කරපු translation එකක්:")} {catalog.languages[doc.translation_profile.target_language]||doc.translation_profile.target_language} · {doc.translation_profile.translation_style}. {t("Create a new version to apply current app settings.","දැනට app settings යොදන්න අලුත් version එකක් හදන්න.")}</p><button className="act" onClick={()=>setPanel("versions")}>{t("Translation versions","Translation versions")}</button></div>}
        {!blocks.slice(0, 8).some((b) => b.type === "heading" && b.source.trim() === doc.title.trim()) &&
          <h1 className="doc-title">{doc.title}</h1>}
        <p className="doc-sub">{doc.translated_title && doc.translated_title !== doc.title ? doc.translated_title : `${doc.page_count} ${t("pages","පිටු")}`}</p>

        {doc.status !== "done" && (
          <div className={"job-strip" + (doc.status === "error" ? " error" : "")} onClick={(e) => e.stopPropagation()}>
            {doc.status === "error" ? (
              <>
                <div>{jobLine(doc)}: {doc.error}</div>
                <button onClick={() => api.resume(docId).then(setDoc).catch((e) => onToast(e.message))}>{t("Retry translation","නැවත උත්සාහ කරන්න")}</button>
              </>
            ) : (
              <>
                <span>{jobLine(doc)}</span>
                <div className="bar"><div style={{ width: `${jobFraction(doc) * 100}%` }} /></div>
                {isActive(doc)
                  ? <button onClick={() => api.pause(docId).then(setDoc)}>Pause</button>
                  : <button onClick={() => api.resume(docId).then(setDoc)}>Resume</button>}
              </>
            )}
          </div>
        )}

        {blocks.length === 0 && doc.stage === "parse" && <p className="empty">{t("Reading the PDF. Passages will appear as they become available.","PDF එක කියවනවා. පිටු ටික ලෑස්ති වුණාම මෙතන පෙන්නයි.")}</p>}

        {blocks.map((b) => {
          const ni = noteInfo.get(b.seq);
          return (
            <Fragment key={b.seq}><BlockView b={b} docId={docId} hl={ni?.color ?? null} hasNote={!!ni?.body}
              selected={sel === b.seq} playing={audio.seq === b.seq} bilingual={prefs.bilingual} displayMode={prefs.displayMode} />
              {doc.sections?.filter((s)=>s.end_seq===b.seq).map((section)=><aside className="chapter-finish" key={section.idx} onClick={(e)=>e.stopPropagation()}><p className="small">{section.title} · {t("Chapter checkpoint","Chapter එකේ අවසානය")}</p><button className="act" onClick={()=>go(`/study/${docId}?boss=1&section=${section.idx}`)}>{t("Boss quiz · set up a hard paper","Boss quiz · hard paper එකක් සකස් කරන්න")} →</button></aside>)}
            </Fragment>
          );
        })}
      </main>

      {audio.state !== "idle" && (
        <div className="audiobar" role="region" aria-label="Audio player">
          <button className="icon-btn" aria-label="Previous paragraph" onClick={() => audio.skip(-1)}><IconPrev /></button>
          <button className="icon-btn play" aria-label={audio.state === "playing" ? "Pause" : "Play"} onClick={audio.toggle}>
            {audio.state === "loading" ? <span className="spinner" /> : audio.state === "playing" ? <IconPause /> : <IconPlay />}
          </button>
          <button className="icon-btn" aria-label="Next paragraph" onClick={() => audio.skip(1)}><IconNext /></button>
          <div className="info">
            {audio.state === "loading" ? t("Preparing audio…","Voice එක හදනවා...") : audio.side==="original" ? blocks[audio.seq!]?.source : (blocks[audio.seq!]?.translated || blocks[audio.seq!]?.source || "")}
          </div>
          <button className="rate" onClick={() => {
            const rates = [0.9, 1, 1.15, 1.3];
            setPrefs({ rate: rates[(rates.indexOf(prefs.rate) + 1) % rates.length] });
          }}>{prefs.rate}×</button>
          <button className="icon-btn" aria-label="Stop" onClick={audio.stop}><IconClose /></button>
        </div>
      )}

      <div className="progress-line"><div style={{ width: `${blocks.length ? ((top + 1) / blocks.length) * 100 : 0}%` }} /></div>

      {selBlock && !lookup && !wordPrompt && listenPrompt===null && !panel && (
        <BlockSheet doc={doc} block={selBlock} notes={notes} onClose={() => setSel(null)}
          onListen={requestListen}
          onNotes={setNotes}
          onBlock={(b) => setBlocks((prev) => mergeBlocks(prev, [b]))}
          onToast={onToast} onZoom={setZoom} onWord={(w) => setWordPrompt({ word: w, seq: selBlock.seq })} />
      )}
      {wordPrompt&&<Sheet label="Translate this word?" onClose={()=>setWordPrompt(null)}><p className="eyebrow">{t("WORD ACTION","වචනය ගැන")}</p><h3 dir="auto">{wordPrompt.word}</h3><p>{t("Translate this word in context? This may use your AI provider.","මේ වචනය මේ වාක්‍යය අනුව translate කරන්නද? AI provider එක භාවිතා වෙන්න පුළුවන්.")}</p><div className="actions"><button className="act primary" onClick={()=>void translateWord()}>{t("Translate","Translate කරන්න")}</button><button className="act" onClick={()=>{setSel(wordPrompt.seq);setWordPrompt(null);}}>{t("Open paragraph","Paragraph බලන්න")}</button><button className="act" onClick={()=>setWordPrompt(null)}>{t("Cancel","එපා")}</button></div></Sheet>}
      {lookup && <WordCard key={`${lookup.seq}-${lookup.word}`} word={lookup.word} initial={lookup.card} docId={docId} seq={lookup.seq}
        onClose={() => {lookupToken.current++;setLookup(null);}} onToast={onToast} />}
      {listenPrompt!==null&&<Sheet label="Confirm cloud audio" onClose={()=>setListenPrompt(null)}><h3>{t("Cloud listening","Cloud voice")}</h3><p>{t("New audio can incur provider charges. Cached audio is reused.","අලුත් audio හදද්දී වියදමක් යන්න පුළුවන්. තිබෙන audio නැවත භාවිතා කරනවා.")}</p><label className="setting-field"><span>{t("Listening scope","අහන කොටස")}</span><select value={listenScope} onChange={(e)=>setListenScope(e.target.value as "paragraph"|"chapter")}><option value="paragraph">{t("This paragraph only","මේ paragraph එක පමණයි")}</option><option value="chapter">{t("Until the end of this chapter","මේ chapter එක අවසන් වන තුරු")}</option></select></label><label className="setting-field"><span>{t("Text to read","කියවන text එක")}</span><select value={listenSide} onChange={(e)=>setListenSide(e.target.value as "original"|"translated")}><option value="original">Original</option><option value="translated">Translation</option></select></label><div className="actions"><button className="act primary" onClick={()=>{const s=listenPrompt;setListenPrompt(null);void audio.playAt(s,listenScope,listenSide);}}>{t("Confirm & listen","තහවුරු කර අහන්න")}</button><button className="act" onClick={()=>setListenPrompt(null)}>{t("Cancel","එපා")}</button></div></Sheet>}
      {panel === "toc" && <TocSheet blocks={blocks} current={top} onClose={() => setPanel("")}
        onJump={(s) => { setPanel(""); scrollTo(s); }} />}
      {panel === "notes" && <NotesSheet notes={notes} blocks={blocks} onClose={() => setPanel("")}
        onJump={(s) => { setPanel(""); scrollTo(s); setSel(null); }} />}
      {panel === "versions" && <TranslationVersions doc={doc} onClose={()=>setPanel("")} onChanged={()=>{audio.stop();location.reload();}} onToast={onToast} />}

      {zoom && (
        <div className="lightbox" onClick={() => setZoom(null)}>
          <button className="icon-btn" aria-label="Close"><IconClose /></button>
          <img src={zoom} alt="Figure, enlarged" />
        </div>
      )}
      {toast && <Toast msg={toast} onDone={() => setToast("")} />}
    </div>
  );
}
