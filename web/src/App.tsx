import { useEffect, useState } from "react";
import Library from "./Library";
import Practice from "./Practice";
import Reader from "./Reader";
import Words from "./Words";
import { applyTheme, usePrefs } from "./prefs";

type Route = { view: "read" | "library" | "words" | "practice"; id: string };

function parseHash(): Route {
  const m = location.hash.match(/^#\/read\/([\w-]+)/);
  if (m) return { view: "read", id: m[1] };
  if (location.hash.startsWith("#/words")) return { view: "words", id: "" };
  if (location.hash.startsWith("#/practice")) return { view: "practice", id: "" };
  return { view: "library", id: "" };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const prefs = usePrefs();

  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => applyTheme(prefs.theme), [prefs.theme]);

  if (route.view === "read") return <Reader key={route.id} docId={route.id} />;
  if (route.view === "words") return <Words />;
  if (route.view === "practice") return <Practice />;
  return <Library />;
}

export function go(path: string) {
  location.hash = path;
}
