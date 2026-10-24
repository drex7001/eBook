export type BlockType =
  | "heading" | "paragraph" | "list_item" | "caption" | "footnote"
  | "figure" | "table" | "equation" | "reference";

export interface Region { page: number; x0: number; y0: number; x1: number; y1: number }

export interface Block {
  seq: number;
  type: BlockType;
  level: number;
  page: number;
  regions: Region[];
  image: string | null;
  source: string;
  translated: string | null;
  status: "pending" | "done" | "failed" | "skip";
  rev: number;
  table_mode: "html" | "image" | null;
  table?: string[][];
  table_si?: string[][];
  qa?: string[];
}

export interface Brief {
  doc_type?: string; domain?: string; audience?: string; tone?: string;
  summary?: string; style_notes?: string; title_si?: string;
}

export interface Doc {
  id: string;
  title: string;
  title_si: string | null;
  filename: string;
  page_count: number;
  status: "queued" | "running" | "paused" | "done" | "error" | "waiting";
  stage: "parse" | "understand" | "translate" | "done";
  stage_done: number;
  stage_total: number;
  error: string | null;
  translatable: number;
  translated: number;
  failed: number;
  prompt_tokens: number;
  output_tokens: number;
  llm_calls: number;
  provider: string;
  model: string;
  blocks: number;
  position: number | null;
  page_sizes: [number, number][];
  brief: Brief | null;
  cached_tokens: number;
  thought_tokens: number;
  cost_usd: number;
  mode: "standard" | "batch";
  batch: Record<string, { state?: string; requests?: number; submitted_at?: number; last_state?: string; note?: string; ingested?: number }>;
  sections?: { idx: number; title: string; start_seq: number; end_seq: number }[];
}

export interface Note {
  id: number;
  doc_id: string;
  seq: number;
  color: string | null;
  quote: string | null;
  body: string | null;
  created_at: number;
}

export interface GlossaryTerm {
  term: string; rendering: string; policy: "keep_en" | "translate" | "transliterate";
  kind: string; count: number; locked: number;
}

export interface Example { en: string; si: string }

export interface WordCardData {
  word: string;
  lemma: string;
  pos?: string;
  ipa?: string;
  meaning_en?: string;
  meaning_si?: string;
  in_context_si?: string;
  examples?: Example[];
  synonyms?: string[];
  level?: string;
  context?: string;
  doc_id?: string | null;
  seq?: number | null;
  saved_id?: number | null;
}

export interface Word extends WordCardData {
  id: number;
  created_at: number;
  due_at: number;
  interval_days: number;
  reps: number;
  lapses: number;
}

export interface VocabStats { total: number; due: number; known: number; streak: number; reviewed_today: number }

export interface PracticeQ {
  item_id: number | null;
  kind: "meaning" | "cloze" | "usage" | "listen" | "recall";
  question: string;
  options: string[];
  answer: number;
  explain_si: string;
  audio_text: string;
  word: Word;
}
