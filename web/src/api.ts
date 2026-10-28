import type { AppSettings, SettingsResponse, KeyStatus, TranslationRun, QuizPaper, QuizAttempt, StudyDashboard, SavedQuizResponse, Progress, Block, Doc, GlossaryTerm, Note, PracticeQ, VocabStats, Word, WordCardData } from "./types";

export const actionKey = () => typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      const detail = j.detail || j.error;
      msg = typeof detail === "string" ? detail : detail?.message ? `${detail.message} Suggested: ${detail.suggested_count}` : JSON.stringify(detail || msg);
    } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  settings: () => req<SettingsResponse>("GET", "/api/settings"),
  saveSettings: (patch: Partial<AppSettings>) => req<AppSettings>("PATCH", "/api/settings", patch),
  saveKey: (key: string) => req<KeyStatus>("PUT", "/api/providers/gemini/key", { key }),
  removeKey: () => req<KeyStatus>("DELETE", "/api/providers/gemini/key"),
  testKey: () => req<{ok: boolean; models: string[]}>("POST", "/api/providers/gemini/test"),
  translations: (id: string) => req<{active_run: string; runs: TranslationRun[]; current_profile: TranslationRun["profile"]}>("GET", `/api/documents/${id}/translations`),
  newTranslation: (id: string, key: string) => req<{run_id: string}>("POST", `/api/documents/${id}/translations`, {confirmed: true, request_key: key}),
  activateTranslation: (id: string, run: string) => req("POST", `/api/documents/${id}/translations/${run}/activate`),
  authorizeAudio: (doc_id: string, seq: number, scope: "paragraph" | "chapter", side: string, voice: string) => req<{grant_id: string; end_seq: number}>("POST", "/api/audio/authorize", {confirmed: true, doc_id, seq, scope, side, voice}),
  revokeAudio: (id: string) => req("DELETE", `/api/audio/authorizations/${id}`),
  study: (id: string) => req<StudyDashboard>("GET", `/api/documents/${id}/study`),
  paper: (id: string) => req<QuizPaper>("GET", `/api/papers/${id}`),
  recheckPaper: (id: string) => req<QuizPaper>("POST", `/api/papers/${id}/recheck`),
  stopPaper: (id: string) => req<QuizPaper>("POST", `/api/papers/${id}/stop`),
  paperResponses: (id: string) => req<{responses:SavedQuizResponse[]}>("GET", `/api/papers/${id}/responses`),
  generatePaper: (id: string, body: {difficulty: string; count: number; sections?: number[]; sequences?: number[]; start_seq?: number; end_seq?: number; request_key: string}) => req<QuizPaper>("POST", `/api/documents/${id}/papers`, {...body, confirmed: true}),
  startAttempt: (id: string, mode: string, minutes: number, key: string) => req<QuizAttempt>("POST", `/api/papers/${id}/attempts`, {mode, minutes, request_key: key}),
  attempt: (id: string) => req<QuizAttempt>("GET", `/api/attempts/${id}`),
  subjectAnswer: (id: string, question_id: string, choice: number) => req<QuizAttempt>("POST", `/api/attempts/${id}/answers`, {question_id, choice}),
  submitAttempt: (id: string) => req<QuizAttempt>("POST", `/api/attempts/${id}/submit`),
  progress: () => req<Progress>("GET", "/api/progress"),
  reading: (doc_id: string, seq: number) => req("POST", "/api/progress/reading", {doc_id, seq, event_id: actionKey()}),
  health: () => req<{ llm_provider: string; model: string; gemini_key: boolean; tts_model: string; tts_voice: string }>("GET", "/api/health"),
  docs: () => req<Doc[]>("GET", "/api/documents"),
  doc: (id: string) => req<Doc>("GET", `/api/documents/${id}`),
  rename: (id: string, title: string) => req<Doc>("PATCH", `/api/documents/${id}`, { title }),
  setMode: (id: string, mode: "standard" | "batch") => req<Doc>("PATCH", `/api/documents/${id}`, { mode }),
  retranslateAll: (id: string) => req<Doc>("POST", `/api/documents/${id}/retranslate-all`, { rebuild_glossary: true, confirmed: true, request_key: actionKey() }),
  remove: (id: string) => req<{ ok: boolean }>("DELETE", `/api/documents/${id}`),
  pause: (id: string) => req<Doc>("POST", `/api/documents/${id}/pause`),
  resume: (id: string) => req<Doc>("POST", `/api/documents/${id}/resume`),
  retryFailed: (id: string) => req<Doc>("POST", `/api/documents/${id}/retry-failed`),
  blocks: (id: string, since = 0) => req<{ rev: number; blocks: Block[] }>("GET", `/api/documents/${id}/blocks?since=${since}`),
  setPosition: (id: string, seq: number) => req("PUT", `/api/documents/${id}/position`, { seq }),
  notes: (id: string) => req<Note[]>("GET", `/api/documents/${id}/notes`),
  addNote: (id: string, n: Partial<Note>) => req<Note>("POST", `/api/documents/${id}/notes`, n),
  editNote: (id: string, noteId: number, n: Partial<Note>) => req<Note>("PATCH", `/api/documents/${id}/notes/${noteId}`, n),
  deleteNote: (id: string, noteId: number) => req("DELETE", `/api/documents/${id}/notes/${noteId}`),
  retranslate: (id: string, seq: number, instruction: string) =>
    req<Block>("POST", `/api/documents/${id}/blocks/${seq}/retranslate`, { instruction, confirmed: true, request_key: actionKey() }),
  tts: (id: string, seq: number, voice: string, grant_id: string, side: string, key: string) =>
    req<{ url?: string; skip?: boolean; cached?: boolean }>("POST", `/api/documents/${id}/blocks/${seq}/tts`, { voice, grant_id, side, request_key: key }),
  voices: () => req<{ voices: string[]; default: string }>("GET", "/api/tts/voices"),
  glossary: (id: string) => req<GlossaryTerm[]>("GET", `/api/documents/${id}/glossary`),
  editTerm: (id: string, t: { term: string; rendering: string; policy: string }) =>
    req("PUT", `/api/documents/${id}/glossary`, t),
  lookup: (word: string, docId?: string, seq?: number) =>
    req<WordCardData>("POST", "/api/lookup", { word, doc_id: docId ?? null, seq: seq ?? null, confirmed: true, request_key: actionKey() }),
  words: (q = "") => req<{ stats: VocabStats; words: Word[] }>("GET", `/api/words?q=${encodeURIComponent(q)}`),
  saveWord: (w: WordCardData) => req<Word>("POST", "/api/words", w),
  deleteWord: (id: number) => req("DELETE", `/api/words/${id}`),
  practice: (limit = 10) => req<{ stats: VocabStats; questions: PracticeQ[] }>("GET", `/api/practice?limit=${limit}`),
  answer: (word_id: number, kind: string, choice_token: string, choice?: number, correct?: boolean) => req<{answer: number; correct: boolean; explanation: string}>("POST", "/api/practice/answer", { word_id, kind, choice_token, choice, correct }),
  wordAudio: (id: number, voice: string) => req<{ url: string }>("POST", `/api/words/${id}/audio`, { voice, confirmed: true, request_key: actionKey() }),
  generatePractice: () => req("POST", "/api/practice/generate", {confirmed: true, request_key: actionKey()}),
  usage: () => req<{ total_usd: number; pricing_date: string; unknown_estimates: boolean; rows: { purpose: string; model: string; batch: number; calls: number; input: number; output: number; cached: number; thinking: number; cost: number; audio_seconds: number; estimate_known: number }[] }>("GET", "/api/usage"),
};

export function upload(file: File, onProgress: (f: number) => void, mode: "standard" | "batch" = "standard"): Promise<Doc> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", mode);
    fd.append("translation_confirmed", "true");
    fd.append("request_key", actionKey());
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        let msg = `Upload failed (${xhr.status})`;
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* ignore */ }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error("Server එකට connect වෙන්න බැරි වුණා."));
    xhr.open("POST", "/api/documents");
    xhr.send(fd);
  });
}

export const assetUrl = (docId: string, name: string) => `/api/documents/${docId}/assets/${encodeURIComponent(name)}`;
export const pageUrl = (docId: string, page: number, zoom = 2) => `/api/documents/${docId}/pages/${page}.png?zoom=${zoom}`;
