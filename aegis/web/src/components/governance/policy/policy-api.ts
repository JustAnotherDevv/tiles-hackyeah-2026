// Typed calls for the policy + budgets pages (CONTRACTS §5.4) with `?view_as=` and mock factories
// (mocks only on 404/405/501/network — 4xx policy answers are real). Owner: B19-dashboard-gov-policy.
import { useEffect } from 'react';
import { api, type ApiResult } from '@/api/client';
import type {
  ApplyResult,
  BudgetDimension,
  BudgetHistoryResponse,
  BudgetsResponse,
  ControlView,
  PolicyDiffResponse,
  PolicyResponse,
  PolicyVersionInfo,
  ValidationReport,
} from '@/api/types';
import { withViewer } from '@/components/governance/gov-api';
import { mockBudgetHistory, mockBudgets, mockKillSwitch, mockRaise } from '@/mocks/governance/budgets';
import { mockApply, mockControls, mockDiff, mockHistory, mockPolicy, mockRollback, mockValidate, mockVersion } from '@/mocks/governance/policy';
import { govStore } from '@/mocks/governance/store';

export interface MockViewer {
  id: string | null;
  role: 'owner' | 'admin' | 'member';
}

export const policyPaths = {
  policy: '/api/policy',
  history: '/api/policy/history',
  controls: '/api/controls',
  version: (v: number) => `/api/policy/versions/${v}`,
  budgets: (viewerId: string | null) => withViewer('/api/budgets', viewerId),
  budgetHistory: (scope: string, dimension: BudgetDimension, window = '24h') =>
    `/api/budgets/history?scope=${encodeURIComponent(scope)}&dimension=${dimension}&window=${window}`,
};

export const policyMocks = {
  policy: () => mockPolicy(),
  history: () => mockHistory(),
  controls: () => mockControls(),
  version: (v: number) => () => mockVersion(v),
  budgets: () => mockBudgets(),
  budgetHistory: (scope: string, dimension: BudgetDimension) => () => mockBudgetHistory(scope, dimension),
};

export const policyApi = {
  /** `baseYaml` only feeds the offline mock (the server diffs against its active policy). */
  validate: (yaml: string, selftest: boolean, baseYaml?: string): Promise<ApiResult<ValidationReport>> =>
    // `selftest` is gap G1 (ignored by a backend that always runs the self-test)
    api.post<ValidationReport>('/api/policy/validate', { yaml, selftest }, () => mockValidate(yaml, selftest, baseYaml)),
  diff: (yaml: string, baseYaml?: string): Promise<ApiResult<PolicyDiffResponse>> =>
    api.post<PolicyDiffResponse>('/api/policy/diff', { yaml }, () => mockDiff(yaml, baseYaml)),
  apply: (body: { yaml: string; base_version: number; reason?: string | null }, viewer: MockViewer): Promise<ApiResult<ApplyResult>> =>
    api.post<ApplyResult>(withViewer('/api/policy/apply', viewer.id), body, () => mockApply(body, viewer)),
  rollback: (body: { version: number; reason?: string | null }, viewer: MockViewer): Promise<ApiResult<ApplyResult>> =>
    api.post<ApplyResult>(withViewer('/api/policy/rollback', viewer.id), body, () => mockRollback(body, viewer)),
  version: (v: number): Promise<ApiResult<{ version: number; yaml: string }>> => api.get(policyPaths.version(v), policyMocks.version(v)),
  history: (): Promise<ApiResult<{ items: PolicyVersionInfo[] }>> => api.get(policyPaths.history, policyMocks.history),
  controls: (): Promise<ApiResult<{ items: ControlView[] }>> => api.get(policyPaths.controls, policyMocks.controls),
  policy: (): Promise<ApiResult<PolicyResponse>> => api.get(policyPaths.policy, policyMocks.policy),
  raise: (body: { scope: string; window: string; dimension: string; new_limit: number; reason: string }, viewer: MockViewer): Promise<ApiResult<ApplyResult>> =>
    api.post<ApplyResult>(withViewer('/api/budgets/raise', viewer.id), body, () => mockRaise(body, viewer)),
  killswitch: (body: { scope: string; active: boolean; reason: string }, viewer: MockViewer): Promise<ApiResult<ApplyResult>> =>
    api.post<ApplyResult>(withViewer('/api/killswitch', viewer.id), body, () => mockKillSwitch(body, viewer)),
  budgets: (viewerId: string | null): Promise<ApiResult<BudgetsResponse>> => api.get(policyPaths.budgets(viewerId), policyMocks.budgets),
  budgetHistory: (scope: string, dimension: BudgetDimension): Promise<ApiResult<BudgetHistoryResponse>> =>
    api.get(policyPaths.budgetHistory(scope, dimension), policyMocks.budgetHistory(scope, dimension)),
};

/** Refetch when the offline mock store changes (approvals executed elsewhere, raises, kills). */
export function useMockStoreRefresh(refresh: () => void, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    return govStore.subscribe(refresh);
  }, [refresh, enabled]);
}
