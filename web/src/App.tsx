import { useEffect, useState } from "react";
import Library from "./Library";
import Practice from "./Practice";
import Reader from "./Reader";
import Words from "./Words";
import { applyTheme, initializeSettings, usePrefs, useSettings } from "./prefs";
import Settings from "./Settings";
import Study from "./Study";
import ProgressPage from "./Progress";
import { Toast } from "./Sheet";

type Route = { view: "read" | "library" | "words" | "practice" | "settings" | "study" | "progress"; id: string };

function parseHash(): Route {
  const m = location.hash.match(/^#\/read\/([\w-]+)/);
  if (m) return { view: "read", id: m[1] };
  const study = location.hash.match(/^#\/study\/([\w-]+)/);
  if (study) return { view: "study", id: study[1] };
  if (location.hash.startsWith("#/settings")) return {view:"settings",id:""};
  if (location.hash.startsWith("#/progress")) return {view:"progress",id:""};
  if (location.hash.startsWith("#/words")) return { view: "words", id: "" };
  if (location.hash.startsWith("#/practice")) return { view: "practice", id: "" };
  return { view: "library", id: "" };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const prefs = usePrefs();
  const settings = useSettings();
  const [ready,setReady] = useState(false), [error,setError] = useState(""), [toast,setToast] = useState("");
  const initialize = () => {setError("");initializeSettings().then(() => setReady(true)).catch((e) => setError(e.message));};
  useEffect(() => {
    initialize();
    const refresh = () => {void initializeSettings().catch((e) => setToast(e.message));};
    const report = (e: Event) => setToast((e as CustomEvent<string>).detail);
    window.addEventListener("focus",refresh);window.addEventListener("ebook-error",report);
    return () => {window.removeEventListener("focus",refresh);window.removeEventListener("ebook-error",report);};
  },[]);

  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => applyTheme(prefs.theme), [prefs.theme]);
  useEffect(() => {document.documentElement.lang=settings.interface_language;document.title=settings.interface_language==="en"?"Reading & Study Studio":"කොළ · කියවන්න සහ ඉගෙන ගන්න";},[settings.interface_language]);

  if (!ready) return <main className="library"><h1>Reading studio</h1><p role={error ? "alert" : "status"}>{error || "Loading app settings…"}</p>{error && <button className="act" onClick={initialize}>Retry</button>}</main>;
  const page = route.view === "read" ? <Reader key={route.id} docId={route.id} /> : route.view === "words" ? <Words /> : route.view === "practice" ? <Practice /> : route.view === "settings" ? <Settings /> : route.view === "study" ? <Study key={location.hash} docId={route.id} /> : route.view === "progress" ? <ProgressPage /> : <Library />;
  return <>{page}{toast && <Toast msg={toast} onDone={() => setToast("")} />}</>;
}

export function openSettings() {go(`/settings?from=${encodeURIComponent(location.hash.slice(1) || "/")}`);}

export function go(path: string) {
  location.hash = path;
}
