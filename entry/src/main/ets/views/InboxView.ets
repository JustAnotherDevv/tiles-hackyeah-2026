import { Colors, Fonts, Radius, Space } from '../common/Theme';
import { ApprovalItem, renderKeyOf } from '../model/Models';
import { ApprovalCard, EmptyState, PersonaSwitcher, ScreenHeader } from '../components/Common';
import { PocketStore } from '../data/PocketStore';

class FilterDef {
  id: string;
  label: string;

  constructor(id: string, label: string) {
    this.id = id;
    this.label = label;
  }
}

const FILTERS: FilterDef[] = [
  new FilterDef('pending', 'Pending'),
  new FilterDef('mine', 'I can act'),
  new FilterDef('decided', 'Decided')
];

/** Approvals inbox with persona switcher and filters. */
@Component
export struct InboxView {
  @StorageProp('approvals') approvals: ApprovalItem[] = [];
  @StorageProp('connState') connState: string = 'loading';
  @StorageProp('connMessage') connMessage: string = '';
  @State filter: string = 'pending';
  @State refreshing: boolean = false;
  onOpenApproval: (id: string) => void = (id: string) => {
  };

  build() {
    Column() {
      ScreenHeader({ title: 'Approvals', subtitle: 'Viewing as' })

      Column({ space: Space.MD }) {
        PersonaSwitcher()

        Row({ space: 6 }) {
          ForEach(FILTERS, (f: FilterDef) => {
            Text(f.label + ' ' + this.countFor(f.id).toString())
              .fontSize(Fonts.SMALL)
              .fontWeight(this.filter === f.id ? FontWeight.Bold : FontWeight.Normal)
              .fontColor(this.filter === f.id ? Colors.TEXT : Colors.TEXT_DIM)
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(Radius.PILL)
              .backgroundColor(this.filter === f.id ? Colors.ACCENT_SOFT : Colors.SURFACE)
              .animation({ duration: 200 })
              .onClick(() => {
                this.filter = f.id;
              })
          }, (f: FilterDef) => f.id)
        }
        .width('100%')

        if (this.connState === 'error') {
          Text(this.connMessage + ' · showing the last data received')
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.BAD)
            .padding(Space.MD)
            .width('100%')
            .borderRadius(Radius.MD)
            .backgroundColor(Colors.BAD_SOFT)
        }
      }
      .padding({ left: Space.PAGE, right: Space.PAGE, bottom: Space.MD })

      Refresh({ refreshing: $$this.refreshing }) {
        List({ space: Space.MD }) {
          ForEach(this.visible(), (it: ApprovalItem) => {
            ListItem() {
              ApprovalCard({ item: it })
                .onClick(() => this.onOpenApproval(it.id))
            }
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ x: 24 }))
              .animation({ duration: 280, curve: Curve.EaseOut }))
          }, (it: ApprovalItem) => renderKeyOf(it))

          if (this.visible().length === 0) {
            ListItem() {
              EmptyState({
                title: this.emptyTitle(),
                hint: 'New agent requests appear here and as notifications.'
              })
            }
          }
        }
        .width('100%')
        .height('100%')
        .padding({ left: Space.PAGE, right: Space.PAGE })
        .contentEndOffset(Space.XL)
        .scrollBar(BarState.Off)
        .edgeEffect(EdgeEffect.Spring)
      }
      .onRefreshing(() => {
        PocketStore.get().refresh().finally(() => {
          this.refreshing = false;
        });
      })
      .layoutWeight(1)
    }
    .width('100%')
    .height('100%')
  }

  private matches(it: ApprovalItem, f: string): boolean {
    if (f === 'pending') {
      return it.status === 'pending';
    }
    if (f === 'mine') {
      return it.status === 'pending' && it.canVote;
    }
    return it.status !== 'pending';
  }

  private visible(): ApprovalItem[] {
    const out: ApprovalItem[] = [];
    const filter: string = this.filter;
    const all: ApprovalItem[] = this.approvals;
    for (const it of all) {
      if (this.matches(it, filter)) {
        out.push(it);
      }
    }
    return out;
  }

  private countFor(f: string): number {
    let n: number = 0;
    const all: ApprovalItem[] = this.approvals;
    for (const it of all) {
      if (this.matches(it, f)) {
        n++;
      }
    }
    return n;
  }

  private emptyTitle(): string {
    if (this.filter === 'decided') {
      return 'No decisions yet';
    }
    if (this.filter === 'mine') {
      return 'Nothing this persona can approve';
    }
    return 'Inbox zero';
  }
}
