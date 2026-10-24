import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Block } from "./types";

const SPEAKABLE = new Set(["heading", "paragraph", "list_item", "caption", "footnote"]);
export const isSpeakable = (b: Block) => SPEAKABLE.has(b.type) && !!(b.translated || b.source || "").trim();

export type AudioState = "idle" | "loading" | "playing" | "paused";

/** Paragraph-by-paragraph player: asks the server for one block's audio at a time, prefetches the next two. */
export function useAudio(docId: string, blocks: Block[], voice: string, rate: number, title: string,
  onError: (msg: string) => void) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blocksRef = useRef(blocks);
  blocksRef.current = blocks;
  const [seq, setSeq] = useState<number | null>(null);
  const seqRef = useRef<number | null>(null);
  const [state, setState] = useState<AudioState>("idle");
  const cache = useRef(new Map<string, Promise<string | null>>());
  const token = useRef(0);

  if (!audioRef.current && typeof Audio !== "undefined") audioRef.current = new Audio();

  const next = useCallback((from: number, dir = 1): number | null => {
    const bs = blocksRef.current;
    for (let i = from + dir; i >= 0 && i < bs.length; i += dir) if (isSpeakable(bs[i])) return i;
    return null;
  }, []);

  const urlFor = useCallback((s: number) => {
    const b = blocksRef.current[s];
    const key = `${s}|${voice}|${b?.rev ?? 0}`;
    let p = cache.current.get(key);
    if (!p) {
      p = api.tts(docId, s, voice).then((r) => r.url ?? null);
      p.catch(() => cache.current.delete(key));
      cache.current.set(key, p);
    }
    return p;
  }, [docId, voice]);

  const stop = useCallback(() => {
    token.current++;
    audioRef.current?.pause();
    setSeq(null);
    seqRef.current = null;
    setState("idle");
  }, []);

  const playAt = useCallback(async (s: number) => {
    const my = ++token.current;
    const a = audioRef.current!;
    a.pause();
    setSeq(s);
    seqRef.current = s;
    setState("loading");
    try {
      const url = await urlFor(s);
      if (my !== token.current) return;
      if (!url) {
        const n = next(s);
        if (n != null) playAt(n); else stop();
        return;
      }
      a.src = url;
      a.playbackRate = rate;
      await a.play();
      if (my !== token.current) return;
      setState("playing");
      let n: number | null = s;
      for (let k = 0; k < 2; k++) {
        n = n == null ? null : next(n);
        if (n == null) break;
        urlFor(n).catch(() => {});
      }
    } catch (e) {
      if (my !== token.current) return;
      setState("paused");
      onError((e as Error).message || "Audio එක හදන්න බැරි වුණා");
    }
  }, [urlFor, next, rate, stop, onError]);

  const toggle = useCallback(() => {
    const a = audioRef.current!;
    if (state === "playing") { a.pause(); setState("paused"); }
    else if (state === "paused" && seqRef.current != null) {
      if (a.src && !a.ended) a.play().then(() => setState("playing")).catch(() => playAt(seqRef.current!));
      else playAt(seqRef.current);
    }
  }, [state, playAt]);

  const skip = useCallback((dir: 1 | -1) => {
    if (seqRef.current == null) return;
    const n = next(seqRef.current, dir);
    if (n != null) playAt(n);
  }, [next, playAt]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    a.onended = () => {
      const s = seqRef.current;
      const n = s == null ? null : next(s);
      if (n != null) playAt(n); else stop();
    };
  }, [next, playAt, stop]);

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = rate; }, [rate]);
  useEffect(() => () => { audioRef.current?.pause(); }, []);

  // lock-screen / headset controls
  useEffect(() => {
    if (!("mediaSession" in navigator) || seq == null) return;
    const ms = navigator.mediaSession;
    ms.metadata = new MediaMetadata({ title: (blocksRef.current[seq]?.translated || "").slice(0, 60), artist: title });
    ms.setActionHandler("play", toggle);
    ms.setActionHandler("pause", toggle);
    ms.setActionHandler("nexttrack", () => skip(1));
    ms.setActionHandler("previoustrack", () => skip(-1));
  }, [seq, title, toggle, skip]);

  return { seq, state, playAt, toggle, skip, stop };
}
