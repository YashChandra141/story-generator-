// Browser speech synthesis: fully offline, nothing is sent anywhere.

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function stopSpeech(): void {
  if (speechSupported()) window.speechSynthesis.cancel();
}

export function speakWord(word: string): void {
  if (!speechSupported()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(word);
  u.rate = 0.8;
  window.speechSynthesis.speak(u);
}

let session = 0;

export function speakSentences(text: string, onDone?: () => void): void {
  if (!speechSupported()) return;
  window.speechSynthesis.cancel();
  const my = ++session;
  const parts = (text.match(/[^.!?\n]+[.!?]*/g) || [text])
    .map((s) => s.trim())
    .filter(Boolean);
  const finish = () => {
    if (my === session && onDone) onDone();
  };
  if (!parts.length) {
    finish();
    return;
  }
  let pending = parts.length;
  const done = () => {
    pending--;
    if (pending <= 0) finish();
  };
  parts.forEach((part) => {
    const u = new SpeechSynthesisUtterance(part);
    u.rate = 0.9; // a little slow, for early readers
    u.onend = done;
    u.onerror = done;
    window.speechSynthesis.speak(u);
  });
}