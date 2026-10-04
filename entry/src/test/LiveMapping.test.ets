import { describe, it, expect } from '@ohos/hypium';
import { ApprovalItem, PostureStats, personaName } from '../main/ets/model/Models';
import { ApprovalsPage, RepoError } from '../main/ets/data/ApprovalsRepository';
import { LiveMapping } from '../main/ets/data/LiveMapping';

const GOOD: string = '{"id":"apr_good","kind":"action","action_type":"purchase","title":"Buy X","status":"pending",' +
  '"created_at":"2026-10-04T10:00:00Z","amount_usd":12.5,"votes":[]}';

function kindOf(f: () => void): string {
  try {
    f();
  } catch (e) {
    if (e instanceof RepoError) {
      return (e as RepoError).kind;
    }
    return 'other';
  }
  return 'none';
}

// Live-mode mapping of untrusted gateway JSON (ERR-POCKET P0-2, P1-1, P2-2, P2-3). Pure: no HTTP, no kits.
export default function liveMappingTest() {
  describe('LiveMapping', () => {
    it('malformedVoteAndStringAmountDoNotCrash', 0, () => {
      const body: string = '{"id":"apr_1","amount_usd":"50","votes":[{"member_id":null,"role":null,"decision":null,' +
        '"comment":null,"ts":null},null,7]}';
      const it: ApprovalItem = LiveMapping.mapChecked(JSON.parse(body) as Object);
      expect(it.amountUsd).assertEqual(50);
      expect(it.votes.length).assertEqual(1);
      expect(it.votes[0].memberId).assertEqual('');
      expect(it.votes[0].role).assertEqual('');
      expect(it.votes[0].decision).assertEqual('');
      expect(personaName(it.votes[0].memberId)).assertEqual('unknown member');
    });

    it('nonNumericAmountFallsBackToNoAmount', 0, () => {
      const a: ApprovalItem = LiveMapping.mapChecked(JSON.parse('{"id":"a","amount_usd":"lots"}') as Object);
      expect(a.amountUsd).assertEqual(-1);
      const b: ApprovalItem = LiveMapping.mapChecked(JSON.parse('{"id":"b","amount_usd":{"v":1}}') as Object);
      expect(b.amountUsd).assertEqual(-1);
      const c: ApprovalItem = LiveMapping.mapChecked(JSON.parse('{"id":"c","amount_usd":null}') as Object);
      expect(c.amountUsd).assertEqual(-1);
    });

    it('wrongTypedFieldsGetDefaults', 0, () => {
      const body: string = '{"id":"apr_2","title":42,"status":null,"can_vote":"yes","two_person":1,' +
        '"requester":"agent","created_at":123,"labels":{"n":5}}';
      const it: ApprovalItem = LiveMapping.mapChecked(JSON.parse(body) as Object);
      expect(it.title).assertEqual('apr_2');
      expect(it.status).assertEqual('pending');
      expect(it.canVote).assertFalse();
      expect(it.twoPerson).assertFalse();
      expect(it.requesterAgent).assertEqual('');
      expect(it.createdAtMs).assertEqual(0);
      expect(it.facts.length).assertEqual(1);
      expect(it.facts[0].value).assertEqual('5');
    });

    it('nullCheckEntryIsSkipped', 0, () => {
      const body: string = '{"id":"apr_3","payload":{"checks":[null,"x",{"name":"budget","ok":true,"detail":"fine"}],' +
        '"budget":{"before":"100","after":150,"scope":"team"}}}';
      const it: ApprovalItem = LiveMapping.mapChecked(JSON.parse(body) as Object);
      expect(it.checks.length).assertEqual(1);
      expect(it.checks[0].ok).assertTrue();
      expect(it.budgetBefore).assertEqual(100);
      expect(it.budgetAfter).assertEqual(150);
    });

    it('entryWithoutIdIsRejected', 0, () => {
      expect(kindOf(() => {
        LiveMapping.mapChecked(JSON.parse('{"title":"no id"}') as Object);
      })).assertEqual('parse');
      expect(kindOf(() => {
        LiveMapping.mapChecked(null);
      })).assertEqual('parse');
    });

    it('oneBadEntryDoesNotFailTheList', 0, () => {
      const body: string = '{"items":[{"bad":true},null,"str",' + GOOD + ',{"id":"apr_x","status":"approved"}]}';
      const page: ApprovalsPage = LiveMapping.parseApprovals(body);
      expect(page.items.length).assertEqual(2);
      expect(page.pending).assertEqual(1);
      expect(page.skipped).assertEqual(3);
      expect(page.items[0].id).assertEqual('apr_good');
      expect(page.items[0].amountUsd).assertEqual(12.5);
    });

    it('nonJsonBodyIsParseError', 0, () => {
      expect(kindOf(() => {
        LiveMapping.parse('<html>captive portal</html>', 'approvals');
      })).assertEqual('parse');
      expect(kindOf(() => {
        LiveMapping.parseApprovals('null');
      })).assertEqual('parse');
      expect(kindOf(() => {
        LiveMapping.parseApprovals('{"items":"nope"}');
      })).assertEqual('parse');
      let msg: string = '';
      try {
        LiveMapping.parse('<html>', 'approvals');
      } catch (e) {
        msg = (e as RepoError).message;
      }
      expect(msg).assertContain('non-JSON');
      expect(msg.indexOf('Unexpected')).assertEqual(-1);
    });

    it('statsCoerceStrings', 0, () => {
      const s: PostureStats = LiveMapping.parseStats('{"kpis":{"requests":"10","spend_today_usd":"abc","blocked":3}}');
      expect(s.requests).assertEqual(10);
      expect(s.spendTodayUsd).assertEqual(0);
      expect(s.blocked).assertEqual(3);
      expect(s.source).assertEqual('live');
    });

    it('friendlyNetworkMessages', 0, () => {
      expect(LiveMapping.friendly(2300007, 'http://10.0.2.2:8080')).assertContain('Cannot connect');
      expect(LiveMapping.friendly(2300006, 'http://gw')).assertContain('Cannot resolve host');
      expect(LiveMapping.friendly(2300028, 'http://gw')).assertContain('timed out');
      expect(LiveMapping.friendly(-1, 'http://gw')).assertContain('Cannot reach the gateway');
    });

    it('errorEnvelopeAndDefaults', 0, () => {
      expect(LiveMapping.errorMessage('{"error":{"type":"x","message":"Sponsor cannot approve"}}', 403))
        .assertEqual('Sponsor cannot approve');
      expect(LiveMapping.errorMessage('{"error":{"message":7}}', 409)).assertEqual('Already decided');
      expect(LiveMapping.errorMessage('null', 403)).assertEqual('Not allowed for this persona');
      expect(LiveMapping.errorMessage('<html>', 502)).assertEqual('Gateway answered HTTP 502');
    });

    it('repoErrorKindDefaults', 0, () => {
      expect(new RepoError('x', 403).kind).assertEqual('http');
      expect(new RepoError('x', 0).kind).assertEqual('network');
      expect(new RepoError('x', 0, 'timeout').kind).assertEqual('timeout');
    });
  });
}
