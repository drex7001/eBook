import { useCallback, useEffect, useRef, useState } from "react";
import { actionKey, api } from "./api";
import { go } from "./App";
import { catalog, useSettings, useText } from "./prefs";
import type { Doc, QuizAttempt, QuizPaper, SavedQuizResponse, StudyDashboard } from "./types";
import Sheet from "./Sheet";

export default function Study({docId}: {docId: string}) {
  const p = useSettings(), t = useText();
  const params = new URLSearchParams(location.hash.split("?")[1]);
  const attemptId = params.get("attempt");
  const [doc,setDoc] = useState<Doc | null>(null), [data,setData] = useState<StudyDashboard | null>(null);
  const [mode,setMode] = useState<"study" | "exam">("study"), [difficulty,setDifficulty] = useState(params.has("boss") ? "hard" : "easy");
  const [scope,setScope] = useState(params.has("start") ? "range" : "chapters");
  const [sections,setSections] = useState<number[]>([Number(params.get("section") || 0)]);
  const [start,setStart] = useState(Number(params.get("start") || 0) + 1), [end,setEnd] = useState(Number(params.get("end") || 0) + 1);
  const [count,setCount] = useState(p.quiz_count), [minutes,setMinutes] = useState(p.exam_minutes);
  const [busy,setBusy] = useState(false), [error,setError] = useState("");
  const [responses,setResponses]=useState<SavedQuizResponse[]|null>(null);
  const key = useRef(actionKey());
  const load = useCallback(async () => {const [d,s] = await Promise.all([api.doc(docId),api.study(docId)]);setDoc(d);setData(s);},[docId]);
  useEffect(() => {load().catch((e) => setError(e.message));},[load]);
  const pending = data?.papers.some((q) => ["queued","running","stopping"].includes(q.status));
  const safeGeneration=data?.generation_contract==="durable-v2";
  useEffect(() => {if (!pending) return;const timer = setInterval(() => void load().catch((e) => setError(e.message)),2000);return () => clearInterval(timer);},[pending,load]);
  const generate = async () => {
    if(!safeGeneration)return;
    setBusy(true);setError("");
    try {
      await api.generatePaper(docId, {difficulty,count,request_key:key.current,
        ...(scope === "chapters" ? {sections} : scope === "range" ? {start_seq:start - 1,end_seq:end - 1} : {})});
      key.current = actionKey();await load();
    } catch (e) {setError((e as Error).message);key.current = actionKey();} finally {setBusy(false);}
  };
  const recheck=async(paper:QuizPaper)=>{setBusy(true);setError("");try{await api.recheckPaper(paper.id);await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  const inspect=async(paper:QuizPaper)=>{setBusy(true);setError("");try{setResponses((await api.paperResponses(paper.id)).responses);}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  const stop=async(paper:QuizPaper)=>{setBusy(true);setError("");try{await api.stopPaper(paper.id);await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  const begin = async (paper: QuizPaper, selectedMode: "study" | "exam", question?: string) => {
    setBusy(true);setError("");
    try {const a = await api.startAttempt(paper.id,selectedMode,minutes,actionKey());go(`/study/${docId}?attempt=${a.id}${question ? `&question=${question}` : ""}`);}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  if (attemptId) return <Attempt docId={docId} attemptId={attemptId} initialQuestion={params.get("question")} />;
  return <main className="study-page"><header className="page-head"><button className="act" onClick={() => go(`/read/${docId}`)}>← {t("Reader","කියවීමට")}</button><div><p className="eyebrow">{t("READ · UNDERSTAND · REMEMBER","කියවන්න · තේරුම් ගන්න · මතක තබාගන්න")}</p><h1>{t("Study studio","Study studio")}</h1><p className="small">{doc?.title}</p></div></header>
    {error && <p role="alert" className="error-box">{error}</p>}
    {data&&!safeGeneration&&<p role="alert" className="error-box">{t("Restart the app to activate safe quiz generation. This page will not send generation requests to the old server.","ආරක්ෂිත quiz generation එක යොදන්න app එක restart කරන්න. මේ page එකෙන් පරණ server එකට generation requests යවන්නේ නෑ.")}</p>}
    <section className="settings-card"><h2>{t("Create a question paper","ප්‍රශ්න පත්‍රයක් හදන්න")}</h2><p className="small">{t("Questions use original source material. Generating a new version uses your configured AI provider; retrying an existing paper does not.","ප්‍රශ්න හදන්නේ original material එකෙන්. අලුත් version එකක් හදන්න AI භාවිතා කරනවා; තිබෙන paper එක නැවත කරන්න AI calls යන්නේ නෑ.")}</p>
      <form onSubmit={(e) => {e.preventDefault();void generate();}}><div className="settings-grid">
        <label className="setting-field"><span>{t("Mode","Mode")}</span><select value={mode} onChange={(e) => {const v=e.target.value as "study"|"exam";setMode(v);setCount(v==="exam"?p.exam_count:p.quiz_count);}}><option value="study">{t("Study · instant feedback","Study · ඒ වෙලාවේම පැහැදිලි කිරීම")}</option><option value="exam">{t("Exam · reveal after submission","Exam · submit කළ පසු පිළිතුරු")}</option></select></label>
        <label className="setting-field"><span>{t("Difficulty","අමාරු මට්ටම")}</span><select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}><option value="easy">Easy · {t("Recall","මතකය")}</option><option value="medium">Medium · {t("Understanding","තේරුම් ගැනීම")}</option><option value="hard">Hard · {t("Application & analysis","යෙදීම සහ විශ්ලේෂණය")}</option></select></label>
        <label className="setting-field"><span>{t("Source scope","ගන්න කොටස")}</span><select value={scope} onChange={(e) => setScope(e.target.value)}><option value="chapters">{t("Selected chapters","තෝරාගත් chapters")}</option><option value="range">{t("Paragraph range","Paragraph පරාසය")}</option><option value="book">{t("Whole book","මුළු පොත")}</option></select></label>
        <label className="setting-field"><span>{t("Questions","ප්‍රශ්න")}</span><input type="number" value={count} min={1} max={60} onChange={(e) => setCount(Number(e.target.value))} required /></label>
        {mode === "exam" && <label className="setting-field"><span>{t("Time limit (minutes)","කාලය (විනාඩි)")}</span><input type="number" value={minutes} min={1} max={180} onChange={(e) => setMinutes(Number(e.target.value))} required /></label>}
      </div>
      {scope === "chapters" && <fieldset className="chapter-picker"><legend>{t("Choose chapters","Chapters තෝරන්න")}</legend>{doc?.sections?.map((s) => <label key={s.idx}><input type="checkbox" checked={sections.includes(s.idx)} onChange={(e) => setSections((prev) => e.target.checked ? [...prev,s.idx] : prev.filter((v) => v!==s.idx))} />{s.title}</label>)}</fieldset>}
      {scope === "range" && <div className="settings-grid"><label className="setting-field"><span>{t("From paragraph","පටන් ගන්න paragraph")}</span><input type="number" min={1} value={start} onChange={(e) => setStart(Number(e.target.value))} required /></label><label className="setting-field"><span>{t("Through paragraph","අවසන් paragraph")}</span><input type="number" min={start} value={end} onChange={(e) => setEnd(Number(e.target.value))} required /></label></div>}
      <p className="generation-summary">{count} {difficulty} · {catalog.languages[p.target_language] || p.target_language} · {p.provider}{p.light_model ? ` / ${p.light_model}` : ""}</p>
      <p className="small">{t(`Up to ${Math.ceil(count/4)} response batches. Every response is saved before validation. A failed/incomplete response stops generation; no automatic paid retries.`,`Response batches උපරිම ${Math.ceil(count/4)}යි. Check කරන්න කලින් හැම response එකම save කරනවා. Response එක fail/අසම්පූර්ණ නම් generation එක නවතිනවා; paid retries ඉබේ යන්නේ නෑ.`)}</p>
      <button className="act primary" disabled={!safeGeneration || busy || !!pending || (scope==="chapters" && !sections.length)}>{busy ? t("Submitting…","යවනවා…") : t("Generate new version · AI","අලුත් version එකක් හදන්න · AI")}</button></form>
    </section>
    <section className="settings-card"><h2>{t("Saved papers","Save කරපු papers")}</h2>{data?.papers.length===0 && <p className="small">{t("Your first paper will appear here. Nothing is generated when you open this page.","මුල් paper එක මෙතන පෙන්වයි. මේ page එක ඇරියට ප්‍රශ්න generate වෙන්නේ නෑ.")}</p>}
      {data?.papers.map((paper) => <article className="paper-row" key={paper.id}><div className="paper-details"><h3>{paper.difficulty.toUpperCase()} <small>V{paper.version}</small></h3><p className="small">{paper.questions.length}/{paper.count} {t("validated questions saved","check කරලා save කරපු ප්‍රශ්න")} · {paper.language} · <span role="status">{paper.status}</span></p>
        {paper.generation?.legacy_unarchived&&<p className="error-box">{t("The previous version did not save the raw answers for this paper. They cannot be recovered locally. Generating again is a new paid action.","පරණ version එක මේ paper එකේ raw answers save කරලා නැහැ. ඒවා මෙතනින් recover කරන්න බැහැ. නැවත generate කිරීම අලුත් paid action එකක්.")}</p>}
        {paper.error&&!paper.generation?.legacy_unarchived&&<p className="small">{paper.error.includes("Some generated questions did not pass source/format checks.")?"Some generated questions did not pass source/format checks.":paper.error}</p>}
        {!!paper.generation?.requests&&<p className="small">{paper.generation.returned_questions} {t("returned","ලැබුණු ප්‍රශ්න")} · {paper.generation.responses_saved} {t("responses saved","responses save කරලා")} · {paper.generation.requests} {t("requests","requests")} · {paper.generation.input_tokens} / {paper.generation.output_tokens} tokens · {paper.generation.estimate_known?`≈ $${paper.generation.estimated_cost_usd.toFixed(4)}`:t("Cost estimate unavailable","වියදමේ estimate එක නෑ")}</p>}
        {!!paper.generation?.diagnostics.length&&<details className="generation-diagnostics"><summary>{t("Why questions were rejected","ප්‍රශ්න reject වුණු හේතු")}</summary><ul>{paper.generation.diagnostics.map((d)=><li key={d.code}>{d.message} ({d.count})</li>)}</ul></details>}
        <div className="actions">{paper.generation?.can_recover&&<button className="act" disabled={busy} onClick={()=>void recheck(paper)}>{t("Recheck saved responses · no AI","Save කරපු responses නැවත check කරන්න · AI නැහැ")}</button>}
        {!!paper.generation?.responses_saved&&<button className="act" disabled={busy} onClick={()=>void inspect(paper)}>{t("View saved responses","Save කරපු responses බලන්න")}</button>}
        {["queued","running"].includes(paper.status)&&safeGeneration&&<button className="act" disabled={busy} onClick={()=>void stop(paper)}>{t("Stop after current response","දැනට යන response එකෙන් පසු නවත්වන්න")}</button>}</div></div>
        {paper.questions.length>0 && !["queued","running","stopping"].includes(paper.status) && <div className="actions"><button className="act" disabled={busy} onClick={() => void begin(paper,"study")}>{t("Study / retry","Study / නැවත කරන්න")}</button><button className="act" disabled={busy} onClick={() => void begin(paper,"exam")}>{t("Start exam","Exam කරන්න")}</button></div>}</article>)}
    </section>
    {!!data?.attempts.length && <section className="settings-card"><h2>{t("Attempts","කළ attempts")}</h2>{data.attempts.map((a) => <button className="attempt-row" key={a.id} onClick={() => go(`/study/${docId}?attempt=${a.id}`)}><span>{a.difficulty} V{a.version} · {a.mode}</span><b>{a.submitted_at ? `${a.score}/${a.total}` : t("Resume →","ඉදිරියට →")}</b></button>)}</section>}
    {!!data?.weak_sections.length && <section className="settings-card"><h2>{t("Chapters to revisit","නැවත බලන්න ඕන chapters")}</h2>{data.weak_sections.map((s) => <p key={s.section}>{doc?.sections?.find((v) => v.idx===s.section)?.title || `Section ${s.section+1}`} · {s.mistakes} {t("questions to review","නැවත බලන්න ප්‍රශ්න")}</p>)}</section>}
    {!!data?.review.length && <section className="settings-card"><h2>{t("Due for review","නැවත මතක් කරගන්න")}</h2>{data.review.map((q) => <button className="attempt-row" key={q.id} onClick={() => {const paper=data.papers.find((v) => v.id===q.paper_id);if (paper) void begin(paper,"study",q.id);}}><span>{q.question}</span><b>→</b></button>)}</section>}
    {responses&&<Sheet label="Saved quiz responses" onClose={()=>setResponses(null)}><h3>{t("Saved responses","Save කරපු responses")}</h3><p className="small">{t("This reads saved local output and uses no AI tokens. Rejected draft answers are not validated questions.","මෙතනින් පෙන්වන්නේ local save කරපු output එක. AI tokens යන්නේ නෑ. Reject වුණු draft answers validated ප්‍රශ්න නෙවෙයි.")}</p>{responses.map((r)=><section className="saved-response" key={r.id}><h4>Batch {r.batch_index+1} · {r.outcome}</h4><p className="small">{r.model} · {r.usage.input_tokens??"?"} / {r.usage.output_tokens??"?"} tokens</p><details><summary>{t("Returned output","ලැබුණු output එක")}</summary><pre>{r.raw||JSON.stringify(r.questions,null,2)||t("No response body received","Response body එකක් ලැබිලා නැහැ")}</pre></details><details><summary>{t("Validation details","Validation විස්තර")}</summary><pre>{JSON.stringify(r.diagnostics,null,2)}</pre></details><details><summary>{t("Original excerpts used","භාවිතා කරපු original කොටස්")}</summary>{r.sources.map((s)=><div key={s.seq}><p className="small">¶{s.seq+1} · {t("Page","පිටුව")} {s.page+1}</p><p dir="auto">{s.text}</p></div>)}</details></section>)}</Sheet>}
  </main>;
}

function Attempt({docId,attemptId,initialQuestion}: {docId:string;attemptId:string;initialQuestion:string|null}) {
  const t=useText();
  const [a,setA]=useState<QuizAttempt|null>(null),[index,setIndex]=useState(0),[error,setError]=useState(""),[busy,setBusy]=useState(false),[now,setNow]=useState(Date.now()/1000);
  const serverOffset=useRef(0), expired=useRef(false);
  const receive=useCallback((value:QuizAttempt) => {serverOffset.current=value.server_time-Date.now()/1000;setA(value);},[]);
  useEffect(() => {let alive=true;api.attempt(attemptId).then((v) => {if(!alive)return;receive(v);const i=v.questions.findIndex((q) => q.id===initialQuestion);if(i>=0)setIndex(i);}).catch((e) => {if(alive)setError(e.message);});return () => {alive=false;};},[attemptId,initialQuestion,receive]);
  useEffect(() => {const timer=setInterval(() => setNow(Date.now()/1000+serverOffset.current),1000);return () => clearInterval(timer);},[]);
  useEffect(() => {if(a?.deadline&&!a.submitted_at&&now>=a.deadline&&!expired.current){expired.current=true;api.attempt(attemptId).then(receive).catch((e) => {setError(e.message);expired.current=false;});}},[a?.deadline,a?.submitted_at,now,attemptId,receive]);
  const run=async(fn:()=>Promise<QuizAttempt>)=>{setBusy(true);setError("");try{receive(await fn());}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  if(!a)return <main className="study-page"><p role={error?"alert":"status"}>{error||t("Loading attempt…","Attempt එක ගන්නවා…")}</p></main>;
  const q=a.questions[index], chosen=q?a.answers[q.id]:undefined, revealed=q?.answer!==undefined;
  const remaining=a.deadline?Math.max(0,Math.ceil(a.deadline-now)):0;
  return <main className="study-page"><header className="page-head"><button className="act" onClick={() => go(`/study/${docId}`)}>← {t("Papers","Papers")}</button><div><p className="eyebrow">{a.mode.toUpperCase()} · {a.paper.difficulty.toUpperCase()} V{a.paper.version}</p><h1>{a.submitted_at ? `${a.score}/${a.questions.length} · ${t("Completed","ඉවරයි")}` : t("Check your understanding","තේරුණාද බලමු")}</h1></div>{a.mode==="exam"&&!a.submitted_at&&<span className="exam-clock" role="timer">{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,"0")}</span>}</header>
    {error&&<p role="alert" className="error-box">{error}</p>}
    <nav className="question-nav" aria-label="Questions">{a.questions.map((item,i)=><button className={index===i?"on":a.answers[item.id]!==undefined?"answered":""} key={item.id} onClick={()=>setIndex(i)} aria-label={`Question ${i+1}`}>{i+1}</button>)}</nav>
    {q&&<section className="settings-card question-card"><p className="small">{index+1}/{a.questions.length}</p><h2 dir="auto">{q.question}</h2><div className="pr-opts">{q.options.map((option,i)=><button key={i} className={`pr-opt${revealed&&i===q.answer?" right":revealed&&i===chosen?" wrong":i===chosen?" picked":""}`} disabled={busy||!!a.submitted_at||(a.mode==="study"&&chosen!==undefined)} onClick={()=>void run(()=>api.subjectAnswer(a.id,q.id,i))} dir="auto"><span className="option-letter">{String.fromCharCode(65+i)}</span>{option}</button>)}</div>
      {revealed&&<div className="answer-feedback" aria-live="polite"><h3>{chosen===q.answer?t("Correct","හරි"):t("Review this concept","මේ සංකල්පය නැවත බලමු")}</h3><p dir="auto">{q.explanation}</p>{q.distractors?.map((reason,i)=><p className="small" key={i}><b>{String.fromCharCode(65+i)}.</b> {reason}</p>)}<blockquote dir="auto">{q.source_quote}</blockquote><button className="act" onClick={()=>go(`/read/${docId}?seq=${q.source_seq}`)}>{t("Read source paragraph","පොතේ අදාළ කොටස බලන්න")} →</button></div>}
      <div className="actions"><button className="act" disabled={index===0} onClick={()=>setIndex((i)=>i-1)}>← {t("Previous","කලින්")}</button><button className="act" disabled={index===a.questions.length-1} onClick={()=>setIndex((i)=>i+1)}>{t("Next","ඊළඟ")} →</button></div>
    </section>}
    {!a.submitted_at&&<div className="submit-exam"><p className="small">{Object.keys(a.answers).length}/{a.questions.length} {t("answered · progress is saved automatically","පිළිතුරු දීලා · ඉබේ save වෙනවා")}</p><button className="act primary" disabled={busy} onClick={()=>void run(()=>api.submitAttempt(a.id))}>{t("Submit attempt","Attempt එක submit කරන්න")}</button></div>}
  </main>;
}
