import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { go } from "./App";
import { IconBack, IconClose } from "./icons";
import { usePrefs, useText } from "./prefs";
import { speak, cancelSpeech } from "./speech";
import { Toast } from "./Sheet";
import type { VocabStats, Word } from "./types";
import WordCard from "./WordCard";

function dueText(w: Word,t:(en:string,si:string)=>string): string {
  const days = (w.due_at - Date.now() / 1000) / 86400;
  if (days <= 0) return t("Due today","අද practice කරන්න");
  if (days < 1) return t("Later today","අද පස්සේ");
  return t(`In ${Math.round(days)} days`,`දවස් ${Math.round(days)}කින්`);
}

export default function Words() {
  const prefs = usePrefs();
  const t=useText();
  const [words, setWords] = useState<Word[] | null>(null);
  const [stats, setStats] = useState<VocabStats | null>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Word | null>(null);
  const [toast, setToast] = useState("");
  const [playing, setPlaying] = useState<{ i: number; list: Word[] } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stopRef = useRef(false);

  const load = useCallback(() => {
    api.words(q).then((r) => { setWords(r.words); setStats(r.stats); }).catch((e) => setToast(e.message));
  }, [q]);
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t); }, [load, q]);

  const playAll = async () => {
    if (!words?.length||prefs.audioMode!=="device") return;
    const list = [...words].sort((a, b) => a.due_at - b.due_at);
    stopRef.current = false;
    for (let i = 0; i < list.length && !stopRef.current; i++) {
      setPlaying({ i, list });
      try {
        await speak(list[i].word,prefs.rate,list[i].source_language||"auto");
      } catch (e) { setToast((e as Error).message); break; }
    }
    setPlaying(null);
  };
  const stop = () => { stopRef.current = true; audioRef.current?.pause();cancelSpeech(); setPlaying(null); };
  useEffect(()=>{if(prefs.audioMode!=="device")stop();},[prefs.audioMode]);
  useEffect(()=>()=>{stopRef.current=true;cancelSpeech();},[]);

  return (
    <main className="library">
      <header className="lib-head">
        <button className="icon-btn" aria-label="Back to library" onClick={() => go("/")}><IconBack /></button>
        <h1 style={{ flex: 1 }}>{t("My words","මගේ වචන")}</h1>
      </header>

      {stats && (
        <div className="vstats">
          <div><b>{stats.total}</b><span>{t("Words","වචන")}</span></div>
          <div><b>{stats.due}</b><span>{t("Due today","අද practice")}</span></div>
          <div><b>{stats.known}</b><span>{t("Mastered","හොඳට දන්නවා")}</span></div>
          <div><b>{stats.streak}</b><span>{t("Day streak","දවස් streak")}</span></div>
        </div>
      )}

      <div className="actions">
        <button className="act primary" disabled={!stats?.due} onClick={() => go("/practice")}>
          {stats?.due ? t(`Practice today (${Math.min(stats.due,10)})`,`අද practice කරන්න (${Math.min(stats.due, 10)})`) : t("No words due today","අද practice කරන්න වචන නෑ")}
        </button>
        {prefs.audioMode==="device"&&<button className="act" disabled={!words?.length || !!playing} onClick={playAll}>▶ {t("Listen · device voice","ඔක්කොම අහන්න · device voice")}</button>}
        <button className="act" onClick={()=>{if(window.confirm(t("Generate vocabulary questions with your AI provider?","AI provider එකෙන් vocabulary ප්‍රශ්න හදන්නද?")))void api.generatePractice().then(()=>setToast(t("Practice questions ready","Practice ප්‍රශ්න ලෑස්තියි"))).catch((e)=>setToast(e.message));}}>{t("Generate practice · AI","Practice ප්‍රශ්න හදන්න · AI")}</button>
      </div>

      <input className="field search" placeholder={t("Search words","වචනයක් හොයන්න")} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search words" />

      {words && words.length === 0 && !q && (
        <p className="empty">{t("Tap a word while reading, confirm its translation, then choose Save word.","තාම වචන නෑ. කියවද්දී වචනයක් tap කරලා translate කරලා මගේ වචන වලට දාන්න.")}</p>
      )}
      {words?.map((w) => (
        <button key={w.id} className="wrow" onClick={() => setOpen(w)}>
          <span className="w">{w.word}</span>
          <span className="m">{w.meaning_si}</span>
          <span className="d">{w.level ? `${w.level}, ` : ""}{dueText(w,t)}</span>
        </button>
      ))}

      {playing && (
        <div className="audiobar" role="region" aria-label="Word audio">
          <div className="info" style={{ paddingLeft: 14 }}>
            {playing.list[playing.i].word} ({playing.i + 1}/{playing.list.length})
          </div>
          <button className="icon-btn" aria-label="Stop" onClick={stop}><IconClose /></button>
        </div>
      )}
      {open && <WordCard saved={open} onClose={() => setOpen(null)} onToast={setToast}
        onDeleted={() => { setOpen(null); load(); }} />}
      {toast && <Toast msg={toast} onDone={() => setToast("")} />}
    </main>
  );
}
