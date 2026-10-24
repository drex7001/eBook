import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { go } from "./App";
import { IconBack, IconClose } from "./icons";
import { usePrefs } from "./prefs";
import { Toast } from "./Sheet";
import type { VocabStats, Word } from "./types";
import WordCard from "./WordCard";

function dueText(w: Word): string {
  const days = (w.due_at - Date.now() / 1000) / 86400;
  if (days <= 0) return "අද practice කරන්න";
  if (days < 1) return "අද පස්සේ";
  return `දවස් ${Math.round(days)}කින්`;
}

export default function Words() {
  const prefs = usePrefs();
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
    if (!words?.length) return;
    const list = [...words].sort((a, b) => a.due_at - b.due_at);
    stopRef.current = false;
    for (let i = 0; i < list.length && !stopRef.current; i++) {
      setPlaying({ i, list });
      try {
        const { url } = await api.wordAudio(list[i].id, prefs.voice || "Kore");
        if (stopRef.current) break;
        await new Promise<void>((res, rej) => {
          const a = new Audio(url);
          audioRef.current = a;
          a.onended = () => res();
          a.onerror = () => rej(new Error("Audio එක play කරන්න බැරි වුණා"));
          a.play().catch(rej);
        });
      } catch (e) { setToast((e as Error).message); break; }
    }
    setPlaying(null);
  };
  const stop = () => { stopRef.current = true; audioRef.current?.pause(); setPlaying(null); };

  return (
    <main className="library">
      <header className="lib-head">
        <button className="icon-btn" aria-label="Back to library" onClick={() => go("/")}><IconBack /></button>
        <h1 style={{ flex: 1 }}>මගේ වචන</h1>
      </header>

      {stats && (
        <div className="vstats">
          <div><b>{stats.total}</b><span>වචන</span></div>
          <div><b>{stats.due}</b><span>අද practice</span></div>
          <div><b>{stats.known}</b><span>හොඳට දන්නවා</span></div>
          <div><b>{stats.streak}</b><span>දවස් streak</span></div>
        </div>
      )}

      <div className="actions">
        <button className="act primary" disabled={!stats?.due} onClick={() => go("/practice")}>
          {stats?.due ? `අද practice කරන්න (${Math.min(stats.due, 10)})` : "අද practice කරන්න වචන නෑ"}
        </button>
        <button className="act" disabled={!words?.length || !!playing} onClick={playAll}>▶ ඔක්කොම අහන්න</button>
      </div>

      <input className="field search" placeholder="වචනයක් හොයන්න" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search words" />

      {words && words.length === 0 && !q && (
        <p className="empty">තාම වචන නෑ. පොතක් කියවද්දී English වචනයක් tap කරලා "මගේ වචන වලට දාන්න" දෙන්න.</p>
      )}
      {words?.map((w) => (
        <button key={w.id} className="wrow" onClick={() => setOpen(w)}>
          <span className="w">{w.word}</span>
          <span className="m">{w.meaning_si}</span>
          <span className="d">{w.level ? `${w.level}, ` : ""}{dueText(w)}</span>
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
