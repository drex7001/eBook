import { useEffect, useState } from "react";
import { api } from "./api";
import type { AppSettings, SettingsResponse } from "./types";

export type Theme = "paper" | "leaf" | "night";
export const DEFAULTS: AppSettings = {
  interface_language: "si", display_mode: "translated", font_size: 19, line_height: 1.8, theme: "night", word_tap: true,
  source_language: "auto", target_language: "si", purpose: "reading", translation_style: "conversational", keep_terms: true,
  auto_translate: true, provider: "gemini", model: "", light_model: "", tts_model: "", audio_mode: "off", voice: "Kore", rate: 1,
  quiz_count: 10, exam_count: 20, exam_minutes: 30, reading_goal: 10, question_goal: 5, gamification: true, timezone: "Asia/Colombo",
};
let current = DEFAULTS;
export const getCurrentSettings = () => current;
const listeners = new Set<(p: AppSettings) => void>();
export let catalog: Pick<SettingsResponse, "languages" | "voices" | "key"> = { languages: {}, voices: [], key: {configured: false, masked: "", source: "", error: null} };
function publish(p: AppSettings) { current = p; listeners.forEach((l) => l(p)); }
export async function initializeSettings() {
  const result = await api.settings();
  catalog = result;
  let settings = result.settings;
  if (!result.initialized) {
    let patch: Partial<AppSettings> = {};
    try {
      const old = JSON.parse(localStorage.getItem("ebook.prefs.v2") || localStorage.getItem("ebook.prefs.v1") || "null");
      if (old) patch = { font_size: old.fontSize, line_height: old.lineHeight, theme: old.theme,
        display_mode: old.bilingual ? "both" : "translated", word_tap: old.wordTap, rate: old.rate, voice: old.voice || "Kore" };
    } catch { /* unusable legacy settings use safe defaults */ }
    settings = await api.saveSettings({...patch, audio_mode: "off"});
  }
  publish(settings);
}
export async function updateSettings(patch: Partial<AppSettings>) { const p = await api.saveSettings(patch); publish(p); return p; }
export function useSettings(): AppSettings {
  const [p, setP] = useState(current);
  useEffect(() => { listeners.add(setP); return () => { listeners.delete(setP); }; }, []);
  return p;
}
export interface Prefs { fontSize: number; lineHeight: number; theme: Theme; bilingual: boolean; voice: string; rate: number; wordTap: boolean; displayMode: AppSettings["display_mode"]; audioMode: AppSettings["audio_mode"] }
export function usePrefs(): Prefs {
  const p = useSettings();
  return {fontSize: p.font_size, lineHeight: p.line_height, theme: p.theme, bilingual: p.display_mode === "both", voice: p.voice,
    rate: p.rate, wordTap: p.word_tap, displayMode: p.display_mode, audioMode: p.audio_mode};
}
export function setPrefs(patch: Partial<Prefs>) {
  const map: Record<string, keyof AppSettings> = {fontSize: "font_size", lineHeight: "line_height", theme: "theme", voice: "voice", rate: "rate", wordTap: "word_tap", displayMode: "display_mode", audioMode: "audio_mode"};
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(patch)) { if (key === "bilingual") out.display_mode = value ? "both" : "translated"; else if (map[key]) out[map[key]] = value; }
  void updateSettings(out).catch((e) => window.dispatchEvent(new CustomEvent("ebook-error", {detail: e.message})));
}
export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "night" ? "#121615" : t === "leaf" ? "#e3dcbd" : "#f6f6f1");
}
export function useText() {
  const p = useSettings();
  return (en: string, si: string) => p.interface_language === "si" ? si : en;
}
