import { common } from '@kit.AbilityKit';
import { ApprovalItem, Persona, PostureStats, VoteOutcome, VoteView, personaById } from '../model/Models';
import { ApprovalsPage, ApprovalsRepository, ConnectionInfo, RepoError } from './ApprovalsRepository';
import { MockRepository } from './MockRepository';
import { LiveRepository } from './LiveRepository';
import { AppSettings, SettingsStore } from '../platform/SettingsStore';
import { NotificationService } from '../platform/NotificationService';
import { WidgetBridge } from '../platform/WidgetBridge';
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

const POLL_MS = 4000;
const CLOCK_MS = 1000;

/**
 * Single source of truth for the app (MVVM "model/service" layer). Owns the active repository
 * (mock or live), polls it, publishes UI state to AppStorage, raises Notification Kit
 * notifications for new requests and pushes posture snapshots to the Form Kit widgets.
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
  private pollTimer: number = -1;
  private clockTimer: number = -1;
  private refreshing: boolean = false;
  private generation: number = 0;

  static get(): PocketStore {
    if (PocketStore.instance === null) {
      PocketStore.instance = new PocketStore();
    }
    return PocketStore.instance as PocketStore;
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

  start(): void {
    if (this.pollTimer === -1) {
      this.pollTimer = setInterval(() => {
        this.repo.tick(Date.now());
        this.refresh();
      }, POLL_MS);
    }
    if (this.clockTimer === -1) {
      this.clockTimer = setInterval(() => {
        AppStorage.set<number>(Keys.NOW, Date.now());
      }, CLOCK_MS);
    }
    this.refresh();
  }

  stop(): void {
    if (this.pollTimer !== -1) {
      clearInterval(this.pollTimer);
      this.pollTimer = -1;
    }
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

  // ------------------------------------------------------------------ settings

  setPersona(id: string): void {
    if (id === this.settings.persona) {
      return;
    }
    this.settings.persona = id;
    this.saveSettings();
    this.publishSettings();
    this.refresh();
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
    this.refresh();
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
      this.refresh();
    }
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

  async refresh(): Promise<void> {
    if (this.refreshing) {
      return;
    }
    this.refreshing = true;
    const gen: number = this.generation;
    const viewAs: string = this.settings.persona;
    try {
      const page: ApprovalsPage = await this.repo.listApprovals(viewAs);
      const stats: PostureStats = await this.repo.getStats(viewAs);
      if (gen !== this.generation) {
        return; // mode switched while loading
      }
      this.mergeItems(page.items);
      stats.approvalsPending = page.pending;
      this.stats = stats;
      this.detectNew();
      this.publishData();
      AppStorage.set<string>(Keys.CONN_STATE, 'ok');
      AppStorage.set<string>(Keys.CONN_MSG, this.settings.mode === 'live' ?
        'Live: ' + this.settings.baseUrl : 'Mock mode: simulated gateway on this device');
    } catch (e) {
      const err: RepoError = e as RepoError;
      Log.warn('refresh failed: ' + err.message);
      AppStorage.set<string>(Keys.CONN_STATE, 'error');
      AppStorage.set<string>(Keys.CONN_MSG, err.message);
    } finally {
      this.refreshing = false;
    }
  }

  find(id: string): ApprovalItem | undefined {
    for (const it of this.items) {
      if (it.id === id) {
        return it;
      }
    }
    return undefined;
  }

  /** Optimistic approve/deny: the card updates at once and is rolled back if the gateway refuses. */
  async vote(id: string, decision: string, comment: string): Promise<VoteOutcome> {
    const idx: number = this.indexOf(id);
    if (idx < 0) {
      return new VoteOutcome(false, 'Request not found');
    }
    const before: ApprovalItem = this.items[idx];
    if (!before.canVote) {
      return new VoteOutcome(false, before.whyNot.length > 0 ? before.whyNot : 'You cannot vote on this request');
    }
    const p: Persona = this.persona();
    const optimistic: ApprovalItem = before.clone();
    optimistic.syncing = true;
    optimistic.canVote = false;
    optimistic.votes.push(new VoteView(p.id, p.role, decision, comment, Date.now()));
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
      const updated: ApprovalItem = await this.repo.vote(id, decision, p.id, comment);
      this.inflight.delete(id);
      this.replace(updated);
      this.publishData();
      NotificationService.cancelFor(id);
      this.refresh();
      if (updated.status === 'pending') {
        return new VoteOutcome(true, 'Vote recorded: waiting for a second approver');
      }
      return new VoteOutcome(true, decision === 'deny' ? 'Denied: the agent will be told no' : 'Approved: the agent may proceed');
    } catch (e) {
      const err: RepoError = e as RepoError;
      this.inflight.delete(id);
      this.replace(before);
      this.publishData();
      return new VoteOutcome(false, err.message);
    }
  }

  // ------------------------------------------------------------------ internals

  private applyRepo(): void {
    this.generation++;
    this.repo = this.settings.mode === 'live' ? new LiveRepository(this.settings.baseUrl) : this.mock;
  }

  private resetData(): void {
    this.items = [];
    this.seen.clear();
    this.firstLoad = true;
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

  private mergeItems(fresh: ApprovalItem[]): void {
    if (this.inflight.size === 0) {
      this.items = fresh;
      return;
    }
    const merged: ApprovalItem[] = [];
    for (const it of fresh) {
      if (this.inflight.has(it.id)) {
        const cur: ApprovalItem | undefined = this.find(it.id);
        merged.push(cur !== undefined ? cur : it);
      } else {
        merged.push(it);
      }
    }
    this.items = merged;
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
      NotificationService.notifyApproval(this.ctx as common.UIAbilityContext, it);
    }
    const first: ApprovalItem = fresh[0];
    const who: string = first.requesterAgent.length > 0 ? first.requesterAgent : first.requesterMember;
    AppStorage.set<string>(Keys.NEW_REQUEST, who + ': ' + first.title + '#' + Date.now().toString());
  }

  private publishData(): void {
    AppStorage.set<ApprovalItem[]>(Keys.APPROVALS, this.items.slice());
    let pending: number = 0;
    let top: string = '';
    for (const it of this.items) {
      if (it.status === 'pending') {
        pending++;
        if (top.length === 0) {
          top = it.amountUsd > 0 ? it.title + ' ($' + it.amountUsd.toFixed(0) + ')' : it.title;
        }
      }
    }
    this.stats.approvalsPending = pending;
    const statsCopy: PostureStats = this.copyStats();
    AppStorage.set<PostureStats>(Keys.STATS, statsCopy);
    AppStorage.set<number>(Keys.PENDING, pending);
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
