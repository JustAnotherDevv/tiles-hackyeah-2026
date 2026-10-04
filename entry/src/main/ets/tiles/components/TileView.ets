import { TileAction, TileBlock, TileSpec, Profile } from '../model/Tile';
import { TileColors, TilesTheme, withAlpha } from '../theme/TilesTheme';
import { BlockStyle, tileIcon } from './blocks/BlockStyle';
import { BlockView } from './blocks/BlockView';

/** One block plus its index in tile.blocks (needed for 'toggle' args) and a stable render key. */
class BlockSlot {
  key: string = '';
  index: number = 0;
  block: TileBlock = new TileBlock();
}

/** How long after creation an assistant tile still plays its "spring in" entrance. */
const APPEAR_WINDOW_MS: number = 20000;

/**
 * Generative-UI renderer: draws ANY TileSpec natively (size 1x1 / 2x1 / 2x2, palette color + on-color text,
 * SymbolGlyph icon, content blocks, actions), adapted to the Profile (textScale, highContrast, readAloud, tap size).
 *
 * The view never performs platform side effects: every interaction is reported through
 * `onAction(action, tile)` — tile tap = kind 'open', read-aloud = kind 'speak' (arg = text to speak),
 * buttons/chips = their TileAction, checklist = kind 'toggle' (arg '<block>:<item>'), timer = kind 'timer'.
 *
 * Usage: TileView({ tile: t, profile: p, dark: isDark, onAction: (a, t) => {...} })
 *        TileView({ tile: t, profile: p, mode: 'detail' })  // full-screen detail rendering
 */
@Component
export struct TileView {
  @Prop tile: TileSpec = new TileSpec();
  @Prop profile: Profile = new Profile();
  /** 'tile' (grid) or 'detail' (full screen, all blocks, larger type). */
  @Prop mode: string = 'tile';
  @Prop dark: boolean = false;
  /** true: take the parent's height (e.g. fixed-height GridItem); false: min height from the size's aspect. */
  @Prop fillHeight: boolean = false;
  @Prop reduceMotion: boolean = false;
  @State private pressed: boolean = false;
  @State private appearScale: number = 1;
  @State private appearOpacity: number = 1;
  @State private cardW: number = 0;
  private animateIn: boolean = false;
  onAction: (action: TileAction, tile: TileSpec) => void = (action: TileAction, tile: TileSpec) => {
  };
  /** Optional long-press (reorder / remove menu in the home grid). */
  onLongPress: (tile: TileSpec) => void = (tile: TileSpec) => {
  };

  aboutToAppear(): void {
    this.animateIn = !this.reduceMotion && this.mode === 'tile' && this.tile.source === 'assistant' &&
      (this.tile.createdAt <= 0 || Date.now() - this.tile.createdAt < APPEAR_WINDOW_MS);
    if (this.animateIn) {
      this.appearScale = 0.6;
      this.appearOpacity = 0;
    }
  }

  private colors(): TileColors {
    return TilesTheme.tile(this.tile.color, this.profile.highContrast, this.dark);
  }

  private isDetail(): boolean {
    return this.mode === 'detail';
  }

  private isCompact(): boolean {
    return !this.isDetail() && this.tile.size === '1x1';
  }

  private style(): BlockStyle {
    const c: TileColors = this.colors();
    const s: BlockStyle = new BlockStyle();
    s.fg = c.on;
    s.fgDim = c.onMuted;
    s.bg = c.bg;
    s.well = c.soft;
    s.solid = c.on;
    s.onSolid = c.bg;
    s.scale = TilesTheme.type(this.profile.textScale).scale;
    s.highContrast = this.profile.highContrast;
    s.minTap = TilesTheme.tapTarget(this.profile);
    s.detail = this.isDetail();
    s.reduceMotion = this.reduceMotion;
    s.compact = this.isCompact();
    return s;
  }

  private fs(base: number): number {
    return Math.round(base * TilesTheme.type(this.profile.textScale).scale * (this.isDetail() ? 1.15 : 1.0));
  }

  /** Which blocks fit this size: 1x1 → one glanceable block; 2x1 → two (keeping the buttons); 2x2 → four. */
  private slots(): BlockSlot[] {
    const all: TileBlock[] = this.tile.blocks;
    const picked: number[] = [];
    if (this.isDetail()) {
      for (let i = 0; i < all.length; i++) {
        picked.push(i);
      }
    } else if (this.tile.size === '1x1') {
      // One glanceable block (value / meter / timer / weather); otherwise the tile's primary action.
      for (let i = 0; i < all.length; i++) {
        const k: string = all[i].kind;
        if (k === 'big' || k === 'progress' || k === 'timer' || k === 'weather') {
          picked.push(i);
          break;
        }
      }
      if (picked.length === 0) {
        for (let i = 0; i < all.length; i++) {
          if (all[i].kind === 'buttons' || all[i].kind === 'text') {
            picked.push(i);
            break;
          }
        }
      }
    } else {
      const max: number = this.tile.size === '2x2' ? 4 : 2;
      for (let i = 0; i < all.length && picked.length < max; i++) {
        picked.push(i);
      }
      // Never hide the tile's actions: swap the last picked block for the first 'buttons' block.
      let btn: number = -1;
      for (let i = 0; i < all.length; i++) {
        if (all[i].kind === 'buttons') {
          btn = i;
          break;
        }
      }
      if (btn >= 0 && picked.indexOf(btn) < 0 && picked.length > 0) {
        picked[picked.length - 1] = btn;
      }
    }
    const out: BlockSlot[] = [];
    for (let j = 0; j < picked.length; j++) {
      const i: number = picked[j];
      const b: TileBlock = all[i];
      const s: BlockSlot = new BlockSlot();
      s.index = i;
      s.block = b;
      s.key = this.tile.id + '#' + i + ':' + b.kind + ':' + b.text + '|' + b.value + '|' + b.progress + '|' +
        b.items.join(',') + '|' + b.checked.join(',') + '|' + b.actions.length;
      out.push(s);
    }
    return out;
  }

  private minHeight(): number {
    if (this.isDetail() || this.cardW <= 0) {
      return 0;
    }
    if (this.tile.size === '2x1') {
      return Math.round(this.cardW * 0.5);
    }
    if (this.tile.size === '2x2') {
      return Math.round(this.cardW * 0.8);
    }
    return Math.round(this.cardW); // 1x1 is square
  }

  /** 1x1: skip the title line when the glanceable block already shows the same value (e.g. '14°'). */
  private titleRepeated(): boolean {
    for (let i = 0; i < this.tile.blocks.length; i++) {
      if (this.tile.blocks[i].value.length > 0 && this.tile.blocks[i].value === this.tile.title) {
        return true;
      }
    }
    return false;
  }

  private a11yText(): string {
    let s: string = this.tile.title;
    if (this.tile.speakText.length > 0) {
      s += '. ' + this.tile.speakText;
    } else if (this.tile.subtitle.length > 0) {
      s += '. ' + this.tile.subtitle;
    }
    return s;
  }

  private isNew(): boolean {
    return this.tile.source === 'assistant' && this.tile.createdAt > 0 &&
      Date.now() - this.tile.createdAt < 10 * 60 * 1000;
  }

  private emit(kind: string, arg: string, label: string): void {
    const a: TileAction = new TileAction();
    a.kind = kind;
    a.arg = arg;
    a.label = label;
    this.onAction(a, this.tile);
  }

  private speak(): void {
    this.emit('speak', this.tile.speakText.length > 0 ? this.tile.speakText : this.a11yText(), 'Read aloud');
  }

  @Builder
  badge(text: string, c: TileColors) {
    Text(text)
      .fontSize(this.fs(11))
      .fontWeight(FontWeight.Bold)
      .fontColor(c.bg)
      .letterSpacing(0.6)
      .padding({ left: 8, right: 8, top: 3, bottom: 3 })
      .borderRadius(999)
      .backgroundColor(c.on)
  }

  @Builder
  header(c: TileColors) {
    Row({ space: 12 }) {
      Stack() {
        SymbolGlyph(tileIcon(this.tile.icon, this.tile.type))
          .fontSize(this.fs(this.isCompact() ? 22 : 24))
          .fontColor([c.on])
      }
      .width(this.isCompact() ? 40 : 44)
      .height(this.isCompact() ? 40 : 44)
      .borderRadius(14)
      .backgroundColor(c.soft)

      if (!this.isCompact()) {
        Column({ space: 2 }) {
          Text(this.tile.title)
            .fontSize(this.fs(20))
            .fontWeight(FontWeight.Bold)
            .fontColor(c.on)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          if (this.tile.subtitle.length > 0) {
            Text(this.tile.subtitle)
              .fontSize(this.fs(14))
              .fontWeight(FontWeight.Medium)
              .fontColor(c.onMuted)
              .maxLines(this.isDetail() ? 3 : 1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
      } else {
        Blank()
      }

      if (this.isNew() && !this.isCompact()) {
        this.badge('NEW', c)
      } else if (this.tile.source === 'adaptation' && !this.isCompact()) {
        this.badge('ADAPTED', c)
      }

      if (this.profile.readAloud || this.isDetail()) {
        Stack() {
          SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
            .fontSize(this.fs(20))
            .fontColor([c.on])
        }
        .width(this.isCompact() ? 40 : 48)
        .height(this.isCompact() ? 40 : 48)
        .borderRadius(999)
        .backgroundColor(c.soft)
        .border({ width: this.profile.highContrast ? 2 : 0, color: c.on })
        .accessibilityText('Read ' + this.tile.title + ' aloud')
        .accessibilityRole(AccessibilityRoleType.BUTTON)
        .onClick(() => {
          this.speak();
        })
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  build() {
    Stack({ alignContent: Alignment.TopStart }) {
      // Decorative oversized glyph in the corner: gives every tile a distinct, poster-like look.
      SymbolGlyph(tileIcon(this.tile.icon, this.tile.type))
        .fontSize(this.isCompact() ? 72 : (this.tile.size === '2x2' || this.isDetail() ? 150 : 110))
        .fontColor([this.colors().on])
        .opacity(this.profile.highContrast ? 0 : 0.08)
        .position({ right: -18, bottom: -22 })
        .accessibilityLevel('no')

      Column({ space: this.isCompact() ? 8 : 14 }) {
        this.header(this.colors())

        if (this.isCompact() && !this.titleRepeated()) {
          Text(this.tile.title)
            .fontSize(this.fs(16))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.colors().on)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .width('100%')
        }

        ForEach(this.slots(), (s: BlockSlot) => {
          BlockView({
            block: s.block,
            bs: this.style(),
            blockIndex: s.index,
            onAction: (a: TileAction) => {
              this.onAction(a, this.tile);
            }
          })
        }, (s: BlockSlot) => s.key)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .justifyContent(FlexAlign.Start)
      .padding(this.isCompact() ? 12 : (this.isDetail() ? 22 : 16))
    }
    .width('100%')
    .height(this.fillHeight ? '100%' : 'auto')
    .constraintSize({ minHeight: this.minHeight() })
    .borderRadius(TilesTheme.radiusFor(this.isDetail() ? '2x2' : this.tile.size))
    .backgroundColor(this.colors().bg)
    .border({ width: this.profile.highContrast ? 3 : 0, color: this.colors().border })
    .shadow({
      radius: this.pressed ? 6 : 18,
      color: withAlpha(this.dark ? '#000000' : this.colors().bg, this.dark ? 0.4 : 0.35),
      offsetX: 0,
      offsetY: this.pressed ? 2 : 8
    })
    .clip(true)
    .opacity(this.appearOpacity)
    .scale({
      x: this.appearScale * (this.pressed ? TilesTheme.PRESS_SCALE : 1),
      y: this.appearScale * (this.pressed ? TilesTheme.PRESS_SCALE : 1)
    })
    .animation({ curve: TilesTheme.springPress(), duration: this.reduceMotion ? 0 : 250 })
    .onAreaChange((oldArea: Area, newArea: Area) => {
      const w: number = Number(newArea.width);
      if (!isNaN(w) && Math.abs(w - this.cardW) > 1) {
        this.cardW = w;
      }
    })
    .onAppear(() => {
      if (this.animateIn) {
        this.getUIContext().animateTo({ curve: TilesTheme.springIn() }, () => {
          this.appearScale = 1;
          this.appearOpacity = 1;
        });
      }
    })
    .onTouch((e: TouchEvent) => {
      if (this.isDetail()) {
        return;
      }
      if (e.type === TouchType.Down) {
        this.pressed = true;
      } else if (e.type === TouchType.Up || e.type === TouchType.Cancel) {
        this.pressed = false;
      }
    })
    .onClick(() => {
      if (!this.isDetail()) {
        this.emit('open', this.tile.id, this.tile.title);
      }
    })
    .gesture(
      LongPressGesture({ repeat: false, duration: 500 })
        .onAction(() => {
          this.pressed = false;
          this.onLongPress(this.tile);
        })
    )
    .accessibilityText(this.a11yText())
    .accessibilityDescription(this.isDetail() ? '' : 'Double tap to open')
  }
}
