import { useCallback, useEffect, useRef, useState } from "react";
import { actionKey, api } from "./api";
import { useSettings } from "./prefs";
import { cancelSpeech, languageFor, speak } from "./speech";
import type { Block, TranslationProfile } from "./types";

export function isSpeakable(b: Block) {return !["figure","equation","table","reference"].includes(b.type)&&!!(b.translated||b.source||"").trim();}
type Session={end:number;start:number;side:"original"|"translated";grant:string;keys:Map<number,string>};
export function useAudio(docId:string,blocks:Block[],voice:string,rate:number,_title:string,onError:(s:string)=>void,profile?:TranslationProfile) {
  const p=useSettings();
  const prefs=useRef(p);prefs.current=p;
  const languages=useRef(profile);languages.current=profile;
  const rows=useRef(blocks);rows.current=blocks;
  const player=useRef<HTMLAudioElement|null>(null),session=useRef<Session|null>(null),token=useRef(0),current=useRef<number|null>(null);
  const playRef=useRef<(n:number)=>Promise<void>>(async()=>{});
  const [seq,setSeq]=useState<number|null>(null),[state,setState]=useState<"idle"|"loading"|"playing"|"paused">("idle");
  const stop=useCallback(()=>{
    token.current++;player.current?.pause();cancelSpeech();
    const old=session.current;session.current=null;
    if(old?.grant)void api.revokeAudio(old.grant).catch(()=>{});
    current.current=null;setSeq(null);setState("idle");
  },[]);
  const next=useCallback((from:number,dir=1)=>{
    const s=session.current;if(!s)return null;
    for(let i=from+dir;i>=s.start&&i<=s.end&&i<rows.current.length;i+=dir)if(isSpeakable(rows.current[i]))return i;
    return null;
  },[]);
  const play=useCallback(async(n:number)=>{
    const s=session.current,b=rows.current[n];
    if(!s||!b||n<s.start||n>s.end||prefs.current.audio_mode==="off"){stop();return;}
    const my=++token.current;current.current=n;setSeq(n);setState("loading");
    const text=s.side==="original"?b.source:b.translated||b.source;
    try{
      if(prefs.current.audio_mode==="device"){
        setState("playing");
        const lang=languageFor(text,s.side==="original"?languages.current?.source_language||prefs.current.source_language:languages.current?.target_language||prefs.current.target_language);
        await speak(text,prefs.current.rate,lang);
      }else{
        if(!s.keys.has(n))s.keys.set(n,actionKey());
        const r=await api.tts(docId,n,voice,s.grant,s.side,s.keys.get(n)!);
        if(my!==token.current)return;
        if(!r.url){const following=next(n);if(following!==null)await playRef.current(following);else stop();return;}
        const a=player.current||(player.current=new Audio());a.pause();a.src=r.url;a.playbackRate=prefs.current.rate;
        await a.play();if(my!==token.current){a.pause();return;}setState("playing");
        a.onended=()=>{if(my!==token.current)return;const following=next(n);if(following!==null)void playRef.current(following);else stop();};
        return;
      }
      if(my!==token.current)return;
      const following=next(n);if(following!==null)await playRef.current(following);else stop();
    }catch(e){if(my!==token.current)return;stop();onError((e as Error).message);}
  },[docId,voice,next,stop,onError]);
  playRef.current=play;
  const playAt=useCallback(async(n:number,scope:"paragraph"|"chapter"="paragraph",side:"original"|"translated"=prefs.current.display_mode==="original"?"original":"translated")=>{
    stop();if(prefs.current.audio_mode==="off"){onError("Voice is Off. Enable it in App settings.");return;}
    let end=n,grant="";const my=token.current;
    try{
      if(prefs.current.audio_mode==="cloud"){
        const result=await api.authorizeAudio(docId,n,scope,side,voice);
        if(my!==token.current){void api.revokeAudio(result.grant_id);return;}
        end=result.end_seq;grant=result.grant_id;
      }else if(scope==="chapter"){
        for(let i=n+1;i<rows.current.length;i++){if(rows.current[i].type==="heading"&&rows.current[i].level<=2)break;end=i;}
      }
      session.current={start:n,end,side,grant,keys:new Map()};await play(n);
    }catch(e){onError((e as Error).message);}
  },[docId,voice,play,stop,onError]);
  const toggle=useCallback(()=>{
    if(prefs.current.audio_mode==="device"){
      if(state==="playing"){speechSynthesis.pause();setState("paused");}else if(state==="paused"){speechSynthesis.resume();setState("playing");}
    }else if(player.current){
      if(state==="playing"){player.current.pause();setState("paused");}else if(state==="paused"){void player.current.play().then(()=>setState("playing")).catch((e)=>onError(e.message));}
    }
  },[state,onError]);
  const skip=useCallback((dir:1|-1)=>{if(current.current!==null){const n=next(current.current,dir);if(n!==null)void play(n);else onError("The next paragraph is outside the authorized listening scope.");}},[next,play,onError]);
  useEffect(()=>{if(player.current)player.current.playbackRate=rate;},[rate]);
  useEffect(()=>{stop();},[p.audio_mode,p.voice,p.tts_model,p.display_mode,p.target_language,stop]);
  useEffect(()=>()=>stop(),[stop]);
  return {seq,state,playAt,toggle,skip,stop,side:session.current?.side};
}
