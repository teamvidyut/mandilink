import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, type DealCard, type MandiInfo, type Receipt } from '../api';
import { CROP_EMOJI, CROP_TINT, fmtNum, fmtRs, fmtTime, LANGS, type Lang, type T } from '../i18n';
import { useStore } from '../store';
import { Avatar, Icon, RateBand, Sheet, Stars, Stepper } from '../components/ui';
import { GROUP, MSG_DEAL, MSG_LISTING, MSG_NOTICE, MSG_TEXT, MSG_VOICE, type ChannelType, type ChatMessage } from '../chat/transport';
import { useVoiceRecorder, type VoiceClip } from '../chat/recorder';
import { useTranslated } from '../chat/useTranslation';
import { speak, useVoiceTyping } from '../chat/speech';

const BOT_ID = 'mandi-mitra';

export default function ChatRoom({ channelType, channelId, onBack, hideHeader = false }: { channelType: ChannelType; channelId: string; onBack?: () => void; hideHeader?: boolean }) {
  const store = useStore();
  const { t, lang, me, transport, profiles, ensureProfiles, conversations, setActiveChannel, toast, status, refreshConversations } = store;
  const conv = conversations.find((c) => c.channelId === channelId);
  const kind = conv?.kind ?? (channelId === BOT_ID ? 'assistant' : me?.role === 'agent' ? 'support' : channelId.startsWith('deal_') ? 'deal' : 'room');
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [typingUser, setTypingUser] = useState<string | null>(null);
  const [thinking, setThinking] = useState(false);
  const [deal, setDeal] = useState<DealCard | null>(null);
  const [offerOpen, setOfferOpen] = useState(false);
  const [receiptOpen, setReceiptOpen] = useState(false);
  const [replies, setReplies] = useState<string[]>([]);
  const [rated, setRated] = useState<boolean | null>(null);
  const [unseen, setUnseen] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const nav = useNavigate();
  const dealStatus = deal?.status;

  // Smart replies (in my language, with the AI fair price) for deal rooms + support chats.
  useEffect(() => {
    if (kind !== 'deal' && kind !== 'support') {
      setReplies([]);
      return;
    }
    let live = true;
    api<{ replies: string[] }>(`/api/chat/suggestions?channel_id=${encodeURIComponent(channelId)}`)
      .then((r) => live && setReplies(r.replies))
      .catch(() => live && setReplies([]));
    return () => {
      live = false;
    };
  }, [kind, channelId, dealStatus, lang]);

  // Post-deal rating prompt.
  useEffect(() => {
    if (kind !== 'deal' || (dealStatus !== 'agreed' && dealStatus !== 'completed') || me?.role === 'agent') {
      setRated(null);
      return;
    }
    api<{ stars: number } | null>(`/api/deals/${channelId}/review`).then((r) => setRated(!!r)).catch(() => setRated(null));
  }, [kind, channelId, dealStatus, me?.role]);

  useEffect(() => {
    setActiveChannel(channelId);
    return () => setActiveChannel(null);
  }, [channelId, setActiveChannel]);

  // ---- history + live messages (through the Nexconn Chat SDK)
  useEffect(() => {
    if (!transport) return;
    let live = true;
    setMessages(null);
    stick.current = true;
    transport
      .history(channelType, channelId, 50)
      .then((h) => live && setMessages(h))
      .catch(() => live && setMessages([]));
    const offMsg = transport.onMessage((m) => {
      if (m.channelId !== channelId || m.channelType !== channelType) return;
      setMessages((cur) => {
        const list = cur ?? [];
        if (list.some((x) => x.messageId === m.messageId)) return list;
        return [...list, m];
      });
      if (!stick.current) setUnseen((n) => n + 1);
      if (m.senderUserId === BOT_ID && m.messageType === MSG_TEXT) setThinking(false);
      if (m.messageType === MSG_DEAL) setDeal(m.content as DealCard);
      setTypingUser(null);
    });
    let typingTimer = 0;
    const offTyping = transport.onTyping((e) => {
      if (e.channelId !== channelId) return;
      setTypingUser(e.userId);
      window.clearTimeout(typingTimer);
      typingTimer = window.setTimeout(() => setTypingUser(null), 4000);
    });
    return () => {
      live = false;
      offMsg();
      offTyping();
    };
  }, [transport, channelId, channelType]);

  useEffect(() => {
    if (kind === 'deal') api<DealCard>(`/api/deals/${channelId}`).then(setDeal).catch(() => undefined);
    else setDeal(null);
  }, [kind, channelId]);

  useEffect(() => {
    if (messages) ensureProfiles([...new Set(messages.map((m) => m.senderUserId))]);
  }, [messages, ensureProfiles]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, thinking, typingUser, rated]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (stick.current) setUnseen(0);
    setAway(!stick.current);
  };
  const [away, setAway] = useState(false);
  const jumpToLatest = () => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    stick.current = true;
    setUnseen(0);
    setAway(false);
  };

  const latestDealMsgId = useMemo(() => [...(messages ?? [])].reverse().find((m) => m.messageType === MSG_DEAL)?.messageId, [messages]);

  // ---- send
  const send = useCallback(
    async (text: string) => {
      if (!transport || !me || !text.trim()) return;
      const tempId = `tmp-${Date.now()}`;
      const extra = { lang };
      const temp: ChatMessage = {
        messageId: tempId, channelType, channelId, senderUserId: me.id, messageType: MSG_TEXT,
        content: { text, extraData: extra }, sentTime: Date.now(), pending: true,
      };
      stick.current = true;
      setMessages((cur) => [...(cur ?? []), temp]);
      try {
        const sent = await transport.sendText(channelType, channelId, text, extra);
        setMessages((cur) => {
          const list = (cur ?? []).filter((m) => m.messageId !== sent.messageId);
          return list.map((m) => (m.messageId === tempId ? sent : m));
        });
        afterSend(text, MSG_TEXT);
      } catch {
        setMessages((cur) => (cur ?? []).map((m) => (m.messageId === tempId ? { ...m, pending: false, failed: true } : m)));
      }
    },
    [transport, me, lang, channelType, channelId, kind, toast, t, refreshConversations],  // eslint-disable-line react-hooks/exhaustive-deps
  );

  // Tell the server what was sent: traction count, Mandi Mitra replies, auto-escalation.
  // Voice messages pass their AI transcript, so spoken questions and complaints work like typed ones.
  function afterSend(text: string, messageType: string) {
    const wantsAi = kind === 'assistant' || /@(mandi|mitra|ai)\b|^\/ai\b|মান্ডি মিত্র|मंडी मित्र/i.test(text);
    if (wantsAi && text) setThinking(true);
    api<{ replied: boolean; escalated?: boolean }>('/api/chat/after-send', {
      method: 'POST',
      json: { channel_type: channelType, channel_id: channelId, text, message_type: messageType },
    })
      .then((r) => {
        if (!r.replied) setThinking(false);
        if (r.escalated) {
          toast(t.helpRequested);
          void refreshConversations();
        }
      })
      .catch(() => setThinking(false));
  }

  const sendVoice = async (clip: VoiceClip) => {
    if (!transport || !me) return;
    const tempId = `tmp-v-${Date.now()}`;
    const temp: ChatMessage = {
      messageId: tempId, channelType, channelId, senderUserId: me.id, messageType: MSG_VOICE,
      content: { url: '', durationMs: clip.durationMs, transcript: '', lang, uploading: true }, sentTime: Date.now(), pending: true,
    };
    stick.current = true;
    setMessages((cur) => [...(cur ?? []), temp]);
    try {
      const up = await api<{ url: string; transcript: string; lang: Lang; durationMs: number }>('/api/voice', {
        method: 'POST', json: { data_url: clip.dataUrl, duration_ms: clip.durationMs, lang },
      });
      const content = { url: up.url, durationMs: up.durationMs, transcript: up.transcript, lang: up.lang };
      const sent = await transport.sendCustom(channelType, channelId, MSG_VOICE, content);
      setMessages((cur) => {
        const list = (cur ?? []).filter((m) => m.messageId !== sent.messageId);
        return list.map((m) => (m.messageId === tempId ? { ...sent, content: { ...content, ...sent.content } } : m));
      });
      afterSend(up.transcript, MSG_VOICE);
    } catch (e) {
      toast((e as Error).message);
      setMessages((cur) => (cur ?? []).map((m) => (m.messageId === tempId ? { ...m, pending: false, failed: true } : m)));
    }
  };

  const askAi = async () => {
    setThinking(true);
    try {
      await api('/api/chat/ask-ai', { method: 'POST', json: { channel_id: channelId } });
    } catch (e) {
      setThinking(false);
      toast((e as Error).message);
    }
  };

  const getHelp = async () => {
    try {
      const r = await api<{ channelId: string }>('/api/support/request', { method: 'POST', json: { channel_id: kind === 'deal' ? channelId : null } });
      toast(t.helpRequested);
      await refreshConversations();
      if (r.channelId !== channelId) nav(`/chats/3/${r.channelId}`);
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const confirmDelivery = async () => {
    try {
      setDeal(await api<DealCard>(`/api/deals/${channelId}/delivered`, { method: 'POST' }));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const dealAction = async (action: 'accept' | 'decline') => {
    try {
      setDeal(await api<DealCard>(`/api/deals/${channelId}/${action}`, { method: 'POST' }));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const title = conv?.title ?? (kind === 'assistant' ? 'Mandi Mitra' : '');
  const showIntro = kind === 'assistant' && messages !== null && messages.length < 2;

  return (
    <section className={`chatroom kind-${kind}`} aria-label={title}>
      <header className="chat-head" hidden={hideHeader}>
        {onBack && (
          <button className="icon-btn" onClick={onBack} aria-label={t.back}>
            <Icon name="back" />
          </button>
        )}
        <Avatar name={title} role={kind === 'assistant' ? 'bot' : kind === 'deal' ? 'deal' : kind} />
        <div className="chat-head-text">
          <h2>{title}</h2>
          <p>
            {typingUser
              ? `${profiles[typingUser]?.name ?? ''} ${t.typing}`
              : status !== 'connected'
                ? t.connecting
                : kind === 'deal'
                  ? `${conv?.subtitle ?? ''}, ${t.statusNames[deal?.status ?? conv?.status ?? 'negotiating']}`
                  : conv?.subtitle}
          </p>
        </div>
        {kind === 'deal' && (dealStatus === 'agreed' || dealStatus === 'completed') && (
          <button className="icon-btn" onClick={() => setReceiptOpen(true)} aria-label={t.receipt} title={t.receipt}>
            <Icon name="receipt" />
          </button>
        )}
        {kind !== 'support' && me?.role !== 'agent' && (
          <button className="btn ghost small" onClick={getHelp}>
            <Icon name="support" size={18} /> <span className="hide-sm">{t.getHelp}</span>
          </button>
        )}
      </header>
      {kind === 'deal' && deal && <Stepper status={deal.status} t={t} />}

      <div className="chat-scroll" ref={scroller} onScroll={onScroll} aria-live="polite">
        {messages === null && <div className="chat-loading">{t.connecting}</div>}
        {showIntro && (
          <div className="mitra-intro">
            <Icon name="spark" size={28} />
            <p>{t.mitraIntro}</p>
            <div className="suggest">
              {t.suggestions.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages?.map((m, i) => {
          const prev = messages[i - 1];
          const grouped = !!prev && prev.senderUserId === m.senderUserId && m.sentTime - prev.sentTime < 120000 && prev.messageType === MSG_TEXT;
          const newDay = !prev || new Date(prev.sentTime).toDateString() !== new Date(m.sentTime).toDateString();
          return (
            <Fragment key={m.messageId}>
            {newDay && <div className="day-sep"><span>{dayLabel(m.sentTime, lang, t)}</span></div>}
            <MessageView
              m={m}
              grouped={grouped}
              mine={m.senderUserId === me?.id}
              senderName={m.senderUserId === BOT_ID ? 'Mandi Mitra' : profiles[m.senderUserId]?.name ?? ''}
              senderRole={m.senderUserId === BOT_ID ? 'bot' : profiles[m.senderUserId]?.role}
              senderLang={profiles[m.senderUserId]?.language}
              lang={lang}
              t={t}
              deal={m.messageId === latestDealMsgId ? deal : null}
              meId={me?.id ?? ''}
              onDeal={dealAction}
              showName={channelType === GROUP}
            />
            </Fragment>
          );
        })}
        {thinking && (
          <div className="msg theirs bot thinking">
            <div className="bubble"><span className="dots"><i /><i /><i /></span></div>
          </div>
        )}
        {rated === false && deal && <RateCard dealId={channelId} t={t} onDone={() => setRated(true)} />}
      </div>

      {away && (
        <button className="jump-latest" onClick={jumpToLatest}>
          <Icon name="down" size={18} /> {unseen > 0 ? `${unseen} ${t.latest}` : t.latest}
        </button>
      )}

      {(kind === 'deal' || replies.length > 0) && (
        <div className="deal-actions" role="toolbar" aria-label="Quick replies">
          {kind === 'deal' && (dealStatus === 'negotiating' || dealStatus === 'proposed' || !deal) && (
            <>
              <button className="chip strong" onClick={() => setOfferOpen(true)}><Icon name="handshake" size={18} /> {t.makeOffer}</button>
              <button className="chip ai" onClick={askAi}><Icon name="spark" size={18} /> {t.askMitra}</button>
            </>
          )}
          {kind === 'deal' && dealStatus === 'agreed' && me?.id === deal?.buyerId && (
            <button className="chip strong" onClick={confirmDelivery}><Icon name="truck" size={18} /> {t.confirmDelivery}</button>
          )}
          {kind === 'deal' && (dealStatus === 'agreed' || dealStatus === 'completed') && (
            <button className="chip" onClick={() => setReceiptOpen(true)}><Icon name="receipt" size={18} /> {t.receipt}</button>
          )}
          {replies.map((r) => (
            <button key={r} className="chip reply" onClick={() => send(r)}>{r}</button>
          ))}
        </div>
      )}

      <Composer
        lang={lang}
        t={t}
        disabled={!transport}
        onSend={send}
        onTyping={() => transport?.sendTyping(channelType, channelId)}
        onVoice={sendVoice}
      />

      {kind === 'deal' && (
        <OfferSheet open={offerOpen} onClose={() => setOfferOpen(false)} dealId={channelId} deal={deal} messages={messages ?? []}
          onDone={(d) => { setDeal(d); setOfferOpen(false); }} />
      )}
      {kind === 'deal' && <ReceiptSheet open={receiptOpen} onClose={() => setReceiptOpen(false)} dealId={channelId} />}
    </section>
  );
}

function dayLabel(ms: number, lang: Lang, t: T) {
  const d = new Date(ms);
  const today = new Date();
  const yest = new Date(Date.now() - 864e5);
  if (d.toDateString() === today.toDateString()) return t.today;
  if (d.toDateString() === yest.toDateString()) return t.yesterday;
  const locale = lang === 'bn' ? 'bn-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN';
  return d.toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'short' });
}

/* ------------------------------------------------------------ rating */
function RateCard({ dealId, t, onDone }: { dealId: string; t: T; onDone: () => void }) {
  const { toast } = useStore();
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState('');
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/api/deals/${dealId}/review`, { method: 'POST', json: { stars, comment } });
      setDone(true);
      window.setTimeout(onDone, 2200);
    } catch (err) {
      toast((err as Error).message);
    }
  };
  return (
    <form className="card rate-card" onSubmit={submit}>
      {done ? (
        <p className="thanks"><Icon name="check" /> {t.rateThanks}</p>
      ) : (
        <>
          <h3><Icon name="star" size={18} /> {t.rateTrade}</h3>
          <Stars value={stars} onChange={setStars} label={t.rateTrade} size={28} />
          {stars > 0 && (
            <>
              <input value={comment} maxLength={300} onChange={(e) => setComment(e.target.value)} placeholder={t.ratePlaceholder} />
              <button className="btn primary">{t.sendFeedback}</button>
            </>
          )}
        </>
      )}
    </form>
  );
}

/* ------------------------------------------------------------ receipt */
function ReceiptSheet({ open, onClose, dealId }: { open: boolean; onClose: () => void; dealId: string }) {
  const { t, lang, toast } = useStore();
  const [r, setR] = useState<Receipt | null>(null);
  useEffect(() => {
    if (open) api<Receipt>(`/api/deals/${dealId}/receipt`).then(setR).catch((e) => toast((e as Error).message));
  }, [open, dealId, toast]);
  const shareText = r
    ? `MandiLink ${t.receipt} ${r.receiptNo}\n${r.cropNames[lang]}: ${fmtNum(r.quantityKg ?? 0, lang)} kg × ${fmtRs(r.pricePerKg ?? 0, lang)}/kg = ${fmtRs(r.totalRs, lang)}\n${t.sellerLbl}: ${r.seller?.name} · ${t.buyerLbl}: ${r.buyer?.name}`
    : '';
  const share = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ title: `MandiLink ${r?.receiptNo}`, text: shareText });
        return;
      } catch {
        /* user cancelled: fall through to WhatsApp */
      }
    }
    window.open(`https://wa.me/?text=${encodeURIComponent(shareText)}`, '_blank', 'noopener');
  };
  return (
    <Sheet open={open} onClose={onClose} title={t.receipt}>
      {r ? (
        <div className="receipt" id="receipt-print">
          <header className="receipt-head">
            <div className="brand small"><img src="/icon.svg" alt="" width={28} height={28} /> MandiLink</div>
            <div className="receipt-no">#{r.receiptNo}</div>
          </header>
          <div className={`receipt-status st-${r.status}`}>
            <Icon name="check" size={18} /> {t.statusNames[r.status]}
            {r.agreedAt && <span> · {t.agreedOn} {new Date(r.agreedAt).toLocaleDateString(lang === 'en' ? 'en-IN' : `${lang}-IN`)}</span>}
          </div>
          <div className="receipt-parties">
            <div><dt>{t.sellerLbl}</dt><dd>{r.seller?.name}</dd><small>{r.seller?.district}</small></div>
            <div><dt>{t.buyerLbl}</dt><dd>{r.buyer?.name}</dd><small>{r.buyer?.district}</small></div>
          </div>
          <dl className="receipt-lines">
            <div><dt>{t.crop}</dt><dd>{CROP_EMOJI[r.crop]} {r.cropNames[lang]}{r.variety && ` · ${r.variety}`} · {t.grade} {r.grade}</dd></div>
            <div><dt>{t.quantity}</dt><dd>{fmtNum(r.quantityKg ?? 0, lang)} kg</dd></div>
            <div><dt>₹/kg</dt><dd>{fmtRs(r.pricePerKg ?? 0, lang)}</dd></div>
            {r.pickupDistrict && <div><dt>{t.pickup}</dt><dd>{r.pickupDistrict}</dd></div>}
            <div className="total"><dt>{t.total}</dt><dd>{fmtRs(r.totalRs, lang)}</dd></div>
          </dl>
          <p className="receipt-note">{t.receiptNote}</p>
          <div className="row-btns no-print">
            <button className="btn ghost" onClick={() => window.print()}><Icon name="print" size={18} /> {t.print}</button>
            <button className="btn primary" onClick={share}><Icon name="share" size={18} /> {t.share}</button>
          </div>
        </div>
      ) : (
        <div className="chat-loading">…</div>
      )}
    </Sheet>
  );
}

/* ------------------------------------------------------------ message */
function MessageView({ m, mine, grouped, senderName, senderRole, senderLang, lang, t, deal, meId, onDeal, showName }: {
  m: ChatMessage; mine: boolean; grouped: boolean; senderName: string; senderRole?: string; senderLang?: Lang;
  lang: Lang; t: T; deal: DealCard | null; meId: string; onDeal: (a: 'accept' | 'decline') => void; showName: boolean;
}) {
  if (m.messageType === MSG_NOTICE) return <NoticeView m={m} t={t} />;
  if (m.messageType === MSG_LISTING) return <ListingCardView m={m} lang={lang} t={t} />;
  if (m.messageType === MSG_DEAL) return <DealCardView card={(deal ?? m.content) as DealCard} live={!!deal} meId={meId} lang={lang} t={t} onDeal={onDeal} />;
  if (m.messageType !== MSG_TEXT && m.messageType !== MSG_VOICE) return null;
  const isBot = senderRole === 'bot';
  return (
    <div className={`msg ${mine ? 'mine' : 'theirs'} ${isBot ? 'bot' : ''} ${grouped ? 'grouped' : ''} ${m.failed ? 'failed' : ''}`}>
      {!mine && !grouped && showName && (
        <span className="msg-name">
          {senderName}
          {isBot && <span className="ai-tag">{t.aiTag}</span>}
        </span>
      )}
      {m.messageType === MSG_VOICE
        ? <VoiceBubble m={m} mine={mine} lang={lang} t={t} />
        : <TextBubble m={m} mine={mine} lang={lang} t={t} senderLang={m.content.extraData?.lang ?? senderLang} />}
    </div>
  );
}

function TextBubble({ m, mine, lang, t, senderLang }: { m: ChatMessage; mine: boolean; lang: Lang; t: T; senderLang?: Lang }) {
  const variant: string | undefined = m.content.extraData?.variants?.[lang];
  const text: string = variant ?? m.content.text ?? '';
  const { needs, loading, result, source } = useTranslated(text, lang, variant ? lang : senderLang, !mine && !variant);
  const [showOriginal, setShowOriginal] = useState(false);
  const translated = needs && result?.translated;
  const shown = translated && !showOriginal ? result!.text : text;
  const shownLang: Lang = translated && !showOriginal ? lang : source;
  const sourceName = LANGS.find((l) => l.code === source)?.native;
  return (
    <div className="bubble">
      <p className="bubble-text" lang={shownLang}>{shown}</p>
      {translated && !showOriginal && <p className="bubble-orig" lang={source}>{text}</p>}
      <div className="bubble-foot">
        {needs && (loading ? (
          <span className="tr-state"><Icon name="globe" size={14} /> …</span>
        ) : translated ? (
          <button className="tr-toggle" onClick={() => setShowOriginal((v) => !v)}>
            <Icon name="globe" size={14} /> {showOriginal ? t.showTranslation : `${t.translatedFrom} ${sourceName}`}
          </button>
        ) : null)}
        <button className="speak-btn" onClick={() => speak(shown, shownLang)} aria-label={t.readAloud} title={t.readAloud}>
          <Icon name="speaker" size={15} />
        </button>
        <time>{m.pending ? '…' : m.failed ? '!' : fmtTime(m.sentTime, lang)}</time>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ voice */
function fmtDur(ms: number) {
  const sec = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

function VoiceBubble({ m, mine, lang, t }: { m: ChatMessage; mine: boolean; lang: Lang; t: T }) {
  const c = m.content as { url: string; durationMs: number; transcript?: string; lang?: Lang; uploading?: boolean };
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const transcript = c.transcript ?? '';
  const { needs, loading, result, source } = useTranslated(transcript, lang, c.lang, !mine && !!transcript);
  const [showOriginal, setShowOriginal] = useState(false);
  const translated = needs && result?.translated;
  const shown = translated && !showOriginal ? result!.text : transcript;

  useEffect(() => () => audio.current?.pause(), []);
  const toggle = () => {
    if (!c.url) return;
    if (!audio.current) {
      const a = new Audio(c.url);
      a.ontimeupdate = () => setPos(a.currentTime * 1000);
      a.onended = () => { setPlaying(false); setPos(0); };
      audio.current = a;
    }
    if (playing) {
      audio.current.pause();
      setPlaying(false);
    } else {
      void audio.current.play();
      setPlaying(true);
    }
  };
  const pct = c.durationMs ? Math.min(100, (pos / c.durationMs) * 100) : 0;
  return (
    <div className="bubble voice-bubble">
      <div className="voice-row">
        <button className="voice-play" onClick={toggle} disabled={!c.url} aria-label={playing ? t.pauseVoice : t.playVoice}>
          <Icon name={playing ? 'pause' : 'play'} size={18} />
        </button>
        <span className="voice-wave" aria-hidden style={{ ['--pct' as string]: `${pct}%` }}>
          {Array.from({ length: 28 }, (_, i) => <i key={i} className={(i / 28) * 100 < pct ? 'on' : ''} style={{ height: `${30 + ((i * 37) % 70)}%` }} />)}
        </span>
        <span className="voice-dur">{fmtDur(playing ? pos : c.durationMs)}</span>
      </div>
      {c.uploading ? (
        <p className="voice-transcript muted"><Icon name="spark" size={13} /> {t.transcribing}</p>
      ) : transcript ? (
        <>
          <p className="voice-transcript" lang={translated && !showOriginal ? lang : source}>{shown}</p>
          {translated && !showOriginal && <p className="bubble-orig" lang={source}>{transcript}</p>}
        </>
      ) : null}
      <div className="bubble-foot">
        {needs && (loading ? <span className="tr-state"><Icon name="globe" size={14} /> …</span> : translated ? (
          <button className="tr-toggle" onClick={() => setShowOriginal((v) => !v)}>
            <Icon name="globe" size={14} /> {showOriginal ? t.showTranslation : `${t.translatedFrom} ${LANGS.find((l) => l.code === source)?.native}`}
          </button>
        ) : null)}
        {!needs && transcript && <span className="tr-state"><Icon name="spark" size={13} /> {t.transcript}</span>}
        <time>{m.pending ? '…' : m.failed ? '!' : fmtTime(m.sentTime, lang)}</time>
      </div>
    </div>
  );
}

function NoticeView({ m, t }: { m: ChatMessage; t: T }) {
  const c = m.content as { kind: string; agent?: string; buyer?: string; seller?: string };
  const text =
    c.kind === 'deal_opened' ? t.dealOpened
      : c.kind === 'ticket_opened' ? t.ticketOpened
        : c.kind === 'agent_joined' ? `${c.agent} ${t.agentJoined}`
          : c.kind === 'ticket_resolved' ? `${c.agent} ${t.ticketResolved}`
            : c.kind === 'delivered' ? `${c.buyer} ${t.deliveredNotice}` : '';
  if (!text) return null;
  return <div className={`notice notice-${c.kind}`}><span>{text}</span></div>;
}

function ListingCardView({ m, lang, t }: { m: ChatMessage; lang: Lang; t: T }) {
  const c = m.content as { crop: string; cropNames: Record<Lang, string>; variety: string; quantityKg: number; pricePerKg: number; district: string; sellerName: string; mandi: MandiInfo | null };
  return (
    <article className="card listing-card" style={{ ['--tint' as string]: CROP_TINT[c.crop] }}>
      <header>
        <span className="detail-emoji" aria-hidden>{CROP_EMOJI[c.crop]}</span>
        <div>
          <p className="card-kicker">{t.enquiry}</p>
          <h3>{c.cropNames?.[lang] ?? c.crop}{c.variety && <em> {c.variety}</em>}</h3>
          <p className="card-sub">{fmtNum(c.quantityKg, lang)} kg · {c.sellerName}{c.district && `, ${c.district}`}</p>
        </div>
        <p className="card-price">{fmtRs(c.pricePerKg, lang)}<small>{t.perKg}</small></p>
      </header>
      {c.mandi && <RateBand info={c.mandi} price={c.pricePerKg} lang={lang} t={t} compact />}
    </article>
  );
}

function DealCardView({ card, live, meId, lang, t, onDeal }: { card: DealCard; live: boolean; meId: string; lang: Lang; t: T; onDeal: (a: 'accept' | 'decline') => void }) {
  const iAccepted = meId === card.buyerId ? card.buyerAccepted : card.sellerAccepted;
  const declined = card.status === 'negotiating';
  const state = card.status === 'agreed' || card.status === 'completed' ? 'agreed' : declined ? 'declined' : 'proposed';
  return (
    <article className={`card deal-card state-${state}`}>
      <header>
        <Icon name={state === 'agreed' ? 'check' : 'handshake'} size={22} />
        <h3>{card.status === 'completed' ? t.statusNames.completed : state === 'agreed' ? t.dealAgreed : state === 'declined' ? t.offerDeclined : t.offer}</h3>
      </header>
      <dl className="deal-terms">
        <div><dt>{t.crop}</dt><dd>{card.cropNames?.[lang] ?? card.crop}</dd></div>
        <div><dt>{t.quantity}</dt><dd>{fmtNum(card.quantityKg ?? 0, lang)}</dd></div>
        <div><dt>₹/kg</dt><dd>{fmtRs(card.pricePerKg ?? 0, lang)}</dd></div>
        <div className="total"><dt>{t.total}</dt><dd>{fmtRs(card.totalRs, lang)}</dd></div>
      </dl>
      {live && state === 'proposed' && (
        iAccepted ? (
          <p className="deal-wait">{t.waitingFor}</p>
        ) : (
          <div className="row-btns">
            <button className="btn ghost" onClick={() => onDeal('decline')}>{t.decline}</button>
            <button className="btn primary" onClick={() => onDeal('accept')}><Icon name="check" size={18} /> {t.accept}</button>
          </div>
        )
      )}
    </article>
  );
}

/* ------------------------------------------------------------ composer */
function Composer({ lang, t, disabled, onSend, onTyping, onVoice }: {
  lang: Lang; t: T; disabled: boolean; onSend: (text: string) => void; onTyping: () => void; onVoice: (clip: VoiceClip) => void;
}) {
  const { toast } = useStore();
  const [text, setText] = useState('');
  const lastTyping = useRef(0);
  const base = useRef('');
  const voice = useVoiceTyping(lang, (spoken, final) => {
    setText((base.current ? base.current + ' ' : '') + spoken);
    if (final) base.current = '';
  });
  const rec = useVoiceRecorder(onVoice, (k) => toast(k === 'blocked' ? t.micBlocked : k === 'short' ? t.voiceTooShort : t.error));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = text.trim();
    if (!v) return;
    voice.stop();
    onSend(v);
    setText('');
  };

  if (rec.recording) {
    return (
      <div className="composer recording" role="status" aria-live="polite">
        <button type="button" className="mic-btn" onClick={rec.cancel} aria-label={t.cancel} title={t.cancel}><Icon name="close" /></button>
        <span className="rec-bar">
          <i className="rec-dot" /> <b>{fmtDur(rec.elapsed)}</b> <span className="rec-hint">{t.recording}</span>
          <span className="rec-meter" style={{ ['--p' as string]: `${(rec.elapsed / 60000) * 100}%` }} />
        </span>
        <button type="button" className="send-btn rec-stop" onClick={rec.stop} aria-label={t.send}><Icon name="stop" /></button>
      </div>
    );
  }

  const showRecord = !text.trim() && rec.supported;
  return (
    <form className="composer" onSubmit={submit}>
      {voice.supported && (
        <button
          type="button"
          className={`mic-btn ${voice.listening ? 'on' : ''}`}
          aria-label={voice.listening ? t.listening : t.speak}
          title={t.speak}
          aria-pressed={voice.listening}
          onClick={() => {
            if (voice.listening) voice.stop();
            else {
              base.current = text.trim();
              voice.start();
            }
          }}
        >
          <Icon name="mic" />
        </button>
      )}
      <input
        value={text}
        lang={lang}
        onChange={(e) => {
          setText(e.target.value);
          if (Date.now() - lastTyping.current > 3000) {
            lastTyping.current = Date.now();
            onTyping();
          }
        }}
        placeholder={voice.listening ? t.listening : t.typeMessage}
        aria-label={t.typeMessage}
        maxLength={2000}
        disabled={disabled}
      />
      {showRecord ? (
        <button type="button" className="send-btn voice-rec" aria-label={t.voiceNote} title={t.voiceNote} disabled={disabled}
          onClick={() => { voice.stop(); void rec.start(); }}>
          <Icon name="wave" />
        </button>
      ) : (
        <button className="send-btn" aria-label={t.send} disabled={disabled || !text.trim()}>
          <Icon name="send" />
        </button>
      )}
    </form>
  );
}

/* ------------------------------------------------------------ offer */
function OfferSheet({ open, onClose, dealId, deal, messages, onDone }: {
  open: boolean; onClose: () => void; dealId: string; deal: DealCard | null; messages: ChatMessage[]; onDone: (d: DealCard) => void;
}) {
  const { t, lang, toast } = useStore();
  const listing = messages.find((m) => m.messageType === MSG_LISTING)?.content as { quantityKg: number; pricePerKg: number; mandi: MandiInfo | null } | undefined;
  const [qty, setQty] = useState('');
  const [price, setPrice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setQty(String(deal?.quantityKg ?? listing?.quantityKg ?? ''));
    setPrice(String(deal?.pricePerKg ?? listing?.pricePerKg ?? ''));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      onDone(await api<DealCard>(`/api/deals/${dealId}/propose`, { method: 'POST', json: { quantity_kg: Number(qty), price_per_kg: Number(price) } }));
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const total = (Number(qty) || 0) * (Number(price) || 0);
  return (
    <Sheet open={open} onClose={onClose} title={t.makeOffer}>
      <form className="form" onSubmit={submit}>
        <div className="two-col">
          <label>{t.quantity}<input required inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></label>
          <label>₹/kg<input required inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
        </div>
        {listing?.mandi && <RateBand info={listing.mandi} price={Number(price) || null} lang={lang} t={t} />}
        <p className="offer-total">{t.total}: <strong>{fmtRs(Math.round(total), lang)}</strong></p>
        <button className="btn primary wide" disabled={busy}><Icon name="handshake" size={18} /> {t.sendOffer}</button>
      </form>
    </Sheet>
  );
}
