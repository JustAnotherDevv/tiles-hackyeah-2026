import { Colors, Fonts, Radius, RoleTone, Space } from '../common/Theme';
import { Fmt } from '../common/Format';
import {
  ApprovalItem,
  CheckItem,
  KeyValue,
  VoteOutcome,
  VoteView,
  actionLabelOf,
  glyphOf,
  personaById,
  personaName,
  requesterOf
} from '../model/Models';
import { Pill } from '../components/Common';
import { PocketStore } from '../data/PocketStore';
import { needsStepUp, sponsorOf, stepUpReason } from '../data/Eligibility';
import { RiskFactor, RiskSummary, explainRisk } from '../data/RiskExplainer';
import { StepUpAuth, StepUpOutcome } from '../platform/StepUpAuth';
import { Haptics } from '../platform/Haptics';
import { promptAction } from '@kit.ArkUI';

/** Approval detail with approve / deny, locked with a reason when the persona's role is insufficient. */
@Component
export struct DetailView {
  @Prop approvalId: string = '';
  @StorageProp('approvals') approvals: ApprovalItem[] = [];
  @StorageProp('nowMs') nowMs: number = Date.now();
  @StorageProp('persona') persona: string = 'u_emily';
  @State busy: string = ''; // '' | 'approve' | 'deny' | 'auth'
  @State comment: string = '';
  onClose: () => void = () => {
  };

  build() {
    NavDestination() {
      if (this.item() === undefined) {
        Column({ space: Space.MD }) {
          Text('Request not found')
            .fontSize(Fonts.H2)
            .fontColor(Colors.TEXT)
          Text('It may have expired or been removed from the gateway.')
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT_DIM)
        }
        .width('100%')
        .padding(Space.XL)
      } else {
        this.content(this.item() as ApprovalItem)
      }
    }
    .title('Request')
    .backgroundColor(Colors.BG)
  }

  @Builder
  content(it: ApprovalItem) {
    Column() {
      Scroll() {
        Column({ space: Space.LG }) {
          this.headerCard(it)
          if (it.status === 'pending') {
            this.riskCard(explainRisk(it))
          }
          this.decisionCard(it)
          if (it.budgetBefore >= 0 && it.budgetAfter >= 0) {
            this.budgetCard(it)
          }
          if (it.facts.length > 0) {
            this.factsCard(it.facts)
          }
          if (it.checks.length > 0) {
            this.checksCard(it.checks)
          }
          if (it.agentNote.length > 0) {
            this.noteCard(it.agentNote)
          }
          if (it.votes.length > 0) {
            this.votesCard(it.votes)
          }
          Text('Request ' + it.id + (it.ruleId.length > 0 ? ' · rule ' + it.ruleId : '') +
            (it.controlId.length > 0 ? ' · ' + it.controlId : ''))
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_FAINT)
            .width('100%')
        }
        .padding({ left: Space.PAGE, right: Space.PAGE, top: Space.SM, bottom: Space.XL })
      }
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .align(Alignment.Top)
      .layoutWeight(1)

      this.actionBar(it)
    }
    .width('100%')
    .height('100%')
  }

  @Builder
  headerCard(it: ApprovalItem) {
    Column({ space: Space.MD }) {
      Row({ space: Space.MD }) {
        Text(glyphOf(it))
          .fontSize(glyphOf(it).length > 1 ? 15 : 22)
          .fontWeight(FontWeight.Bold)
          .fontColor(RoleTone.of(it.requiredRole).fg)
          .textAlign(TextAlign.Center)
          .width(52)
          .height(52)
          .borderRadius(16)
          .backgroundColor(RoleTone.of(it.requiredRole).bg)
        Column({ space: 2 }) {
          Text(actionLabelOf(it).toUpperCase())
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_DIM)
            .letterSpacing(1)
          Text(requesterOf(it))
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT)
          if (it.requesterAgent.length > 0 && sponsorOf(it.requesterAgent).length > 0) {
            Text('sponsor: ' + personaName(sponsorOf(it.requesterAgent)))
              .fontSize(Fonts.TINY)
              .fontColor(Colors.TEXT_FAINT)
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Pill({ text: it.status, fg: RoleTone.ofStatus(it.status).fg, bg: RoleTone.ofStatus(it.status).bg })
      }
      .width('100%')

      Text(it.title)
        .fontSize(22)
        .fontWeight(FontWeight.Bold)
        .fontColor(Colors.TEXT)
        .width('100%')
      if (it.summary.length > 0) {
        Text(it.summary)
          .fontSize(Fonts.BODY)
          .fontColor(Colors.TEXT_DIM)
          .width('100%')
      }
      if (it.amountUsd > 0) {
        Text(Fmt.usd(it.amountUsd))
          .fontSize(40)
          .fontWeight(FontWeight.Bold)
          .fontColor(Colors.TEXT)
          .fontFeature('"tnum" on')
          .width('100%')
      }
      if (it.resource.length > 0) {
        Text(it.resource)
          .fontSize(Fonts.SMALL)
          .fontFamily('monospace')
          .fontColor(Colors.TEXT_DIM)
          .padding({ left: 8, right: 8, top: 4, bottom: 4 })
          .borderRadius(Radius.SM)
          .backgroundColor(Colors.SURFACE_2)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  riskCard(r: RiskSummary) {
    Column({ space: Space.SM }) {
      Row({ space: Space.SM }) {
        Text('WHY A HUMAN IS ASKED')
          .fontSize(Fonts.TINY)
          .fontColor(Colors.TEXT_DIM)
          .letterSpacing(1)
        Blank()
        Pill({
          text: r.level + ' risk · ' + r.score.toString(),
          fg: this.riskTone(r.level),
          bg: this.riskToneSoft(r.level),
          fontPx: Fonts.SMALL
        })
      }
      .width('100%')

      Row() {
        Column()
          .width(r.score.toString() + '%')
          .height('100%')
          .borderRadius(3)
          .backgroundColor(this.riskTone(r.level))
          .animation({ duration: 400, curve: Curve.EaseOut })
      }
      .width('100%')
      .height(6)
      .borderRadius(3)
      .backgroundColor(Colors.SURFACE_3)

      Text(r.headline)
        .fontSize(Fonts.BODY)
        .fontWeight(FontWeight.Medium)
        .fontColor(Colors.TEXT)
        .width('100%')
      ForEach(r.factors, (f: RiskFactor) => {
        Row({ space: Space.SM }) {
          Text('+' + f.points.toString())
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_FAINT)
            .fontFeature('"tnum" on')
            .width(28)
          Text(f.text)
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT_DIM)
            .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }, (f: RiskFactor) => f.text)
      Text(r.advice + ' On-device, rule-based: nothing is sent anywhere to compute it.')
        .fontSize(Fonts.TINY)
        .fontColor(Colors.TEXT_FAINT)
        .width('100%')
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
    .accessibilityGroup(true)
    .accessibilityText('Risk ' + r.level + ', score ' + r.score.toString() + ' of 100. ' + r.headline)
  }

  @Builder
  decisionCard(it: ApprovalItem) {
    Column({ space: Space.SM }) {
      Row() {
        Text('Who can approve')
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT_DIM)
        Blank()
        Pill({
          text: it.requiredRole + (it.twoPerson ? ' + admin (two-person)' : ''),
          fg: RoleTone.of(it.requiredRole).fg,
          bg: RoleTone.of(it.requiredRole).bg,
          fontPx: Fonts.SMALL
        })
      }
      .width('100%')

      if (it.twoPerson) {
        Row({ space: 6 }) {
          ForEach([0, 1], (i: number) => {
            Column()
              .height(6)
              .layoutWeight(1)
              .borderRadius(3)
              .backgroundColor(i < this.approveVotes(it) ? Colors.GOOD : Colors.SURFACE_3)
              .animation({ duration: 300 })
          }, (i: number) => i.toString())
        }
        .width('100%')

        Text(this.approveVotes(it).toString() + ' of 2 approvals')
          .fontSize(Fonts.TINY)
          .fontColor(Colors.TEXT_DIM)
      }

      Row() {
        Text(it.status === 'pending' ? 'Expires' : 'Decided')
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT_DIM)
        Blank()
        Text(it.status === 'pending' ? Fmt.countdown(it.expiresAtMs, this.nowMs) :
          (it.decidedAtMs > 0 ? Fmt.ago(it.decidedAtMs, this.nowMs) : it.status))
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT)
          .fontFeature('"tnum" on')
      }
      .width('100%')

      Row() {
        Text('Requested')
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT_DIM)
        Blank()
        Text(Fmt.ago(it.createdAtMs, this.nowMs))
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT)
      }
      .width('100%')
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  budgetCard(it: ApprovalItem) {
    Column({ space: Space.SM }) {
      Text('BUDGET CHANGE · ' + it.budgetScope)
        .fontSize(Fonts.TINY)
        .fontColor(Colors.TEXT_DIM)
        .letterSpacing(1)
      Row({ space: Space.MD }) {
        Text(Fmt.usd(it.budgetBefore))
          .fontSize(26)
          .fontWeight(FontWeight.Bold)
          .fontColor(Colors.TEXT_DIM)
        Text('→')
          .fontSize(22)
          .fontColor(Colors.TEXT_FAINT)
        Text(Fmt.usd(it.budgetAfter))
          .fontSize(26)
          .fontWeight(FontWeight.Bold)
          .fontColor(Colors.WARN)
        Blank()
        Text('+' + Math.round((it.budgetAfter - it.budgetBefore) / Math.max(1, it.budgetBefore) * 100).toString() + '%')
          .fontSize(Fonts.BODY)
          .fontColor(Colors.WARN)
      }
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  factsCard(facts: KeyValue[]) {
    Column() {
      Text('FACTS')
        .fontSize(Fonts.TINY)
        .fontColor(Colors.TEXT_DIM)
        .letterSpacing(1)
        .width('100%')
        .margin({ bottom: Space.SM })
      ForEach(facts, (kv: KeyValue, idx: number) => {
        Row() {
          Text(kv.key)
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT_DIM)
            .layoutWeight(1)
          Text(kv.value)
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT)
            .textAlign(TextAlign.End)
            .layoutWeight(1.4)
        }
        .width('100%')
        .padding({ top: 7, bottom: 7 })
        .border({ width: { top: idx === 0 ? 0 : 1 }, color: Colors.BORDER })
      }, (kv: KeyValue) => kv.key)
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  checksCard(checks: CheckItem[]) {
    Column({ space: Space.SM }) {
      Text('POLICY CHECKS')
        .fontSize(Fonts.TINY)
        .fontColor(Colors.TEXT_DIM)
        .letterSpacing(1)
        .width('100%')
      ForEach(checks, (c: CheckItem) => {
        Row({ space: Space.SM }) {
          Text(c.ok ? '✓' : '!')
            .fontSize(12)
            .fontWeight(FontWeight.Bold)
            .fontColor(c.ok ? Colors.GOOD : Colors.WARN)
            .width(20)
            .height(20)
            .textAlign(TextAlign.Center)
            .borderRadius(10)
            .backgroundColor(c.ok ? Colors.GOOD_SOFT : Colors.WARN_SOFT)
          Column() {
            Text(c.name)
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT)
            if (c.detail.length > 0) {
              Text(c.detail)
                .fontSize(Fonts.TINY)
                .fontColor(Colors.TEXT_FAINT)
            }
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
      }, (c: CheckItem) => c.name)
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  noteCard(note: string) {
    Column({ space: Space.SM }) {
      Row() {
        Text('AGENT NOTE')
          .fontSize(Fonts.TINY)
          .fontColor(Colors.TEXT_DIM)
          .letterSpacing(1)
        Blank()
        Pill({ text: 'agent-supplied, untrusted', fg: Colors.WARN, bg: Colors.WARN_SOFT })
      }
      .width('100%')
      Text('"' + note + '"')
        .fontSize(Fonts.SMALL)
        .fontStyle(FontStyle.Italic)
        .fontColor(Colors.TEXT_DIM)
        .width('100%')
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  votesCard(votes: VoteView[]) {
    Column({ space: Space.SM }) {
      Text('VOTES')
        .fontSize(Fonts.TINY)
        .fontColor(Colors.TEXT_DIM)
        .letterSpacing(1)
        .width('100%')
      ForEach(votes, (v: VoteView) => {
        Row({ space: Space.SM }) {
          Circle()
            .width(8)
            .height(8)
            .fill(v.decision === 'approve' ? Colors.GOOD : Colors.BAD)
          Text(personaName(v.memberId) + ' (' + v.role + ') ' + (v.decision === 'approve' ? 'approved' : 'denied'))
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT)
            .layoutWeight(1)
          Text(v.tsMs > 0 ? Fmt.ago(v.tsMs, this.nowMs) : '')
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_FAINT)
        }
        .width('100%')
      }, (v: VoteView) => v.memberId + v.decision)
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  actionBar(it: ApprovalItem) {
    Column({ space: Space.SM }) {
      if (it.status === 'pending') {
        if (!it.canVote) {
          Row({ space: Space.SM }) {
            Text('LOCKED')
              .fontSize(9)
              .fontWeight(FontWeight.Bold)
              .fontColor(Colors.WARN)
              .letterSpacing(0.8)
            Text(it.whyNot.length > 0 ? it.whyNot : 'You cannot vote on this request')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT_DIM)
              .layoutWeight(1)
          }
          .width('100%')
          .padding({ left: Space.MD, right: Space.MD, top: Space.SM, bottom: Space.SM })
          .borderRadius(Radius.MD)
          .backgroundColor(Colors.WARN_SOFT)
        } else {
          TextInput({ placeholder: 'Comment (optional)', text: $$this.comment })
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT)
            .placeholderColor(Colors.TEXT_FAINT)
            .backgroundColor(Colors.SURFACE_2)
            .borderRadius(Radius.MD)
            .height(40)
            .maxLength(200)
        }
        if (it.canVote && needsStepUp(it)) {
          Row({ space: Space.SM }) {
            Text('STEP-UP')
              .fontSize(9)
              .fontWeight(FontWeight.Bold)
              .fontColor(Colors.ACCENT)
              .letterSpacing(0.8)
            Text('Approving asks for your face, fingerprint or PIN · ' + stepUpReason(it))
              .fontSize(Fonts.TINY)
              .fontColor(Colors.TEXT_DIM)
              .layoutWeight(1)
          }
          .width('100%')
          .padding({ left: Space.MD, right: Space.MD, top: 6, bottom: 6 })
          .borderRadius(Radius.MD)
          .backgroundColor(Colors.ACCENT_SOFT)
          .accessibilityGroup(true)
        }
        Row({ space: Space.MD }) {
          Button(this.busy === 'deny' ? 'Denying…' : 'Deny')
            .fontSize(Fonts.BODY)
            .fontWeight(FontWeight.Medium)
            .fontColor(it.canVote ? Colors.BAD : Colors.TEXT_FAINT)
            .backgroundColor(it.canVote ? Colors.BAD_SOFT : Colors.SURFACE_2)
            .constraintSize({ minHeight: 48 })
            .layoutWeight(1)
            .enabled(it.canVote && this.busy.length === 0)
            .accessibilityText('Deny request')
            .accessibilityDescription(it.canVote ? 'Tells the agent no: ' + it.title :
              (it.whyNot.length > 0 ? it.whyNot : 'You cannot vote on this request'))
            .onClick(() => this.vote(it.id, 'deny'))
          Button(this.busy === 'auth' ? 'Verifying…' : (this.busy === 'approve' ? 'Approving…' : 'Approve'))
            .fontSize(Fonts.BODY)
            .fontWeight(FontWeight.Bold)
            .fontColor(it.canVote ? Color.White : Colors.TEXT_FAINT)
            .backgroundColor(it.canVote ? Colors.GOOD : Colors.SURFACE_2)
            .constraintSize({ minHeight: 48 })
            .layoutWeight(1.4)
            .enabled(it.canVote && this.busy.length === 0)
            .accessibilityText('Approve request')
            .accessibilityDescription(it.canVote ? (needsStepUp(it) ?
              'Asks for face, fingerprint or PIN, then lets the agent proceed: ' + it.title :
              'Lets the agent proceed: ' + it.title) :
              (it.whyNot.length > 0 ? it.whyNot : 'You cannot vote on this request'))
            .onClick(() => this.vote(it.id, 'approve'))
        }
        .width('100%')

        Text('Acting as ' + personaById(this.persona).name + ' (' + personaById(this.persona).role + ')')
          .fontSize(Fonts.TINY)
          .fontColor(Colors.TEXT_FAINT)
      } else {
        Text(this.decidedText(it))
          .fontSize(Fonts.BODY)
          .fontWeight(FontWeight.Medium)
          .fontColor(RoleTone.ofStatus(it.status).fg)
          .textAlign(TextAlign.Center)
          .width('100%')
          .padding(Space.MD)
          .borderRadius(Radius.MD)
          .backgroundColor(RoleTone.ofStatus(it.status).bg)
          .transition(TransitionEffect.scale({ x: 0.9, y: 0.9 }).combine(TransitionEffect.OPACITY)
            .animation({ duration: 260, curve: Curve.EaseOut }))
      }
    }
    .padding({ left: Space.PAGE, right: Space.PAGE, top: Space.MD, bottom: Space.LG })
    .width('100%')
    .backgroundColor(Colors.BG)
    .border({ width: { top: 1 }, color: Colors.BORDER })
  }

  private item(): ApprovalItem | undefined {
    const id: string = this.approvalId.split('#')[0];
    for (const it of this.approvals) {
      if (it.id === id) {
        return it;
      }
    }
    return undefined;
  }

  private approveVotes(it: ApprovalItem): number {
    let n: number = 0;
    for (const v of it.votes) {
      if (v.decision === 'approve') {
        n++;
      }
    }
    return n;
  }

  private decidedText(it: ApprovalItem): string {
    if (it.status === 'approved') {
      return 'Approved · the agent may proceed';
    }
    if (it.status === 'denied') {
      return 'Denied · the agent was told no';
    }
    if (it.status === 'expired') {
      return 'Expired · nobody decided in time (fail-closed)';
    }
    return it.status;
  }

  private riskTone(level: string): string {
    return level === 'high' ? Colors.BAD : (level === 'medium' ? Colors.WARN : Colors.GOOD);
  }

  private riskToneSoft(level: string): string {
    return level === 'high' ? Colors.BAD_SOFT : (level === 'medium' ? Colors.WARN_SOFT : Colors.GOOD_SOFT);
  }

  private vote(id: string, decision: string): void {
    if (this.busy.length > 0) {
      return;
    }
    const it: ApprovalItem | undefined = this.item();
    if (decision === 'approve' && it !== undefined && needsStepUp(it)) {
      this.stepUpThenVote(it);
      return;
    }
    this.submit(id, decision, '');
  }

  /** User Authentication Kit step-up; labelled manual fallback when the device has no authenticator. */
  private stepUpThenVote(it: ApprovalItem): void {
    this.busy = 'auth';
    const title: string = 'Approve: ' + it.title + (it.amountUsd > 0 ? ' (' + Fmt.usd(it.amountUsd) + ')' : '');
    StepUpAuth.authenticate(title).then((o: StepUpOutcome) => {
      if (o.status === 'verified') {
        Haptics.success();
        this.busy = '';
        this.submit(it.id, 'approve', 'Verified with ' + o.detail + '. ');
      } else if (o.status === 'unavailable') {
        this.busy = '';
        this.confirmFallback(it, o.detail);
      } else {
        this.busy = '';
        Haptics.failure();
        this.getUIContext().getPromptAction().showToast({ message: o.detail + ': not approved', duration: 2500 });
      }
    });
  }

  private confirmFallback(it: ApprovalItem, reason: string): void {
    this.getUIContext().getPromptAction().showDialog({
      title: 'Device authentication unavailable',
      message: reason + '. This happens on the emulator, which cannot simulate biometrics, or when no lock-screen ' +
        'PIN is set.\n\nFALLBACK (not biometric): confirm manually to approve "' + it.title + '".',
      buttons: [
        { text: 'Cancel', color: Colors.TEXT_DIM },
        { text: 'Approve without biometrics', color: Colors.WARN }
      ]
    }).then((r: promptAction.ShowDialogSuccessResponse) => {
      if (r.index === 1) {
        this.submit(it.id, 'approve', 'Manual confirmation (no device authentication). ');
      }
    }).catch(() => {
      // dismissed: nothing approved
    });
  }

  private submit(id: string, decision: string, toastPrefix: string): void {
    this.busy = decision;
    PocketStore.get().vote(id, decision, this.comment).then((r: VoteOutcome) => {
      this.busy = '';
      this.comment = '';
      if (r.ok && decision === 'approve') {
        Haptics.success();
      } else {
        Haptics.failure();
      }
      this.getUIContext().getPromptAction().showToast({ message: toastPrefix + r.message, duration: 2500 });
    });
  }
}
