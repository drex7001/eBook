/** English pronunciation through the browser's own voices: free and instant. Returns false if unavailable. */
let voice: SpeechSynthesisVoice | null = null;

function pickVoice(): SpeechSynthesisVoice | null {
  if (!("speechSynthesis" in window)) return null;
  const vs = speechSynthesis.getVoices();
  return vs.find((v) => v.lang === "en-GB") || vs.find((v) => v.lang === "en-US") || vs.find((v) => v.lang.startsWith("en")) || null;
}

if ("speechSynthesis" in window) {
  voice = pickVoice();
  speechSynthesis.onvoiceschanged = () => { voice = pickVoice(); };
}

export function canSpeak(): boolean {
  return "speechSynthesis" in window;
}

export function speak(text: string, rate = 0.9): Promise<void> {
  return new Promise((resolve) => {
    if (!canSpeak()) return resolve();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = voice?.lang || "en-GB";
    if (voice) u.voice = voice;
    u.rate = rate;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    speechSynthesis.speak(u);
  });
}
