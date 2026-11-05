import { useEffect, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useStore } from './store';
import { Icon } from './components/ui';
import Welcome from './screens/Welcome';
import Market from './screens/Market';
import Chats from './screens/Chats';
import Support from './screens/Support';
import Profile from './screens/Profile';
import Impact from './screens/Impact';

/** True when Chrome/Edge page-translation has rewritten the DOM despite translate="no". */
function useBrowserTranslated() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const html = document.documentElement;
    const check = () =>
      setOn(/translated-(ltr|rtl)/.test(html.className) || !!document.querySelector('#root font[style], #root font[class]'));
    const mo = new MutationObserver(check);
    mo.observe(html, { attributes: true, attributeFilter: ['class'] });
    mo.observe(document.body, { childList: true, subtree: true });
    check();
    return () => mo.disconnect();
  }, []);
  return on;
}

function Nav() {
  const { t, me, unread, conversations } = useStore();
  const loc = useLocation();
  // Count only chats this deployment lists: Nexconn may also deliver offline messages from
  // channels of another deployment that shares the app (e.g. local testing with demo users).
  const known = new Set(conversations.map((c) => c.channelId));
  const total = Object.entries(unread).reduce((n, [k, v]) => (k === 'mandi-mitra' || !known.has(k) ? n : n + v), 0);
  const items =
    me?.role === 'agent'
      ? [
          { to: '/support', icon: 'support', label: t.support },
          { to: '/chats', icon: 'chats', label: t.chats, badge: total },
          { to: '/me', icon: 'me', label: t.me },
        ]
      : [
          { to: '/market', icon: 'market', label: t.market },
          { to: '/chats', icon: 'chats', label: t.chats, badge: total },
          { to: '/chats/1/mandi-mitra', icon: 'mitra', label: t.mitra, badge: unread['mandi-mitra'] || 0 },
          { to: '/me', icon: 'me', label: t.me },
        ];
  const inRoom = /^\/chats\/\d\//.test(loc.pathname);
  return (
    <nav className={`app-nav ${inRoom ? 'in-room' : ''}`} aria-label="Main">
      <div className="nav-brand"><img src="/icon.svg" alt="" width={32} height={32} /> <span>MandiLink</span></div>
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === '/chats'}
          className={({ isActive }) => {
            const chatsActive = it.to === '/chats' && loc.pathname.startsWith('/chats') && !loc.pathname.includes('mandi-mitra');
            return `nav-item ${isActive || chatsActive ? 'on' : ''}`;
          }}
        >
          <span className="nav-icon"><Icon name={it.icon} />{!!it.badge && <span className="badge">{it.badge}</span>}</span>
          <span className="nav-label">{it.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export default function App() {
  const { me, booting, demoMode, status, t, toastMsg } = useStore();
  const translatedByBrowser = useBrowserTranslated();
  if (booting) return <div className="boot"><img src="/icon.svg" alt="MandiLink" width={56} height={56} /></div>;

  return (
    <>
      {translatedByBrowser && <div className="banner offline" role="alert">{t.browserTranslated}</div>}
      {me && demoMode && <div className="banner demo">{t.demoBanner}</div>}
      {me && status === 'offline' && <div className="banner offline" role="status">{t.offline}</div>}
      <Routes>
        <Route path="/impact" element={<div className="app-shell">{me && <Nav />}<main className="app-main"><Impact /></main></div>} />
        {!me ? (
          <Route path="*" element={<Welcome />} />
        ) : (
          <Route
            path="*"
            element={
              <div className="app-shell">
                <Nav />
                <main className="app-main">
                  <Routes>
                    <Route path="/market" element={<Market />} />
                    <Route path="/chats" element={<Chats />} />
                    <Route path="/chats/:type/:id" element={<Chats />} />
                    <Route path="/support" element={me.role === 'agent' ? <Support /> : <Navigate to="/market" replace />} />
                    <Route path="/me" element={<Profile />} />
                    <Route path="*" element={<Navigate to={me.role === 'agent' ? '/support' : '/market'} replace />} />
                  </Routes>
                </main>
              </div>
            }
          />
        )}
      </Routes>
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
    </>
  );
}
