import { describe, it, expect } from '@ohos/hypium';
import { ApprovalItem, PostureStats, VoteOutcome, VoteView } from '../main/ets/model/Models';
import { ApprovalsPage, ApprovalsRepository, ConnectionInfo, RepoError } from '../main/ets/data/ApprovalsRepository';
import { MAX_BACKOFF_MS, POLL_MS, PocketStore, StepUp, backoffDelayMs, isUnknownOutcome } from '../main/ets/data/PocketStore';

/** A promise whose settlement the test controls. */
class Deferred<T> {
  promise: Promise<T>;
  private res: ((v: T) => void) | null = null;
  private rej: ((e: Error) => void) | null = null;

  constructor() {
    this.promise = new Promise<T>((resolve, reject) => {
      this.res = resolve;
      this.rej = reject;
    });
  }

  resolve(v: T): void {
    const f: ((v: T) => void) | null = this.res;
    if (f !== null) {
      f(v);
    }
  }

  reject(e: Error): void {
    const f: ((e: Error) => void) | null = this.rej;
    if (f !== null) {
      f(e);
    }
  }
}

function item(id: string, status: string, canVote: boolean): ApprovalItem {
  const it: ApprovalItem = new ApprovalItem();
  it.id = id;
  it.title = 'Test ' + id;
  it.requesterAgent = 'research-agent@research';
  it.requiredRole = 'self';
  it.amountUsd = -1;
  it.status = status;
  it.canVote = canVote;
  return it;
}

function pageOf(items: ApprovalItem[]): ApprovalsPage {
  const p: ApprovalsPage = new ApprovalsPage();
  p.items = items.map((i: ApprovalItem) => i.clone());
  let pending: number = 0;
  for (const i of items) {
    if (i.status === 'pending') {
      pending++;
    }
  }
  p.pending = pending;
  return p;
}

/** Fake gateway: list calls are deferred unless `autoPage` is set; vote/getApproval are scripted. */
class FakeRepo implements ApprovalsRepository {
  readonly mode: string = 'live';
  autoPage: ApprovalsPage | null = null;
  lists: Deferred<ApprovalsPage>[] = [];
  listViewers: string[] = [];
  voteResult: ApprovalItem | null = null;
  voteError: RepoError | null = null;
  voteComments: string[] = [];
  approval: ApprovalItem | null = null;
  approvalCalls: number = 0;

  listApprovals(viewAs: string): Promise<ApprovalsPage> {
    this.listViewers.push(viewAs);
    if (this.autoPage !== null) {
      return Promise.resolve(pageOf((this.autoPage as ApprovalsPage).items));
    }
    const d: Deferred<ApprovalsPage> = new Deferred<ApprovalsPage>();
    this.lists.push(d);
    return d.promise;
  }

  getApproval(id: string, viewAs: string): Promise<ApprovalItem> {
    this.approvalCalls++;
    if (this.approval === null) {
      return Promise.reject(new RepoError('Approval ' + id + ' not found', 404, 'http'));
    }
    return Promise.resolve((this.approval as ApprovalItem).clone());
  }

  getStats(viewAs: string): Promise<PostureStats> {
    return Promise.resolve(new PostureStats());
  }

  vote(id: string, decision: string, viewAs: string, comment: string): Promise<ApprovalItem> {
    this.voteComments.push(comment);
    if (this.voteError !== null) {
      return Promise.reject(this.voteError as RepoError);
    }
    if (this.voteResult === null) {
      return Promise.reject(new RepoError('no scripted vote result', 500, 'http'));
    }
    return Promise.resolve((this.voteResult as ApprovalItem).clone());
  }

  testConnection(viewAs: string): Promise<ConnectionInfo> {
    return Promise.resolve(new ConnectionInfo(true, 'fake'));
  }

  tick(nowMs: number): void {
    // nothing to simulate
  }
}

/** Lets pending promise continuations run. */
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
}

/** A store with one pending, votable request already loaded. */
async function loaded(fake: FakeRepo, it: ApprovalItem): Promise<PocketStore> {
  const store: PocketStore = PocketStore.forTest(fake, 'u_emily');
  fake.autoPage = pageOf([it]);
  await store.refresh();
  fake.autoPage = null;
  return store;
}

function statusOf(store: PocketStore, id: string): string {
  const it: ApprovalItem | undefined = store.find(id);
  return it === undefined ? 'missing' : it.status;
}

// PocketStore state machine: poll/vote races, persona switch, unknown vote outcomes, step-up gate, fetchOne, backoff.
export default function pocketStoreTest() {
  describe('PocketStore', () => {
    it('staleInFlightPollDoesNotUndoAVote', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      const poll: Promise<void> = store.refresh(); // started before the vote
      expect(fake.lists.length).assertEqual(1);
      fake.voteResult = item('apr_1', 'denied', false);
      const r: VoteOutcome = await store.vote('apr_1', 'deny', '', StepUp.NONE);
      expect(r.ok).assertTrue();
      fake.lists[0].resolve(pageOf([item('apr_1', 'pending', true)])); // stale server copy
      await flush();
      expect(statusOf(store, 'apr_1')).assertEqual('denied');
      expect((store.find('apr_1') as ApprovalItem).canVote).assertFalse();
      // the refresh requested by the vote was not dropped: a second list call was made
      expect(fake.lists.length).assertEqual(2);
      fake.lists[1].resolve(pageOf([item('apr_1', 'denied', false)]));
      await poll;
      expect(statusOf(store, 'apr_1')).assertEqual('denied');
    });

    it('personaSwitchDiscardsTheOldPersonasPage', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      const poll: Promise<void> = store.refresh(); // as Emily
      store.setPersona('u_piotr');
      // the old persona's eligibility is not shown under the new name while loading
      expect((store.find('apr_1') as ApprovalItem).canVote).assertFalse();
      const emilyOnly: ApprovalItem = item('apr_emily', 'pending', true);
      fake.lists[0].resolve(pageOf([item('apr_1', 'pending', true), emilyOnly]));
      await flush();
      expect(store.find('apr_emily') === undefined).assertTrue();
      expect(fake.listViewers[fake.listViewers.length - 1]).assertEqual('u_piotr');
      fake.lists[1].resolve(pageOf([item('apr_1', 'pending', false)]));
      await poll;
      expect((store.find('apr_1') as ApprovalItem).canVote).assertFalse();
      expect(store.find('apr_emily') === undefined).assertTrue();
    });

    it('timedOutVoteIsConfirmedNotRolledBack', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      fake.voteError = new RepoError('Gateway timed out', 0, 'timeout');
      const truth: ApprovalItem = item('apr_1', 'approved', false);
      truth.votes = [new VoteView('u_emily', 'admin', 'approve', '', 1)];
      fake.approval = truth;
      const r: VoteOutcome = await store.vote('apr_1', 'approve', '', StepUp.NONE);
      expect(r.ok).assertTrue();
      expect(fake.approvalCalls).assertEqual(1);
      expect(statusOf(store, 'apr_1')).assertEqual('approved');
      expect((store.find('apr_1') as ApprovalItem).canVote).assertFalse();
      expect((store.find('apr_1') as ApprovalItem).syncing).assertFalse();
    });

    it('unknownOutcomeThatDidNotLandIsReported', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      fake.voteError = new RepoError('Cannot reach the gateway', 0, 'network');
      fake.approval = item('apr_1', 'pending', true);
      const r: VoteOutcome = await store.vote('apr_1', 'approve', '', StepUp.NONE);
      expect(r.ok).assertFalse();
      expect(statusOf(store, 'apr_1')).assertEqual('pending');
      expect((store.find('apr_1') as ApprovalItem).canVote).assertTrue();
    });

    it('unconfirmableVoteStaysSyncing', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      fake.voteError = new RepoError('Gateway returned non-JSON', 200, 'parse');
      fake.approval = null; // the confirming GET fails too
      const r: VoteOutcome = await store.vote('apr_1', 'deny', '', StepUp.NONE);
      expect(r.ok).assertFalse();
      const it: ApprovalItem = store.find('apr_1') as ApprovalItem;
      expect(it.syncing).assertTrue();
      expect(it.canVote).assertFalse();
    });

    it('definiteRefusalRollsBack', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      fake.voteError = new RepoError('forbidden: admins only', 403, 'http');
      const r: VoteOutcome = await store.vote('apr_1', 'approve', '', StepUp.NONE);
      expect(r.ok).assertFalse();
      expect(r.message).assertEqual('forbidden: admins only');
      expect(fake.approvalCalls).assertEqual(0);
      const it: ApprovalItem = store.find('apr_1') as ApprovalItem;
      expect(it.status).assertEqual('pending');
      expect(it.canVote).assertTrue();
      expect(it.syncing).assertFalse();
    });

    it('unknownOutcomeClassification', 0, () => {
      expect(isUnknownOutcome(new RepoError('t', 0, 'timeout'))).assertTrue();
      expect(isUnknownOutcome(new RepoError('n', 0, 'network'))).assertTrue();
      expect(isUnknownOutcome(new RepoError('p', 200, 'parse'))).assertTrue();
      expect(isUnknownOutcome(new RepoError('h', 409, 'http'))).assertFalse();
      expect(isUnknownOutcome(new RepoError('h', 503, 'http'))).assertFalse();
      expect(isUnknownOutcome(new Error('mapping failed'))).assertTrue();
    });

    it('stepUpGateRefusesApproveWithoutStepUp', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const admin: ApprovalItem = item('apr_1', 'pending', true);
      admin.requiredRole = 'admin';
      const store: PocketStore = await loaded(fake, admin);
      const r: VoteOutcome = await store.vote('apr_1', 'approve', 'ok', StepUp.NONE);
      expect(r.ok).assertFalse();
      expect(fake.voteComments.length).assertEqual(0);
      expect(statusOf(store, 'apr_1')).assertEqual('pending');
      fake.voteResult = item('apr_1', 'approved', false);
      const r2: VoteOutcome = await store.vote('apr_1', 'approve', 'ok', StepUp.verified('face'));
      expect(r2.ok).assertTrue();
      expect(fake.voteComments[0]).assertEqual('[step-up: face] ok');
    });

    it('denyNeedsNoStepUpAndManualIsRecorded', 0, async () => {
      expect(StepUp.satisfied(StepUp.NONE)).assertFalse();
      expect(StepUp.satisfied('verified:')).assertFalse();
      expect(StepUp.satisfied('bogus')).assertFalse();
      expect(StepUp.satisfied(StepUp.MANUAL)).assertTrue();
      expect(StepUp.auditComment(StepUp.MANUAL, '')).assertEqual('[step-up: manual (no device authentication)]');
      expect(StepUp.auditComment(StepUp.NONE, 'fine')).assertEqual('fine');
      const fake: FakeRepo = new FakeRepo();
      const admin: ApprovalItem = item('apr_1', 'pending', true);
      admin.requiredRole = 'admin';
      const store: PocketStore = await loaded(fake, admin);
      fake.voteResult = item('apr_1', 'denied', false);
      const r: VoteOutcome = await store.vote('apr_1', 'deny', '', StepUp.NONE);
      expect(r.ok).assertTrue();
    });

    it('fetchOneLoadsAMissingRequestAndKeepsIt', 0, async () => {
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = await loaded(fake, item('apr_1', 'pending', true));
      expect(store.find('apr_9') === undefined).assertTrue();
      fake.approval = item('apr_9', 'pending', true);
      const got: ApprovalItem | undefined = await store.fetchOne('apr_9');
      expect(got !== undefined).assertTrue();
      expect(statusOf(store, 'apr_9')).assertEqual('pending');
      fake.autoPage = pageOf([item('apr_1', 'pending', true)]); // the list still lacks apr_9
      await store.refresh();
      expect(statusOf(store, 'apr_9')).assertEqual('pending');
      fake.approval = null;
      const none: ApprovalItem | undefined = await store.fetchOne('apr_404');
      expect(none === undefined).assertTrue();
    });

    it('pollBackoff', 0, async () => {
      expect(backoffDelayMs(0)).assertEqual(POLL_MS);
      expect(backoffDelayMs(1)).assertEqual(POLL_MS * 2);
      expect(backoffDelayMs(3)).assertEqual(POLL_MS * 8);
      expect(backoffDelayMs(4)).assertEqual(MAX_BACKOFF_MS);
      expect(backoffDelayMs(50)).assertEqual(MAX_BACKOFF_MS);
      const fake: FakeRepo = new FakeRepo();
      const store: PocketStore = PocketStore.forTest(fake, 'u_emily');
      const p1: Promise<void> = store.refresh();
      fake.lists[0].reject(new RepoError('Cannot connect', 0, 'network'));
      await p1;
      expect(store.failureCount()).assertEqual(1);
      fake.autoPage = pageOf([item('apr_1', 'pending', true)]);
      await store.refresh();
      expect(store.failureCount()).assertEqual(0);
    });
  });
}
