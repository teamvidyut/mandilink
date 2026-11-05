import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { Conversation } from '../api';
import { fmtTime, type Lang, type T } from '../i18n';
import { useStore } from '../store';
import { Avatar } from '../components/ui';
import ChatRoom from './ChatRoom';
import type { ChannelType, ChatMessage } from '../chat/transport';
import { useTranslated } from '../chat/useTranslation';

function preview(m: ChatMessage | undefined, fallback: string, t: T, lang: Lang) {
  if (!m) return fallback;
  if (m.messageType === 'RC:TxtMsg') return m.content.extraData?.variants?.[lang] ?? m.content.text ?? '';
  if (m.messageType === 'ML:Voice') return '🎤 ' + (m.content.transcript || t.voiceLabel);
  if (m.messageType === 'ML:Deal') return '🤝 ' + (t.statusNames[m.content.status] ?? '');
  if (m.messageType === 'ML:Listing') return '🧺 ' + (m.content.cropNames?.[lang] ?? m.content.crop ?? '');
  return fallback;
}

/** Last-message preview, translated into the viewer's language like the chat itself. */
function ConvPreview({ m, fallback, t, lang, meId }: { m: ChatMessage | undefined; fallback: string; t: T; lang: Lang; meId?: string }) {
  const text = preview(m, fallback, t, lang);
  const isText = (m?.messageType === 'RC:TxtMsg' && !m.content.extraData?.variants?.[lang]) || (m?.messageType === 'ML:Voice' && !!m.content.transcript);
  const hint = m?.messageType === 'ML:Voice' ? m.content.lang : m?.content.extraData?.lang;
  const { needs, result } = useTranslated(text, lang, hint, isText && m?.senderUserId !== meId);
  return <>{needs && result?.translated ? result.text : text}</>;
}

const ORDER: Record<Conversation['kind'], number> = { assistant: 0, support: 1, deal: 2, room: 3 };

export default function Chats() {
  const { t, lang, me, conversations, lastMessages, unread, refreshConversations } = useStore();
  const { type, id } = useParams();
  const nav = useNavigate();
  const selected = id ? { channelType: Number(type) as ChannelType, channelId: id } : null;

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  const sorted = [...conversations].sort((a, b) => {
    const ta = lastMessages[a.channelId]?.sentTime ?? a.updatedAt ?? 0;
    const tb = lastMessages[b.channelId]?.sentTime ?? b.updatedAt ?? 0;
    if (a.kind === 'assistant' || b.kind === 'assistant') return ORDER[a.kind] - ORDER[b.kind];
    return tb - ta || ORDER[a.kind] - ORDER[b.kind];
  });

  return (
    <div className={`screen chats ${selected ? 'has-room' : ''}`}>
      <aside className="conv-pane">
        <header className="screen-head"><h1>{t.chats}</h1></header>
        {sorted.length <= 1 && <p className="empty small">{t.noChats}</p>}
        <ul className="conv-list">
          {sorted.map((c) => {
            const last = lastMessages[c.channelId];
            const n = unread[c.channelId] || 0;
            return (
              <li key={c.channelId}>
                <button
                  className={`conv-row kind-${c.kind} ${selected?.channelId === c.channelId ? 'on' : ''}`}
                  onClick={() => nav(`/chats/${c.channelType}/${c.channelId}`)}
                >
                  <Avatar name={c.title} role={c.kind === 'assistant' ? 'bot' : c.kind} />
                  <span className="conv-text">
                    <span className="conv-title">{c.title}</span>
                    <span className="conv-sub">
                      <ConvPreview m={last} meId={me?.id} t={t} lang={lang}
                        fallback={c.kind === 'deal' ? `${c.subtitle}, ${t.statusNames[c.status ?? 'negotiating']}` : c.subtitle} />
                    </span>
                  </span>
                  <span className="conv-side">
                    {last && <time>{fmtTime(last.sentTime, lang)}</time>}
                    {n > 0 && <span className="badge" aria-label={`${n} unread`}>{n}</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>
      <div className="room-pane">
        {selected ? (
          <ChatRoom key={selected.channelId} channelType={selected.channelType} channelId={selected.channelId} onBack={() => nav('/chats')} />
        ) : (
          <div className="room-empty"><p>{t.noChats}</p></div>
        )}
      </div>
    </div>
  );
}
