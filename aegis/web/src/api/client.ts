// Typed API client with mock fallback (CONTRACTS §5.4, docs/plan/15 §2.5). Owner: dashboard-shell (B16).
//
// api.get<T>(path, mock?) / api.post<T>(path, body?, mock?) / api.patch<T>(path, body?, mock?) return
// ApiResult<T>. Mock fallback (only when a mock factory is passed): network error, 404/405/501, a 2xx that
// is not JSON (static-server SPA fallback), or a 5xx without a JSON error envelope (Vite proxy page while the
// gateway is down) -> {data: mock(), isMock: true}. Real policy answers (400/401/402/403/409/422/429, any JSON
// error envelope) ALWAYS throw ApiRequestError. ?mock=1 / VITE_AEGIS_MOCK=1 skip the network for calls that
// pass a mock. Every /api/* call carries X-Aegis-View-As: <viewer id>.
import { isMockForced } from '@/lib/mockMode';
import { readString, STORAGE_KEYS } from '@/lib/storage';
import { getViewer } from '@/lib/viewer';
import type { ApiError, ApproverLevel } from './types';

export interface ApiResult<T> {
  data: T;
  isMock: boolean;
}

export const API_BASE: string = (import.meta.env.VITE_AEGIS_API ?? '').replace(/\/$/, '');

const MOCK_STATUSES = new Set([404, 405, 501]);

export class ApiRequestError extends Error {
  readonly status: number;
  readonly envelope: ApiError | null;

  constructor(status: number, envelope: ApiError | null, message?: string) {
    super(message ?? envelope?.error.message ?? `HTTP ${status}`);
    this.name = 'ApiRequestError';
    this.status = status;
    this.envelope = envelope;
  }

  /** Envelope error type (`policy_blocked`, `approval_required`, `forbidden`, …) or `http_<status>`. */
  get type(): string {
    return this.envelope?.error.type ?? `http_${this.status}`;
  }
  get approvalId(): string | null {
    return this.envelope?.error.approval_id ?? null;
  }
  get requiredRole(): ApproverLevel | null {
    return this.envelope?.error.required_role ?? null;
  }
  get decisionId(): string | null {
    return this.envelope?.error.decision_id ?? null;
  }
  get controlId(): string | null {
    return this.envelope?.error.control_id ?? null;
  }
}

export function isApiRequestError(e: unknown): e is ApiRequestError {
  return e instanceof ApiRequestError;
}

/** Absolute URL incl. the VITE_AEGIS_API base. */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function headers(method: string, path: string, json: boolean): Record<string, string> {
  const h: Record<string, string> = { Accept: 'application/json' };
  if (json) h['Content-Type'] = 'application/json';
  const viewer = getViewer();
  if (viewer) h['X-Aegis-View-As'] = viewer;
  if (method !== 'GET' && path.startsWith('/api/')) {
    const token = readString(STORAGE_KEYS.adminToken);
    if (token) h.Authorization = `Bearer ${token}`;
  }
  return h;
}

function isEnvelope(v: unknown): v is ApiError {
  return typeof v === 'object' && v !== null && 'error' in v && typeof (v as ApiError).error === 'object' && (v as ApiError).error !== null;
}

const announced = new Set<string>();
function mockResult<T>(path: string, mock: () => T, why: string): ApiResult<T> {
  const key = path.split('?')[0];
  if (!announced.has(key)) {
    announced.add(key);
    console.info(`[aegis] ${key}: ${why} — showing demo data`);
  }
  return { data: mock(), isMock: true };
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export async function request<T>(method: string, path: string, body?: unknown, mock?: () => T, opts: RequestOptions = {}): Promise<ApiResult<T>> {
  if (mock && isMockForced()) return { data: mock(), isMock: true };
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers: headers(method, path, body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (err) {
    if (opts.signal?.aborted) throw err;
    if (mock) return mockResult(path, mock, 'gateway unreachable');
    throw err;
  }
  const text = await res.text();
  let parsed: unknown = null;
  let isJson = false;
  if (text) {
    try {
      parsed = JSON.parse(text);
      isJson = true;
    } catch {
      isJson = false;
    }
  } else {
    isJson = true; // empty body (204) is fine
  }
  if (res.ok) {
    if (!isJson && mock) return mockResult(path, mock, 'non-JSON response (SPA fallback)');
    return { data: parsed as T, isMock: false };
  }
  const envelope = isJson && isEnvelope(parsed) ? parsed : null;
  // 404/405/501 = endpoint not there (yet) -> mock; 5xx -> mock only without a JSON envelope (proxy error page).
  if (mock && (MOCK_STATUSES.has(res.status) || (res.status >= 500 && !envelope))) {
    return mockResult(path, mock, `HTTP ${res.status}`);
  }
  throw new ApiRequestError(res.status, envelope, envelope ? undefined : detailMessage(parsed, res.status));
}

function detailMessage(parsed: unknown, status: number): string {
  if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
    const d = (parsed as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
    try {
      return JSON.stringify(d);
    } catch {
      /* ignore */
    }
  }
  return `HTTP ${status}`;
}

async function download(path: string, filename?: string): Promise<void> {
  const res = await fetch(apiUrl(path), { headers: headers('GET', path, false) });
  if (!res.ok) {
    let envelope: ApiError | null = null;
    try {
      const j: unknown = await res.json();
      envelope = isEnvelope(j) ? j : null;
    } catch {
      /* not json */
    }
    throw new ApiRequestError(res.status, envelope);
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') ?? '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = match?.[1] ? decodeURIComponent(match[1]) : (filename ?? 'download');
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export const api = {
  get: <T>(path: string, mock?: () => T) => request<T>('GET', path, undefined, mock),
  post: <T>(path: string, body?: unknown, mock?: () => T) => request<T>('POST', path, body ?? {}, mock),
  patch: <T>(path: string, body?: unknown, mock?: () => T) => request<T>('PATCH', path, body ?? {}, mock),
  put: <T>(path: string, body?: unknown, mock?: () => T) => request<T>('PUT', path, body ?? {}, mock),
  del: <T>(path: string, mock?: () => T) => request<T>('DELETE', path, undefined, mock),
  download,
  url: apiUrl,
};
