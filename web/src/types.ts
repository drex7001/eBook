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
  translated_table?: string[][];
  qa?: string[];
}

export interface Brief {
  translated_title?: string;
  doc_type?: string; domain?: string; audience?: string; tone?: string;
  summary?: string; style_notes?: string; title_si?: string;
}

export interface Doc {
  active_run?: string;
  translated_title?: string | null;
  translation_profile?: TranslationProfile;
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
  meaning_target?: string;
  meaning_source?: string;
  context_meaning?: string;
  source_language?: string;
  target_language?: string;
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
  choice_token: string;
  item_id: number | null;
  kind: "meaning" | "cloze" | "usage" | "listen" | "recall";
  question: string;
  options: string[];
  answer: number;
  explain_si: string;
  audio_text: string;
  word: Word;
}

export interface AppSettings {
  interface_language: "si" | "en"; display_mode: "original" | "translated" | "both";
  font_size: number; line_height: number; theme: "paper" | "leaf" | "night"; word_tap: boolean;
  source_language: string; target_language: string; purpose: "reading" | "language" | "study";
  translation_style: "conversational" | "formal"; keep_terms: boolean; auto_translate: boolean;
  provider: "gemini" | "ollama" | "mock"; model: string; light_model: string; tts_model: string;
  audio_mode: "off" | "device" | "cloud"; voice: string; rate: number;
  quiz_count: number; exam_count: number; exam_minutes: number;
  reading_goal: number; question_goal: number; gamification: boolean; timezone: string;
}
export interface KeyStatus { configured: boolean; masked: string; source: string; error: string | null }
export interface SettingsResponse { settings: AppSettings; key: KeyStatus; languages: Record<string, string>; voices: string[]; initialized: boolean }
export interface TranslationProfile { source_language: string; target_language: string; purpose: string; translation_style: string; keep_terms: boolean; model?: string; prompt_version?: string }
export interface TranslationRun { id: string; profile: TranslationProfile; status: string; created_at: number; error?: string }
export interface SubjectQuestion { id: string; question: string; options: string[]; answer?: number; explanation?: string; distractors?: string[]; source_seq?: number; source_quote?: string }
export interface QuizGeneration { requests:number; responses_saved:number; returned_questions:number|null; input_tokens:number; output_tokens:number; estimated_cost_usd:number; estimate_known:boolean; diagnostics:{code:string;count:number;message:string}[]; max_requests:number; can_recover:boolean; legacy_unarchived:boolean }
export interface SavedQuizResponse { id:string; batch_index:number; model:string; raw:string|null; questions:unknown[]|null; sources:{seq:number;text:string;section:number;page:number}[]; usage:{response_received:boolean;input_tokens:number|null;output_tokens:number|null}; outcome:string; diagnostics:unknown[] }
export interface QuizPaper { id: string; doc_id: string; difficulty: "easy" | "medium" | "hard"; version: number; language: string; status: string; count: number; error: string | null; questions: SubjectQuestion[]; scope: Record<string, unknown>; generation?:QuizGeneration }
export interface QuizAttempt { id: string; paper_id: string; mode: "study" | "exam"; deadline: number | null; submitted_at: number | null; started_at: number; score: number | null; answers: Record<string, number>; questions: SubjectQuestion[]; paper: QuizPaper; server_time: number }
export interface StudyDashboard { generation_contract?:string; papers: QuizPaper[]; attempts: { id: string; paper_id: string; mode: string; submitted_at: number | null; score: number | null; total: number; difficulty: string; version: number }[]; review: { id: string; paper_id: string; question: string; section: number }[]; weak_sections: { section: number; mistakes: number }[] }
export interface Progress { xp: number; level: number; streak: number; reading_minutes: number; answers: number; reading_goal: number; question_goal: number; challenge_complete: boolean; badges: string[]; enabled: boolean; history: {day: string; reading_minutes: number; answers: number; xp: number}[] }
