import { getCurrentSettings } from "./prefs";

export function languageFor(text:string,code:string){
  if(code&&code!=="auto")return code;
  for(const [lang,rx] of [["si",/[\u0d80-\u0dff]/],["ta",/[\u0b80-\u0bff]/],["ar",/[\u0600-\u06ff]/],["hi",/[\u0900-\u097f]/],["ja",/[\u3040-\u30ff]/],["zh",/[\u4e00-\u9fff]/]] as const)if(rx.test(text))return lang;
  return "en";
}
export function canSpeak(){return "speechSynthesis" in window&&getCurrentSettings().audio_mode!=="off";}
let finish:(()=>void)|null=null;
export function cancelSpeech(){if("speechSynthesis" in window)speechSynthesis.cancel();finish?.();finish=null;}
export function speak(text:string,rate=0.9,language="auto"):Promise<void>{
  if(!canSpeak())return Promise.resolve();
  const lang=languageFor(text,language);
  const voices=speechSynthesis.getVoices();
  const voice=voices.find((v)=>v.lang.toLowerCase()===lang.toLowerCase())||voices.find((v)=>v.lang.split("-")[0]===lang.split("-")[0]);
  if(!voice)return Promise.reject(new Error(`No device voice for ${lang}. Choose an installed device voice or explicitly enable cloud voice in settings.`));
  cancelSpeech();
  return new Promise((resolve,reject)=>{
    const utterance=new SpeechSynthesisUtterance(text);utterance.lang=voice.lang;utterance.voice=voice;utterance.rate=rate;finish=resolve;
    utterance.onend=()=>{if(finish===resolve)finish=null;resolve();};utterance.onerror=(e)=>{if(finish===resolve)finish=null;if(e.error==="canceled"||e.error==="interrupted")resolve();else reject(new Error(`Device voice: ${e.error}`));};
    speechSynthesis.speak(utterance);
  });
}
