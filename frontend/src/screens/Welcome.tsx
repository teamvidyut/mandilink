import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, type SessionPayload } from '../api';
import { LANGS, type Lang } from '../i18n';
import { useStore } from '../store';
import { Icon } from '../components/ui';

type Step = 'lang' | 'role' | 'details' | 'signin';

const DEMOS: { key: 'demoFarmer' | 'demoBuyer' | 'demoTrader' | 'demoAgent'; phone: string; pin: string }[] = [
  { key: 'demoFarmer', phone: '9000000001', pin: '1234' },
  { key: 'demoBuyer', phone: '9000000002', pin: '1234' },
  { key: 'demoTrader', phone: '9000000003', pin: '1234' },
  { key: 'demoAgent', phone: '9000000000', pin: '2468' },
];

export default function Welcome() {
  const { t, lang, setLang, signIn } = useStore();
  const nav = useNavigate();
  const [step, setStep] = useState<Step>('lang');
  const [role, setRole] = useState<'farmer' | 'buyer'>('farmer');
  const [form, setForm] = useState({ name: '', phone: '', pin: '', district: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const done = async (p: SessionPayload) => {
    await signIn(p);
    nav(p.user.role === 'agent' ? '/support' : p.user.role === 'farmer' ? '/market?mine=1' : '/market', { replace: true });
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr('');
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message || t.error);
    } finally {
      setBusy(false);
    }
  };

  const register = (e: FormEvent) => {
    e.preventDefault();
    run(async () => done(await api<SessionPayload>('/api/auth/register', { method: 'POST', json: { ...form, role, language: lang } })));
  };
  const login = (e: FormEvent) => {
    e.preventDefault();
    run(async () => done(await api<SessionPayload>('/api/auth/login', { method: 'POST', json: { phone: form.phone, pin: form.pin } })));
  };
  const demo = (phone: string, pin: string) =>
    run(async () => done(await api<SessionPayload>('/api/auth/login', { method: 'POST', json: { phone, pin } })));

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <main className="welcome">
      <section className="welcome-hero">
        <div className="brand">
          <img src="/icon.svg" alt="" width={44} height={44} />
          <span>MandiLink</span>
          <a className="brand-link" href="/impact">Impact →</a>
        </div>
        <p className="welcome-tagline">{t.tagline}</p>
        <HeroDemo />
        <ul className="features">
          {([['globe', t.f1Title, t.f1Text], ['spark', t.f2Title, t.f2Text], ['shield', t.f3Title, t.f3Text]] as const).map(([icon, title, text]) => (
            <li key={title}>
              <span className="feature-icon"><Icon name={icon} size={20} /></span>
              <span><b>{title}</b><small>{text}</small></span>
            </li>
          ))}
        </ul>
        <p className="powered"><Icon name="bolt" size={14} /> {t.poweredBy}</p>
      </section>

      <section className="welcome-panel">
        {step === 'lang' && (
          <>
            <h1>{t.chooseLanguage}</h1>
            <div className="lang-grid">
              {LANGS.map((l) => (
                <button key={l.code} className={`lang-btn ${lang === l.code ? 'on' : ''}`} onClick={() => setLang(l.code as Lang)}>
                  <span className="native">{l.native}</span>
                  <span className="eng">{l.english}</span>
                </button>
              ))}
            </div>
            <button className="btn primary wide" onClick={() => setStep('role')}>
              {t.next}
            </button>
            <button className="btn link" onClick={() => setStep('signin')}>
              {t.haveAccount}
            </button>
            <div className="demo-row">
              <p>{t.tryDemo}</p>
              <div className="demo-btns">
                {DEMOS.map((d) => (
                  <button key={d.key} className="chip" disabled={busy} onClick={() => demo(d.phone, d.pin)}>
                    {t[d.key]}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {step === 'role' && (
          <>
            <h1>{t.iAm}</h1>
            <div className="role-grid">
              {(['farmer', 'buyer'] as const).map((r) => (
                <button key={r} className={`role-btn ${role === r ? 'on' : ''}`} onClick={() => setRole(r)}>
                  <span className="role-emoji" aria-hidden>{r === 'farmer' ? '👩🏽‍🌾' : '🧺'}</span>
                  <span className="role-name">{t[r]}</span>
                  <span className="role-hint">{r === 'farmer' ? t.farmerHint : t.buyerHint}</span>
                </button>
              ))}
            </div>
            <div className="row-btns">
              <button className="btn ghost" onClick={() => setStep('lang')}>{t.back}</button>
              <button className="btn primary" onClick={() => setStep('details')}>{t.next}</button>
            </div>
          </>
        )}

        {step === 'details' && (
          <form onSubmit={register} className="form">
            <h1>{t[role]}</h1>
            <label>{t.yourName}<input required minLength={2} maxLength={40} value={form.name} onChange={set('name')} autoComplete="name" /></label>
            <label>{t.mobile}<input required inputMode="numeric" value={form.phone} onChange={set('phone')} autoComplete="tel" placeholder="98xxxxxxxx" /></label>
            <label>{t.pin}<input required inputMode="numeric" pattern="\d{4,6}" maxLength={6} type="password" value={form.pin} onChange={set('pin')} /><small>{t.pinHint}</small></label>
            <label>{t.district}<input maxLength={40} value={form.district} onChange={set('district')} /></label>
            {err && <p className="form-error" role="alert">{err}</p>}
            <div className="row-btns">
              <button type="button" className="btn ghost" onClick={() => setStep('role')}>{t.back}</button>
              <button className="btn primary" disabled={busy}>{t.createAccount}</button>
            </div>
          </form>
        )}

        {step === 'signin' && (
          <form onSubmit={login} className="form">
            <h1>{t.signIn}</h1>
            <label>{t.mobile}<input required inputMode="numeric" value={form.phone} onChange={set('phone')} autoComplete="tel" /></label>
            <label>{t.pin}<input required inputMode="numeric" type="password" value={form.pin} onChange={set('pin')} /></label>
            {err && <p className="form-error" role="alert">{err}</p>}
            <button className="btn primary wide" disabled={busy}>{t.signIn}</button>
            <button type="button" className="btn link" onClick={() => setStep('lang')}>{t.newHere}</button>
          </form>
        )}
        {err && step === 'lang' && <p className="form-error" role="alert">{err}</p>}
      </section>
    </main>
  );
}

/* Live demo loop: one message, typed in one language, read in another. */
const SCENES = [
  { from: 'farmer', said: 'আলু ১৪ টাকা কেজি, ২৫০০ কেজি আছে।', read: 'Potato ₹14/kg, 2,500 kg available.', tag: 'বাংলা → English' },
  { from: 'buyer', said: 'Can you do ₹13.5/kg for 500 kg?', read: '৫০০ কেজির জন্য ₹১৩.৫/কেজি দেবেন?', tag: 'English → বাংলা' },
  { from: 'ai', said: 'Mandi ₹11–16/kg · ₹13.5 is a fair price', read: 'মান্ডি ₹১১–১৬/কেজি · ₹১৩.৫ ন্যায্য দাম', tag: 'Mandi Mitra AI' },
  { from: 'trader', said: 'प्याज़ का आज का भाव क्या है?', read: 'What is today’s onion price?', tag: 'हिन्दी → English' },
];

function HeroDemo() {
  const [i, setI] = useState(0);
  const [flip, setFlip] = useState(false);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const a = window.setInterval(() => {
      setFlip(false);
      setI((n) => (n + 1) % SCENES.length);
    }, 3600);
    return () => window.clearInterval(a);
  }, []);
  useEffect(() => {
    const id = window.setTimeout(() => setFlip(true), 1100);
    return () => window.clearTimeout(id);
  }, [i]);
  const sc = SCENES[i];
  return (
    <div className="hero-demo" aria-hidden>
      <div className="hero-phone">
        <div className="hero-phone-bar"><span /><b>Deal room · Potato</b><span className="live-dot" /></div>
        <div key={i} className={`hero-msg from-${sc.from}`}>
          {sc.from === 'ai' && <span className="hero-ai"><Icon name="spark" size={14} /> AI</span>}
          <p className={flip ? 'faded' : ''}>{sc.said}</p>
          <p className={`hero-tr ${flip ? 'on' : ''}`}><Icon name="globe" size={14} /> {sc.read}</p>
        </div>
        <div className="hero-tag">{sc.tag}</div>
        <div className="hero-dots">{SCENES.map((_, n) => <i key={n} className={n === i ? 'on' : ''} />)}</div>
      </div>
    </div>
  );
}
