import { Colors, Fonts, Radius, Space } from '../common/Theme';
import { Fmt } from '../common/Format';
import { ApprovalItem, PostureStats, budgetLeftPctOf, renderKeyOf } from '../model/Models';
import { ApprovalCard, KpiTile, ScreenHeader } from '../components/Common';

/** Dashboard: pending approvals hero, AI security posture KPIs, top requests. */
@Component
export struct HomeView {
  @StorageProp('approvals') approvals: ApprovalItem[] = [];
  @StorageProp('stats') stats: PostureStats = new PostureStats();
  @StorageProp('pendingCount') pending: number = 0;
  @StorageProp('connMessage') connMessage: string = '';
  @StorageProp('connState') connState: string = 'loading';
  @State pulse: number = 1;
  onOpenApproval: (id: string) => void = (id: string) => {
  };
  onOpenInbox: () => void = () => {
  };

  build() {
    Scroll() {
      Column({ space: Space.LG }) {
        ScreenHeader({ title: 'Aegis Pocket', subtitle: 'Human in the loop for your AI agents' })

        Column({ space: Space.LG }) {
          this.hero()

          if (this.connState === 'error') {
            Text(this.connMessage)
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.BAD)
              .padding(Space.MD)
              .width('100%')
              .borderRadius(Radius.MD)
              .backgroundColor(Colors.BAD_SOFT)
          }

          Text('AI SECURITY POSTURE · 24H')
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_DIM)
            .letterSpacing(1)
            .width('100%')

          Grid() {
            GridItem() {
              KpiTile({
                label: 'Threats blocked',
                value: Fmt.num(this.stats.blocked),
                hint: 'injection, exfil, secrets',
                tone: Colors.BAD
              })
            }

            GridItem() {
              KpiTile({
                label: 'Personal data redacted',
                value: Fmt.num(this.stats.redacted),
                hint: 'before leaving the org',
                tone: Colors.WARN
              })
            }

            GridItem() {
              KpiTile({
                label: 'Budget left today',
                value: Math.round(budgetLeftPctOf(this.stats)).toString() + '%',
                hint: Fmt.usd(this.stats.spendTodayUsd) + ' spent',
                tone: budgetLeftPctOf(this.stats) < 20 ? Colors.BAD : Colors.GOOD
              })
            }

            GridItem() {
              KpiTile({
                label: 'Agent requests',
                value: Fmt.num(this.stats.requests),
                hint: this.stats.activeAgents.toString() + ' active agents',
                tone: Colors.TEXT
              })
            }
          }
          .columnsTemplate('1fr 1fr')
          .columnsGap(Space.MD)
          .rowsGap(Space.MD)
          .width('100%')

          this.budgetBar()

          Row() {
            Text('NEEDS ATTENTION')
              .fontSize(Fonts.TINY)
              .fontColor(Colors.TEXT_DIM)
              .letterSpacing(1)
            Blank()
            Text('See all')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.ACCENT)
              .onClick(() => this.onOpenInbox())
          }
          .width('100%')

          ForEach(this.topPending(), (it: ApprovalItem) => {
            ApprovalCard({ item: it })
              .onClick(() => this.onOpenApproval(it.id))
              .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 16 }))
                .animation({ duration: 300, curve: Curve.EaseOut }))
          }, (it: ApprovalItem) => renderKeyOf(it))

          if (this.topPending().length === 0) {
            Text('No pending requests. Your agents are within policy.')
              .fontSize(Fonts.SMALL)
              .fontColor(Colors.TEXT_DIM)
              .width('100%')
          }

          Text('Tip: long-press the home screen and add the "AI posture" widget to see this at a glance.')
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_FAINT)
            .width('100%')
            .margin({ bottom: Space.XL })
        }
        .padding({ left: Space.PAGE, right: Space.PAGE })
      }
    }
    .scrollBar(BarState.Off)
    .edgeEffect(EdgeEffect.Spring)
    .align(Alignment.Top)
    .width('100%')
    .height('100%')
  }

  @Builder
  hero() {
    Row({ space: Space.LG }) {
      Stack() {
        Circle()
          .width(76)
          .height(76)
          .fill(this.pending > 0 ? Colors.VIOLET : Colors.GOOD)
          .opacity(Math.max(0, 0.45 - (this.pulse - 1) * 0.75))
          .scale({ x: this.pulse, y: this.pulse })
        Circle()
          .width(76)
          .height(76)
          .fill(this.pending > 0 ? Colors.VIOLET_SOFT : Colors.GOOD_SOFT)
        Text(this.pending.toString())
          .fontSize(34)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.pending > 0 ? Colors.VIOLET : Colors.GOOD)
          .fontFeature('"tnum" on')
      }
      .width(96)
      .height(96)
      .onAppear(() => {
        this.getUIContext().animateTo({ duration: 1600, iterations: -1, curve: Curve.EaseOut }, () => {
          this.pulse = 1.6;
        });
      })

      Column({ space: 4 }) {
        Text(this.pending === 1 ? 'request waiting for you' : 'requests waiting for you')
          .fontSize(Fonts.H2)
          .fontWeight(FontWeight.Bold)
          .fontColor(Colors.TEXT)
        Text(this.pending > 0 ? 'Agents are paused until a human approves.' : 'All clear. Nothing needs a decision.')
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT_DIM)
        Button('Review now')
          .fontSize(Fonts.SMALL)
          .fontColor(Color.White)
          .backgroundColor(Colors.ACCENT)
          .height(32)
          .margin({ top: 4 })
          .visibility(this.pending > 0 ? Visibility.Visible : Visibility.Hidden)
          .onClick(() => this.onOpenInbox())
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding(Space.LG)
    .borderRadius(Radius.LG)
    .linearGradient({
      angle: 135,
      colors: [[Colors.SURFACE_3, 0], [Colors.SURFACE, 1]]
    })
    .border({ width: 1, color: Colors.BORDER })
  }

  @Builder
  budgetBar() {
    Column({ space: 6 }) {
      Row() {
        Text('Org AI spend today')
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT_DIM)
        Blank()
        Text(Math.round(this.stats.budgetUsedPct).toString() + '% used')
          .fontSize(Fonts.SMALL)
          .fontColor(Colors.TEXT)
      }
      .width('100%')

      Progress({ value: Math.min(100, this.stats.budgetUsedPct), total: 100, type: ProgressType.Linear })
        .color(this.stats.budgetUsedPct > 80 ? Colors.BAD : Colors.ACCENT)
        .backgroundColor(Colors.SURFACE_3)
        .style({ strokeWidth: 8, strokeRadius: 4 })
        .width('100%')
    }
    .padding(Space.MD)
    .borderRadius(Radius.MD)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }

  private topPending(): ApprovalItem[] {
    const out: ApprovalItem[] = [];
    for (const it of this.approvals) {
      if (it.status === 'pending') {
        out.push(it);
        if (out.length >= 2) {
          break;
        }
      }
    }
    return out;
  }
}
