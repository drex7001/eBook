import type { Doc } from "./types";
import { getCurrentSettings } from "./prefs";

export function pct(n: number, d: number) {
  return d > 0 ? Math.round((100 * n) / d) : 0;
}

/** One short line describing where the pipeline is, in the app's code-mixed voice. */
export function jobLine(d: Doc): string {
  if(getCurrentSettings().interface_language==="en"){
    if(d.status==="error")return "Translation interrupted";
    if(d.status==="paused")return `Paused · ${pct(d.translated,d.translatable)}% translated`;
    if(d.status==="queued")return "Queued";
    if(d.status==="waiting")return `Waiting for batch · ${d.stage}`;
    if(d.status==="done")return d.failed?`Complete · ${d.failed} passages need attention`:"Translation complete";
    if(d.stage==="parse")return `Reading PDF ${d.stage_done}/${d.stage_total||d.page_count}`;
    if(d.stage==="understand")return `Understanding ${d.stage_done}/${d.stage_total}`;
    return `Translating ${pct(d.translated,d.translatable)}%`;
  }
  if (d.status === "error") return "Error එකක් ආවා";
  if (d.status === "paused") return `Pause කරලා, ${pct(d.translated, d.translatable)}%ක් translate වෙලා`;
  if (d.status === "queued") return "පෝලිමේ ඉන්නවා";
  if (d.status === "waiting") return `Batch job එක Google පැත්තේ run වෙනවා (${d.stage === "understand" ? "පොත තේරුම් ගන්නවා" : "translate කරනවා"})`;
  if (d.status === "done") {
    return d.failed ? `ඉවරයි, blocks ${d.failed}ක් translate වුණේ නෑ` : "සම්පූර්ණයෙන් translate වෙලා";
  }
  if (d.stage === "parse") return `පිටු කියවනවා ${d.stage_done}/${d.stage_total || d.page_count}`;
  if (d.stage === "understand") return `පොත තේරුම් ගන්නවා ${d.stage_done}/${d.stage_total}`;
  return `Translate කරනවා ${pct(d.translated, d.translatable)}%`;
}

export function jobFraction(d: Doc): number {
  if (d.stage === "translate" || d.stage === "done") return d.translatable ? (d.translated + d.failed) / d.translatable : 0;
  return d.stage_total ? d.stage_done / d.stage_total : 0;
}

export const isActive = (d: Doc) => d.status === "running" || d.status === "queued" || d.status === "waiting";
