// Typed API client with mock fallback (CONTRACTS §5.4). Owner: dashboard-shell (scaffold seed).
//
// api.get<T>(path, mock?) / api.post<T>(path, body, mock?) / api.patch<T>(path, body, mock?) return
// ApiResult<T>. When the request fails with 404/405/501 or a network error AND a mock factory was
// passed, the mock is returned with isMock=true. Real policy answers (400/402/403/409/422/429, any
// JSON error envelope) always throw ApiRequestError. ?mock=1 or VITE_AEGIS_MOCK=1 forces mocks.
import { isMockForced } from '@/lib/mockMode';
import { getViewer } from '@/lib/viewer';
import type { ApiError, ApproverLevel } from './types';

export interface ApiResult<T> {
  data: T;
  isMock: boolean;
}

export const API_BASE: string = import.meta.env.VITE_AEGIS_API ?? '';

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

  get type(): string | null {
    return this.envelope?.error.type ?? null;
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

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function headers(json: boolean): Record<string, string> {
  const h: Record<string, string> = { Accept: 'application/json' };
  if (json) h['Content-Type'] = 'application/json';
  const viewer = getViewer();
  if (viewer) h['X-Aegis-View-As'] = viewer;
  return h;
}

function isEnvelope(v: unknown): v is ApiError {
  return typeof v === 'object' && v !== null && 'error' in v && typeof (v as ApiError).error === 'object';
}

async function request<T>(method: string, path: string, body?: unknown, mock?: () => T): Promise<ApiResult<T>> {
  if (mock && isMockForced()) return { data: mock(), isMock: true };
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers: headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (mock) return { data: mock(), isMock: true };
    throw err;
  }
  const text = await res.text();
  let parsed: unknown = undefined;
  let isJson = false;
  try {
    parsed = text ? JSON.parse(text) : null;
    isJson = true;
  } catch {
    isJson = false;
  }
  if (res.ok) {
    if (!isJson && mock) return { data: mock(), isMock: true }; // SPA-fallback HTML
    return { data: parsed as T, isMock: false };
  }
  const envelope = isJson && isEnvelope(parsed) ? parsed : null;
  if (mock && !envelope && (MOCK_STATUSES.has(res.status) || res.status >= 500)) {
    return { data: mock(), isMock: true };
  }
  throw new ApiRequestError(res.status, envelope);
}

async function download(path: string, filename?: string): Promise<void> {
  const res = await fetch(apiUrl(path), { headers: headers(false) });
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
  const match = /filename="?([^";]+)"?/i.exec(cd);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = match?.[1] ?? filename ?? 'download';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export const api = {
  get: <T>(path: string, mock?: () => T) => request<T>('GET', path, undefined, mock),
  post: <T>(path: string, body: unknown, mock?: () => T) => request<T>('POST', path, body ?? {}, mock),
  patch: <T>(path: string, body: unknown, mock?: () => T) => request<T>('PATCH', path, body ?? {}, mock),
  del: <T>(path: string, mock?: () => T) => request<T>('DELETE', path, undefined, mock),
  download,
  url: apiUrl,
};
