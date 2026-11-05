import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, getSessionToken, setSessionToken, type Conversation, type Me, type Profile, type SessionPayload } from './api';
import { DICTS, type Lang, type T } from './i18n';
import { DemoTransport, NexconnTransport, type ChatMessage, type Status, type Transport } from './chat/transport';

interface Store {
  me: Me | null;
  lang: Lang;
  t: T;
  booting: boolean;
  demoMode: boolean;
  status: Status;
  transport: Transport | null;
  conversations: Conversation[];
  lastMessages: Record<string, ChatMessage>;
  unread: Record<string, number>;
  activeChannel: string | null;
  setActiveChannel: (id: string | null) => void;
  refreshConversations: () => Promise<void>;
  profiles: Record<string, Profile>;
  ensureProfiles: (ids: string[]) => void;
  signIn: (payload: SessionPayload) => Promise<void>;
  signOut: () => Promise<void>;
  setLang: (l: Lang) => void;
  updateMe: (m: Me) => void;
  toast: (msg: string) => void;
  toastMsg: string | null;
  theme: Theme;
  setTheme: (t: Theme) => void;
}

export type Theme = 'light' | 'dark' | 'system';
const THEME_KEY = 'mandilink.theme';

const Ctx = createContext<Store | null>(null);

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error('StoreProvider missing');
  return s;
}

const GUEST_LANG_KEY = 'mandilink.lang';

export function StoreProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [guestLang, setGuestLang] = useState<Lang>(() => {
    try {
      return (localStorage.getItem(GUEST_LANG_KEY) as Lang) || 'bn';
    } catch {
      return 'bn';
    }
  });
  const [booting, setBooting] = useState(true);
  const [demoMode, setDemoMode] = useState(false);
  const [status, setStatus] = useState<Status>('connecting');
  const [transport, setTransport] = useState<Transport | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [lastMessages, setLastMessages] = useState<Record<string, ChatMessage>>({});
  const [unread, setUnread] = useState<Record<string, number>>({});
  const [activeChannel, setActiveChannel] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Record<string, Profile>>({});
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      return (localStorage.getItem(THEME_KEY) as Theme) || 'system';
    } catch {
      return 'system';
    }
  });
  const setTheme = useCallback((th: Theme) => {
    setThemeState(th);
    try {
      localStorage.setItem(THEME_KEY, th);
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') delete root.dataset.theme;
    else root.dataset.theme = theme;
    const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0E1326' : '#1F2A5C');
  }, [theme]);
  const requested = useRef(new Set<string>());
  const activeRef = useRef<string | null>(null);
  activeRef.current = activeChannel;

  const lang: Lang = me?.language ?? guestLang;
  const t = DICTS[lang];

  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    window.setTimeout(() => setToastMsg((cur) => (cur === msg ? null : cur)), 3200);
  }, []);

  const ensureProfiles = useCallback((ids: string[]) => {
    const missing = ids.filter((id) => id && !requested.current.has(id));
    if (!missing.length) return;
    missing.forEach((id) => requested.current.add(id));
    api<Record<string, Profile>>(`/api/profiles?ids=${encodeURIComponent(missing.join(','))}`)
      .then((p) => setProfiles((cur) => ({ ...cur, ...p })))
      .catch(() => missing.forEach((id) => requested.current.delete(id)));
  }, []);

  const refreshConversations = useCallback(async () => {
    if (!getSessionToken()) return;
    try {
      setConversations(await api<Conversation[]>('/api/conversations'));
    } catch {
      /* keep the previous list */
    }
  }, []);

  const signIn = useCallback(
    async (payload: SessionPayload) => {
      setSessionToken(payload.session);
      setMe(payload.user);
      setProfiles((cur) => ({ ...cur, [payload.user.id]: { ...payload.user } as Profile }));
      setDemoMode(payload.nexconn.demoMode);
      const tr: Transport = payload.nexconn.demoMode
        ? new DemoTransport()
        : new NexconnTransport(payload.nexconn.appKey, payload.nexconn.token);
      tr.onStatus(setStatus);
      tr.onMessage((m) => {
        setLastMessages((cur) => ({ ...cur, [m.channelId]: m }));
        if (m.senderUserId !== payload.user.id && activeRef.current !== m.channelId) {
          setUnread((cur) => ({ ...cur, [m.channelId]: (cur[m.channelId] || 0) + 1 }));
        }
        if (m.messageType.startsWith('ML:')) void refreshConversations();
      });
      setTransport(tr);
      await refreshConversations();
      try {
        await tr.connect();
      } catch (e) {
        console.error(e);
        toast(String((e as Error).message));
      }
    },
    [refreshConversations, toast],
  );

  const signOut = useCallback(async () => {
    await transport?.disconnect().catch(() => undefined);
    setTransport(null);
    setSessionToken(null);
    setMe(null);
    setConversations([]);
    setLastMessages({});
    setUnread({});
  }, [transport]);

  const setLang = useCallback(
    (l: Lang) => {
      try {
        localStorage.setItem(GUEST_LANG_KEY, l);
      } catch {
        /* ignore */
      }
      setGuestLang(l);
      if (me) {
        setMe({ ...me, language: l });
        api<Me>('/api/auth/me', { method: 'PATCH', json: { language: l } }).then(setMe).catch(() => undefined);
      }
    },
    [me],
  );

  // Resume a saved session on reload: get a fresh Nexconn token.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) return; // StrictMode runs effects twice in dev
    resumed.current = true;
    if (!getSessionToken()) {
      setBooting(false);
      return;
    }
    api<SessionPayload>('/api/auth/refresh', { method: 'POST' })
      .then(signIn)
      .catch(() => setSessionToken(null))
      .finally(() => setBooting(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeChannel) setUnread((cur) => ({ ...cur, [activeChannel]: 0 }));
  }, [activeChannel]);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const value = useMemo<Store>(
    () => ({
      me, lang, t, booting, demoMode, status, transport, conversations, lastMessages, unread, activeChannel,
      setActiveChannel, refreshConversations, profiles, ensureProfiles, signIn, signOut, setLang,
      updateMe: setMe, toast, toastMsg, theme, setTheme,
    }),
    [me, lang, t, booting, demoMode, status, transport, conversations, lastMessages, unread, activeChannel,
      refreshConversations, profiles, ensureProfiles, signIn, signOut, setLang, toast, toastMsg, theme, setTheme],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
