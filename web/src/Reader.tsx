import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "./api";
import { go } from "./App";
import BlockSheet from "./BlockSheet";
import BlockView from "./BlockView";
import { IconBack, IconClose, IconNext, IconNote, IconPause, IconPlay, IconPrev, IconSpeaker, IconToc, IconType } from "./icons";
import { NotesSheet, SettingsSheet, TocSheet } from "./Panels";
import { setPrefs, usePrefs } from "./prefs";
import { Toast } from "./Sheet";
import { isActive, jobFraction, jobLine } from "./status";
import type { Block, Doc, Note } from "./types";
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
  const [doc, setDoc] = useState<Doc | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const [panel, setPanel] = useState<"" | "toc" | "notes" | "settings">("");
  const [zoom, setZoom] = useState<string | null>(null);
  const [lookup, setLookup] = useState<{ word: string; seq: number } | null>(null);
  const [toast, setToast] = useState("");
  const [hidden, setHidden] = useState(false);
  const [top, setTop] = useState(0);
  const rev = useRef(0);
  const restored = useRef(false);
  const lastY = useRef(0);
  const saveT = useRef<number | undefined>(undefined);

  const onToast = useCallback((m: string) => setToast(m), []);
  const audio = useAudio(docId, blocks, prefs.voice || "Kore", prefs.rate, doc?.title ?? "", onToast);

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
    let seq = doc.position ?? 0;
    try {
      const local = localStorage.getItem(POS_KEY(docId));
      if (doc.position == null && local) seq = +local;
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
          const el = document.elementFromPoint(window.innerWidth / 2, probe)?.closest("[data-seq]");
          if (el) { seq = +(el as HTMLElement).dataset.seq!; break; }
        }
        if (seq == null || !restored.current) return;
        setTop(seq);
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
      if (b.type === "heading" && b.level <= 2) return b.translated || b.source;
    }
    return doc?.title ?? "";
  }, [top, blocks, doc?.title]);

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
      if (w) { setLookup({ word: w, seq }); return; }   // an English word: show its meaning
    }
    setSel(seq);
  };

  const listenHere = () => {
    let s = top;
    while (s < blocks.length && !isSpeakable(blocks[s])) s++;
    if (s < blocks.length) audio.playAt(s);
  };

  if (err) return <p className="center-msg">{err}<br /><button className="act" onClick={() => go("/")}>Library එකට</button></p>;
  if (!doc) return <p className="center-msg">Load වෙනවා...</p>;

  const style = { "--fs": `${prefs.fontSize}px`, "--lh": prefs.lineHeight } as CSSProperties;
  const selBlock = sel != null ? blocks[sel] : null;

  return (
    <div style={style}>
      <header className={"topbar" + (hidden && !panel && sel == null ? " hidden" : "")}>
        <button className="icon-btn" aria-label="Back to library" onClick={() => go("/")}><IconBack /></button>
        <div className="where">{heading}</div>
        <button className="icon-btn" aria-label="Listen from here" onClick={listenHere}><IconSpeaker /></button>
        <button className="icon-btn" aria-label="Contents" onClick={() => setPanel("toc")}><IconToc /></button>
        <button className="icon-btn" aria-label="Notes" onClick={() => setPanel("notes")}><IconNote /></button>
        <button className="icon-btn" aria-label="Reading settings" onClick={() => setPanel("settings")}><IconType /></button>
      </header>

      <main className="reader" onClick={onTap}>
        {!blocks.slice(0, 8).some((b) => b.type === "heading" && b.source.trim() === doc.title.trim()) &&
          <h1 className="doc-title">{doc.title}</h1>}
        <p className="doc-sub">{doc.title_si && doc.title_si !== doc.title ? doc.title_si : `පිටු ${doc.page_count}`}</p>

        {doc.status !== "done" && (
          <div className={"job-strip" + (doc.status === "error" ? " error" : "")} onClick={(e) => e.stopPropagation()}>
            {doc.status === "error" ? (
              <>
                <div>{jobLine(doc)}: {doc.error}</div>
                <button onClick={() => api.resume(docId).then(setDoc).catch((e) => onToast(e.message))}>නැවත උත්සාහ කරන්න</button>
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

        {blocks.length === 0 && doc.stage === "parse" && <p className="empty">PDF එක කියවනවා. පිටු ටික ලෑස්ති වුණාම මෙතන පෙන්නයි.</p>}

        {blocks.map((b) => {
          const ni = noteInfo.get(b.seq);
          return (
            <BlockView key={b.seq} b={b} docId={docId} hl={ni?.color ?? null} hasNote={!!ni?.body}
              selected={sel === b.seq} playing={audio.seq === b.seq} bilingual={prefs.bilingual} />
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
            {audio.state === "loading" ? "Voice එක හදනවා..." : (blocks[audio.seq!]?.translated || blocks[audio.seq!]?.source || "")}
          </div>
          <button className="rate" onClick={() => {
            const rates = [0.9, 1, 1.15, 1.3];
            setPrefs({ rate: rates[(rates.indexOf(prefs.rate) + 1) % rates.length] });
          }}>{prefs.rate}×</button>
          <button className="icon-btn" aria-label="Stop" onClick={audio.stop}><IconClose /></button>
        </div>
      )}

      <div className="progress-line"><div style={{ width: `${blocks.length ? ((top + 1) / blocks.length) * 100 : 0}%` }} /></div>

      {selBlock && (
        <BlockSheet doc={doc} block={selBlock} notes={notes} onClose={() => setSel(null)}
          onListen={(s) => { setSel(null); audio.playAt(s); }}
          onNotes={setNotes}
          onBlock={(b) => setBlocks((prev) => mergeBlocks(prev, [b]))}
          onToast={onToast} onZoom={setZoom} onWord={(w) => setLookup({ word: w, seq: selBlock.seq })} />
      )}
      {lookup && <WordCard key={`${lookup.seq}-${lookup.word}`} word={lookup.word} docId={docId} seq={lookup.seq}
        onClose={() => setLookup(null)} onToast={onToast} />}
      {panel === "toc" && <TocSheet blocks={blocks} current={top} onClose={() => setPanel("")}
        onJump={(s) => { setPanel(""); scrollTo(s); }} />}
      {panel === "notes" && <NotesSheet notes={notes} blocks={blocks} onClose={() => setPanel("")}
        onJump={(s) => { setPanel(""); scrollTo(s); setSel(null); }} />}
      {panel === "settings" && <SettingsSheet doc={doc} onClose={() => setPanel("")} onDoc={setDoc} onToast={onToast} />}

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
