import { common } from '@kit.AbilityKit';
import { ApprovalItem, Persona, PostureStats, VoteOutcome, VoteView, personaById } from '../model/Models';
import { ApprovalsPage, ApprovalsRepository, ConnectionInfo, RepoError } from './ApprovalsRepository';
import { MockRepository } from './MockRepository';
import { LiveRepository } from './LiveRepository';
import { needsStepUp } from './Eligibility';
import { AppSettings, SettingsStore } from '../platform/SettingsStore';
import { NotificationService } from '../platform/NotificationService';
import { WidgetBridge } from '../platform/WidgetBridge';
import { BackgroundRefresh } from '../platform/BackgroundRefresh';
import { Haptics } from '../platform/Haptics';
import { Log } from '../common/Format';

/** AppStorage keys shared by the store and the views (@StorageProp / @StorageLink). */
export class Keys {
  static readonly APPROVALS: string = 'approvals';
  static readonly STATS: string = 'stats';
  static readonly PENDING: string = 'pendingCount';
  static readonly MODE: string = 'mode';
  static readonly PERSONA: string = 'persona';
  static readonly BASE_URL: string = 'baseUrl';
  static readonly NOW: string = 'nowMs';
  static readonly CONN_STATE: string = 'connState'; // ok | error | loading
  static readonly CONN_MSG: string = 'connMessage';
  static readonly OPEN_APPROVAL: string = 'openApprovalId';
  static readonly OPEN_TARGET: string = 'openTarget';
  static readonly NOTIF_ENABLED: string = 'notifEnabled';
  static readonly NEW_REQUEST: string = 'newRequestTitle';
}

/** Poll interval while the gateway answers. */
export const POLL_MS: number = 4000;
/** Upper bound of the exponential backoff after failed polls. */
export const MAX_BACKOFF_MS: number = 60000;
const CLOCK_MS = 1000;

/** `stepUp` values accepted by PocketStore.vote. */
export class StepUp {
  static readonly NONE: string = 'none';
  static readonly MANUAL: string = 'manual';
  static readonly VERIFIED_PREFIX: string = 'verified:';

  /** 'verified:<type>' for a User Authentication Kit success, e.g. StepUp.verified('face'). */
  static verified(type: string): string {
    return StepUp.VERIFIED_PREFIX + type;
  }

  /** True when the value proves a step-up happened (device authentication or the labelled manual fallback). */
  static satisfied(stepUp: string): boolean {
    if (stepUp === StepUp.MANUAL) {
      return true;
    }
    return stepUp.startsWith(StepUp.VERIFIED_PREFIX) && stepUp.length > StepUp.VERIFIED_PREFIX.length;
  }

  /**
   * Comment sent to the gateway. The approve/deny body only has `comment` (CONTRACTS.md: `{comment?}`), so the
   * step-up method is recorded there as a machine-readable prefix, e.g. "[step-up: face] looks fine".
   */
  static auditComment(stepUp: string, comment: string): string {
    let method: string = '';
    if (stepUp === StepUp.MANUAL) {
      method = 'manual (no device authentication)';
    } else if (StepUp.satisfied(stepUp)) {
      method = stepUp.substring(StepUp.VERIFIED_PREFIX.length);
    }
    if (method.length === 0) {
      return comment;
    }
    const tag: string = '[step-up: ' + method + ']';
    return comment.trim().length > 0 ? tag + ' ' + comment : tag;
  }
}

/** Poll delay after `failures` consecutive failed refreshes: 4 s, then 8, 16, 32, capped at 60 s. */
export function backoffDelayMs(failures: number): number {
  if (failures <= 0) {
    return POLL_MS;
  }
  const exp: number = Math.min(failures, 5);
  return Math.min(MAX_BACKOFF_MS, POLL_MS * Math.pow(2, exp));
}

/**
 * True when a failed vote POST may still have been applied by the gateway: the request timed out or the
 * connection dropped (no HTTP status), or a 2xx body could not be parsed. Only a definite HTTP status
 * (4xx/5xx, kind 'http') means the vote was refused.
 */
export function isUnknownOutcome(e: Object): boolean {
  if (e instanceof RepoError) {
    const err: RepoError = e as RepoError;
    if (err.kind === 'http' && err.code > 0) {
      return false;
    }
    return true;
  }
  // Anything else (e.g. a TypeError while mapping a 2xx body) happened after the request was sent.
  return true;
}

function messageOf(e: Object): string {
  if (e instanceof Error) {
    const err: Error = e as Error;
    return err.message.length > 0 ? err.message : 'Unexpected error';
  }
  return 'Unexpected error';
}

/**
 * Single source of truth for the app (MVVM "model/service" layer). Owns the active repository
 * (mock or live), polls it, publishes UI state to AppStorage, raises Notification Kit
 * notifications for new requests and pushes posture snapshots to the Form Kit widgets.
 *
 * Concurrency rules (all on the UI thread, interleaved only at `await`):
 * - `generation` changes on mode, gateway URL and persona switches; any response started under an older
 *   generation is discarded.
 * - `refresh()` never drops a request: a call while one is running sets `rerun`, and the running loop fetches again.
 * - Items with a vote in flight, or changed locally after a refresh started (`mutatedAt` > that refresh's epoch),
 *   keep their local copy when the stale page lands.
 */
export class PocketStore {
  private static instance: PocketStore | null = null;

  private ctx: common.UIAbilityContext | null = null;
  private settings: AppSettings = new AppSettings();
  private mock: MockRepository = new MockRepository();
  private repo: ApprovalsRepository = this.mock;
  private items: ApprovalItem[] = [];
  private stats: PostureStats = new PostureStats();
  private seen: Set<string> = new Set<string>();
  private firstLoad: boolean = true;
  private inflight: Set<string> = new Set<string>();
  /** Requests loaded by fetchOne() that the list endpoint did not return; kept across polls. */
  private extras: Set<string> = new Set<string>();
  /** id -> mutationEpoch of the last local change. */
  private mutatedAt: Map<string, number> = new Map<string, number>();
  private mutationEpoch: number = 0;
  private polling: boolean = false;
  private pollTimer: number = -1;
  private pollDelay: number = POLL_MS;
  private clockTimer: number = -1;
  private running: Promise<void> | null = null;
  private rerun: boolean = false;
  private failures: number = 0;
  private generation: number = 0;
  private knownPendingIds: string = '';

  static get(): PocketStore {
    if (PocketStore.instance === null) {
      PocketStore.instance = new PocketStore();
    }
    return PocketStore.instance as PocketStore;
  }

  /**
   * Test seam: a store that is not the app singleton, has no ability context (so no preferences, notifications,
   * widget or background-task calls) and talks to the given repository.
   */
  static forTest(repo: ApprovalsRepository, persona: string): PocketStore {
    PocketStore.seedStorage();
    const s: PocketStore = new PocketStore();
    s.settings.persona = persona;
    s.settings.mode = repo.mode;
    s.repo = repo;
    return s;
  }

  /** Seeds AppStorage with defaults so views can bind before init() finishes. */
  static seedStorage(): void {
    AppStorage.setOrCreate<ApprovalItem[]>(Keys.APPROVALS, []);
    AppStorage.setOrCreate<PostureStats>(Keys.STATS, new PostureStats());
    AppStorage.setOrCreate<number>(Keys.PENDING, 0);
    AppStorage.setOrCreate<string>(Keys.MODE, 'mock');
    AppStorage.setOrCreate<string>(Keys.PERSONA, 'u_emily');
    AppStorage.setOrCreate<string>(Keys.BASE_URL, '');
    AppStorage.setOrCreate<number>(Keys.NOW, Date.now());
    AppStorage.setOrCreate<string>(Keys.CONN_STATE, 'loading');
    AppStorage.setOrCreate<string>(Keys.CONN_MSG, '');
    AppStorage.setOrCreate<string>(Keys.OPEN_APPROVAL, '');
    AppStorage.setOrCreate<string>(Keys.OPEN_TARGET, '');
    AppStorage.setOrCreate<boolean>(Keys.NOTIF_ENABLED, false);
    AppStorage.setOrCreate<string>(Keys.NEW_REQUEST, '');
  }

  init(ctx: common.UIAbilityContext): void {
    this.ctx = ctx;
    PocketStore.seedStorage();
    this.settings = SettingsStore.load(ctx);
    this.applyRepo();
    this.publishSettings();
    this.start();
  }

  /** Starts polling (chained timeouts with backoff, see backoffDelayMs) and the clock. Safe to call repeatedly. */
  start(): void {
    this.polling = true;
    if (this.clockTimer === -1) {
      this.clockTimer = setInterval(() => {
        AppStorage.set<number>(Keys.NOW, Date.now());
      }, CLOCK_MS);
    }
    this.pollNow();
  }

  stop(): void {
    this.polling = false;
    this.clearPollTimer();
    if (this.clockTimer !== -1) {
      clearInterval(this.clockTimer);
      this.clockTimer = -1;
    }
  }

  persona(): Persona {
    return personaById(this.settings.persona);
  }

  mode(): string {
    return this.settings.mode;
  }

  baseUrl(): string {
    return this.settings.baseUrl;
  }

  /** Current snapshot of the items (copy of the array; for tests and non-UI callers). */
  snapshot(): ApprovalItem[] {
    return this.items.slice();
  }

  /** Consecutive failed refreshes (drives the poll backoff). */
  failureCount(): number {
    return this.failures;
  }

  // ------------------------------------------------------------------ settings

  setPersona(id: string): void {
    if (id === this.settings.persona) {
      return;
    }
    this.settings.persona = id;
    this.saveSettings();
    this.publishSettings();
    // Responses already in flight were computed for the previous persona (can_vote / why_not): drop them, and do
    // not show the old persona's eligibility under the new name while the new list loads.
    this.generation++;
    this.extras.clear();
    const name: string = personaById(id).name;
    this.items = this.items.map((it: ApprovalItem) => {
      const c: ApprovalItem = it.clone();
      if (c.canVote) {
        c.canVote = false;
        c.whyNot = 'Checking what ' + name + ' can do…';
      }
      return c;
    });
    this.publishData();
    this.kick();
  }

  setMode(mode: string): void {
    if (mode === this.settings.mode) {
      return;
    }
    this.settings.mode = mode;
    this.saveSettings();
    this.applyRepo();
    this.publishSettings();
    this.resetData();
    this.kick();
  }

  setBaseUrl(url: string): void {
    const u: string = url.trim();
    if (u.length === 0 || u === this.settings.baseUrl) {
      return;
    }
    this.settings.baseUrl = u;
    this.saveSettings();
    this.applyRepo();
    this.publishSettings();
    if (this.settings.mode === 'live') {
      this.resetData();
    }
    this.kick();
  }

  async testConnection(url: string): Promise<ConnectionInfo> {
    const repo: ApprovalsRepository = this.settings.mode === 'live' || url.length > 0 ?
      new LiveRepository(url.length > 0 ? url : this.settings.baseUrl) : this.mock;
    return repo.testConnection(this.settings.persona);
  }

  async requestNotifications(): Promise<boolean> {
    if (this.ctx === null) {
      return false;
    }
    const ok: boolean = await NotificationService.requestPermission(this.ctx as common.UIAbilityContext);
    AppStorage.set<boolean>(Keys.NOTIF_ENABLED, ok);
    return ok;
  }

  async syncNotificationState(): Promise<void> {
    AppStorage.set<boolean>(Keys.NOTIF_ENABLED, await NotificationService.isEnabled());
  }

  // ------------------------------------------------------------------ data

  /**
   * Fetches the list and stats. Never rejects. A call while a refresh is running is not dropped: it makes the
   * running loop fetch once more, and the returned promise settles after that re-run.
   */
  refresh(): Promise<void> {
    this.rerun = true;
    if (this.running !== null) {
      return this.running as Promise<void>;
    }
    const p: Promise<void> = this.drain();
    this.running = p;
    return p;
  }

  find(id: string): ApprovalItem | undefined {
    for (const it of this.items) {
      if (it.id === id) {
        return it;
      }
    }
    return undefined;
  }

  /**
   * Returns the request, loading it with GET /api/approvals/{id} when the list does not contain it (cold start
   * from a notification, or a request beyond the list limit). Resolves undefined when the gateway does not know it,
   * the viewer may not see it, or the persona/mode changed while loading.
   */
  async fetchOne(id: string): Promise<ApprovalItem | undefined> {
    const have: ApprovalItem | undefined = this.find(id);
    if (have !== undefined) {
      return have;
    }
    const gen: number = this.generation;
    const repo: ApprovalsRepository = this.repo;
    try {
      const it: ApprovalItem = await repo.getApproval(id, this.settings.persona);
      if (gen !== this.generation) {
        return undefined;
      }
      if (this.inflight.has(id)) {
        return this.find(id);
      }
      this.seen.add(it.id); // the user is looking at it: no "new request" notification for it
      this.extras.add(it.id);
      if (this.indexOf(it.id) >= 0) {
        this.replace(it);
      } else {
        this.items = this.items.concat([it]);
      }
      this.markMutated(it.id);
      this.publishData();
      return it;
    } catch (e) {
      Log.warn('fetchOne ' + id + ' failed: ' + messageOf(e as Object));
      return undefined;
    }
  }

  /**
   * Optimistic approve/deny: the card updates at once. `stepUp` is 'verified:<type>', 'manual' or 'none' (see
   * StepUp); an approve that needsStepUp() is refused without one, and the method is recorded in the comment.
   * - definite refusal (HTTP 4xx/5xx): rolled back, then refreshed;
   * - unknown outcome (timeout, dropped connection, unparseable 2xx): the item stays "syncing" and is re-read with
   *   GET /api/approvals/{id} to learn whether the vote landed.
   */
  async vote(id: string, decision: string, comment: string, stepUp: string = StepUp.NONE): Promise<VoteOutcome> {
    if (decision !== 'approve' && decision !== 'deny') {
      return new VoteOutcome(false, 'Unknown decision "' + decision + '"');
    }
    const idx: number = this.indexOf(id);
    if (idx < 0) {
      return new VoteOutcome(false, 'Request not found');
    }
    const before: ApprovalItem = this.items[idx];
    if (this.inflight.has(id)) {
      return new VoteOutcome(false, 'A vote on this request is already being sent');
    }
    if (!before.canVote) {
      return new VoteOutcome(false, before.whyNot.length > 0 ? before.whyNot : 'You cannot vote on this request');
    }
    if (decision === 'approve' && needsStepUp(before) && !StepUp.satisfied(stepUp)) {
      return new VoteOutcome(false, 'Device authentication is required to approve this request');
    }
    const gen: number = this.generation;
    const repo: ApprovalsRepository = this.repo;
    const p: Persona = this.persona();
    const sent: string = StepUp.auditComment(stepUp, comment);
    const optimistic: ApprovalItem = before.clone();
    optimistic.syncing = true;
    optimistic.canVote = false;
    optimistic.votes = optimistic.votes.concat([new VoteView(p.id, p.role, decision, sent, Date.now())]);
    if (decision === 'deny') {
      optimistic.status = 'denied';
    } else {
      let approvals: number = 0;
      for (const v of optimistic.votes) {
        if (v.decision === 'approve') {
          approvals++;
        }
      }
      if (!optimistic.twoPerson || approvals >= 2) {
        optimistic.status = 'approved';
      }
    }
    this.inflight.add(id);
    this.replace(optimistic);
    this.publishData();
    try {
      const updated: ApprovalItem = await repo.vote(id, decision, p.id, sent);
      this.settle(updated, gen);
      return new VoteOutcome(true, PocketStore.successMessage(updated, decision));
    } catch (e) {
      if (isUnknownOutcome(e as Object)) {
        return this.confirmUnknown(id, decision, p.id, gen, repo, messageOf(e as Object));
      }
      this.inflight.delete(id);
      if (gen === this.generation) {
        this.replace(before);
      } else {
        const c: ApprovalItem = before.clone(); // persona switched meanwhile: its can_vote is unknown until refresh
        c.canVote = false;
        this.replace(c);
      }
      this.markMutated(id);
      this.publishData();
      this.refresh();
      return new VoteOutcome(false, messageOf(e as Object));
    }
  }

  // ------------------------------------------------------------------ internals

  private static successMessage(updated: ApprovalItem, decision: string): string {
    if (updated.status === 'pending') {
      return 'Vote recorded: waiting for a second approver';
    }
    if (updated.status === 'approved') {
      return 'Approved: the agent may proceed';
    }
    if (updated.status === 'denied') {
      return decision === 'deny' ? 'Denied: the agent will be told no' : 'Denied by another approver';
    }
    return 'Request is now ' + updated.status;
  }

  /** Publishes the gateway's copy after a vote and refreshes to pick up related changes. */
  private settle(updated: ApprovalItem, gen: number): void {
    this.inflight.delete(updated.id);
    if (gen === this.generation) {
      this.replace(updated);
    } else {
      // The persona changed while the vote was in flight: the returned can_vote is the previous persona's.
      const c: ApprovalItem = updated.clone();
      c.canVote = false;
      this.replace(c);
    }
    this.markMutated(updated.id);
    this.publishData();
    if (this.ctx !== null) {
      NotificationService.cancelFor(updated.id).catch(() => {
        // already gone
      });
    }
    this.refresh();
  }

  /** The vote POST failed without a definite answer: ask the gateway what happened instead of rolling back. */
  private async confirmUnknown(id: string, decision: string, voterId: string, gen: number,
    repo: ApprovalsRepository, reason: string): Promise<VoteOutcome> {
    Log.warn('vote ' + id + ' outcome unknown (' + reason + '); confirming');
    let truth: ApprovalItem;
    try {
      truth = await repo.getApproval(id, voterId);
    } catch (e) {
      // Still unknown: keep the optimistic card locked in "syncing" until a refresh brings the real status.
      this.inflight.delete(id);
      this.markMutated(id);
      this.publishData();
      this.refresh();
      return new VoteOutcome(false, 'Vote sent but not confirmed (' + reason + '). The status will update when ' +
        'the gateway answers.');
    }
    let ours: boolean = false;
    for (const v of truth.votes) {
      if (v.memberId === voterId && v.decision === decision) {
        ours = true;
      }
    }
    const target: string = decision === 'deny' ? 'denied' : 'approved';
    this.settle(truth, gen);
    if (ours || truth.status === target) {
      return new VoteOutcome(true, 'Confirmed with the gateway. ' + PocketStore.successMessage(truth, decision));
    }
    if (truth.status === 'pending') {
      return new VoteOutcome(false, 'The vote did not reach the gateway; nothing was recorded. Try again.');
    }
    return new VoteOutcome(false, 'This request is now ' + truth.status + '; your vote was not recorded.');
  }

  private async drain(): Promise<void> {
    try {
      while (this.rerun) {
        this.rerun = false;
        await this.refreshOnce();
      }
    } finally {
      this.running = null;
    }
    // A success after failures shortens a long backoff timer that is still pending.
    if (this.polling && this.pollTimer !== -1 && this.failures === 0 && this.pollDelay > POLL_MS) {
      this.clearPollTimer();
      this.scheduleNext();
    }
  }

  private async refreshOnce(): Promise<void> {
    const gen: number = this.generation;
    const epoch: number = this.mutationEpoch;
    const viewAs: string = this.settings.persona;
    const repo: ApprovalsRepository = this.repo;
    try {
      const pageP: Promise<ApprovalsPage> = repo.listApprovals(viewAs);
      const statsP: Promise<PostureStats> = repo.getStats(viewAs);
      statsP.catch(() => {
        // handled by the await below; avoids an unhandled rejection when the list fails first
      });
      const page: ApprovalsPage = await pageP;
      const stats: PostureStats = await statsP;
      if (gen !== this.generation) {
        return; // mode, gateway or persona switched while loading; the switch queued a re-run
      }
      this.mergeItems(page.items, epoch);
      stats.approvalsPending = page.pending;
      this.stats = stats;
      this.failures = 0;
      this.detectNew();
      this.publishData();
      AppStorage.set<string>(Keys.CONN_STATE, 'ok');
      AppStorage.set<string>(Keys.CONN_MSG, this.settings.mode === 'live' ?
        'Live: ' + this.settings.baseUrl : 'Mock mode: simulated gateway on this device');
    } catch (e) {
      if (gen !== this.generation) {
        return;
      }
      this.failures++;
      const msg: string = messageOf(e as Object);
      Log.warn('refresh failed (' + this.failures + '): ' + msg);
      AppStorage.set<string>(Keys.CONN_STATE, 'error');
      AppStorage.set<string>(Keys.CONN_MSG, this.polling ?
        msg + ' Retrying in ' + Math.round(backoffDelayMs(this.failures) / 1000) + ' s.' : msg);
    }
  }

  /** Refreshes now and restarts the poll timer from the result (used on start and on settings switches). */
  private kick(): void {
    if (this.polling) {
      this.pollNow();
    } else {
      this.refresh();
    }
  }

  private pollNow(): void {
    this.clearPollTimer();
    this.refresh().then(() => {
      this.scheduleNext();
    });
  }

  private scheduleNext(): void {
    if (!this.polling || this.pollTimer !== -1) {
      return;
    }
    this.pollDelay = backoffDelayMs(this.failures);
    this.pollTimer = setTimeout(() => {
      this.pollTimer = -1;
      this.repo.tick(Date.now());
      this.pollNow();
    }, this.pollDelay);
  }

  private clearPollTimer(): void {
    if (this.pollTimer !== -1) {
      clearTimeout(this.pollTimer);
      this.pollTimer = -1;
    }
  }

  private markMutated(id: string): void {
    this.mutationEpoch++;
    this.mutatedAt.set(id, this.mutationEpoch);
  }

  private keepLocal(id: string, startEpoch: number): boolean {
    if (this.inflight.has(id)) {
      return true;
    }
    const at: number | undefined = this.mutatedAt.get(id);
    return at !== undefined && at > startEpoch;
  }

  private applyRepo(): void {
    this.generation++;
    this.repo = this.settings.mode === 'live' ? new LiveRepository(this.settings.baseUrl) : this.mock;
  }

  private resetData(): void {
    this.items = [];
    this.seen.clear();
    this.extras.clear();
    this.mutatedAt.clear();
    this.firstLoad = true;
    this.failures = 0;
    this.stats = new PostureStats();
    this.stats.source = this.settings.mode;
    AppStorage.set<string>(Keys.CONN_STATE, 'loading');
    this.publishData();
  }

  private saveSettings(): void {
    if (this.ctx !== null) {
      SettingsStore.save(this.ctx as common.UIAbilityContext, this.settings);
    }
  }

  private publishSettings(): void {
    AppStorage.set<string>(Keys.MODE, this.settings.mode);
    AppStorage.set<string>(Keys.PERSONA, this.settings.persona);
    AppStorage.set<string>(Keys.BASE_URL, this.settings.baseUrl);
  }

  /**
   * Applies a page fetched by a refresh that started at `startEpoch`. Local copies win for votes in flight and for
   * items changed after the refresh started (the page is older than them). Items loaded by fetchOne() survive even
   * when the list does not include them.
   */
  private mergeItems(fresh: ApprovalItem[], startEpoch: number): void {
    const merged: ApprovalItem[] = [];
    const freshIds: Set<string> = new Set<string>();
    for (const it of fresh) {
      freshIds.add(it.id);
      if (this.keepLocal(it.id, startEpoch)) {
        const cur: ApprovalItem | undefined = this.find(it.id);
        merged.push(cur !== undefined ? cur : it);
      } else {
        merged.push(it);
      }
    }
    for (const cur of this.items) {
      if (!freshIds.has(cur.id) && (this.extras.has(cur.id) || this.keepLocal(cur.id, startEpoch))) {
        merged.push(cur);
      }
    }
    this.items = merged;
    const settled: string[] = [];
    this.mutatedAt.forEach((at: number, id: string) => {
      if (at <= startEpoch) {
        settled.push(id);
      }
    });
    for (const id of settled) {
      this.mutatedAt.delete(id);
    }
  }

  private detectNew(): void {
    const fresh: ApprovalItem[] = [];
    for (const it of this.items) {
      if (!this.seen.has(it.id)) {
        this.seen.add(it.id);
        if (!this.firstLoad && it.status === 'pending') {
          fresh.push(it);
        }
      }
    }
    this.firstLoad = false;
    if (fresh.length === 0 || this.ctx === null) {
      return;
    }
    for (const it of fresh) {
      NotificationService.notifyApproval(this.ctx as common.UIAbilityContext, it).catch((e: Error) => {
        Log.warn('notify ' + it.id + ' failed: ' + messageOf(e as Object));
      });
    }
    Haptics.notice();
    const first: ApprovalItem = fresh[0];
    const who: string = first.requesterAgent.length > 0 ? first.requesterAgent : first.requesterMember;
    AppStorage.set<string>(Keys.NEW_REQUEST, who + ': ' + first.title + '#' + Date.now().toString());
  }

  private publishData(): void {
    AppStorage.set<ApprovalItem[]>(Keys.APPROVALS, this.items.slice());
    let pending: number = 0;
    let top: string = '';
    const pendingIds: string[] = [];
    for (const it of this.items) {
      if (it.status === 'pending') {
        pending++;
        pendingIds.push(it.id);
        if (top.length === 0) {
          top = it.amountUsd > 0 ? it.title + ' ($' + it.amountUsd.toFixed(0) + ')' : it.title;
        }
      }
    }
    this.stats.approvalsPending = pending;
    const statsCopy: PostureStats = this.copyStats();
    AppStorage.set<PostureStats>(Keys.STATS, statsCopy);
    AppStorage.set<number>(Keys.PENDING, pending);
    const joined: string = pendingIds.join(',');
    if (this.ctx !== null && this.settings.mode === 'live' && joined !== this.knownPendingIds) {
      // Lets the background deferred task notify only about requests the user has not seen in the app.
      this.knownPendingIds = joined;
      BackgroundRefresh.saveKnownPending(this.ctx as common.UIAbilityContext, pendingIds);
    }
    if (this.ctx !== null) {
      WidgetBridge.push(this.ctx as common.UIAbilityContext, WidgetBridge.build(statsCopy, pending, top));
    }
  }

  private copyStats(): PostureStats {
    const s: PostureStats = new PostureStats();
    s.requests = this.stats.requests;
    s.blocked = this.stats.blocked;
    s.redacted = this.stats.redacted;
    s.approvalsPending = this.stats.approvalsPending;
    s.spendTodayUsd = this.stats.spendTodayUsd;
    s.budgetUsedPct = this.stats.budgetUsedPct;
    s.activeAgents = this.stats.activeAgents;
    s.costAvoidedUsd = this.stats.costAvoidedUsd;
    s.p50OverheadMs = this.stats.p50OverheadMs;
    s.degraded = this.stats.degraded;
    s.updatedAtMs = this.stats.updatedAtMs;
    s.source = this.settings.mode;
    return s;
  }

  private indexOf(id: string): number {
    for (let i = 0; i < this.items.length; i++) {
      if (this.items[i].id === id) {
        return i;
      }
    }
    return -1;
  }

  private replace(item: ApprovalItem): void {
    const idx: number = this.indexOf(item.id);
    if (idx >= 0) {
      const next: ApprovalItem[] = this.items.slice();
      next[idx] = item;
      this.items = next;
    }
  }
}
