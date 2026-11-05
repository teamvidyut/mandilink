import { useCallback, useEffect, useRef, useState } from 'react';
import { LANGS, type Lang } from '../i18n';

/* Browser speech APIs: voice typing (SpeechRecognition) and read-aloud
   (speechSynthesis). Both run on-device in Chrome/Android and cost nothing. */

type Rec = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((e: any) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: any) => void) | null;
};

function recognitionCtor(): (new () => Rec) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export const speechInputSupported = () => !!recognitionCtor();

export function useVoiceTyping(lang: Lang, onText: (text: string, final: boolean) => void) {
  const [listening, setListening] = useState(false);
  const rec = useRef<Rec | null>(null);
  const cb = useRef(onText);
  cb.current = onText;

  const stop = useCallback(() => rec.current?.stop(), []);
  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    const r = new Ctor();
    r.lang = LANGS.find((l) => l.code === lang)?.speech || 'en-IN';
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e: any) => {
      let text = '';
      let final = false;
      for (let i = 0; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
        final = final || e.results[i].isFinal;
      }
      cb.current(text, final);
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    rec.current = r;
    setListening(true);
    r.start();
  }, [lang]);

  useEffect(() => () => rec.current?.stop(), []);
  return { listening, start, stop, supported: speechInputSupported() };
}

export function speak(text: string, lang: Lang) {
  if (!('speechSynthesis' in window)) return false;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[*_#]/g, ''));
  const code = LANGS.find((l) => l.code === lang)?.speech || 'en-IN';
  u.lang = code;
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(code.slice(0, 2)));
  if (voice) u.voice = voice;
  u.rate = 0.95;
  window.speechSynthesis.speak(u);
  return true;
}
