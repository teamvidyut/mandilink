import type { Lang } from './i18n';

export type Role = 'farmer' | 'buyer' | 'agent' | 'bot';

export interface Me {
  id: string;
  name: string;
  role: Role;
  language: Lang;
  district: string;
  phone: string;
  avatarUrl: string;
}

export interface SessionPayload {
  session: string;
  user: Me;
  nexconn: { appKey: string; token: string; demoMode: boolean };
}

export interface MandiInfo {
  crop: string;
  min_per_kg: number;
  max_per_kg: number;
  modal_per_kg: number;
  market: string;
  date: string;
  source: 'agmarknet' | 'reference';
  live: boolean;
}

export interface Trust {
  rating: number | null;
  reviews: number;
  deals: number;
  badge: 'new' | 'trusted' | 'top';
  since: number | null;
}

export interface PriceRow extends MandiInfo {
  names: Record<Lang, string>;
}

export interface BuyRequest {
  id: number;
  crop: string;
  cropNames: Record<Lang, string>;
  quantityKg: number;
  targetPricePerKg: number | null;
  district: string;
  note: string;
  status: 'open' | 'closed';
  notified: number;
  createdAt: number;
  buyer: { id: string; name: string; district: string; trust: Trust } | null;
  mandi: MandiInfo | null;
  myMatchingListings: { id: number; quantityKg: number; pricePerKg: number; variety: string }[];
}

export interface Brief {
  category: string;
  headline: string;
  facts: string[];
  suggestedAction: string;
  userLanguage: Lang;
  fairPrice: number | null;
}

export interface Listing {
  id: number;
  crop: string;
  cropNames: Record<Lang, string>;
  variety: string;
  quantityKg: number;
  pricePerKg: number;
  district: string;
  grade: string;
  description: string;
  photoUrl: string;
  status: 'active' | 'sold' | 'paused';
  createdAt: number;
  seller: { id: string; name: string; district: string; language: Lang; trust?: Trust } | null;
  mandi: MandiInfo | null;
  fairness: 'low' | 'fair' | 'high' | null;
}

export interface Conversation {
  channelType: 1 | 3;
  channelId: string;
  kind: 'assistant' | 'deal' | 'room' | 'support';
  title: string;
  subtitle: string;
  emoji: string;
  status?: string;
  updatedAt?: number;
}

export interface Profile {
  id: string;
  name: string;
  role: Role;
  language: Lang;
  district: string;
  avatarUrl: string;
}

export interface DealCard {
  dealId: string;
  status: 'negotiating' | 'proposed' | 'agreed' | 'completed' | 'cancelled';
  crop: string;
  cropNames: Record<Lang, string>;
  quantityKg: number | null;
  pricePerKg: number | null;
  totalRs: number;
  proposedBy: string | null;
  buyerAccepted: boolean;
  sellerAccepted: boolean;
  buyerId: string;
  sellerId: string;
  updatedAt: number;
  agreedAt?: number | null;
}

export interface Receipt extends DealCard {
  receiptNo: string;
  variety: string;
  grade: string;
  askPricePerKg: number;
  buyer: { name: string; district: string } | null;
  seller: { name: string; district: string } | null;
  pickupDistrict: string;
}

export interface Ticket {
  id: number;
  channelId: string;
  dealId: string | null;
  reason: string;
  summary: string;
  priority: 'normal' | 'high';
  status: 'open' | 'assigned' | 'resolved';
  user: { id: string; name: string; role: Role; language: Lang; district: string } | null;
  agent: { id: string; name: string } | null;
  deal: { crop: string; status: string; askPrice: number; offerPrice: number | null; offerQty: number | null } | null;
  createdAt: number;
  updatedAt: number;
}

export interface Metrics {
  users: number;
  farmers: number;
  buyers: number;
  activeUsers7d: number;
  messages: number;
  translations: number;
  aiReplies: number;
  dealsOpened: number;
  dealsAgreed: number;
  tickets: number;
  ticketsResolved: number;
  listings: number;
  feedbackAvg: number | null;
  feedbackCount: number;
  series: { date: string; messages: number; activeUsers: number }[];
  gmvRs: number;
  kgTraded: number;
  dealsCompleted: number;
  requests: number;
  languages: Record<Lang, number>;
  tradeRating: number | null;
  tradeReviews: number;
}

const STORE_KEY = 'mandilink.session';

export function savedSession(): string | null {
  try {
    return localStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}

export function saveSession(token: string | null) {
  try {
    if (token) localStorage.setItem(STORE_KEY, token);
    else localStorage.removeItem(STORE_KEY);
  } catch {
    /* private mode: session lives in memory only */
  }
}

let sessionToken: string | null = savedSession();
export function setSessionToken(t: string | null) {
  sessionToken = t;
  saveSession(t);
}
export function getSessionToken() {
  return sessionToken;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (sessionToken) headers.set('Authorization', `Bearer ${sessionToken}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, headers, body });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') msg = data.detail;
      else if (Array.isArray(data.detail)) msg = data.detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join(', ');
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}
