import { useEffect, useRef, useState } from "react";
import { actionKey, api } from "./api";
import { catalog, useSettings, useText } from "./prefs";
import Sheet from "./Sheet";
import { CostLine, Glossary } from "./Panels";
import type { Doc, TranslationRun } from "./types";

export function TranslationVersions({doc,onClose,onChanged,onToast}: {doc:Doc;onClose:()=>void;onChanged:()=>void;onToast:(m:string)=>void}) {
  const p=useSettings(),t=useText();
  const [runs,setRuns]=useState<TranslationRun[]>([]),[busy,setBusy]=useState(false);
  const [glossary,setGlossary]=useState(false);
  const key=useRef(actionKey());
  useEffect(()=>{api.translations(doc.id).then((r)=>setRuns(r.runs)).catch((e)=>onToast(e.message));},[doc.id,onToast]);
  const active=["queued","running","waiting"].includes(doc.status);
  const create=async()=>{setBusy(true);try{await api.newTranslation(doc.id,key.current);onChanged();}catch(e){key.current=actionKey();onToast((e as Error).message);}finally{setBusy(false);}};
  const activate=async(id:string)=>{setBusy(true);try{await api.activateTranslation(doc.id,id);onChanged();}catch(e){onToast((e as Error).message);}finally{setBusy(false);}};
  return <Sheet label="Translation versions" onClose={onClose}><h3>{t("Translation versions","Translation versions")}</h3><p className="small">{t("Original text, notes and your reading position are shared across all versions.","Original text, notes සහ කියවන තැන හැම version එකකටම පොදුයි.")}</p>
    <section className="version-create"><p className="eyebrow">{t("CURRENT APP PROFILE","දැනට APP SETTINGS")}</p><p>{catalog.languages[p.target_language]||p.target_language} · {p.translation_style} · {p.purpose}</p><p className="small">{t("Create a new whole-book translation using these settings. This uses your AI provider and keeps every saved version.","මේ settings වලින් මුළු පොතේ අලුත් translation එකක් හදන්න. AI භාවිතා වෙනවා; save කරපු versions තියෙනවා.")}</p><button className="act primary" disabled={busy||active} onClick={()=>void create()}>{t("Create new version · AI","අලුත් version එකක් හදන්න · AI")}</button>{active&&<p className="small">{t("Pause the translation and wait until it stops before switching versions.","Versions මාරු කරන්න මුලින් translation එක pause කරලා නවතින තුරු ඉන්න.")}</p>}</section>
    {runs.map((r)=><article key={r.id} className="paper-row"><div><b>{catalog.languages[r.profile.target_language]||r.profile.target_language}</b><p className="small">{r.profile.translation_style} · {r.profile.purpose}<br/>{new Date(r.created_at*1000).toLocaleString()}</p></div>{r.id===doc.active_run?<span className="chip">{t("Active","දැනට")}</span>:<button className="act" disabled={busy||active} onClick={()=>void activate(r.id)}>{t("Read version","මේ version එක")}</button>}</article>)}<CostLine doc={doc}/>
    <button className="act" onClick={()=>setGlossary((v)=>!v)}>{t("Version glossary","මේ version එකේ glossary")}</button>{glossary&&<Glossary docId={doc.id} onToast={onToast}/>}
  </Sheet>;
}
