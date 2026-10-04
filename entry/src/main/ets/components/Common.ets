import { Colors, Fonts, Radius, RoleTone, Space } from '../common/Theme';
import { Fmt } from '../common/Format';
import {
  ApprovalItem,
  PERSONAS,
  Persona,
  actionLabelOf,
  glyphOf,
  requesterOf
} from '../model/Models';
import { PocketStore } from '../data/PocketStore';

/** Small rounded label. */
@Component
export struct Pill {
  @Prop text: string = '';
  @Prop fg: string = Colors.TEXT_DIM;
  @Prop bg: string = Colors.SURFACE_2;
  @Prop fontPx: number = Fonts.TINY;

  build() {
    Text(this.text)
      .fontSize(this.fontPx)
      .fontWeight(FontWeight.Medium)
      .fontColor(this.fg)
      .backgroundColor(this.bg)
      .borderRadius(Radius.PILL)
      .padding({ left: 8, right: 8, top: 3, bottom: 3 })
      .maxLines(1)
  }
}

/** "MOCK MODE" / "LIVE" badge. Mock data is always labelled. */
@Component
export struct ModeBadge {
  @StorageProp('mode') mode: string = 'mock';
  @StorageProp('connState') connState: string = 'loading';

  build() {
    Row({ space: 6 }) {
      Circle()
        .width(7)
        .height(7)
        .fill(this.dotColor())
      Text(this.mode === 'live' ? (this.connState === 'error' ? 'LIVE · OFFLINE' : 'LIVE') : 'MOCK MODE')
        .fontSize(Fonts.TINY)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.mode === 'live' ? (this.connState === 'error' ? Colors.BAD : Colors.GOOD) : Colors.WARN)
        .letterSpacing(0.8)
    }
    .padding({ left: 10, right: 10, top: 5, bottom: 5 })
    .borderRadius(Radius.PILL)
    .backgroundColor(this.mode === 'live' ? (this.connState === 'error' ? Colors.BAD_SOFT : Colors.GOOD_SOFT) :
    Colors.WARN_SOFT)
    .animation({ duration: 250 })
  }

  private dotColor(): string {
    if (this.mode !== 'live') {
      return Colors.WARN;
    }
    return this.connState === 'error' ? Colors.BAD : Colors.GOOD;
  }
}

/** Screen title row used by every tab. */
@Component
export struct ScreenHeader {
  @Prop title: string = '';
  @Prop subtitle: string = '';

  build() {
    Row() {
      Column({ space: 2 }) {
        Text(this.title)
          .fontSize(Fonts.TITLE)
          .fontWeight(FontWeight.Bold)
          .fontColor(Colors.TEXT)
        if (this.subtitle.length > 0) {
          Text(this.subtitle)
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT_DIM)
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      ModeBadge()
    }
    .width('100%')
    .padding({ left: Space.PAGE, right: Space.PAGE, top: Space.MD, bottom: Space.MD })
  }
}

/** Switches the viewer persona; sent to the gateway as X-Aegis-View-As. */
@Component
export struct PersonaSwitcher {
  @StorageProp('persona') persona: string = 'u_emily';

  build() {
    Row({ space: 6 }) {
      ForEach(PERSONAS, (p: Persona) => {
        Column({ space: 1 }) {
          Text(p.name)
            .fontSize(Fonts.SMALL)
            .fontWeight(this.persona === p.id ? FontWeight.Bold : FontWeight.Normal)
            .fontColor(this.persona === p.id ? Colors.TEXT : Colors.TEXT_DIM)
            .maxLines(1)
          Text(p.role)
            .fontSize(10)
            .fontColor(this.persona === p.id ? RoleTone.of(p.role).fg : Colors.TEXT_FAINT)
        }
        .layoutWeight(1)
        .padding({ top: 6, bottom: 6 })
        .borderRadius(Radius.SM)
        .backgroundColor(this.persona === p.id ? Colors.SURFACE_3 : Color.Transparent)
        .border({ width: this.persona === p.id ? 1 : 0, color: RoleTone.of(p.role).fg })
        .animation({ duration: 200, curve: Curve.EaseOut })
        .onClick(() => {
          PocketStore.get().setPersona(p.id);
        })
      }, (p: Persona) => p.id)
    }
    .width('100%')
    .padding(4)
    .borderRadius(Radius.MD)
    .backgroundColor(Colors.SURFACE)
  }
}

/** KPI tile for the posture dashboard. */
@Component
export struct KpiTile {
  @Prop label: string = '';
  @Prop value: string = '';
  @Prop hint: string = '';
  @Prop tone: string = Colors.TEXT;

  build() {
    Column({ space: 4 }) {
      Text(this.label)
        .fontSize(Fonts.TINY)
        .fontColor(Colors.TEXT_DIM)
        .letterSpacing(0.5)
      Text(this.value)
        .fontSize(22)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.tone)
        .fontFeature('"tnum" on')
      if (this.hint.length > 0) {
        Text(this.hint)
          .fontSize(Fonts.TINY)
          .fontColor(Colors.TEXT_FAINT)
          .maxLines(1)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .padding(Space.MD)
    .width('100%')
    .borderRadius(Radius.MD)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: Colors.BORDER })
  }
}

/** One approval request in a list. */
@Component
export struct ApprovalCard {
  @Prop item: ApprovalItem = new ApprovalItem();
  @StorageProp('nowMs') nowMs: number = Date.now();

  build() {
    Column({ space: Space.SM }) {
      Row({ space: Space.MD }) {
        Text(glyphOf(this.item))
          .fontSize(this.glyphSize())
          .fontWeight(FontWeight.Bold)
          .fontColor(RoleTone.of(this.item.requiredRole).fg)
          .textAlign(TextAlign.Center)
          .width(40)
          .height(40)
          .borderRadius(12)
          .backgroundColor(RoleTone.of(this.item.requiredRole).bg)

        Column({ space: 2 }) {
          Text(this.item.title)
            .fontSize(Fonts.BODY)
            .fontWeight(FontWeight.Medium)
            .fontColor(Colors.TEXT)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(requesterOf(this.item))
            .fontSize(Fonts.SMALL)
            .fontColor(Colors.TEXT_DIM)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        if (this.item.amountUsd > 0) {
          Text(Fmt.usd(this.item.amountUsd))
            .fontSize(Fonts.H2)
            .fontWeight(FontWeight.Bold)
            .fontColor(Colors.TEXT)
            .fontFeature('"tnum" on')
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      Row({ space: 6 }) {
        Pill({ text: actionLabelOf(this.item), fg: Colors.TEXT_DIM, bg: Colors.SURFACE_2 })
        Pill({
          text: 'needs ' + this.item.requiredRole + (this.item.twoPerson ? ' ×2' : ''),
          fg: RoleTone.of(this.item.requiredRole).fg,
          bg: RoleTone.of(this.item.requiredRole).bg
        })
        Blank()
        if (this.item.status === 'pending') {
          Text(this.item.syncing ? 'syncing…' : Fmt.countdown(this.item.expiresAtMs, this.nowMs))
            .fontSize(Fonts.TINY)
            .fontColor(this.urgent() ? Colors.BAD : Colors.TEXT_DIM)
            .fontFeature('"tnum" on')
        } else {
          Pill({
            text: this.item.status,
            fg: RoleTone.ofStatus(this.item.status).fg,
            bg: RoleTone.ofStatus(this.item.status).bg
          })
        }
      }
      .width('100%')

      if (this.item.status === 'pending' && !this.item.canVote && this.item.whyNot.length > 0) {
        Row({ space: 6 }) {
          Text('LOCKED')
            .fontSize(9)
            .fontWeight(FontWeight.Bold)
            .fontColor(Colors.TEXT_FAINT)
            .letterSpacing(0.8)
          Text(this.item.whyNot)
            .fontSize(Fonts.TINY)
            .fontColor(Colors.TEXT_FAINT)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
        }
        .width('100%')
      }
    }
    .padding(Space.LG)
    .width('100%')
    .borderRadius(Radius.LG)
    .backgroundColor(Colors.SURFACE)
    .border({ width: 1, color: this.item.status === 'pending' && this.item.canVote ? Colors.VIOLET_SOFT : Colors.BORDER })
    .opacity(this.item.status === 'pending' ? 1 : 0.72)
    .animation({ duration: 250, curve: Curve.EaseOut })
  }

  private glyphSize(): number {
    return glyphOf(this.item).length > 1 ? 13 : 18;
  }

  private urgent(): boolean {
    return this.item.expiresAtMs > 0 && this.item.expiresAtMs - this.nowMs < 5 * 60 * 1000;
  }
}

/** Placeholder for empty lists. */
@Component
export struct EmptyState {
  @Prop title: string = '';
  @Prop hint: string = '';

  build() {
    Column({ space: Space.SM }) {
      Text('✓')
        .fontSize(28)
        .fontColor(Colors.GOOD)
        .width(56)
        .height(56)
        .textAlign(TextAlign.Center)
        .borderRadius(28)
        .backgroundColor(Colors.GOOD_SOFT)
      Text(this.title)
        .fontSize(Fonts.BODY)
        .fontWeight(FontWeight.Medium)
        .fontColor(Colors.TEXT)
      Text(this.hint)
        .fontSize(Fonts.SMALL)
        .fontColor(Colors.TEXT_DIM)
        .textAlign(TextAlign.Center)
    }
    .width('100%')
    .padding({ top: 48, bottom: 48, left: Space.XL, right: Space.XL })
  }
}
