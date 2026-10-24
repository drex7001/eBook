import { useEffect, useState } from "react";
import { api } from "./api";
import { IconSpeaker } from "./icons";
import { usePrefs } from "./prefs";
import Sheet from "./Sheet";
import { canSpeak, speak } from "./speech";
import type { Word, WordCardData } from "./types";

function Marked({ text, word }: { text: string; word: string }) {
  const rx = new RegExp(`(${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "i");
  const parts = text.split(rx);
  return <>{parts.map((p, i) => (rx.test(p) && i % 2 === 1 ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>))}</>;
}

/** Definition card for one word. Looks it up when `word` is given; shows a saved word when `saved` is given. */
export default function WordCard({ word, docId, seq, saved, onClose, onSaved, onDeleted, onToast }: {
  word?: string; docId?: string; seq?: number; saved?: Word;
  onClose: () => void; onSaved?: (w: Word) => void; onDeleted?: (id: number) => void; onToast: (m: string) => void;
}) {
  const prefs = usePrefs();
  const [card, setCard] = useState<WordCardData | null>(saved ?? null);
  const [err, setErr] = useState("");
  const [savedId, setSavedId] = useState<number | null>(saved?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (saved || !word) return;
    api.lookup(word, docId, seq)
      .then((c) => { setCard(c); setSavedId(c.saved_id ?? null); })
      .catch((e) => setErr(e.message));
  }, [word, docId, seq, saved]);

  const save = async () => {
    if (!card) return;
    setBusy(true);
    try {
      const w = await api.saveWord({ ...card, doc_id: docId ?? card.doc_id, seq: seq ?? card.seq });
      setSavedId(w.id);
      onSaved?.(w);
      onToast(`"${w.word}" මගේ වචන වලට දැම්මා`);
    } catch (e) { onToast((e as Error).message); } finally { setBusy(false); }
  };

  const remove = async () => {
    if (savedId == null) return;
    await api.deleteWord(savedId).catch(() => {});
    onDeleted?.(savedId);
    setSavedId(null);
    onClose();
  };

  const lesson = async () => {
    if (savedId == null) return;
    setPlaying(true);
    try {
      const { url } = await api.wordAudio(savedId, prefs.voice || "Kore");
      const a = new Audio(url);
      a.onended = () => setPlaying(false);
      await a.play();
    } catch (e) { setPlaying(false); onToast((e as Error).message); }
  };

  const title = card?.word || word || "";
  return (
    <Sheet onClose={onClose} label={`Meaning of ${title}`}>
      <div className="wc-head">
        <span className="wc-word">{title}</span>
        {canSpeak() && <button className="icon-btn" aria-label="Pronounce" onClick={() => speak(card?.lemma || title)}><IconSpeaker /></button>}
      </div>
      {!card && !err && <p className="small">තේරුම හොයනවා...</p>}
      {err && <p className="small">{err}</p>}
      {card && (
        <>
          <p className="wc-meta">
            {card.ipa && <span>/{card.ipa}/</span>}
            {card.pos && <span className="chip">{card.pos}</span>}
            {card.level && <span className="chip">{card.level}</span>}
            {card.lemma && card.lemma.toLowerCase() !== title.toLowerCase() && <span>base form: {card.lemma}</span>}
          </p>
          <p className="wc-si">{card.meaning_si}</p>
          <p className="wc-en">{card.meaning_en}</p>
          {card.in_context_si && (
            <div className="wc-ctx">
              <p className="wc-label">මේ වාක්‍යයේ තේරුම</p>
              <p>{card.in_context_si}</p>
              {card.context && <p className="wc-quote"><Marked text={card.context} word={title} /></p>}
            </div>
          )}
          {!!card.examples?.length && (
            <div className="wc-ex">
              <p className="wc-label">හැමදාම පාවිච්චි කරන විදිය</p>
              {card.examples.map((x, i) => (
                <div key={i} className="wc-exrow">
                  {canSpeak() && <button className="icon-btn" aria-label="Play example" onClick={() => speak(x.en)}><IconSpeaker width={18} height={18} /></button>}
                  <div><p className="en"><Marked text={x.en} word={card.lemma || title} /></p><p className="si">{x.si}</p></div>
                </div>
              ))}
            </div>
          )}
          {!!card.synonyms?.length && <p className="small">සමාන වචන: {card.synonyms.join(", ")}</p>}
          <div className="actions">
            {savedId == null
              ? <button className="act primary" disabled={busy} onClick={save}>මගේ වචන වලට දාන්න</button>
              : <span className="act" aria-live="polite">✓ මගේ වචන වල තියෙනවා</span>}
            {savedId != null && <button className="act" onClick={lesson} disabled={playing}>{playing ? "අහනවා..." : "▶ සිංහල තේරුමත් එක්ක අහන්න"}</button>}
            {savedId != null && saved && <button className="act" onClick={remove}>List එකෙන් අයින් කරන්න</button>}
          </div>
        </>
      )}
    </Sheet>
  );
}
