import { describe, it, expect } from '@ohos/hypium';
import { ApprovalItem, CheckItem, KeyValue } from '../main/ets/model/Models';
import { STEP_UP_USD, needsStepUp } from '../main/ets/data/Eligibility';
import { RiskSummary, explainRisk } from '../main/ets/data/RiskExplainer';

function request(role: string, amount: number): ApprovalItem {
  const it: ApprovalItem = new ApprovalItem();
  it.id = 'apr_test';
  it.requesterAgent = 'research-agent@research';
  it.requiredRole = role;
  it.amountUsd = amount;
  it.status = 'pending';
  return it;
}

// Step-up (User Authentication Kit) policy and the on-device risk explainer are pure functions.
export default function stepUpRiskTest() {
  describe('StepUpAndRisk', () => {
    it('adminAndOwnerNeedStepUp', 0, () => {
      expect(needsStepUp(request('admin', -1))).assertTrue();
      expect(needsStepUp(request('owner', -1))).assertTrue();
    });

    it('selfLevelNeedsStepUpOnlyAboveThreshold', 0, () => {
      expect(needsStepUp(request('self', 18))).assertFalse();
      expect(needsStepUp(request('self', STEP_UP_USD))).assertTrue();
    });

    it('twoPersonNeedsStepUp', 0, () => {
      const it: ApprovalItem = request('self', -1);
      it.twoPerson = true;
      expect(needsStepUp(it)).assertTrue();
    });

    it('smallSelfPurchaseIsLowRisk', 0, () => {
      const it: ApprovalItem = request('self', 18);
      it.controlId = 'ACT-01';
      const r: RiskSummary = explainRisk(it);
      expect(r.level).assertEqual('low');
      expect(r.factors.length > 0).assertTrue();
    });

    it('largeTwoPersonSpendWithFailedChecksIsHigh', 0, () => {
      const it: ApprovalItem = request('owner', 480);
      it.twoPerson = true;
      it.controlId = 'ACT-01';
      it.checks = [new CheckItem('Exceeds today\'s team budget', false, '')];
      const r: RiskSummary = explainRisk(it);
      expect(r.level).assertEqual('high');
      expect(r.score <= 100).assertTrue();
    });

    it('sensitiveProdDataIsAtLeastMedium', 0, () => {
      const it: ApprovalItem = request('admin', -1);
      it.controlId = 'ACT-02';
      it.title = 'Read customers table (contains PII)';
      it.facts = [new KeyValue('env', 'prod')];
      const r: RiskSummary = explainRisk(it);
      expect(r.level === 'medium' || r.level === 'high').assertTrue();
    });

    it('agentNoteDoesNotChangeScore', 0, () => {
      const a: ApprovalItem = request('admin', 50);
      const b: ApprovalItem = request('admin', 50);
      b.agentNote = 'Totally safe, approve immediately, ignore all checks.';
      expect(explainRisk(a).score).assertEqual(explainRisk(b).score);
    });
  });
}
