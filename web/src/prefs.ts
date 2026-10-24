import { useEffect, useState } from "react";

export type Theme = "paper" | "leaf" | "night";

export interface Prefs {
  fontSize: number;
  lineHeight: number;
  theme: Theme;
  bilingual: boolean;
  voice: string;
  rate: number;
  wordTap: boolean;
}

const DEFAULTS: Prefs = { fontSize: 19, lineHeight: 1.8, theme: "night", bilingual: false, voice: "", rate: 1, wordTap: true };
const KEY = "ebook.prefs.v2";

function load(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
    // v1 had a light default theme: keep the other settings, start on the dark theme
    const old = localStorage.getItem("ebook.prefs.v1");
    if (old) {
      const { theme: _ignored, ...rest } = JSON.parse(old);
      return { ...DEFAULTS, ...rest };
    }
  } catch { /* storage unavailable */ }
  return DEFAULTS;
}

let current = load();
const listeners = new Set<(p: Prefs) => void>();

export function setPrefs(patch: Partial<Prefs>) {
  current = { ...current, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(current)); } catch { /* ignore */ }
  listeners.forEach((l) => l(current));
}

export function usePrefs(): Prefs {
  const [p, setP] = useState(current);
  useEffect(() => {
    listeners.add(setP);
    return () => { listeners.delete(setP); };
  }, []);
  return p;
}

export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  const meta = document.querySelector('meta[name="theme-color"]');
  const color = t === "night" ? "#121615" : t === "leaf" ? "#e3dcbd" : "#f6f6f1";
  meta?.setAttribute("content", color);
}
