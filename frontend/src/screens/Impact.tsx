import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type Metrics } from '../api';
import { fmtNum, fmtRs, LANGS, type Lang } from '../i18n';
import { useStore } from '../store';
import { Icon } from '../components/ui';

const LANG_ORDER: Lang[] = ['bn', 'hi', 'en']; // fixed order = fixed colour (validated palette)

/** Public traction page: real usage counted from the app, no personal data. */
export default function Impact() {
  const { lang, me } = useStore();
  const [m, setM] = useState<Metrics | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  useEffect(() => {
    api<Metrics>('/api/metrics').then(setM).catch(() => undefined);
  }, []);
  if (!m) return <div className="screen impact"><div className="skeleton-grid" aria-busy><div className="skeleton-card" /><div className="skeleton-card" /></div></div>;

  const peak = Math.max(1, ...m.series.map((d) => d.messages));
  const langTotal = Math.max(1, LANG_ORDER.reduce((n, l) => n + (m.languages?.[l] ?? 0), 0));
  const stats: [string, string, string][] = [
    ['chats', 'Messages sent', fmtNum(m.messages, lang)],
    ['globe', 'Messages translated', fmtNum(m.translations, lang)],
    ['spark', 'AI answers', fmtNum(m.aiReplies, lang)],
    ['handshake', 'Deal rooms opened', fmtNum(m.dealsOpened, lang)],
    ['truck', 'Deliveries confirmed', fmtNum(m.dealsCompleted, lang)],
    ['megaphone', 'Buyer requests', fmtNum(m.requests, lang)],
    ['support', 'Support tickets resolved', `${fmtNum(m.ticketsResolved, lang)}/${fmtNum(m.tickets, lang)}`],
    ['star', 'Trade rating', m.tradeRating != null ? `${m.tradeRating}★ (${m.tradeReviews})` : '—'],
  ];
  const h = hover != null ? m.series[hover] : null;

  return (
    <div className="screen impact">
      <header className="screen-head">
        <div>
          <p className="hero-kicker">Live traction</p>
          <h1>MandiLink in numbers</h1>
        </div>
        {!me && <Link className="btn ghost small" to="/">Open app</Link>}
      </header>
      <p className="impact-lede">Every number is counted from real use of the app. Demo accounts are excluded.</p>

      <section className="kpi-hero">
        <div className="kpi main">
          <dt>Value traded through chat</dt>
          <dd>{fmtRs(m.gmvRs, lang)}</dd>
          <small>{fmtNum(m.kgTraded, lang)} kg · {fmtNum(m.dealsAgreed, lang)} deals agreed</small>
        </div>
        <div className="kpi"><dt>People signed up</dt><dd>{fmtNum(m.users, lang)}</dd><small>{fmtNum(m.farmers, lang)} farmers · {fmtNum(m.buyers, lang)} buyers</small></div>
        <div className="kpi"><dt>Active in last 7 days</dt><dd>{fmtNum(m.activeUsers7d, lang)}</dd><small>sent at least one message</small></div>
      </section>

      <dl className="impact-stats">
        {stats.map(([icon, k, v]) => (
          <div key={k}><Icon name={icon} size={18} /><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>

      <section className="panel chart-panel">
        <div className="chart-head">
          <h2>Messages per day · last 14 days</h2>
          <button className="btn link small" onClick={() => setTable((v) => !v)}>{table ? 'Show chart' : 'Show table'}</button>
        </div>
        {table ? (
          <table className="data-table">
            <thead><tr><th>Date</th><th>Messages</th><th>Active people</th></tr></thead>
            <tbody>{m.series.map((d) => <tr key={d.date}><td>{d.date}</td><td>{d.messages}</td><td>{d.activeUsers}</td></tr>)}</tbody>
          </table>
        ) : (
          <div className="bars-wrap" onMouseLeave={() => setHover(null)}>
            <div className="bars-tip" style={{ visibility: h ? 'visible' : 'hidden' }}>
              {h && <><b>{h.date}</b> · {fmtNum(h.messages, lang)} messages · {fmtNum(h.activeUsers, lang)} people</>}
            </div>
            <div className="bars" role="img" aria-label="Messages per day">
              {m.series.map((d, i) => (
                <div key={d.date} className={`bar ${hover === i ? 'hot' : ''}`} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0}>
                  <span style={{ height: `${(d.messages / peak) * 100}%` }} />
                  <small>{d.date.slice(8)}</small>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Languages people use</h2>
        <div className="lang-bar" role="img" aria-label="Users by language">
          {LANG_ORDER.map((l) => {
            const n = m.languages?.[l] ?? 0;
            return n > 0 ? <span key={l} className={`seg-${l}`} style={{ flexGrow: n }} title={`${n}`} /> : null;
          })}
          {langTotal === 1 && LANG_ORDER.every((l) => !(m.languages?.[l])) && <span className="seg-empty" />}
        </div>
        <ul className="legend">
          {LANG_ORDER.map((l) => (
            <li key={l}>
              <i className={`seg-${l}`} />
              {LANGS.find((x) => x.code === l)?.native} <b>{fmtNum(m.languages?.[l] ?? 0, lang)}</b>
              <span className="muted"> ({Math.round(((m.languages?.[l] ?? 0) / langTotal) * 100)}%)</span>
            </li>
          ))}
        </ul>
      </section>

      {m.feedbackCount > 0 && (
        <p className="impact-lede">App rating {m.feedbackAvg}★ from {m.feedbackCount} users.</p>
      )}
      <p className="powered center"><Icon name="bolt" size={14} /> Real-time chat by Nexconn</p>
    </div>
  );
}
