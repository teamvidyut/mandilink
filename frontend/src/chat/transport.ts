/**
 * Chat transport abstraction.
 *
 *  - NexconnTransport: the real thing. Every message is sent and received
 *    through the Nexconn Chat SDK (@nexconn/chat): NCEngine, DirectChannel,
 *    GroupChannel, MessageHandler, ChannelHandler (typing), custom messages.
 *  - DemoTransport: local WebSocket stand-in used only when the server has no
 *    Nexconn credentials, so the app can be developed and demoed offline.
 */
import {
  BaseChannel,
  ChannelHandler,
  ConnectionStatus,
  ConnectionStatusHandler,
  DirectChannel,
  DirectChannelIdentifier,
  GroupChannel,
  GroupChannelIdentifier,
  LogLevel,
  MessageHandler,
  NCEngine,
  SendMessageParams,
  SendTextMessageParams,
  type Message,
} from '@nexconn/chat';
import { getSessionToken, api } from '../api';

export const DIRECT = 1 as const;
export const GROUP = 3 as const;
export type ChannelType = typeof DIRECT | typeof GROUP;

export const MSG_TEXT = 'RC:TxtMsg';
export const MSG_LISTING = 'ML:Listing';
export const MSG_DEAL = 'ML:Deal';
export const MSG_NOTICE = 'ML:Notice';
/** Voice message: {url, durationMs, transcript, lang}. Audio lives on the MandiLink server. */
export const MSG_VOICE = 'ML:Voice';
/** Typing signal for group channels (the SDK's sendTypingStatus is direct-only). Not stored or counted. */
export const MSG_TYPING = 'ML:Typing';

export interface ChatMessage {
  messageId: string;
  channelType: ChannelType;
  channelId: string;
  senderUserId: string;
  messageType: string;
  content: Record<string, any>;
  sentTime: number;
  pending?: boolean;
  failed?: boolean;
}

export type Status = 'connecting' | 'connected' | 'offline';

export interface Transport {
  readonly kind: 'nexconn' | 'demo';
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  sendText(type: ChannelType, channelId: string, text: string, extra?: Record<string, unknown>): Promise<ChatMessage>;
  sendTyping(type: ChannelType, channelId: string): void;
  sendCustom(type: ChannelType, channelId: string, messageType: string, content: Record<string, unknown>): Promise<ChatMessage>;
  history(type: ChannelType, channelId: string, count?: number): Promise<ChatMessage[]>;
  onMessage(cb: (m: ChatMessage) => void): () => void;
  onTyping(cb: (e: { channelType: ChannelType; channelId: string; userId: string }) => void): () => void;
  onStatus(cb: (s: Status) => void): () => void;
}

class Emitter<T> {
  private subs = new Set<(v: T) => void>();
  on(cb: (v: T) => void) {
    this.subs.add(cb);
    return () => {
      this.subs.delete(cb);
    };
  }
  emit(v: T) {
    this.subs.forEach((cb) => cb(v));
  }
}

function parseExtra(content: Record<string, any>) {
  if (typeof content?.extra === 'string') {
    try {
      return { ...content, extraData: JSON.parse(content.extra) };
    } catch {
      return content;
    }
  }
  return content;
}

// ------------------------------------------------------------------ Nexconn
export class NexconnTransport implements Transport {
  readonly kind = 'nexconn' as const;
  private messages = new Emitter<ChatMessage>();
  private typing = new Emitter<{ channelType: ChannelType; channelId: string; userId: string }>();
  private status = new Emitter<Status>();
  private static initialized = false;

  constructor(private appKey: string, private token: string) {}

  private normalize(m: Message<any>): ChatMessage {
    const id = m.channelIdentifier;
    return {
      messageId: m.messageId || String(m.clientId),
      channelType: id.channelType as ChannelType,
      channelId: id.channelId,
      senderUserId: m.senderUserId,
      messageType: m.messageType,
      content: parseExtra({ ...(m.content as Record<string, any>) }),
      sentTime: m.sentTime,
    };
  }

  private channel(type: ChannelType, id: string): BaseChannel {
    return type === DIRECT ? new DirectChannel(id) : new GroupChannel(id);
  }

  async connect() {
    if (!NexconnTransport.initialized) {
      NCEngine.initialize({ appKey: this.appKey, logLevel: import.meta.env.DEV ? LogLevel.INFO : LogLevel.WARN });
      // MandiLink structured cards travel as Nexconn custom messages.
      NCEngine.registerCustomMessages([
        { messageType: MSG_LISTING, isPersisted: true, isCounted: true },
        { messageType: MSG_DEAL, isPersisted: true, isCounted: true },
        { messageType: MSG_NOTICE, isPersisted: true, isCounted: false },
        { messageType: MSG_VOICE, isPersisted: true, isCounted: true },
        { messageType: MSG_TYPING, isPersisted: false, isCounted: false },
      ]);
      NexconnTransport.initialized = true;
    }
    NCEngine.addConnectionStatusHandler(
      'mandilink',
      new ConnectionStatusHandler({
        onConnectionStatusChanged: ({ status }) => {
          this.status.emit(
            status === ConnectionStatus.CONNECTED ? 'connected' : status === ConnectionStatus.CONNECTING ? 'connecting' : 'offline',
          );
        },
      }),
    );
    NCEngine.addMessageHandler(
      'mandilink',
      new MessageHandler({
        onMessageReceived: ({ messages }) =>
          messages.forEach((m) => {
            const msg = this.normalize(m);
            if (msg.messageType === MSG_TYPING) {
              this.typing.emit({ channelType: msg.channelType, channelId: msg.channelId, userId: msg.senderUserId });
            } else this.messages.emit(msg);
          }),
      }),
    );
    NCEngine.addChannelHandler(
      'mandilink',
      new ChannelHandler({
        onTypingStatusChanged: ({ channelIdentifier, userTypingStatus }) => {
          userTypingStatus.forEach((u) =>
            this.typing.emit({
              channelType: channelIdentifier.channelType as ChannelType,
              channelId: channelIdentifier.channelId,
              userId: u.userId,
            }),
          );
        },
      }),
    );
    this.status.emit('connecting');
    const res = await NCEngine.connect({ token: this.token });
    if (!res.isOk) {
      this.status.emit('offline');
      throw new Error(`Nexconn connect failed (code ${res.code})`);
    }
    this.status.emit('connected');
  }

  async disconnect() {
    NCEngine.removeMessageHandler('mandilink');
    NCEngine.removeChannelHandler('mandilink');
    NCEngine.removeConnectionStatusHandler('mandilink');
    await NCEngine.disconnect();
  }

  async sendText(type: ChannelType, channelId: string, text: string, extra?: Record<string, unknown>) {
    const params = new SendTextMessageParams({ text, extra: extra ? JSON.stringify(extra) : undefined });
    const res = await this.channel(type, channelId).sendMessage(params as SendMessageParams<any>);
    if (!res.isOk || !res.data) throw new Error(`Send failed (code ${res.code})`);
    return this.normalize(res.data);
  }

  sendTyping(type: ChannelType, channelId: string) {
    if (type === DIRECT) {
      void new DirectChannel(channelId).sendTypingStatus(MSG_TEXT);
      return;
    }
    // Group channels: a silent, non-persisted custom message carries the typing signal.
    const params = new SendMessageParams<Record<string, unknown>>({ t: Date.now() }, MSG_TYPING);
    params.disableNotification = true;
    params.disableUpdateLastMessage = true;
    void new GroupChannel(channelId).sendMessage(params).catch(() => undefined);
  }

  async sendCustom(type: ChannelType, channelId: string, messageType: string, content: Record<string, unknown>) {
    const params = new SendMessageParams<Record<string, unknown>>(content, messageType);
    params.pushConfig = { pushTitle: 'MandiLink' } as SendMessageParams['pushConfig'];
    const res = await this.channel(type, channelId).sendMessage(params);
    if (!res.isOk || !res.data) throw new Error(`Send failed (code ${res.code})`);
    return this.normalize(res.data);
  }

  async history(type: ChannelType, channelId: string, count = 40) {
    const identifier = type === DIRECT ? new DirectChannelIdentifier(channelId) : new GroupChannelIdentifier(channelId);
    const query = BaseChannel.createMessagesQuery({ channelIdentifier: identifier, pageSize: count, isAscending: false });
    const res = await query.loadNextPage();
    if (!res.isOk || !res.data) return [];
    return res.data.data.map((m) => this.normalize(m)).sort((a, b) => a.sentTime - b.sentTime);
  }

  onMessage(cb: (m: ChatMessage) => void) {
    return this.messages.on(cb);
  }
  onTyping(cb: (e: { channelType: ChannelType; channelId: string; userId: string }) => void) {
    return this.typing.on(cb);
  }
  onStatus(cb: (s: Status) => void) {
    return this.status.on(cb);
  }
}

// --------------------------------------------------------------------- Demo
export class DemoTransport implements Transport {
  readonly kind = 'demo' as const;
  private ws: WebSocket | null = null;
  private messages = new Emitter<ChatMessage>();
  private typing = new Emitter<{ channelType: ChannelType; channelId: string; userId: string }>();
  private status = new Emitter<Status>();
  private pending = new Map<string, { resolve: (m: ChatMessage) => void; reject: (e: Error) => void }>();
  private closed = false;
  private retry = 0;

  connect(): Promise<void> {
    this.closed = false;
    return new Promise((resolve) => {
      const open = () => {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${proto}://${location.host}/api/dev/ws?token=${encodeURIComponent(getSessionToken() || '')}`);
        this.ws = ws;
        this.status.emit('connecting');
        ws.onopen = () => {
          this.retry = 0;
          this.status.emit('connected');
          resolve();
        };
        ws.onmessage = (ev) => {
          const data = JSON.parse(ev.data);
          if (data.op === 'message') this.messages.emit({ ...data.message, content: parseExtra(data.message.content) });
          else if (data.op === 'typing') this.typing.emit(data);
          else if (data.op === 'ack') {
            this.pending.get(data.reqId)?.resolve({ ...data.message, content: parseExtra(data.message.content) });
            this.pending.delete(data.reqId);
          } else if (data.op === 'error') {
            this.pending.get(data.reqId)?.reject(new Error(`Send failed (${data.code})`));
            this.pending.delete(data.reqId);
          }
        };
        ws.onclose = () => {
          this.status.emit('offline');
          this.pending.forEach((p) => p.reject(new Error('Disconnected')));
          this.pending.clear();
          if (this.closed) return;
          // A tab opened while the server was in demo mode keeps this transport after the
          // server switches to real Nexconn. Reload once, so it picks up the Nexconn SDK.
          fetch('/api/health')
            .then((r) => r.json())
            .then((h: { demoMode?: boolean }) => {
              if (h.demoMode === false) location.reload();
              else setTimeout(open, Math.min(8000, 500 * 2 ** this.retry++));
            })
            .catch(() => setTimeout(open, Math.min(8000, 500 * 2 ** this.retry++)));
        };
      };
      open();
    });
  }

  async disconnect() {
    this.closed = true;
    this.ws?.close();
  }

  sendText(type: ChannelType, channelId: string, text: string, extra?: Record<string, unknown>) {
    return new Promise<ChatMessage>((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return reject(new Error('Offline'));
      const reqId = Math.random().toString(36).slice(2);
      this.pending.set(reqId, { resolve, reject });
      const content: Record<string, unknown> = { text };
      if (extra) content.extra = JSON.stringify(extra);
      this.ws.send(JSON.stringify({ op: 'send', reqId, channelType: type, channelId, messageType: MSG_TEXT, content }));
    });
  }

  sendTyping(type: ChannelType, channelId: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ op: 'typing', channelType: type, channelId }));
  }

  sendCustom(type: ChannelType, channelId: string, messageType: string, content: Record<string, unknown>) {
    return new Promise<ChatMessage>((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return reject(new Error('Offline'));
      const reqId = Math.random().toString(36).slice(2);
      this.pending.set(reqId, { resolve, reject });
      this.ws.send(JSON.stringify({ op: 'send', reqId, channelType: type, channelId, messageType, content }));
    });
  }

  async history(type: ChannelType, channelId: string, count = 40) {
    const rows = await api<ChatMessage[]>(`/api/dev/history?channel_type=${type}&channel_id=${encodeURIComponent(channelId)}&limit=${count}`);
    return rows.map((m) => ({ ...m, content: parseExtra(m.content) }));
  }

  onMessage(cb: (m: ChatMessage) => void) {
    return this.messages.on(cb);
  }
  onTyping(cb: (e: { channelType: ChannelType; channelId: string; userId: string }) => void) {
    return this.typing.on(cb);
  }
  onStatus(cb: (s: Status) => void) {
    return this.status.on(cb);
  }
}
