import { useCallback, useEffect, useState } from 'react';
import { api, type Brief, type Ticket } from '../api';
import { fmtNum, fmtRs, fmtTime, LANGS } from '../i18n';
import { useStore } from '../store';
import { Avatar, Icon } from '../components/ui';
import ChatRoom from './ChatRoom';

export default function Support() {
  const { t, lang, me, lastMessages, toast, refreshConversations } = useStore();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [filter, setFilter] = useState<'active' | 'resolved'>('active');
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefOpen, setBriefOpen] = useState(true);
  const selectedId = selected?.id;
  const selectedStatus = selected?.status;
  useEffect(() => {
    setBriefOpen(selectedStatus === 'open');
  }, [selectedId, selectedStatus]);
  useEffect(() => {
    setBrief(null);
    if (selectedId == null) return;
    let live = true;
    api<Brief>(`/api/support/tickets/${selectedId}/brief`).then((b) => live && setBrief(b)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [selectedId]);

  const load = useCallback(() => {
    api<Ticket[]>('/api/support/tickets').then(setTickets).catch(() => setTickets([]));
  }, []);
  useEffect(() => {
    load();
    const id = window.setInterval(load, 10000);
    return () => window.clearInterval(id);
  }, [load]);
  // New-ticket pings arrive as Nexconn direct messages from the bot: refresh instantly.
  const ping = lastMessages['mandi-mitra']?.messageId;
  useEffect(() => {
    if (ping) load();
  }, [ping, load]);

  const act = async (tk: Ticket, action: 'claim' | 'resolve') => {
    try {
      const updated = await api<Ticket>(`/api/support/tickets/${tk.id}/${action}`, { method: 'POST' });
      setTickets((cur) => cur?.map((x) => (x.id === tk.id ? updated : x)) ?? null);
      setSelected(updated);
      await refreshConversations();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const visible = (tickets ?? []).filter((tk) => (filter === 'active' ? tk.status !== 'resolved' : tk.status === 'resolved'));

  return (
    <div className={`screen support ${selected ? 'has-room' : ''}`}>
      <aside className="conv-pane">
        <header className="screen-head">
          <h1>{t.support}</h1>
          <div className="seg">
            <button className={filter === 'active' ? 'on' : ''} onClick={() => setFilter('active')}>{t.open}</button>
            <button className={filter === 'resolved' ? 'on' : ''} onClick={() => setFilter('resolved')}>{t.resolved}</button>
          </div>
        </header>
        {me?.demo && <p className="demo-desk-note">{t.demoDesk}</p>}
        {tickets && visible.length === 0 && <p className="empty small">{t.noTickets}</p>}
        <ul className="ticket-list">
          {visible.map((tk) => (
            <li key={tk.id}>
              <button className={`ticket-row pri-${tk.priority} st-${tk.status} ${selected?.id === tk.id ? 'on' : ''}`} onClick={() => setSelected(tk)}>
                <Avatar name={tk.user?.name ?? '?'} role={tk.user?.role} size={36} />
                <span className="conv-text">
                  <span className="conv-title">
                    #{tk.id} {tk.user?.name}
                    {tk.priority === 'high' && <span className="pri-tag">{t.high}</span>}
                  </span>
                  <span className="conv-sub">{tk.reason}</span>
                </span>
                <span className="conv-side">
                  <time>{fmtTime(tk.createdAt, lang)}</time>
                  <span className={`st st-${tk.status}`}>{t[tk.status]}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <div className="room-pane">
        {selected ? (
          <div className="ticket-pane">
            <div className="ticket-context">
              <div>
                <h2>#{selected.id} · {selected.user?.name}</h2>
                <p>
                  {selected.user && t[selected.user.role as 'farmer' | 'buyer']}, {LANGS.find((l) => l.code === selected.user?.language)?.native}
                  {selected.user?.district && `, ${selected.user.district}`}
                </p>
                {selected.deal && (
                  <p className="ticket-deal">
                    {selected.deal.crop}: ask {fmtRs(selected.deal.askPrice, lang)}/kg
                    {selected.deal.offerPrice != null && `, offer ${fmtNum(selected.deal.offerQty ?? 0, lang)} kg @ ${fmtRs(selected.deal.offerPrice, lang)}`} · {selected.deal.status}
                  </p>
                )}
              </div>
              {selected.status === 'open' && <button className="btn primary" onClick={() => act(selected, 'claim')}>{t.claim}</button>}
              {selected.status === 'assigned' && <button className="btn ghost" onClick={() => act(selected, 'resolve')}>{t.resolve}</button>}
            </div>
            {brief && (
              <section className={`brief ${briefOpen ? 'open' : ''}`} aria-label={t.caseBrief}>
                <button className="brief-head" onClick={() => setBriefOpen((v) => !v)} aria-expanded={briefOpen}>
                  <Icon name="spark" size={18} />
                  <b>{t.caseBrief}</b>
                  <span className={`brief-cat cat-${brief.category}`}>{brief.headline}</span>
                  <Icon name="down" size={18} />
                </button>
                {briefOpen && (
                  <div className="brief-body">
                    <ul>{brief.facts.map((f) => <li key={f}>{f}</li>)}</ul>
                    <p className="brief-action"><b>{t.suggestedAction}:</b> {brief.suggestedAction}</p>
                  </div>
                )}
              </section>
            )}
            {selected.status === 'open' ? (
              <div className="room-empty"><p>{selected.summary || selected.reason}</p></div>
            ) : (
              <ChatRoom key={selected.channelId} channelType={3} channelId={selected.channelId} onBack={() => setSelected(null)} hideHeader />
            )}
          </div>
        ) : (
          <div className="room-empty"><p>{t.noTickets}</p></div>
        )}
      </div>
    </div>
  );
}
