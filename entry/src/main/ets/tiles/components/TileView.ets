import { TileAction, TileBlock, TileSpec, Profile } from '../model/Tile';
import { TileColors, TilesTheme, withAlpha } from '../theme/TilesTheme';
import { BlockStyle, tileIcon } from './blocks/BlockStyle';
import { BlockView } from './blocks/BlockView';
import { percentOf } from './blocks/ProgressBlock';

/** One block plus its index in tile.blocks (needed for 'toggle' args) and a stable render key. */
class BlockSlot {
  key: string = '';
  index: number = 0;
  block: TileBlock = new TileBlock();
  /** 0 = keep longest (hero value) ... 3 = drop first when the tile is too short. */
  priority: number = 2;
}

/** Block kinds that can be a tile's single "key value" in compact tiles. */
const KEY_KINDS: string[] = ['big', 'timer', 'progress', 'weather', 'alert'];

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
 * Responsive: the layout tier comes from the tile's MEASURED size (onAreaChange), scaled by the profile's text size:
 *  - compact (narrow and short, or 1x1): icon + title (<= 2 lines, shrinks before it ellipsizes, never mid-word),
 *    ONE key value (big / timer / progress / weather / alert), at most one primary button; no subtitle/chips/lists.
 *  - medium: title + 1-line subtitle + the primary block(s) + up to 2 chips + up to 2 buttons.
 *  - full: everything that fits (detail mode is always full).
 * In fixed-height grid cells, blocks that would overflow the tile are dropped lowest-priority first (measured,
 * not guessed); a soft fade is only drawn if even the last block cannot fit. accessibilityText always carries the
 * full content (title, subtitle, every block), so nothing hidden visually is lost to screen-reader users.
 *
 * Usage: TileView({ tile: t, profile: p, dark: isDark, onAction: (a, t) => {...} })
 *        TileView({ tile: t, profile: p, mode: 'detail' })  // full-screen detail rendering
 */
@Component
export struct TileView {
  @Prop @Watch('onInputs') tile: TileSpec = new TileSpec();
  @Prop @Watch('onInputs') profile: Profile = new Profile();
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
  @State private cardH: number = 0;
  /** tile.blocks indexes dropped because they did not fit the measured tile height. */
  @State private dropped: number[] = [];
  /** Even the last remaining block overflows: draw a soft fade at the bottom edge (last resort). */
  @State private overflowFade: boolean = false;
  /** Measured bottom edge (vp, inside the content column) per block index. */
  private bottoms: Map<number, number> = new Map<number, number>();
  private fitPending: boolean = false;
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

  onInputs(): void {
    this.resetFit();
  }

  private resetFit(): void {
    this.bottoms.clear();
    if (this.dropped.length > 0) {
      this.dropped = [];
    }
    if (this.overflowFade) {
      this.overflowFade = false;
    }
  }

  private colors(): TileColors {
    return TilesTheme.tile(this.tile.color, this.profile.highContrast, this.dark);
  }

  private isDetail(): boolean {
    return this.mode === 'detail';
  }

  private typeScale(): number {
    const s: number = TilesTheme.type(this.profile.textScale).scale;
    return s > 0 ? s : 1;
  }

  /** Measured width in "unscaled" vp (width / text scale): how much room the text really has. */
  private effW(): number {
    const w: number = this.cardW > 0 ? this.cardW : (this.tile.size === '1x1' ? 90 : 184);
    return w / this.typeScale();
  }

  /** Measured height in unscaled vp; unbounded when the tile sizes to its content. */
  private effH(): number {
    if (!this.fillHeight || this.isDetail()) {
      return 9999;
    }
    return (this.cardH > 0 ? this.cardH : 150) / this.typeScale();
  }

  /** Layout tier from the measured size: 'compact' | 'medium' | 'full'. */
  private tier(): string {
    if (this.isDetail()) {
      return 'full';
    }
    if (this.tile.size === '1x1') {
      return 'compact';
    }
    const ew: number = this.effW();
    const eh: number = this.effH();
    if (ew < 200 && eh < 200) {
      return 'compact';
    }
    if (ew < 320 || eh < 200) {
      return 'medium';
    }
    return 'full';
  }

  private isCompact(): boolean {
    return this.tier() === 'compact';
  }

  private narrow(): boolean {
    return !this.isDetail() && this.effW() < 230;
  }

  private tiny(): boolean {
    return !this.isDetail() && this.effW() < 120;
  }

  /** Title next to the icon (wide or short tiles) vs. icon row on top + full-width title (narrow, tall tiles). */
  private titleBeside(): boolean {
    return !this.tiny() && (!this.narrow() || this.effH() < 170);
  }

  private pad(): number {
    if (this.isDetail()) {
      return 22;
    }
    if (this.tiny()) {
      return 10;
    }
    return this.isCompact() ? 12 : 16;
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
    s.scale = this.typeScale();
    s.highContrast = this.profile.highContrast;
    s.minTap = TilesTheme.tapTarget(this.profile);
    s.detail = this.isDetail();
    s.reduceMotion = this.reduceMotion;
    s.tier = this.tier();
    s.compact = s.tier === 'compact';
    s.narrow = this.narrow();
    s.tiny = this.tiny();
    return s;
  }

  private fs(base: number): number {
    return Math.round(base * this.typeScale() * (this.isDetail() ? 1.15 : 1.0));
  }

  private titleFs(): number {
    if (this.isCompact()) {
      return this.fs(this.tiny() ? 15 : 16);
    }
    return this.fs(this.narrow() ? 18 : 20);
  }

  private firstKind(kind: string): number {
    for (let i = 0; i < this.tile.blocks.length; i++) {
      if (this.tile.blocks[i].kind === kind) {
        return i;
      }
    }
    return -1;
  }

  /** Which blocks this tier shows (before height capping), in original order. */
  private pickIndexes(): number[] {
    const all: TileBlock[] = this.tile.blocks;
    const picked: number[] = [];
    const tier: string = this.tier();
    if (this.isDetail()) {
      for (let i = 0; i < all.length; i++) {
        picked.push(i);
      }
      return picked;
    }
    if (tier === 'compact') {
      // ONE key value; tiny tiles only take a short hero value (no controls).
      for (let i = 0; i < all.length; i++) {
        const k: string = all[i].kind;
        if (this.tiny() ? (k === 'big' || k === 'weather') : KEY_KINDS.indexOf(k) >= 0) {
          picked.push(i);
          break;
        }
      }
      if (picked.length === 0 && !this.tiny()) {
        const cl: number = this.firstKind('checklist'); // shown as "2 of 6 done"
        if (cl >= 0) {
          picked.push(cl);
        }
      }
      if (!this.tiny()) {
        const btn: number = this.firstKind('buttons');
        if (btn >= 0) {
          picked.push(btn); // rendered as a single primary button; dropped first if it does not fit
        }
        if (picked.length === 0) {
          const tx: number = this.firstKind('text');
          if (tx >= 0) {
            picked.push(tx);
          }
        }
      }
    } else if (tier === 'medium') {
      const maxContent: number = this.effH() >= 240 ? 2 : 1;
      let n: number = 0;
      let chips: boolean = false;
      let btns: boolean = false;
      for (let i = 0; i < all.length; i++) {
        const k: string = all[i].kind;
        if (k === 'buttons') {
          if (!btns) {
            picked.push(i);
            btns = true;
          }
        } else if (k === 'chips') {
          if (!chips) {
            picked.push(i);
            chips = true;
          }
        } else if (n < maxContent) {
          picked.push(i);
          n++;
        }
      }
    } else {
      const max: number = this.tile.size === '2x2' ? 4 : 2;
      for (let i = 0; i < all.length && picked.length < max; i++) {
        picked.push(i);
      }
      // Never hide the tile's actions: swap the last picked block for the first 'buttons' block.
      const btn: number = this.firstKind('buttons');
      if (btn >= 0 && picked.indexOf(btn) < 0 && picked.length > 0) {
        picked[picked.length - 1] = btn;
      }
    }
    picked.sort((a: number, b: number) => a - b);
    return picked;
  }

  /** Visible blocks: the tier's picks minus the ones dropped for height. */
  private slots(): BlockSlot[] {
    const picked: number[] = this.pickIndexes();
    const out: BlockSlot[] = [];
    let first: boolean = true;
    for (let j = 0; j < picked.length; j++) {
      const i: number = picked[j];
      const b: TileBlock = this.tile.blocks[i];
      if (this.dropped.indexOf(i) >= 0) {
        continue;
      }
      const s: BlockSlot = new BlockSlot();
      s.index = i;
      s.block = b;
      if (b.kind === 'buttons' || b.kind === 'alert') {
        s.priority = 1;
      } else if (b.kind === 'chips') {
        s.priority = 3;
      } else if (first) {
        s.priority = 0;
        first = false;
      } else {
        s.priority = 2;
      }
      s.key = this.tile.id + '#' + i + ':' + b.kind + ':' + b.text + '|' + b.value + '|' + b.progress + '|' +
        b.items.join(',') + '|' + b.checked.join(',') + '|' + b.actions.length;
      out.push(s);
    }
    return out;
  }

  private scheduleFit(): void {
    if (!this.fillHeight || this.isDetail() || this.fitPending) {
      return;
    }
    this.fitPending = true;
    setTimeout(() => {
      this.fitPending = false;
      this.fit();
    }, 32);
  }

  /** Drop the lowest-priority block while any visible block's measured bottom exceeds the tile. */
  private fit(): void {
    if (this.cardH <= 0) {
      return;
    }
    const limit: number = this.cardH - this.pad() + 2;
    const visible: BlockSlot[] = this.slots();
    let over: boolean = false;
    for (let i = 0; i < visible.length; i++) {
      const b: number | undefined = this.bottoms.get(visible[i].index);
      if (b !== undefined && b > limit) {
        over = true;
      }
    }
    if (!over) {
      if (this.overflowFade) {
        this.overflowFade = false;
      }
      return;
    }
    if (visible.length <= 1) {
      this.overflowFade = true;
      return;
    }
    let victim: BlockSlot = visible[0];
    for (let i = 1; i < visible.length; i++) {
      const s: BlockSlot = visible[i];
      if (s.priority > victim.priority || (s.priority === victim.priority && s.index > victim.index)) {
        victim = s;
      }
    }
    const next: number[] = this.dropped.slice();
    next.push(victim.index);
    this.bottoms.delete(victim.index);
    this.dropped = next;
    this.scheduleFit();
  }

  private minHeight(): number {
    if (this.isDetail() || this.cardW <= 0 || this.fillHeight) {
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

  /** Compact: skip the title line when the hero block already shows the same value (e.g. '14°'). */
  private titleRepeated(): boolean {
    if (!this.isCompact()) {
      return false;
    }
    for (let i = 0; i < this.tile.blocks.length; i++) {
      if (this.tile.blocks[i].value.length > 0 && this.tile.blocks[i].value === this.tile.title) {
        return true;
      }
    }
    return false;
  }

  /** Spoken summary of one block (screen readers get everything, even what the tile hides). */
  private blockSummary(b: TileBlock): string {
    const parts: string[] = [];
    if (b.kind === 'buttons') {
      const labels: string[] = [];
      for (let i = 0; i < b.actions.length; i++) {
        labels.push(b.actions[i].label.length > 0 ? b.actions[i].label : b.actions[i].kind);
      }
      return labels.length > 0 ? 'Actions: ' + labels.join(', ') : '';
    }
    if (b.kind === 'checklist') {
      const rows: string[] = [];
      for (let i = 0; i < b.items.length; i++) {
        rows.push(b.items[i] + (i < b.checked.length && b.checked[i] ? ', done' : ''));
      }
      return (b.text.length > 0 ? b.text + ': ' : '') + rows.join('; ');
    }
    if (b.kind === 'progress') {
      if (b.value.length > 0) {
        parts.push(b.value);
      }
      parts.push(percentOf(b.progress) + ' percent');
      if (b.text.length > 0) {
        parts.push(b.text);
      }
      return parts.join(', ');
    }
    if (b.kind === 'timer') {
      const v: string = b.value.startsWith('at:') ? 'at ' + b.value.substring(3) :
        (b.value.length > 0 ? parseInt(b.value) + ' minute timer' : 'timer');
      return (b.text.length > 0 ? b.text + ', ' : '') + v;
    }
    if (b.kind === 'chips' && b.actions.length > 0) {
      const labels: string[] = [];
      for (let i = 0; i < b.actions.length; i++) {
        labels.push(b.actions[i].label);
      }
      return (b.text.length > 0 ? b.text + ': ' : '') + 'options ' + labels.join(', ');
    }
    if (b.value.length > 0) {
      parts.push(b.value);
    }
    if (b.text.length > 0) {
      parts.push(b.text);
    }
    if (b.items.length > 0) {
      parts.push(b.items.join(', '));
    }
    return parts.join(', ');
  }

  private a11yText(): string {
    const parts: string[] = [this.tile.title];
    if (this.tile.subtitle.length > 0) {
      parts.push(this.tile.subtitle);
    }
    const plain: string = this.tile.subtitle.length > 0 ? this.tile.title + '. ' + this.tile.subtitle : this.tile.title;
    if (this.tile.speakText.length > 0 && this.tile.speakText !== plain && this.tile.speakText !== this.tile.title) {
      parts.push(this.tile.speakText);
    }
    for (let i = 0; i < this.tile.blocks.length; i++) {
      const s: string = this.blockSummary(this.tile.blocks[i]);
      if (s.length > 0) {
        parts.push(s);
      }
    }
    if (this.badgeText().length > 0) {
      parts.push(this.badgeText() === 'NEW' ? 'New tile' : 'Adapted for you');
    }
    return parts.join('. ');
  }

  private isNew(): boolean {
    return this.tile.source === 'assistant' && this.tile.createdAt > 0 &&
      Date.now() - this.tile.createdAt < 10 * 60 * 1000;
  }

  private badgeText(): string {
    if (this.isNew()) {
      return 'NEW';
    }
    return this.tile.source === 'adaptation' ? 'ADAPTED' : '';
  }

  /** Narrow / compact tiles show the NEW / ADAPTED badge as a dot on the icon instead of a pill. */
  private smallBadge(): boolean {
    return this.isCompact() || this.narrow();
  }

  private showSpeaker(): boolean {
    return this.profile.readAloud || this.isDetail();
  }

  private iconSize(): number {
    if (this.tiny()) {
      return 32;
    }
    return this.isCompact() || this.narrow() ? 38 : 44;
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
  badgePill() {
    Text(this.badgeText())
      .fontSize(this.fs(11))
      .fontWeight(FontWeight.Bold)
      .fontColor(this.colors().bg)
      .letterSpacing(0.6)
      .maxLines(1)
      .padding({ left: 8, right: 8, top: 3, bottom: 3 })
      .borderRadius(999)
      .backgroundColor(this.colors().on)
      .flexShrink(0)
  }

  @Builder
  iconBox() {
    Stack({ alignContent: Alignment.TopEnd }) {
      Stack() {
        SymbolGlyph(tileIcon(this.tile.icon, this.tile.type))
          .fontSize(Math.round(this.iconSize() * 0.56))
          .fontColor([this.colors().on])
      }
      .width(this.iconSize())
      .height(this.iconSize())
      .borderRadius(this.tiny() ? 11 : 14)
      .backgroundColor(this.colors().soft)

      if (this.smallBadge() && this.badgeText().length > 0) {
        Circle()
          .width(14)
          .height(14)
          .fill(this.colors().on)
          .stroke(this.colors().bg)
          .strokeWidth(2.5)
          .margin({ top: -4, right: -4 })
      }
    }
    .flexShrink(0)
  }

  @Builder
  speaker() {
    Stack() {
      SymbolGlyph($r('sys.symbol.speaker_wave_2_fill'))
        .fontSize(this.fs(this.isCompact() ? 18 : 20))
        .fontColor([this.colors().on])
    }
    .width(this.isCompact() || this.narrow() ? 44 : 48)
    .height(this.isCompact() || this.narrow() ? 44 : 48)
    .borderRadius(999)
    .backgroundColor(this.colors().soft)
    .border({ width: this.profile.highContrast ? 2 : 0, color: this.colors().on })
    .flexShrink(0)
    .accessibilityText('Read ' + this.tile.title + ' aloud')
    .accessibilityRole(AccessibilityRoleType.BUTTON)
    .onClick(() => {
      this.speak();
    })
  }

  /** Title: up to 2 lines, breaks only between words, shrinks (down to ~75%) before it ellipsizes. */
  @Builder
  titleText() {
    Text(this.tile.title)
      .fontSize(this.titleFs())
      .maxFontSize(this.titleFs())
      .minFontSize(Math.max(11, Math.round(this.titleFs() * 0.75)))
      .heightAdaptivePolicy(TextHeightAdaptivePolicy.MAX_LINES_FIRST)
      .fontWeight(FontWeight.Bold)
      .fontColor(this.colors().on)
      .lineHeight(Math.round(this.titleFs() * 1.2))
      .maxLines(2)
      .wordBreak(WordBreak.NORMAL)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
  }

  @Builder
  subtitleText() {
    Text(this.tile.subtitle)
      .fontSize(this.fs(this.narrow() ? 13 : 14))
      .fontWeight(FontWeight.Medium)
      .fontColor(this.colors().onMuted)
      .maxLines(this.isDetail() ? 3 : 1)
      .wordBreak(WordBreak.NORMAL)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
  }

  @Builder
  header() {
    if (this.titleBeside()) {
      Row({ space: this.isCompact() || this.narrow() ? 10 : 12 }) {
        this.iconBox()
        if (!this.titleRepeated()) {
          Column({ space: 2 }) {
            this.titleText()
            if (!this.isCompact() && this.tile.subtitle.length > 0) {
              this.subtitleText()
            }
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        } else {
          Blank()
        }
        if (!this.smallBadge() && this.badgeText().length > 0) {
          this.badgePill()
        }
        if (this.showSpeaker()) {
          this.speaker()
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    } else {
      Column({ space: 6 }) {
        Row() {
          this.iconBox()
          Blank()
          if (!this.smallBadge() && this.badgeText().length > 0) {
            this.badgePill()
          }
          if (this.showSpeaker()) {
            this.speaker()
          }
        }
        .width('100%')

        if (!this.titleRepeated()) {
          this.titleText()
        }
        if (!this.isCompact() && this.tile.subtitle.length > 0) {
          this.subtitleText()
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
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

      Column({ space: this.isCompact() ? 8 : (this.isDetail() ? 14 : 12) }) {
        this.header()

        ForEach(this.slots(), (s: BlockSlot) => {
          Column() {
            BlockView({
              block: s.block,
              bs: this.style(),
              blockIndex: s.index,
              onAction: (a: TileAction) => {
                this.onAction(a, this.tile);
              }
            })
          }
          .width('100%')
          .onAreaChange((oldArea: Area, newArea: Area) => {
            const bottom: number = Number(newArea.position.y) + Number(newArea.height);
            if (!isNaN(bottom)) {
              this.bottoms.set(s.index, bottom);
              this.scheduleFit();
            }
          })
        }, (s: BlockSlot) => s.key)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .justifyContent(FlexAlign.Start)
      .padding(this.pad())

      if (this.overflowFade) {
        Column()
          .width('100%')
          .height(28)
          .linearGradient({
            direction: GradientDirection.Bottom,
            colors: [[withAlpha(this.colors().bg, 0), 0.0], [this.colors().bg, 1.0]]
          })
          .position({ left: 0, bottom: 0 })
          .hitTestBehavior(HitTestMode.Transparent)
          .accessibilityLevel('no')
      }
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
      const h: number = Number(newArea.height);
      let changed: boolean = false;
      if (!isNaN(w) && Math.abs(w - this.cardW) > 1) {
        this.cardW = w;
        changed = true;
      }
      if (!isNaN(h) && Math.abs(h - this.cardH) > 1) {
        this.cardH = h;
        changed = changed || this.fillHeight;
      }
      if (changed) {
        this.resetFit();
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
