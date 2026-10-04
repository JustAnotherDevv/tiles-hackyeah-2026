// Mock factory for GET /api/approvals/rules (seed-fix rule ids). Owner: B18-dashboard-gov-approvals.
import type { ApprovalRulesResponse } from '@/api/types';
import { RULES } from './fixtures';

export function mockRules(): ApprovalRulesResponse {
  return RULES;
}
