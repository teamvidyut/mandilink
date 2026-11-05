import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, type BuyRequest, type Listing, type MandiInfo, type PriceRow } from '../api';
import { CROP_EMOJI, CROP_TINT, fmtNum, fmtRs, fmtTime, type Lang, type T } from '../i18n';
import { useStore } from '../store';
import { Icon, LangSwitch, RateBand, Sheet, Ticker, TrustBadge } from '../components/ui';
import { resizeImage } from '../lib/photo';

interface Crop {
  key: string;
  names: Record<Lang, string>;
}
type Tab = 'produce' | 'wanted' | 'mine';
type Sort = 'new' | 'price_asc' | 'price_desc' | 'fair';

export default function Market() {
  const { t, lang, me, toast, setLang } = useStore();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get('mine') === '1' && me?.role === 'farmer' ? 'mine' : params.get('tab') === 'wanted' ? 'wanted' : 'produce';
  const setTab = (next: Tab) => setParams(next === 'mine' ? { mine: '1' } : next === 'wanted' ? { tab: 'wanted' } : {});
  const [crop, setCrop] = useState<string | null>(null);
  const [crops, setCrops] = useState<Crop[]>([]);
  const [prices, setPrices] = useState<PriceRow[]>([]);
  const [rows, setRows] = useState<Listing[] | null>(null);
  const [requests, setRequests] = useState<BuyRequest[] | null>(null);
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [sort, setSort] = useState<Sort>('new');
  const [open, setOpen] = useState<Listing | null>(null);
  const [selling, setSelling] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [respondTo, setRespondTo] = useState<BuyRequest | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Crop[]>('/api/crops').then(setCrops).catch(() => undefined);
    api<PriceRow[]>('/api/prices').then(setPrices).catch(() => undefined);
  }, []);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(id);
  }, [query]);

  const load = useCallback(() => {
    if (tab === 'wanted') {
      api<BuyRequest[]>('/api/requests').then(setRequests).catch(() => setRequests([]));
      return;
    }
    const q = new URLSearchParams({ sort });
    if (crop) q.set('crop', crop);
    if (tab === 'mine') q.set('mine', 'true');
    if (debounced) q.set('q', debounced);
    api<Listing[]>(`/api/listings?${q}`).then(setRows).catch(() => setRows([]));
  }, [crop, tab, debounced, sort]);
  useEffect(load, [load]);

  const enquire = async (li: Listing) => {
    setBusy(true);
    try {
      const { dealId } = await api<{ dealId: string }>(`/api/listings/${li.id}/enquire`, { method: 'POST' });
      nav(`/chats/3/${dealId}`);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (li: Listing, status: string) => {
    try {
      const updated = await api<Listing>(`/api/listings/${li.id}?status=${status}`, { method: 'PATCH' });
      setRows((r) => r?.map((x) => (x.id === li.id ? updated : x)) ?? null);
      setOpen(updated);
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const visibleRequests = (requests ?? []).filter((r) => !crop || r.crop === crop);
  const firstName = me?.name.replace(/\s*\(Demo\)/, '').split(' ')[0] ?? '';

  return (
    <div className="screen market">
      <header className="market-hero">
        <div>
          <p className="hero-kicker">{t.liveRates}</p>
          <h1>{firstName ? `${greeting(lang)}, ${firstName}` : t.market}</h1>
        </div>
        <LangSwitch lang={lang} onChange={setLang} />
        <div className="seg" role="tablist">
          <button role="tab" aria-selected={tab === 'produce'} className={tab === 'produce' ? 'on' : ''} onClick={() => setTab('produce')}>{t.produce}</button>
          <button role="tab" aria-selected={tab === 'wanted'} className={tab === 'wanted' ? 'on' : ''} onClick={() => setTab('wanted')}>
            <Icon name="megaphone" size={16} /> {t.wanted}
          </button>
          {me?.role === 'farmer' && (
            <button role="tab" aria-selected={tab === 'mine'} className={tab === 'mine' ? 'on' : ''} onClick={() => setTab('mine')}>{t.myListings}</button>
          )}
        </div>
      </header>

      <Ticker rows={prices} lang={lang} t={t} onPick={(c) => setCrop(c)} />

      {tab !== 'wanted' && (
        <div className="toolbar">
          <label className="search">
            <Icon name="search" size={18} />
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t.search} aria-label={t.search} />
          </label>
          <label className="sort">
            <Icon name="sort" size={16} />
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
              <option value="new">{t.sortNew}</option>
              <option value="price_asc">{t.sortPriceLow}</option>
              <option value="price_desc">{t.sortPriceHigh}</option>
              <option value="fair">{t.sortFair}</option>
            </select>
          </label>
        </div>
      )}

      <div className="crop-strip" role="toolbar" aria-label={t.crop}>
        <button className={`crop-chip ${crop === null ? 'on' : ''}`} onClick={() => setCrop(null)}>{t.allCrops}</button>
        {crops.map((c) => (
          <button key={c.key} className={`crop-chip ${crop === c.key ? 'on' : ''}`} onClick={() => setCrop(crop === c.key ? null : c.key)}>
            <span aria-hidden>{CROP_EMOJI[c.key]}</span> {c.names[lang]}
          </button>
        ))}
      </div>

      {tab === 'wanted' ? (
        requests === null ? <Skeleton /> : visibleRequests.length === 0 ? (
          <div className="empty">
            <span className="empty-art" aria-hidden>📢</span>
            <p>{t.noRequests}</p>
            {me?.role === 'buyer' && <button className="btn primary" onClick={() => setRequesting(true)}>{t.postRequest}</button>}
          </div>
        ) : (
          <ul className="request-list">
            {visibleRequests.map((r) => (
              <li key={r.id} className="request-card" style={{ ['--tint' as string]: CROP_TINT[r.crop] }}>
                <span className="crop-swatch" aria-hidden>{CROP_EMOJI[r.crop]}</span>
                <div className="request-main">
                  <p className="request-title">
                    <b>{r.buyer?.name}</b> {t.wantsQty} <strong>{fmtNum(r.quantityKg, lang)} kg {r.cropNames[lang]}</strong>
                  </p>
                  <p className="request-meta">
                    {r.targetPricePerKg != null && <span className="pill">{fmtRs(r.targetPricePerKg, lang)}{t.perKg}</span>}
                    {r.district && <span>{r.district}</span>}
                    <span>{fmtTime(r.createdAt, lang)}</span>
                    {r.buyer && <TrustBadge trust={r.buyer.trust} t={t} compact />}
                  </p>
                  {r.note && <p className="request-note">“{r.note}”</p>}
                </div>
                {me?.role === 'farmer' && (
                  <button className="btn primary small" onClick={() => setRespondTo(r)}><Icon name="handshake" size={16} /> {t.iHaveThis}</button>
                )}
                {me?.id === r.buyer?.id && r.notified > 0 && (
                  <span className="request-sent"><Icon name="megaphone" size={14} /> {fmtNum(r.notified, lang)} {t.farmersNotified}</span>
                )}
              </li>
            ))}
          </ul>
        )
      ) : rows === null ? <Skeleton /> : rows.length === 0 ? (
        <div className="empty">
          <span className="empty-art" aria-hidden>🧺</span>
          <p>{tab === 'mine' ? t.noListingsFarmer : t.noListings}</p>
          {me?.role === 'farmer' && <button className="btn primary" onClick={() => setSelling(crop || 'potato')}>{t.sell}</button>}
        </div>
      ) : (
        <ul className="listing-grid">
          {rows.map((li, i) => (
            <li key={li.id} style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
              <ListingCard li={li} lang={lang} t={t} mine={tab === 'mine'} onOpen={() => setOpen(li)} />
            </li>
          ))}
        </ul>
      )}

      {me?.role === 'farmer' && tab !== 'wanted' && rows && rows.length > 0 && (
        <button className="fab" onClick={() => setSelling(crop || 'potato')}><Icon name="plus" /> {t.sell}</button>
      )}
      {me?.role === 'buyer' && tab === 'wanted' && visibleRequests.length > 0 && (
        <button className="fab" onClick={() => setRequesting(true)}><Icon name="megaphone" /> {t.postRequest}</button>
      )}

      <Sheet open={!!open} onClose={() => setOpen(null)} title={open ? open.cropNames[lang] : ''}>
        {open && (
          <div className="listing-detail">
            {open.photoUrl ? (
              <figure className="detail-photo"><img src={open.photoUrl} alt={open.cropNames[lang]} /></figure>
            ) : null}
            <div className="detail-top" style={{ ['--tint' as string]: CROP_TINT[open.crop] }}>
              <span className="detail-emoji" aria-hidden>{CROP_EMOJI[open.crop]}</span>
              <div>
                <p className="detail-price">{fmtRs(open.pricePerKg, lang)}<small>{t.perKg}</small></p>
                <p className="detail-qty">{fmtNum(open.quantityKg, lang)} kg · {t.grade} {open.grade}{open.variety && ` · ${open.variety}`}</p>
              </div>
            </div>
            {open.mandi && <RateBand info={open.mandi} price={open.pricePerKg} lang={lang} t={t} />}
            {open.description && <p className="detail-desc">{open.description}</p>}
            {open.seller && (
              <div className="detail-seller">
                <div>
                  <b>{open.seller.name}</b>
                  {open.seller.district && <span> · {open.seller.district}</span>}
                </div>
                <TrustBadge trust={open.seller.trust} t={t} />
              </div>
            )}
            {open.seller?.id === me?.id ? (
              <div className="row-btns">
                {open.status === 'active' ? (
                  <button className="btn ghost" onClick={() => setStatus(open, 'paused')}>{t.pause}</button>
                ) : (
                  <button className="btn ghost" onClick={() => setStatus(open, 'active')}>{t.resume}</button>
                )}
                <button className="btn ghost" onClick={() => setStatus(open, 'sold')}>{t.sold}</button>
              </div>
            ) : (
              <button className="btn primary wide" disabled={busy || open.status !== 'active'} onClick={() => enquire(open)}>
                <Icon name="chats" /> {t.chatWithSeller}
              </button>
            )}
          </div>
        )}
      </Sheet>

      <SellSheet
        crop={selling}
        crops={crops}
        onClose={() => setSelling(null)}
        onDone={() => {
          setSelling(null);
          toast(t.published);
          setTab('mine');
          load();
        }}
      />
      <RequestSheet
        open={requesting}
        crops={crops}
        onClose={() => setRequesting(false)}
        onDone={() => {
          setRequesting(false);
          toast(t.requestPosted);
          load();
        }}
      />
      <RespondSheet
        req={respondTo}
        onClose={() => setRespondTo(null)}
        onSell={(c) => {
          setRespondTo(null);
          setSelling(c);
        }}
      />
    </div>
  );
}

function greeting(lang: Lang) {
  return lang === 'bn' ? 'নমস্কার' : lang === 'hi' ? 'नमस्ते' : 'Namaste';
}

function Skeleton() {
  return <div className="skeleton-grid" aria-busy>{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton-card" />)}</div>;
}

function ListingCard({ li, lang, t, mine, onOpen }: { li: Listing; lang: Lang; t: T; mine: boolean; onOpen: () => void }) {
  const verdict = li.fairness === 'low' ? t.priceLow : li.fairness === 'high' ? t.priceHigh : li.fairness === 'fair' ? t.priceFair : null;
  return (
    <button className={`lcard status-${li.status}`} onClick={onOpen} style={{ ['--tint' as string]: CROP_TINT[li.crop] }}>
      <span className="lcard-media">
        {li.photoUrl ? <img src={li.photoUrl} alt="" loading="lazy" /> : <span className="lcard-emoji" aria-hidden>{CROP_EMOJI[li.crop]}</span>}
        {verdict && <span className={`verdict v-${li.fairness}`}>{verdict}</span>}
        {li.status !== 'active' && <span className="lcard-status">{li.status === 'sold' ? t.sold : t.pause}</span>}
      </span>
      <span className="lcard-body">
        <span className="lcard-top">
          <span className="lcard-title">{li.cropNames[lang]}{li.variety && <em> {li.variety}</em>}</span>
          <span className="lcard-price">{fmtRs(li.pricePerKg, lang)}<small>{t.perKg}</small></span>
        </span>
        <span className="lcard-meta">
          {fmtNum(li.quantityKg, lang)} kg · {t.grade} {li.grade}{li.district && <> · {li.district}</>}
        </span>
        {li.seller && !mine && (
          <span className="lcard-foot">
            <span className="lcard-seller">{li.seller.name}</span>
            <TrustBadge trust={li.seller.trust} t={t} compact />
          </span>
        )}
      </span>
    </button>
  );
}

function CropPicker({ crops, value, onChange, lang, t }: { crops: Crop[]; value: string; onChange: (c: string) => void; lang: Lang; t: T }) {
  return (
    <fieldset className="crop-pick">
      <legend>{t.crop}</legend>
      {crops.map((c) => (
        <label key={c.key} className={`crop-chip ${value === c.key ? 'on' : ''}`}>
          <input type="radio" name="crop" value={c.key} checked={value === c.key} onChange={() => onChange(c.key)} />
          <span aria-hidden>{CROP_EMOJI[c.key]}</span> {c.names[lang]}
        </label>
      ))}
    </fieldset>
  );
}

function useBand(crop: string, active: boolean) {
  const [band, setBand] = useState<MandiInfo | null>(null);
  useEffect(() => {
    if (active) api<MandiInfo>(`/api/prices/${encodeURIComponent(crop)}`).then(setBand).catch(() => setBand(null));
  }, [crop, active]);
  return band;
}

function SellSheet({ crop: initialCrop, crops, onClose, onDone }: { crop: string | null; crops: Crop[]; onClose: () => void; onDone: () => void }) {
  const { t, lang, me, toast } = useStore();
  const open = initialCrop !== null;
  const [crop, setCrop] = useState('potato');
  const empty = { variety: '', quantity_kg: '', price_per_kg: '', grade: 'A', description: '' };
  const [form, setForm] = useState(empty);
  const [photo, setPhoto] = useState<string>('');
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const band = useBand(crop, open);

  useEffect(() => {
    if (open && initialCrop) setCrop(initialCrop);
  }, [open, initialCrop]);

  const pickPhoto = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const dataUrl = await resizeImage(file);
      const { url } = await api<{ url: string }>('/api/photos', { method: 'POST', json: { data_url: dataUrl } });
      setPhoto(url);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api('/api/listings', {
        method: 'POST',
        json: { ...form, crop, quantity_kg: Number(form.quantity_kg), price_per_kg: Number(form.price_per_kg), district: me?.district || '', photo_url: photo },
      });
      setForm(empty);
      setPhoto('');
      onDone();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });
  const price = Number(form.price_per_kg) || null;

  return (
    <Sheet open={open} onClose={onClose} title={t.sell}>
      <form className="form" onSubmit={submit}>
        <CropPicker crops={crops} value={crop} onChange={setCrop} lang={lang} t={t} />
        <div className="photo-pick">
          <button type="button" className={`photo-slot ${photo ? 'has' : ''}`} onClick={() => fileRef.current?.click()} disabled={uploading}>
            {photo ? <img src={photo} alt="" /> : <Icon name="camera" size={26} />}
            <span>{uploading ? '…' : photo ? t.changePhoto : t.addPhoto}</span>
          </button>
          <p className="field-note">{t.photoHint}</p>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pickPhoto(e.target.files?.[0])} />
        </div>
        <div className="two-col">
          <label>{t.quantity}<input required inputMode="decimal" value={form.quantity_kg} onChange={set('quantity_kg')} /></label>
          <label>{t.price}<input required inputMode="decimal" value={form.price_per_kg} onChange={set('price_per_kg')} /></label>
        </div>
        {band && (
          <div className="band-block">
            <div className="ai-suggest">
              <Icon name="spark" size={16} />
              <span>{t.suggestedPrice}: <b>{fmtRs(band.modal_per_kg, lang)}{t.perKg}</b></span>
              <button type="button" className="chip small" onClick={() => setForm({ ...form, price_per_kg: String(band.modal_per_kg) })}>{t.useThis}</button>
            </div>
            <RateBand info={band} price={price} lang={lang} t={t} />
          </div>
        )}
        <div className="two-col">
          <label>{t.variety}<input maxLength={40} value={form.variety} onChange={set('variety')} /></label>
          <label>{t.grade}
            <select value={form.grade} onChange={set('grade')}>
              <option>A</option><option>B</option><option>C</option>
            </select>
          </label>
        </div>
        <label>{t.notes}<textarea rows={2} maxLength={400} value={form.description} onChange={set('description')} /></label>
        <button className="btn primary wide" disabled={busy || uploading}>{t.publish}</button>
      </form>
    </Sheet>
  );
}

function RequestSheet({ open, crops, onClose, onDone }: { open: boolean; crops: Crop[]; onClose: () => void; onDone: () => void }) {
  const { t, lang, me, toast } = useStore();
  const [crop, setCrop] = useState('potato');
  const [qty, setQty] = useState('');
  const [price, setPrice] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const band = useBand(crop, open);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api('/api/requests', {
        method: 'POST',
        json: { crop, quantity_kg: Number(qty), target_price_per_kg: price ? Number(price) : null, district: me?.district || '', note },
      });
      setQty('');
      setPrice('');
      setNote('');
      onDone();
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title={t.postRequest}>
      <form className="form" onSubmit={submit}>
        <CropPicker crops={crops} value={crop} onChange={setCrop} lang={lang} t={t} />
        <div className="two-col">
          <label>{t.quantity}<input required inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></label>
          <label>{t.targetPrice}<input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
        </div>
        {band && <RateBand info={band} price={Number(price) || null} lang={lang} t={t} />}
        <label>{t.notes}<textarea rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button className="btn primary wide" disabled={busy}><Icon name="megaphone" size={18} /> {t.postRequest}</button>
      </form>
    </Sheet>
  );
}

function RespondSheet({ req, onClose, onSell }: { req: BuyRequest | null; onClose: () => void; onSell: (crop: string) => void }) {
  const { t, lang, toast } = useStore();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const offer = async (listingId: number) => {
    if (!req) return;
    setBusy(true);
    try {
      const { dealId } = await api<{ dealId: string }>(`/api/requests/${req.id}/respond`, { method: 'POST', json: { listing_id: listingId } });
      nav(`/chats/3/${dealId}`);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open={!!req} onClose={onClose} title={t.offerListing}>
      {req && (
        <div className="form">
          <p className="request-title">
            <b>{req.buyer?.name}</b> {t.wantsQty} <strong>{fmtNum(req.quantityKg, lang)} kg {req.cropNames[lang]}</strong>
            {req.targetPricePerKg != null && <> @ {fmtRs(req.targetPricePerKg, lang)}{t.perKg}</>}
          </p>
          {req.mandi && <RateBand info={req.mandi} price={req.targetPricePerKg} lang={lang} t={t} />}
          {req.myMatchingListings.length === 0 ? (
            <>
              <p className="field-note">{t.listFirst}</p>
              <button className="btn primary wide" onClick={() => onSell(req.crop)}><Icon name="plus" size={18} /> {t.sell}</button>
            </>
          ) : (
            <ul className="pick-list">
              {req.myMatchingListings.map((l) => (
                <li key={l.id}>
                  <button className="pick-row" disabled={busy} onClick={() => offer(l.id)}>
                    <span>{CROP_EMOJI[req.crop]} {req.cropNames[lang]}{l.variety && ` · ${l.variety}`}</span>
                    <span>{fmtNum(l.quantityKg, lang)} kg · <b>{fmtRs(l.pricePerKg, lang)}{t.perKg}</b></span>
                    <Icon name="send" size={18} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Sheet>
  );
}
