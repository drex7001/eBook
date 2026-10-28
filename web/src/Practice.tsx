import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { go } from "./App";
import { IconBack, IconSpeaker } from "./icons";
import { Toast } from "./Sheet";
import { canSpeak, speak } from "./speech";
import type { PracticeQ } from "./types";
import { useText } from "./prefs";

const KIND_LABEL: Record<PracticeQ["kind"], string> = {
  meaning: "තේරුම තෝරන්න",
  cloze: "හිස්තැනට ගැලපෙන වචනය",
  usage: "හරියට පාවිච්චි කරපු වාක්‍යය",
  listen: "අහලා තෝරන්න",
  recall: "මතකද?",
};

export default function Practice() {
  const t=useText(),answering=useRef(false);
  const [qs, setQs] = useState<PracticeQ[] | null>(null);
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [score, setScore] = useState(0);
  const [err, setErr] = useState("");
  const [toast, setToast] = useState("");
  const [grading,setGrading]=useState(false);

  useEffect(() => {
    api.practice(10).then((r) => setQs(r.questions)).catch((e) => setErr(e.message));
  }, []);

  const q = qs?.[i];
  const grade = async (correct: boolean,choice?:number) => {
    if (!q||answering.current) return;
    answering.current=true;
    setGrading(true);
    try{const result=await api.answer(q.word.id,q.kind,q.choice_token,choice,correct);if(result.correct)setScore((s)=>s+1);setQs((prev)=>prev?.map((v,n)=>n===i?{...v,answer:result.answer,explain_si:result.explanation}:v)||null);return true;}
    catch(e){setToast((e as Error).message);setPicked(null);return false;}finally{answering.current=false;setGrading(false);}
  };

  const choose = (k: number) => {
    if (picked !== null || !q) return;
    setPicked(k);
    void grade(false,k);
  };

  const next = () => { setPicked(null); setRevealed(false); setI((x) => x + 1); };

  if (err) return <main className="library"><p className="center-msg">{err}</p></main>;
  if (!qs) return <main className="library"><p className="center-msg">{t("Loading saved practice…","Save කරපු practice ගන්නවා...")}</p></main>;

  if (!q) {
    return (
      <main className="library">
        <header className="lib-head"><h1>{t("Practice complete","ඉවරයි")}</h1></header>
        {qs.length === 0
          ? <p className="empty">{t("No words are due. Save some words or return when a review is due.","දැනට practice කරන්න වචන නෑ. අලුත් වචන එකතු කරන්න, නැත්නම් පසුව එන්න.")}</p>
          : <p className="pr-score">{score}/{qs.length} {t("correct","හරි")}</p>}
        <p className="small">{t("Missed words return in ten minutes. Remembered words are scheduled for a later day.","වැරදුණ වචන විනාඩි 10කින් ආයෙ එනවා. හරි ගිය ඒවා දවස් කිහිපයකින්.")}</p>
        <div className="actions">
          <button className="act primary" onClick={() => go("/words")}>{t("My words","මගේ වචන වලට")}</button>
          <button className="act" onClick={() => go("/")}>{t("Library","Library එකට")}</button>
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
        <p className="wc-label">{t({meaning:"Choose the meaning",cloze:"Fill the gap",usage:"Choose the correct usage",listen:"Listen and choose",recall:"Do you remember?"}[q.kind],KIND_LABEL[q.kind])}</p>
        {q.kind === "listen" && (
          <button className="act primary" onClick={() => void speak(q.audio_text, 0.85).catch((e)=>setToast(e.message))} disabled={!canSpeak()}>
            <IconSpeaker width={19} height={19} /> {t("Listen · device voice","අහන්න · device voice")}
          </button>
        )}
        <p className="pr-q">
          {q.kind === "cloze" ? parts.map((p, k) => <span key={k}>{p}{k < parts.length - 1 && <span className="blank">{answered ? q.options[q.answer] : "____"}</span>}</span>) : q.question}
        </p>

        {q.kind === "recall" ? (
          !revealed ? <button className="act primary" onClick={() => setRevealed(true)}>{t("Reveal meaning","තේරුම බලන්න")}</button> : (
            <>
              <p className="wc-si">{q.word.meaning_si}</p>
              <div className="actions">
                <button className="act primary" disabled={grading} onClick={() => {void grade(true).then((ok)=>{if(ok)next();});}}>{t("Remembered","මතක තිබුණා")}</button>
                <button className="act" disabled={grading} onClick={() => {void grade(false).then((ok)=>{if(ok)next();});}}>{t("Forgot","අමතක වුණා")}</button>
              </div>
            </>
          )
        ) : (
          <div className="pr-opts">
            {q.options.map((o, k) => {
              let cls = "pr-opt";
              if (picked !== null && !grading && k === q.answer) cls += " right";
              else if (picked === k && !grading) cls += " wrong";
              return <button key={k} className={cls} onClick={() => choose(k)} disabled={picked !== null}>{o}</button>;
            })}
          </div>
        )}

        {grading&&<p role="status">{t("Checking answer…","පිළිතුර බලනවා…")}</p>}
        {picked !== null && !grading && (
          <div className="pr-feedback" aria-live="polite">
            <p className={picked === q.answer ? "ok" : "no"}>{picked === q.answer ? t("Correct!","හරි!") : `${t("Correct answer:","හරි උත්තරය:")} ${q.options[q.answer]}`}</p>
            {q.explain_si && <p>{q.explain_si}</p>}
            <p className="small"><b>{q.word.word}</b>: {q.word.meaning_si}</p>
            {q.word.examples?.[0] && (
              <p className="small">
                {canSpeak() && <button className="icon-btn" aria-label="Play example" onClick={() => void speak(q.word.examples![0].en).catch((e)=>setToast(e.message))}><IconSpeaker width={16} height={16} /></button>}
                {q.word.examples[0].en}
              </p>
            )}
            <button className="act primary" onClick={next}>{i + 1 < qs.length ? t("Next","ඊළඟ එක") : t("Finish","ඉවර කරන්න")}</button>
          </div>
        )}
      </section>
      {toast && <Toast msg={toast} onDone={() => setToast("")} />}
    </main>
  );
}
