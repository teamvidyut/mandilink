import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, type Trust } from '../api';
import { fmtNum, LANGS } from '../i18n';
import { useStore } from '../store';
import { Avatar, Icon, TrustBadge } from '../components/ui';

export default function Profile() {
  const { t, me, lang, setLang, signOut, toast, theme, setTheme } = useStore();
  const nav = useNavigate();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [sent, setSent] = useState(false);
  const [trust, setTrust] = useState<Trust | null>(null);
  const meId = me?.id;
  useEffect(() => {
    if (meId && me?.role !== 'agent') api<Trust>(`/api/users/${meId}/trust`).then(setTrust).catch(() => undefined);
  }, [meId, me?.role]);
  if (!me) return null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!rating) return;
    try {
      await api('/api/feedback', { method: 'POST', json: { rating, comment } });
      setSent(true);
    } catch (err) {
      toast((err as Error).message);
    }
  };

  return (
    <div className="screen profile">
      <header className="profile-head">
        <Avatar name={me.name} role={me.role} size={64} />
        <div>
          <h1>{me.name}</h1>
          <p>{me.role === 'agent' ? t.support : t[me.role as 'farmer' | 'buyer']}{me.district && `, ${me.district}`}</p>
          {trust && <TrustBadge trust={trust} t={t} />}
        </div>
      </header>

      {trust && (
        <section className="stat-row" aria-label={t.yourTrades}>
          <div><dd>{fmtNum(trust.deals, lang)}</dd><dt>{t.yourTrades}</dt></div>
          <div><dd>{trust.rating != null ? `${trust.rating.toFixed(1)}★` : '—'}</dd><dt>{t.rating} ({fmtNum(trust.reviews, lang)})</dt></div>
          <div><dd>{trust.since ? new Date(trust.since).toLocaleDateString(lang === 'en' ? 'en-IN' : `${lang}-IN`, { month: 'short', year: 'numeric' }) : '—'}</dd><dt>{t.memberSince}</dt></div>
        </section>
      )}

      <section className="panel">
        <h2>{t.language}</h2>
        <div className="lang-grid compact">
          {LANGS.map((l) => (
            <button key={l.code} className={`lang-btn ${lang === l.code ? 'on' : ''}`} onClick={() => setLang(l.code)}>
              <span className="native">{l.native}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>{t.appearance}</h2>
        <div className="seg wide">
          {([['light', 'sun', t.themeLight], ['dark', 'moon', t.themeDark], ['system', 'globe2', t.themeSystem]] as const).map(([k, icon, label]) => (
            <button key={k} className={theme === k ? 'on' : ''} onClick={() => setTheme(k)} aria-pressed={theme === k}>
              <Icon name={icon} size={16} /> {label}
            </button>
          ))}
        </div>
      </section>

      {me.role !== 'agent' && (
        <section className="panel">
          <h2>{t.feedback}</h2>
          {sent ? (
            <p className="thanks"><Icon name="check" /> {t.thanks}</p>
          ) : (
            <form className="form" onSubmit={submit}>
              <div className="stars" role="radiogroup" aria-label={t.feedback}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button type="button" key={n} role="radio" aria-checked={rating === n} aria-label={`${n}/5`}
                    className={n <= rating ? 'on' : ''} onClick={() => setRating(n)}>★</button>
                ))}
              </div>
              <textarea rows={3} maxLength={1000} placeholder={t.feedbackPlaceholder} value={comment} onChange={(e) => setComment(e.target.value)} />
              <button className="btn primary" disabled={!rating}>{t.sendFeedback}</button>
            </form>
          )}
        </section>
      )}

      <section className="panel links">
        <Link to="/impact"><Icon name="chart" /> {t.impact}</Link>
        <button className="btn ghost" onClick={async () => { await signOut(); nav('/', { replace: true }); }}>{t.signOut}</button>
      </section>
    </div>
  );
}
