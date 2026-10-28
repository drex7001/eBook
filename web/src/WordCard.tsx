import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { IconSpeaker } from "./icons";
import { getCurrentSettings, usePrefs, useText } from "./prefs";
import Sheet from "./Sheet";
import { canSpeak, speak } from "./speech";
import type { Word, WordCardData } from "./types";

function Marked({ text, word }: { text: string; word: string }) {
  const rx = new RegExp(`(${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "i");
  const parts = text.split(rx);
  return <>{parts.map((p, i) => (rx.test(p) && i % 2 === 1 ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>))}</>;
}

/** Definition card for one word. Looks it up when `word` is given; shows a saved word when `saved` is given. */
export default function WordCard({ word, docId, seq, saved, initial, onClose, onSaved, onDeleted, onToast }: {
  word?: string; docId?: string; seq?: number; saved?: Word;
  initial?: WordCardData | null;
  onClose: () => void; onSaved?: (w: Word) => void; onDeleted?: (id: number) => void; onToast: (m: string) => void;
}) {
  const prefs = usePrefs();
  const t=useText();
  const [card, setCard] = useState<WordCardData | null>(saved ?? initial ?? null);
  const [savedId, setSavedId] = useState<number | null>(saved?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [audioConfirm,setAudioConfirm]=useState(false);
  const player=useRef<HTMLAudioElement|null>(null);
  const alive=useRef(true);

  useEffect(() => {
    const next=saved||initial;
    if(next){setCard(next);setSavedId(saved?.id||next.saved_id||null);}
  }, [saved,initial]);
  useEffect(()=>{if(prefs.audioMode==="off"){player.current?.pause();setPlaying(false);}},[prefs.audioMode]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;player.current?.pause();};},[]);

  const save = async () => {
    if (!card) return;
    setBusy(true);
    try {
      const w = await api.saveWord({ ...card, doc_id: docId ?? card.doc_id, seq: seq ?? card.seq });
      setSavedId(w.id);
      onSaved?.(w);
      onToast(t(`Saved "${w.word}"`,`"${w.word}" මගේ වචන වලට දැම්මා`));
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
      if(!alive.current||getCurrentSettings().audio_mode!=="cloud")return;
      const a = new Audio(url);
      player.current=a;
      a.onended = () => setPlaying(false);
      await a.play();
    } catch (e) { setPlaying(false); onToast((e as Error).message); }
  };

  const title = card?.word || word || "";
  return (
    <Sheet onClose={onClose} label={`Meaning of ${title}`}>
      <div className="wc-head">
        <span className="wc-word">{title}</span>
        {canSpeak() && <button className="icon-btn" aria-label="Pronounce · device voice" onClick={() => void speak(card?.lemma || title).catch((e)=>onToast(e.message))}><IconSpeaker /></button>}
      </div>
      {!card && <p className="small">{t("Looking up the word…","තේරුම හොයනවා...")}</p>}
      {card && (
        <>
          <p className="wc-meta">
            {card.ipa && <span>/{card.ipa}/</span>}
            {card.pos && <span className="chip">{card.pos}</span>}
            {card.level && <span className="chip">{card.level}</span>}
            {card.lemma && card.lemma.toLowerCase() !== title.toLowerCase() && <span>{t("Base form:","මූලික වචනය:")} {card.lemma}</span>}
          </p>
          <p className="wc-si" dir="auto">{card.meaning_target||card.meaning_si}</p>
          <p className="wc-en" dir="auto">{card.meaning_source||card.meaning_en}</p>
          {card.in_context_si && (
            <div className="wc-ctx">
              <p className="wc-label">{t("Meaning in this context","මේ වාක්‍යයේ තේරුම")}</p>
              <p>{card.in_context_si}</p>
              {card.context && <p className="wc-quote"><Marked text={card.context} word={title} /></p>}
            </div>
          )}
          {!!card.examples?.length && (
            <div className="wc-ex">
              <p className="wc-label">{t("Everyday examples","හැමදාම පාවිච්චි කරන විදිය")}</p>
              {card.examples.map((x, i) => (
                <div key={i} className="wc-exrow">
                  {canSpeak() && <button className="icon-btn" aria-label="Play example · device voice" onClick={() => void speak(x.en).catch((e)=>onToast(e.message))}><IconSpeaker width={18} height={18} /></button>}
                  <div><p className="en"><Marked text={x.en} word={card.lemma || title} /></p><p className="si">{x.si}</p></div>
                </div>
              ))}
            </div>
          )}
          {!!card.synonyms?.length && <p className="small">{t("Synonyms:","සමාන වචන:")} {card.synonyms.join(", ")}</p>}
          <div className="actions">
            {savedId == null
              ? <button className="act primary" disabled={busy} onClick={save}>{t("Save word","මගේ වචන වලට දාන්න")}</button>
              : <span className="act" aria-live="polite">✓ {t("Saved word","මගේ වචන වල තියෙනවා")}</span>}
            {savedId != null && prefs.audioMode==="cloud" && <button className="act" onClick={()=>setAudioConfirm(true)} disabled={playing}>{playing?t("Playing…","අහනවා..."):t("Listen with meaning · cloud","තේරුමත් එක්ක අහන්න · cloud")}</button>}
            {savedId != null && saved && <button className="act" onClick={remove}>{t("Remove saved word","List එකෙන් අයින් කරන්න")}</button>}
          </div>
          {audioConfirm&&<div className="version-create"><p>{t("Generate cloud audio for this word? Provider charges may apply.","මේ වචනයේ cloud audio හදන්නද? වියදමක් යන්න පුළුවන්.")}</p><div className="actions"><button className="act primary" onClick={()=>{setAudioConfirm(false);void lesson();}}>{t("Confirm & listen","තහවුරු කර අහන්න")}</button><button className="act" onClick={()=>setAudioConfirm(false)}>{t("Cancel","එපා")}</button></div></div>}
        </>
      )}
    </Sheet>
  );
}
