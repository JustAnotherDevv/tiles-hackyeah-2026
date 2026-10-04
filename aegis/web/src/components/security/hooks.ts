// Security-section data hooks. Shell usage is concentrated here so a shell API change is fixed in one place.
// Owner: dashboard-security.
import { useMemo } from 'react';
import { useApi, useEvents } from '@/api/hooks';
import type {
  Agent,
  ControlView,
  DecisionDetail,
  DecisionSummary,
  HealthResponse,
  SseEventMap,
  SseEventName,
} from '@/api/types';
import { mockAgents, mockControls, mockDecisionDetail, mockHealth } from '@/mocks/security';
import { FALLBACK_CONTROLS } from './lib/catalog';
import type { CatalogControl } from './types';

/** Typed SSE subscription (adapter over the shell's useEvents). */
export function useSecEvents<N extends SseEventName>(names: N[], handler: (name: N, data: SseEventMap[N]) => void): void {
  useEvents(names, (name, data) => handler(name as N, data as SseEventMap[N]));
}

export function controlViewToCatalog(c: ControlView): CatalogControl {
  return {
    id: c.id,
    name: c.name,
    family: c.family,
    kind: c.kind,
    owner: c.owner,
    surfaces: c.surfaces ?? [],
    enabled: c.enabled,
    mode: c.mode,
    action: c.action,
    threshold: c.threshold,
    owasp: c.owasp,
  };
}

/** GET /api/controls (refreshes on policy.applied) → catalog, with the §4.4 fallback. */
export function useControlsCatalog() {
  const res = useApi<{ items: ControlView[] }>('/api/controls', { mock: mockControls, refreshOn: ['policy.applied'] });
  const items = res.data?.items;
  const catalog = useMemo<CatalogControl[]>(() => {
    if (!items || items.length === 0) return FALLBACK_CONTROLS;
    const known = new Map(items.map((c) => [c.id, controlViewToCatalog(c)]));
    // keep §4.4 order (pipeline-ish), then any extra controls
    const ordered = FALLBACK_CONTROLS.map((c) => known.get(c.id)).filter((c): c is CatalogControl => Boolean(c));
    for (const c of known.values()) if (!ordered.includes(c)) ordered.push(c);
    return ordered;
  }, [items]);
  return { catalog, items: items ?? [], isMock: res.isMock, loading: res.loading, refresh: res.refresh, error: res.error };
}

export interface CurrentVersions {
  policyVersion: number | null;
  feedSerial: number | null;
  isMock: boolean;
}

/** Current policy/feed versions from /healthz (refreshes on policy.applied / feed.updated). */
export function useCurrentVersions(): CurrentVersions {
  const res = useApi<HealthResponse>('/healthz', { mock: mockHealth, refreshOn: ['policy.applied', 'feed.updated'], refreshMs: 30000 });
  return { policyVersion: res.data?.policy_version ?? null, feedSerial: res.data?.feed_serial ?? null, isMock: res.isMock };
}

/** GET /api/decisions/{id} with a mock built from the summary hint (only on 404/405/501/network or forced mocks). */
export function useDecisionDetail(id: string | null, hint?: DecisionSummary | null) {
  const hintRef = hint ?? null;
  return useApi<DecisionDetail>(id ? `/api/decisions/${encodeURIComponent(id)}` : null, {
    mock: id ? () => mockDecisionDetail(id, hintRef) : undefined,
    refreshOn: ['approval.updated'],
  });
}

/** GET /api/agents → id-indexed map. */
export function useAgentsIndex() {
  const res = useApi<{ items: Agent[] }>('/api/agents', { mock: mockAgents });
  const items = res.data?.items;
  const byId = useMemo(() => new Map((items ?? []).map((a) => [a.id, a])), [items]);
  return { agents: items ?? [], byId, isMock: res.isMock };
}
