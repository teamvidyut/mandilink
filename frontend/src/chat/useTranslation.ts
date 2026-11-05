import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Lang } from '../i18n';

export interface TranslationResult {
  text: string;
  source: Lang;
  target: Lang;
  translated: boolean;
  engine: string;
}

const cache = new Map<string, Promise<TranslationResult>>();

export function detectScript(text: string): Lang {
  const bn = (text.match(/[ঀ-৿]/g) || []).length;
  const hi = (text.match(/[ऀ-ॿ]/g) || []).length;
  if (!bn && !hi) return 'en';
  return bn >= hi ? 'bn' : 'hi';
}

export function translate(text: string, target: Lang, sourceHint?: Lang): Promise<TranslationResult> {
  const key = `${target}|${sourceHint || ''}|${text}`;
  let p = cache.get(key);
  if (!p) {
    // A request can stall on a busy free-tier server: give up after 25 s and try once more,
    // so a message never stays stuck on "…" forever.
    const once = () =>
      Promise.race([
        api<TranslationResult>('/api/translate', { method: 'POST', json: { text, target, source_hint: sourceHint } }),
        new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error('translate timeout')), 25000)),
      ]);
    p = once().catch(() => once());
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}

/** Translate `text` into the viewer's language when it was written in another one. */
export function useTranslated(text: string, viewerLang: Lang, sourceHint?: Lang, enabled = true) {
  const script = detectScript(text);
  const source = script !== 'en' ? script : sourceHint || 'en';
  const needs = enabled && !!text && source !== viewerLang;
  const [result, setResult] = useState<TranslationResult | null>(null);
  const [loading, setLoading] = useState(needs);

  useEffect(() => {
    if (!needs) {
      setResult(null);
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    translate(text, viewerLang, source)
      .then((r) => live && setResult(r))
      .catch(() => live && setResult(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [text, viewerLang, source, needs]);

  return { needs, loading, result, source };
}
