import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({
  width: 22, height: 22, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, ...p,
});

export const IconBack = (p: P) => <svg {...base(p)}><path d="M15 5l-7 7 7 7" /></svg>;
export const IconToc = (p: P) => <svg {...base(p)}><path d="M5 6h14M5 12h10M5 18h12" /></svg>;
export const IconType = (p: P) => (
  <svg {...base(p)}><path d="M4 19l5-14 5 14M6 14h6" /><path d="M15.5 19c0-2 1.2-3 3-3s2.5.9 2.5 2v1M21 19c-.5-1.8-5.5-1.8-5.5 0" /></svg>
);
export const IconNote = (p: P) => <svg {...base(p)}><path d="M4 20h4l11-11-4-4L4 16v4z" /><path d="M13.5 6.5l4 4" /></svg>;
export const IconPlay = (p: P) => <svg {...base(p)}><path d="M7 5v14l12-7z" fill="currentColor" /></svg>;
export const IconPause = (p: P) => <svg {...base(p)}><path d="M8 5v14M16 5v14" strokeWidth={3} /></svg>;
export const IconPrev = (p: P) => <svg {...base(p)}><path d="M18 6l-8 6 8 6V6zM6 6v12" /></svg>;
export const IconNext = (p: P) => <svg {...base(p)}><path d="M6 6l8 6-8 6V6zM18 6v12" /></svg>;
export const IconClose = (p: P) => <svg {...base(p)}><path d="M6 6l12 12M18 6L6 18" /></svg>;
export const IconPlus = (p: P) => <svg {...base(p)}><path d="M12 5v14M5 12h14" /></svg>;
export const IconMore = (p: P) => <svg {...base(p)}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></svg>;
export const IconRetry = (p: P) => <svg {...base(p)}><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></svg>;
export const IconCopy = (p: P) => <svg {...base(p)}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a1 1 0 0 1 1-1h10" /></svg>;
export const IconSpeaker = (p: P) => <svg {...base(p)}><path d="M4 9v6h4l5 4V5L8 9H4z" /><path d="M16.5 8.5a5 5 0 0 1 0 7" /></svg>;
export const IconBook = (p: P) => <svg {...base(p)}><path d="M4 5.5C4 4.7 4.7 4 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5v-13zM20 5.5c0-.8-.7-1.5-1.5-1.5H13v16h5.5c.8 0 1.5-.7 1.5-1.5v-13z" /></svg>;
export const IconMark = (p: P) => <svg {...base(p)}><path d="M14 4l6 6-8.5 8.5H6v-5.5L14 4z" /><path d="M4 20h16" /></svg>;
