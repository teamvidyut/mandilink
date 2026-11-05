import { useEffect, useRef, type ReactNode } from 'react';
import type { MandiInfo, PriceRow, Trust } from '../api';
import { fmtNum, fmtRs, LANGS, type Lang, type T } from '../i18n';

/* ------------------------------------------------------------------ icons */
const paths: Record<string, ReactNode> = {
  market: <path d="M3 10h18M5 10V20h14V10M3 10l2-6h14l2 6M9 20v-5h6v5" />,
  chats: <path d="M4 5h16v10H9l-5 4V5z" />,
  mitra: <><circle cx="12" cy="12" r="8" /><path d="M8.5 14c1 1.3 2.1 2 3.5 2s2.5-.7 3.5-2M9 10h.01M15 10h.01" /></>,
  me: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>,
  support: <><path d="M4 13v-1a8 8 0 0116 0v1" /><rect x="3" y="13" width="4" height="6" rx="1.5" /><rect x="17" y="13" width="4" height="6" rx="1.5" /></>,
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></>,
  send: <path d="M4 12l16-8-6 16-2.5-6.5L4 12z" />,
  speaker: <><path d="M4 9v6h4l5 4V5L8 9H4z" /><path d="M16.5 8.5a5 5 0 010 7M19 6a8.5 8.5 0 010 12" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  back: <path d="M15 5l-7 7 7 7" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z" /></>,
  handshake: <path d="M3 12l4-4 3 2 3-3 4 1 4 4-5 5-2-2-2 2-2-2-2 1-5-4z" />,
  spark: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>,
  receipt: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3z" /><path d="M9 8h6M9 12h6M9 16h3" /></>,
  star: <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9L12 3.5z" />,
  camera: <><path d="M4 8h3l2-3h6l2 3h3v11H4V8z" /><circle cx="12" cy="13" r="3.5" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" />,
  down: <path d="M6 9l6 6 6-6" />,
  megaphone: <><path d="M3 10v4h3l7 5V5L6 10H3z" /><path d="M17 8a5 5 0 010 8" /></>,
  truck: <><path d="M2 6h11v10H2zM13 10h4l3 3v3h-7" /><circle cx="6" cy="17.5" r="1.8" /><circle cx="17" cy="17.5" r="1.8" /></>,
  shield: <><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
  print: <><path d="M7 9V3h10v6M7 17H4v-7h16v7h-3" /><path d="M7 14h10v7H7z" /></>,
  share: <><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4" /></>,
  sort: <path d="M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4" />,
  bolt: <path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />,
  play: <path d="M8 5.5v13l11-6.5-11-6.5z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="2" />,
  wave: <path d="M3 12h1.5M7 8v8M11 5v14M15 8v8M19 10.5v3" />,
  globe2: <><circle cx="12" cy="12" r="9" /><path d="M3.6 9h16.8M3.6 15h16.8M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></>,
};

export function Icon({ name, size = 22, label }: { name: keyof typeof paths | string; size?: number; label?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {paths[name]}
    </svg>
  );
}

/* --------------------------------------------------------------- rate band */
/**
 * The signature element: a chalkboard strip showing today's mandi range
 * (min … typical … max) with the asking/offer price pinned on it.
 */
export function RateBand({ info, price, lang, t, compact = false }: {
  info: MandiInfo; price?: number | null; lang: Lang; t: T; compact?: boolean;
}) {
  const lo = Math.min(info.min_per_kg, price ?? info.min_per_kg) * 0.9;
  const hi = Math.max(info.max_per_kg, price ?? info.max_per_kg) * 1.08;
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`;
  const verdict = price == null ? null : price < info.modal_per_kg * 0.85 ? 'low' : price > info.modal_per_kg * 1.2 ? 'high' : 'fair';
  const verdictText = verdict === 'low' ? t.priceLow : verdict === 'high' ? t.priceHigh : verdict === 'fair' ? t.priceFair : '';
  return (
    <div className={`rateband ${compact ? 'is-compact' : ''}`}>
      {!compact && (
        <div className="rateband-head">
          <span>{info.live ? t.todayMandi : t.estimate}</span>
          {verdict && <span className={`verdict v-${verdict}`}>{verdictText}</span>}
        </div>
      )}
      <div className="rateband-track" aria-hidden>
        <div className="rateband-range" style={{ left: pos(info.min_per_kg), right: `calc(100% - ${pos(info.max_per_kg)})` }} />
        <div className="rateband-modal" style={{ left: pos(info.modal_per_kg) }} />
        {price != null && <div className={`rateband-pin v-${verdict}`} style={{ left: pos(price) }} />}
      </div>
      <div className="rateband-scale">
        <span>{fmtRs(info.min_per_kg, lang)}</span>
        <span className="modal">{fmtRs(info.modal_per_kg, lang)}</span>
        <span>{fmtRs(info.max_per_kg, lang)}</span>
      </div>
      {compact && verdict && <span className={`verdict v-${verdict}`}>{verdictText}</span>}
      <p className="sr-only">
        {verdictText} {price != null ? fmtRs(price, lang) : ''} · {fmtNum(info.min_per_kg, lang)}–{fmtNum(info.max_per_kg, lang)}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ sheet */
export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('input,select,textarea,button')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      prev?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} ref={ref} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Avatar({ name, role, size = 40 }: { name: string; role?: string; size?: number }) {
  const initial = (name || '?').trim().charAt(0).toUpperCase();
  return (
    <span className={`avatar role-${role || 'x'}`} style={{ width: size, height: size, fontSize: size * 0.42 }} aria-hidden>
      {role === 'bot' ? <Icon name="spark" size={size * 0.55} /> : initial}
    </span>
  );
}

/* ------------------------------------------------------------- trust badge */
export function TrustBadge({ trust, t, compact = false }: { trust?: Trust | null; t: T; compact?: boolean }) {
  if (!trust) return null;
  const label = trust.badge === 'top' ? t.trustTop : trust.badge === 'trusted' ? t.trustTrusted : t.trustNew;
  return (
    <span className={`trust trust-${trust.badge}`} title={label}>
      <Icon name={trust.badge === 'new' ? 'spark' : 'shield'} size={14} />
      {trust.rating != null ? <><b>{trust.rating.toFixed(1)}</b>★</> : (compact && trust.deals > 0) ? null : label}
      {trust.deals > 0 && <span className="trust-deals">· {trust.deals} {t.dealsDone}</span>}
    </span>
  );
}

/* ------------------------------------------------------------- deal stepper */
export function Stepper({ status, t }: { status: string; t: T }) {
  const steps = [t.stepEnquiry, t.stepOffer, t.stepAgreed, t.stepDelivered];
  const at = status === 'completed' ? 3 : status === 'agreed' ? 2 : status === 'proposed' ? 1 : 0;
  return (
    <ol className="stepper" aria-label={steps[at]}>
      {steps.map((s, i) => (
        <li key={s} className={i < at ? 'done' : i === at ? 'now' : ''} aria-current={i === at ? 'step' : undefined}>
          <span className="step-dot">{i < at || (i === 3 && at === 3) ? <Icon name="check" size={12} /> : i + 1}</span>
          <span className="step-label">{s}</span>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------- star input */
export function Stars({ value, onChange, label, size = 34 }: { value: number; onChange?: (n: number) => void; label: string; size?: number }) {
  return (
    <div className="stars" role={onChange ? 'radiogroup' : 'img'} aria-label={label}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button type="button" key={n} role={onChange ? 'radio' : undefined} aria-checked={onChange ? value === n : undefined}
          aria-label={`${n}/5`} className={n <= value ? 'on' : ''} disabled={!onChange} onClick={() => onChange?.(n)}
          style={{ width: size + 8, height: size + 8 }}>
          <Icon name="star" size={size} />
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- price ticker */
export function Ticker({ rows, lang, t, onPick }: { rows: PriceRow[]; lang: Lang; t: T; onPick?: (crop: string) => void }) {
  if (!rows.length) return null;
  const live = rows.some((r) => r.live);
  const items = rows.map((r) => (
    <button key={r.crop} className="tick" onClick={() => onPick?.(r.crop)} tabIndex={-1}>
      <span className="tick-name">{r.names[lang]}</span>
      <span className="tick-val">{fmtRs(r.modal_per_kg, lang)}</span>
      <span className="tick-range">{fmtNum(r.min_per_kg, lang)}–{fmtNum(r.max_per_kg, lang)}</span>
    </button>
  ));
  return (
    <div className="ticker" aria-label={t.liveRates}>
      <span className={`ticker-label ${live ? 'is-live' : ''}`}><i />{live ? t.todayMandi : t.estimate}</span>
      <div className="ticker-viewport">
        <div className="ticker-track">{items}<span aria-hidden className="ticker-dup">{items}</span></div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- language switch */
/** One-tap language switch (বাংলা · हिन्दी · EN) for screens judges and users visit first. */
export function LangSwitch({ lang, onChange }: { lang: Lang; onChange: (l: Lang) => void }) {
  return (
    <div className="seg lang-switch" role="radiogroup" aria-label="Language">
      {LANGS.map((l) => (
        <button key={l.code} role="radio" aria-checked={lang === l.code} lang={l.code}
          className={lang === l.code ? 'on' : ''} onClick={() => onChange(l.code)}>
          {l.code === 'en' ? 'EN' : l.native}
        </button>
      ))}
    </div>
  );
}
