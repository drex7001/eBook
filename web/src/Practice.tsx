import { useEffect, useState } from "react";
import { api } from "./api";
import { go } from "./App";
import { IconBack, IconSpeaker } from "./icons";
import { Toast } from "./Sheet";
import { canSpeak, speak } from "./speech";
import type { PracticeQ } from "./types";

const KIND_LABEL: Record<PracticeQ["kind"], string> = {
  meaning: "තේරුම තෝරන්න",
  cloze: "හිස්තැනට ගැලපෙන වචනය",
  usage: "හරියට පාවිච්චි කරපු වාක්‍යය",
  listen: "අහලා තෝරන්න",
  recall: "මතකද?",
};

export default function Practice() {
  const [qs, setQs] = useState<PracticeQ[] | null>(null);
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [score, setScore] = useState(0);
  const [err, setErr] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    api.practice(10).then((r) => setQs(r.questions)).catch((e) => setErr(e.message));
  }, []);

  const q = qs?.[i];
  useEffect(() => {
    if (q?.kind === "listen" && q.audio_text) speak(q.audio_text);
  }, [q]);

  const grade = (correct: boolean) => {
    if (!q) return;
    if (correct) setScore((s) => s + 1);
    api.answer(q.word.id, q.kind, correct).catch((e) => setToast(e.message));
  };

  const choose = (k: number) => {
    if (picked !== null || !q) return;
    setPicked(k);
    grade(k === q.answer);
  };

  const next = () => { setPicked(null); setRevealed(false); setI((x) => x + 1); };

  if (err) return <main className="library"><p className="center-msg">{err}</p></main>;
  if (!qs) return <main className="library"><p className="center-msg">අද ප්‍රශ්න හදනවා...</p></main>;

  if (!q) {
    return (
      <main className="library">
        <header className="lib-head"><h1>ඉවරයි</h1></header>
        {qs.length === 0
          ? <p className="empty">දැනට practice කරන්න වචන නෑ. අලුත් වචන එකතු කරන්න, නැත්නම් හෙට එන්න.</p>
          : <p className="pr-score">{qs.length}න් {score}ක් හරි.</p>}
        <p className="small">වැරදුණ වචන විනාඩි 10කින් ආයෙ එනවා. හරි ගිය ඒවා දවස් කිහිපයකින්.</p>
        <div className="actions">
          <button className="act primary" onClick={() => go("/words")}>මගේ වචන වලට</button>
          <button className="act" onClick={() => go("/")}>Library එකට</button>
        </div>
      </main>
    );
  }

  const answered = picked !== null || revealed;
  const parts = q.kind === "cloze" ? q.question.split("____") : [q.question];

  return (
    <main className="library">
      <header className="lib-head">
        <button className="icon-btn" aria-label="Stop practice" onClick={() => go("/words")}><IconBack /></button>
        <span className="pr-count">{i + 1} / {qs.length}</span>
      </header>
      <div className="pr-bar"><div style={{ width: `${(i / qs.length) * 100}%` }} /></div>

      <section className="pr-card">
        <p className="wc-label">{KIND_LABEL[q.kind]}</p>
        {q.kind === "listen" && (
          <button className="act primary" onClick={() => speak(q.audio_text, 0.85)} disabled={!canSpeak()}>
            <IconSpeaker width={19} height={19} /> ආයෙ අහන්න
          </button>
        )}
        <p className="pr-q">
          {q.kind === "cloze" ? parts.map((p, k) => <span key={k}>{p}{k < parts.length - 1 && <span className="blank">{answered ? q.options[q.answer] : "____"}</span>}</span>) : q.question}
        </p>

        {q.kind === "recall" ? (
          !revealed ? <button className="act primary" onClick={() => setRevealed(true)}>තේරුම බලන්න</button> : (
            <>
              <p className="wc-si">{q.word.meaning_si}</p>
              <div className="actions">
                <button className="act primary" onClick={() => { grade(true); next(); }}>මතක තිබුණා</button>
                <button className="act" onClick={() => { grade(false); next(); }}>අමතක වුණා</button>
              </div>
            </>
          )
        ) : (
          <div className="pr-opts">
            {q.options.map((o, k) => {
              let cls = "pr-opt";
              if (picked !== null && k === q.answer) cls += " right";
              else if (picked === k) cls += " wrong";
              return <button key={k} className={cls} onClick={() => choose(k)} disabled={picked !== null}>{o}</button>;
            })}
          </div>
        )}

        {picked !== null && (
          <div className="pr-feedback" aria-live="polite">
            <p className={picked === q.answer ? "ok" : "no"}>{picked === q.answer ? "හරි!" : `හරි උත්තරය: ${q.options[q.answer]}`}</p>
            {q.explain_si && <p>{q.explain_si}</p>}
            <p className="small"><b>{q.word.word}</b>: {q.word.meaning_si}</p>
            {q.word.examples?.[0] && (
              <p className="small">
                {canSpeak() && <button className="icon-btn" aria-label="Play example" onClick={() => speak(q.word.examples![0].en)}><IconSpeaker width={16} height={16} /></button>}
                {q.word.examples[0].en}
              </p>
            )}
            <button className="act primary" onClick={next}>{i + 1 < qs.length ? "ඊළඟ එක" : "ඉවර කරන්න"}</button>
          </div>
        )}
      </section>
      {toast && <Toast msg={toast} onDone={() => setToast("")} />}
    </main>
  );
}
