import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { go } from "./App";
import { catalog, updateSettings, useSettings, useText } from "./prefs";
import type { AppSettings, KeyStatus } from "./types";

function Field({ label, children, hint }: {label: string; children: ReactNode; hint?: string}) {
  return <label className="setting-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
function Toggle({label, value, onChange}: {label: string; value: boolean; onChange: (v: boolean) => void}) {
  return <label className="setting-check"><input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />{label}</label>;
}
export default function Settings() {
  const p = useSettings(), t = useText();
  const [draft, setDraft] = useState(p);
  const [key, setKey] = useState("");
  const [keyStatus, setKeyStatus] = useState<KeyStatus>(catalog.key);
  const [models, setModels] = useState<string[]>([]);
  const [usage, setUsage] = useState<Awaited<ReturnType<typeof api.usage>> | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const change = <K extends keyof AppSettings>(k: K, value: AppSettings[K]) => setDraft((d) => ({...d, [k]: value}));
  useEffect(() => { let alive = true; Promise.all([api.usage(),api.settings()]).then(([u,s]) => {if (alive){setUsage(u);setKeyStatus(s.key);}}).catch((e) => {if (alive) setMessage(e.message);}); return () => {alive = false;}; }, []);
  const run = async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true); setMessage("");
    try {await fn(); setMessage(success);} catch (e) {setMessage((e as Error).message);} finally {setBusy(false);}
  };
  const select = <K extends keyof AppSettings>(k: K, options: [string, string][]) => <select value={String(draft[k])} onChange={(e) => change(k, e.target.value as AppSettings[K])}>{options.map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select>;
  const number = (k: "font_size" | "line_height" | "rate" | "quiz_count" | "exam_count" | "exam_minutes" | "reading_goal" | "question_goal", min: number, max: number, step = 1) => <input type="number" min={min} max={max} step={step} value={draft[k]} onChange={(e) => change(k, Number(e.target.value))} required />;
  const language = (k: "source_language" | "target_language") => <input list="language-codes" value={draft[k]} onChange={(e) => change(k, e.target.value)} aria-label={k} required />;
  const back = () => go(new URLSearchParams(location.hash.split("?")[1]).get("from") || "/");
  return <main className="settings-page">
    <header className="page-head"><button className="act" onClick={back}>← {t("Back", "ආපසු")}</button><div><p className="eyebrow">PRIVATE BETA</p><h1>{t("App settings", "App settings")}</h1><p className="small">{t("One set of preferences for every book on this local server.", "මේ settings මේ app එකේ හැම පොතකටම අදාළයි.")}</p></div></header>
    <form onSubmit={(e) => {e.preventDefault(); void run(() => updateSettings(draft), t("Settings saved. Existing translation versions are preserved.", "Settings save කළා. පරණ translation versions තියෙනවා."));}}>
      <section className="settings-card"><h2>{t("Reading", "කියවන විදිය")}</h2><div className="settings-grid">
        <Field label={t("Interface language", "Interface භාෂාව")}>{select("interface_language", [["si","සිංහල"],["en","English"]])}</Field>
        <Field label={t("Default view", "මුලින් පෙන්වන්නේ")}>{select("display_mode", [["translated",t("Translation","Translation")],["original",t("Original text","Original text")],["both",t("Both","දෙකම")]])}</Field>
        <Field label={t("Theme", "Theme")}>{select("theme", [["night",t("Night","රෑ")],["paper",t("Paper","සුදු")],["leaf",t("Leaf","පුස්කොළ")]])}</Field>
        <Field label={t("Font size", "අකුරු ප්‍රමාණය")}>{number("font_size",15,32)}</Field><Field label={t("Line spacing", "පේළි අතර ඉඩ")}>{number("line_height",1.3,2.5,0.05)}</Field>
      </div><Toggle label={t("Word taps offer a confirmation before translating", "වචනයක් tap කළාම translate කිරීමට පෙර අහන්න")} value={draft.word_tap} onChange={(v) => change("word_tap",v)} /></section>
      <section className="settings-card"><h2>{t("Languages & purpose", "භාෂා සහ කියවීමේ අරමුණ")}</h2><div className="settings-grid">
        <datalist id="language-codes"><option value="auto">Auto detect</option>{Object.entries(catalog.languages).map(([code,name]) => <option key={code} value={code}>{name}</option>)}</datalist>
        <Field label={t("Source language code", "Original භාෂාවේ code එක")} hint="auto / en / si / ta / ar …">{language("source_language")}</Field>
        <Field label={t("Translate into", "Translate කරන භාෂාව")} hint={catalog.languages[draft.target_language] || "Language code, e.g. pt-BR"}>{language("target_language")}</Field>
        <Field label={t("Reading purpose", "කියවීමේ අරමුණ")}>{select("purpose", [["reading",t("General reading","සාමාන්‍ය කියවීම")],["language",t("Language learning","භාෂාවක් ඉගෙනීම")],["study",t("Subject study","විෂයක් ඉගෙනීම")]])}</Field>
        <Field label={t("Translation style", "Translation style")}>{select("translation_style", [["conversational",t("Conversational","කතා කරන විදියට")],["formal",t("Formal","විධිමත්")]])}</Field>
      </div><Toggle label={t("Keep technical terms in the source script", "Technical terms original අකුරෙන් තබන්න")} value={draft.keep_terms} onChange={(v) => change("keep_terms",v)} />
      <Toggle label={t("Automatically translate the whole book on upload", "Upload කළාම මුළු පොතම translate කරන්න")} value={draft.auto_translate} onChange={(v) => change("auto_translate",v)} /><p className="small">{t("Language/style changes apply to new versions. Create a new version from a book's Translation versions panel.", "භාෂාව/style වෙනස් කළාම පරණ පොත් ආයෙ translate වෙන්නේ නෑ. Translation versions වලින් අලුත් version එකක් ඉල්ලන්න.")}</p></section>
      <section className="settings-card"><h2>{t("AI provider & audio", "AI provider සහ voice")}</h2><div className="settings-grid">
        <Field label="Provider">{select("provider", [["gemini","Gemini · own API key"],["ollama","Ollama · local"],["mock","Mock · offline testing"]])}</Field>
        <datalist id="available-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
        <Field label={t("Translation model", "Translation model")} hint={t("Blank uses the existing environment default.", "හිස් නම් දැනට .env එකේ model එක භාවිතා කරනවා.")}><input list="available-models" value={draft.model} onChange={(e) => change("model",e.target.value)} /></Field>
        <Field label={t("Understanding / quiz model", "Understanding / quiz model")}><input list="available-models" value={draft.light_model} onChange={(e) => change("light_model",e.target.value)} /></Field>
        <Field label={t("Voice mode", "Voice mode")}>{select("audio_mode", [["off",t("Off","Off")],["device",t("Device / browser voice","Device / browser voice")],["cloud",t("Cloud · confirm before generation","Cloud · හදන්න කලින් අහනවා")]])}</Field>
        <Field label="Cloud TTS model"><input list="available-models" value={draft.tts_model} onChange={(e) => change("tts_model",e.target.value)} /></Field>
        <Field label="Cloud voice">{select("voice", catalog.voices.map((v) => [v,v]))}</Field><Field label={t("Audio speed", "කියවන වේගය")}>{number("rate",0.5,2,0.05)}</Field>
      </div><p className="small">{t("Cloud listening asks for one paragraph or the rest of the current chapter. Audio is never generated ahead of playback.", "Cloud voice එක paragraph එකටද chapter එකටද කියලා අහනවා. ඊළඟ කොටස්වල audio කලින් හදන්නේ නෑ.")}</p></section>
      <section className="settings-card"><h2>{t("Study & challenges", "Study සහ challenges")}</h2><div className="settings-grid">
        <Field label={t("Chapter quiz questions", "Chapter quiz ප්‍රශ්න")}>{number("quiz_count",1,40)}</Field><Field label={t("Exam questions", "Exam ප්‍රශ්න")}>{number("exam_count",1,60)}</Field>
        <Field label={t("Exam minutes", "Exam විනාඩි")}>{number("exam_minutes",1,180)}</Field><Field label={t("Daily reading minutes", "දිනකට කියවන විනාඩි")}>{number("reading_goal",1,120)}</Field>
        <Field label={t("Daily answers", "දිනකට පිළිතුරු")}>{number("question_goal",1,100)}</Field><Field label={t("Timezone", "Timezone")}><input value={draft.timezone} onChange={(e) => change("timezone",e.target.value)} required /></Field>
      </div><Toggle label={t("XP, levels, streaks & daily challenges", "XP, levels, streaks සහ daily challenges")} value={draft.gamification} onChange={(v) => change("gamification",v)} /></section>
      <div className="save-settings"><button type="submit" className="act primary" disabled={busy}>{busy ? t("Saving…","Save කරනවා…") : t("Save app settings","App settings save කරන්න")}</button><span role="status">{message}</span></div>
    </form>
    <section className="settings-card"><h2>{t("Gemini API key", "Gemini API key")}</h2><p className="small">{keyStatus.configured ? `${t("Configured","සකස් කරලා තියෙනවා")} · ${keyStatus.masked} · ${keyStatus.source}` : t("No active key", "API key එකක් නෑ")}{keyStatus.error && ` · ${keyStatus.error}`}</p>
      <p className="small">{t("Keys are stored using Windows account encryption. Manage keys from localhost. Removing a saved key also disables the environment fallback until you save another key.", "Key එක Windows account එකෙන් encrypt කරලා තබනවා. Key එක සකස් කරන්න localhost භාවිතා කරන්න. Remove කළාම .env fallback එකත් නැවත key එකක් දාන තුරු Off වෙනවා.")}</p>
      <label className="setting-field"><span>{t("New API key", "අලුත් API key එක")}</span><input type="password" autoComplete="new-password" value={key} onChange={(e) => setKey(e.target.value)} /></label>
      <div className="actions"><button className="act" disabled={busy || !key.trim()} onClick={() => void run(async () => {setKeyStatus(await api.saveKey(key));setKey("");},t("Key saved securely","Key එක save කළා"))}>{t("Save key","Key save කරන්න")}</button>
      <button className="act" disabled={busy || !keyStatus.configured} onClick={() => void run(async () => {setModels((await api.testKey()).models);},t("Connection verified. No content generated.","Connection හරි. Content generate කළේ නෑ."))}>{t("Test connection","Connection බලන්න")}</button>
      <button className="act" disabled={busy || !keyStatus.configured} onClick={() => void run(async () => setKeyStatus(await api.removeKey()),t("Key disabled","Key Off කළා"))}>{t("Remove key","Key අයින් කරන්න")}</button></div>
    </section>
    <section className="settings-card"><h2>{t("Usage & estimated cost", "Usage සහ ඇස්තමේන්තු වියදම")}</h2>{usage && <><p>≈ ${usage.total_usd.toFixed(4)} · {t("Pricing date","මිල දිනය")}: {usage.pricing_date}</p>{usage.unknown_estimates && <p className="small">{t("Some model costs are unavailable; they are excluded from this total.","සමහර models වල වියදම දන්නේ නෑ; ඒවා total එකට ඇතුළත් නෑ.")}</p>}<div className="tablewrap"><table><thead><tr><th>Action / model</th><th>Calls</th><th>Input / output</th><th>Audio</th><th>Estimate</th></tr></thead><tbody>{usage.rows.map((r) => <tr key={`${r.purpose}-${r.model}-${r.batch}`}><td>{r.purpose}<br/><small>{r.model}</small></td><td>{r.calls}</td><td>{r.input} / {r.output}</td><td>{r.audio_seconds.toFixed(1)}s</td><td>{r.estimate_known ? `≈ $${r.cost.toFixed(4)}` : "Estimate unavailable"}</td></tr>)}</tbody></table></div></>}</section>
  </main>;
}
