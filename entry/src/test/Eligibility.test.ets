import { describe, it, expect } from '@ohos/hypium';
import { ApprovalItem, VoteView, personaById } from '../main/ets/model/Models';
import { approvalComplete, checkEligibility } from '../main/ets/data/Eligibility';

function request(role: string, twoPerson: boolean): ApprovalItem {
  const it: ApprovalItem = new ApprovalItem();
  it.id = 'apr_test';
  it.requesterAgent = 'trading-copilot@trading';
  it.requiredRole = role;
  it.twoPerson = twoPerson;
  it.status = 'pending';
  return it;
}

// Mirrors the gateway's approval rules (aegis CONTRACTS Addendum A-20) used in mock mode.
export default function eligibilityTest() {
  describe('Eligibility', () => {
    it('adminLevelNeedsAdmin', 0, () => {
      const it: ApprovalItem = request('admin', false);
      expect(checkEligibility(it, personaById('u_emily')).canVote).assertTrue();
      expect(checkEligibility(it, personaById('u_katarzyna')).canVote).assertTrue();
    });

    it('sponsorCannotApproveOwnAgent', 0, () => {
      const it: ApprovalItem = request('admin', false);
      expect(checkEligibility(it, personaById('u_piotr')).canVote).assertFalse();
    });

    it('ownerLevelLocksAdmins', 0, () => {
      const it: ApprovalItem = request('owner', false);
      expect(checkEligibility(it, personaById('u_marek')).canVote).assertFalse();
      expect(checkEligibility(it, personaById('u_katarzyna')).canVote).assertTrue();
    });

    it('twoPersonNeedsOwnerAndAdmin', 0, () => {
      const it: ApprovalItem = request('owner', true);
      it.votes.push(new VoteView('u_emily', 'admin', 'approve', '', 1));
      expect(approvalComplete(it)).assertFalse();
      expect(checkEligibility(it, personaById('u_marek')).canVote).assertFalse();
      expect(checkEligibility(it, personaById('u_katarzyna')).canVote).assertTrue();
      it.votes.push(new VoteView('u_katarzyna', 'owner', 'approve', '', 2));
      expect(approvalComplete(it)).assertTrue();
    });
  });
}
