import type { Block, Doc, GlossaryTerm, Note, PracticeQ, VocabStats, Word, WordCardData } from "./types";

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
      msg = j.detail || j.error || msg;
    } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<{ llm_provider: string; model: string; gemini_key: boolean; tts_model: string; tts_voice: string }>("GET", "/api/health"),
  docs: () => req<Doc[]>("GET", "/api/documents"),
  doc: (id: string) => req<Doc>("GET", `/api/documents/${id}`),
  rename: (id: string, title: string) => req<Doc>("PATCH", `/api/documents/${id}`, { title }),
  setMode: (id: string, mode: "standard" | "batch") => req<Doc>("PATCH", `/api/documents/${id}`, { mode }),
  retranslateAll: (id: string) => req<Doc>("POST", `/api/documents/${id}/retranslate-all`, { rebuild_glossary: true }),
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
    req<Block>("POST", `/api/documents/${id}/blocks/${seq}/retranslate`, { instruction }),
  tts: (id: string, seq: number, voice: string) =>
    req<{ url?: string; skip?: boolean; cached?: boolean }>("POST", `/api/documents/${id}/blocks/${seq}/tts`, { voice }),
  voices: () => req<{ voices: string[]; default: string }>("GET", "/api/tts/voices"),
  glossary: (id: string) => req<GlossaryTerm[]>("GET", `/api/documents/${id}/glossary`),
  editTerm: (id: string, t: { term: string; rendering: string; policy: string }) =>
    req("PUT", `/api/documents/${id}/glossary`, t),
  lookup: (word: string, docId?: string, seq?: number) =>
    req<WordCardData>("POST", "/api/lookup", { word, doc_id: docId ?? null, seq: seq ?? null }),
  words: (q = "") => req<{ stats: VocabStats; words: Word[] }>("GET", `/api/words?q=${encodeURIComponent(q)}`),
  saveWord: (w: WordCardData) => req<Word>("POST", "/api/words", w),
  deleteWord: (id: number) => req("DELETE", `/api/words/${id}`),
  practice: (limit = 10) => req<{ stats: VocabStats; questions: PracticeQ[] }>("GET", `/api/practice?limit=${limit}`),
  answer: (word_id: number, kind: string, correct: boolean) => req("POST", "/api/practice/answer", { word_id, kind, correct }),
  wordAudio: (id: number, voice: string) => req<{ url: string }>("POST", `/api/words/${id}/audio`, { voice }),
  usage: () => req<{ total_usd: number; rows: { purpose: string; model: string; batch: number; calls: number; input: number; output: number; cached: number; thinking: number; cost: number }[] }>("GET", "/api/usage"),
};

export function upload(file: File, onProgress: (f: number) => void, mode: "standard" | "batch" = "standard"): Promise<Doc> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", mode);
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
