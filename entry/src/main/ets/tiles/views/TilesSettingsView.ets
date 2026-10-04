import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { LengthMetrics, window } from '@kit.ArkUI';
import { LLPageMotion, llToast } from './ShellKeys';
import { Profile, TileSpec } from '../model/Tile';
import { TileStore } from '../data/TileStore';
import { profileFor } from '../data/SeedTiles';
import { Adaptation, copyProfile } from '../ai/Adaptation';
import { LL_FONT_FAMILY, TilesTheme, ThemePalette, TypeScale } from '../theme/TilesTheme';
import { tileIcon } from '../components/blocks/BlockStyle';
import { TilesPlatform } from '../platform/TilesPlatform';
import { PROFILE_CHOICES } from './OnboardingView';

/** AppStorage key for light/dark (same key as views/ShellKeys K_DARK; Index syncs it from the app color mode). */
export const K_DARK: string = 'tiles.dark';

/** Applies the dark-mode choice app-wide: AppStorage flag for the views + the application color mode. */
let lastDarkAt: number = 0;
let lastDark: boolean = false;

export function applyDarkMode(dark: boolean): void {
  // Changing the app color mode rebuilds the view and the Toggle fires a spurious onChange with the old
  // value right after; ignore a flip-back within 1.5 s so the user's choice sticks.
  const now: number = Date.now();
  if (now - lastDarkAt < 1500 && dark !== lastDark) {
    return;
  }
  lastDarkAt = now;
  lastDark = dark;
  // Remember the explicit choice so Index.syncDark() does not overwrite it with a stale config value.
  AppStorage.setOrCreate<number>('tiles.darkUser', dark ? 2 : 1);
  AppStorage.setOrCreate<boolean>(K_DARK, dark);
  const ctx: common.UIAbilityContext | null = TilesPlatform.context();
  if (ctx === null) {
    return;
  }
  try {
    (ctx as common.UIAbilityContext).getApplicationContext().setColorMode(dark ? ConfigurationConstant.ColorMode.COLOR_MODE_DARK :
      ConfigurationConstant.ColorMode.COLOR_MODE_LIGHT);
  } catch (e) {
    // color mode is cosmetic; the AppStorage flag still switches the Tiles palette
  }
}

/**
 * Settings (route 'settings'): switch profile (regenerates the home), text size, high contrast, read aloud,
 * dark mode, caregiver, demo controls (simulate a day, reset demo) and an honest "about".
 */
@Component
export struct TilesSettingsView {
  @Consume('tilesNav') nav: NavPathStack;
  @StorageProp('tiles.dark') dark: boolean = false;
  @StorageProp('tiles.profile') profile: Profile = new Profile();
  @State scaleDraft: number = 1.0;
  @State caregiverDraft: string = '';
  @State roleDraft: string = '';
  @State resetArmed: boolean = false;
  @State lastProfileId: string = '';
  @State llMotion: LLPageMotion = new LLPageMotion();
  /** Status-bar height (vp) and where the page actually starts: the window is full-screen (immersive). */
  @State sysTop: number = 0;
  @State rootY: number = 0;

  aboutToAppear(): void {
    this.syncDrafts();
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      window.getLastWindow(ctx).then((win: window.Window) => {
        const area: window.AvoidArea = win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
        this.sysTop = this.getUIContext().px2vp(area.topRect.height);
      }).catch(() => {
      });
    } catch (e) {
      // no window (preview)
    }
  }

  /** Extra top padding only when the page really lays out under the status bar. */
  private topPad(): number {
    return Math.max(0, this.sysTop - this.rootY);
  }

  private syncDrafts(): void {
    const p: Profile = TileStore.get().profile();
    this.scaleDraft = p.textScale;
    this.caregiverDraft = p.caregiver;
    this.roleDraft = p.caregiverRole;
    this.lastProfileId = p.id;
  }

  private pal(): ThemePalette {
    return TilesTheme.palette(this.dark, this.profile.highContrast);
  }

  /** Settings honour the person's text size, capped so the screen stays usable. */
  private ty(): TypeScale {
    return TilesTheme.type(Math.min(1.3, this.profile.textScale));
  }

  private toast(msg: string): void {
    llToast(this.getUIContext(), msg, 2000);
  }

  private update(fn: (p: Profile) => void): void {
    const p: Profile = copyProfile(TileStore.get().profile());
    fn(p);
    TileStore.get().setProfile(p);
  }

  private switchTo(id: string): void {
    if (id === this.profile.id) {
      return;
    }
    this.getUIContext().animateTo({ duration: 300, curve: TilesTheme.springReflow() }, () => {
      TileStore.get().switchProfile(id);
    });
    this.syncDrafts();
    this.resetArmed = false;
    const p: Profile = TileStore.get().profile();
    this.toast('Home regenerated for ' + p.name);
  }


  private tap(): number {
    return TilesTheme.tapTarget(this.profile);
  }

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: TilesTheme.SPACE_M }) {
          // ----- header -----
          Row({ space: 12 }) {
            Row() {
              SymbolGlyph($r('sys.symbol.chevron_left'))
                .fontSize(24)
                .fontColor([this.pal().ink])
            }
            .width(this.tap())
            .height(this.tap())
            .justifyContent(FlexAlign.Center)
            .borderRadius(this.tap() / 2)
            .backgroundColor(this.pal().surface)
            .backdropBlur(TilesTheme.LL_BLUR)
            .shadow(TilesTheme.LL_SHADOW_SOFT)
            .onClick(() => this.nav.pop())
            .accessibilityText('Back')
            Text('Settings')
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(this.ty().headline)
              .fontWeight(FontWeight.Bold)
              .letterSpacing(TilesTheme.letterSpacing(this.ty().headline) * 1.6)
              .fontColor(this.pal().ink)
          }
          .width('100%')
          .margin({ bottom: 4 })

          // ----- profile -----
          this.section('Who is this phone for?')
          Column() {
            Column({ space: TilesTheme.SPACE_S + 2 }) {
              Row({ space: TilesTheme.SPACE_S + 2 }) {
                this.profileChip(0)
                this.profileChip(1)
              }
              .width('100%')
              Row({ space: TilesTheme.SPACE_S + 2 }) {
                this.profileChip(2)
                this.profileChip(3)
              }
              .width('100%')
              Text('Switching regenerates the home for that person: their tiles, size, colors and helper.')
                .fontFamily(LL_FONT_FAMILY)
                .fontSize(this.ty().caption)
                .fontColor(this.pal().muted)
                .width('100%')
                .padding({ left: 2, right: 2, top: 2 })
            }
            .padding(14)
            this.sep(16)
            this.rowButton('Run setup again', 'arrow_counterclockwise', () => {
              this.nav.pushPathByName('onboarding', '');
            })
          }
          .width('100%')
          .padding({ bottom: 4 })
          .borderRadius(TilesTheme.LL_RADIUS_L)
          .backgroundColor(this.pal().surface)
          .backdropBlur(TilesTheme.LL_BLUR)
          .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
          .shadow(TilesTheme.LL_SHADOW_SOFT)

          // ----- display -----
          this.section('Display')
          Column() {
            Column({ space: TilesTheme.SPACE_M }) {
              Row() {
                Text('Text size')
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(this.ty().body)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.pal().ink)
                  .layoutWeight(1)
                Text(Math.round(this.scaleDraft * 100).toString() + '%')
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(this.ty().label)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.pal().accent)
                  .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                  .borderRadius(TilesTheme.LL_RADIUS_PILL)
                  .backgroundColor(this.pal().surface2)
              }
              .width('100%')
              Row({ space: 8 }) {
                Text('A')
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(14)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.pal().muted)
                Slider({
                  value: this.scaleDraft,
                  min: 0.85,
                  max: 2.0,
                  step: 0.05,
                  style: SliderStyle.OutSet
                })
                  .layoutWeight(1)
                  .selectedColor(this.pal().accent)
                  .trackColor(this.pal().surface2)
                  .blockColor('#FFFFFF')
                  .blockBorderColor(this.pal().accent)
                  .blockBorderWidth(2)
                  .trackThickness(6)
                  .onChange((v: number, mode: SliderChangeMode) => {
                    this.scaleDraft = Math.round(v * 100) / 100;
                    if (mode === SliderChangeMode.End || mode === SliderChangeMode.Click) {
                      const target: number = this.scaleDraft;
                      this.update((p: Profile) => {
                        p.textScale = target;
                      });
                    }
                  })
                  .accessibilityText('Text size ' + Math.round(this.scaleDraft * 100).toString() + ' percent')
                Text('A')
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(26)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.pal().muted)
              }
              .width('100%')
              Row({ space: 10 }) {
                SymbolGlyph(tileIcon('pill', ''))
                  .fontSize(Math.round(22 * this.scaleDraft))
                  .fontColor([TilesTheme.tile('sun', this.profile.highContrast, this.dark).on])
                Text('Pills 8:00 — tap when taken')
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(Math.round(17 * this.scaleDraft))
                  .fontWeight(FontWeight.Bold)
                  .letterSpacing(TilesTheme.letterSpacing(Math.round(17 * this.scaleDraft)))
                  .fontColor(TilesTheme.tile('sun', this.profile.highContrast, this.dark).on)
                  .layoutWeight(1)
              }
              .width('100%')
              .padding(TilesTheme.SPACE_L)
              .borderRadius(TilesTheme.LL_RADIUS_M)
              .linearGradient({
                angle: TilesTheme.tile('sun', this.profile.highContrast, this.dark).gradient.angle,
                colors: TilesTheme.tile('sun', this.profile.highContrast, this.dark).gradient.colors
              })
              .shadow(TilesTheme.LL_SHADOW_SOFT)
            }
            .padding(16)

            this.sep(16)
            this.toggleRow('High contrast', 'Deeper colors, black or white text, outlines', 'contrast',
              this.profile.highContrast, (on: boolean) => {
                this.update((p: Profile) => {
                  p.highContrast = on;
                });
              })
            this.sep(16)
            this.toggleRow('Read tiles aloud', 'Speaks a tile when it is opened', 'speaker_wave_3',
              this.profile.readAloud, (on: boolean) => {
                this.update((p: Profile) => {
                  p.readAloud = on;
                });
              })
            this.sep(16)
            this.darkRow()
          }
          .width('100%')
          .padding({ bottom: 4 })
          .borderRadius(TilesTheme.LL_RADIUS_L)
          .backgroundColor(this.pal().surface)
          .backdropBlur(TilesTheme.LL_BLUR)
          .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
          .shadow(TilesTheme.LL_SHADOW_SOFT)

          // ----- caregiver -----
          this.section('Caregiver')
          Column() {
            Column({ space: TilesTheme.SPACE_M }) {
              Text(this.profile.caregiver.length > 0 ?
                this.profile.caregiver + ' approves new tiles and suggested changes for ' + this.profile.name + '.' :
                'No caregiver: changes are approved on this phone.')
                .fontFamily(LL_FONT_FAMILY)
                .fontSize(this.ty().label)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.pal().muted)
                .width('100%')
              Row({ space: TilesTheme.SPACE_S }) {
                TextInput({ text: this.caregiverDraft, placeholder: 'Name, e.g. Kasia' })
                  .onChange((v: string) => {
                    this.caregiverDraft = v;
                  })
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(this.ty().body)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.pal().ink)
                  .placeholderColor(this.pal().muted)
                  .caretColor(this.pal().accent)
                  .backgroundColor(this.pal().inputBg)
                  .borderRadius(TilesTheme.LL_RADIUS_S)
                  .height(this.tap())
                  .layoutWeight(3)
                TextInput({ text: this.roleDraft, placeholder: 'daughter' })
                  .onChange((v: string) => {
                    this.roleDraft = v;
                  })
                  .fontFamily(LL_FONT_FAMILY)
                  .fontSize(this.ty().body)
                  .fontColor(this.pal().ink)
                  .placeholderColor(this.pal().muted)
                  .caretColor(this.pal().accent)
                  .backgroundColor(this.pal().inputBg)
                  .borderRadius(TilesTheme.LL_RADIUS_S)
                  .height(this.tap())
                  .layoutWeight(2)
              }
              .width('100%')
            }
            .padding(16)
            this.sep(16)
            this.rowButton('Save caregiver', 'checkmark', () => {
              const cg: string = this.caregiverDraft.trim();
              const role: string = cg.length > 0 ? this.roleDraft.trim() : '';
              this.update((p: Profile) => {
                p.caregiver = cg;
                p.caregiverRole = role;
              });
              this.toast(cg.length > 0 ? cg + ' is now the caregiver' : 'Caregiver removed');
            })
            this.sep(16)
            this.rowButton(this.profile.caregiver.length > 0 ? 'Open ' + this.profile.caregiver + '\'s phone (simulated)' :
              'Review suggestions', 'person_2_fill', () => {
              this.nav.pushPathByName('caregiver', '');
            })
          }
          .width('100%')
          .padding({ bottom: 4 })
          .borderRadius(TilesTheme.LL_RADIUS_L)
          .backgroundColor(this.pal().surface)
          .backdropBlur(TilesTheme.LL_BLUR)
          .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
          .shadow(TilesTheme.LL_SHADOW_SOFT)

          // ----- demo -----
          this.section('Demo')
          Column() {
            this.rowButton('Simulate a day of use (demo data)', 'play_fill', () => {
              this.toast(Adaptation.simulateDay());
            })
            this.sep(16)
            this.rowButton(this.resetArmed ? 'Tap again to reset ' + this.profile.name + '\'s home' : 'Reset demo',
              'arrow_counterclockwise', () => {
                if (!this.resetArmed) {
                  this.resetArmed = true;
                  return;
                }
                this.resetArmed = false;
                const st: TileStore = TileStore.get();
                this.getUIContext().animateTo({ duration: 300, curve: TilesTheme.springReflow() }, () => {
                  st.setProfile(profileFor(this.profile.id));
                  st.resetToSeed();
                });
                this.syncDrafts();
                this.toast('Demo reset: ' + st.profile().name + '\'s home is back to the start');
              })
            Text('Reset restores this profile\'s starting tiles, settings and suggestions.')
              .fontFamily(LL_FONT_FAMILY)
              .fontSize(this.ty().caption)
              .fontColor(this.pal().muted)
              .width('100%')
              .padding({ left: 16, right: 16, top: 4, bottom: 12 })
          }
          .width('100%')
          .padding({ top: 4 })
          .borderRadius(TilesTheme.LL_RADIUS_L)
          .backgroundColor(this.pal().surface)
          .backdropBlur(TilesTheme.LL_BLUR)
          .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
          .shadow(TilesTheme.LL_SHADOW_SOFT)

          // ----- about -----
          this.section('About')
          Text('Tiles · HarmonyOS (API 20+). The assistant is an on-device, rule-based generator that outputs ' +
            'tiles as structured data (no LLM, no account). Adaptation suggestions come from on-device usage ' +
            'rules; "simulate a day", Guardian demo calls and the caregiver\'s phone are clearly labelled ' +
            'simulations. People and places are fictional.')
            .fontFamily(LL_FONT_FAMILY)
            .fontSize(this.ty().caption)
            .lineHeight(Math.round(this.ty().caption * 1.45))
            .fontColor(this.pal().muted)
            .width('100%')
            .padding(TilesTheme.SPACE_L)
            .borderRadius(TilesTheme.LL_RADIUS_L)
            .backgroundColor(this.pal().surface)
            .backdropBlur(TilesTheme.LL_BLUR)
            .border({ width: this.profile.highContrast ? 1 : 0, color: this.pal().line })
            .margin({ bottom: 32 })
        }
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 12 + this.topPad(), bottom: 56 })
      }
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .fadingEdge(true, { fadingEdgeLength: LengthMetrics.vp(28 + this.topPad()) })
      .align(Alignment.Top)
      .width('100%')
      .height('100%')
      .linearGradient({ angle: this.pal().bgGradient.angle, colors: this.pal().bgGradient.colors })
      .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
      .onAreaChange((o: Area, n: Area) => {
        const y: number = Number(n.globalPosition.y);
        if (!isNaN(y) && Math.abs(y - this.rootY) > 0.5) {
          this.rootY = y;
        }
      })
    }
    .hideTitleBar(true)
    .backgroundColor(this.pal().bg)
    .opacity(this.llMotion.opacity)
    .scale({ x: this.llMotion.scale, y: this.llMotion.scale })
    .translate({ y: this.llMotion.ty })
    .customTransition((op: NavigationOperation, isEnter: boolean) =>
      this.llMotion.transitions(this.getUIContext(), op, isEnter))
    .onShown(() => {
      this.syncDrafts();
    })
  }

  /** Small uppercase section kicker (prototype: 12-13px, 700, letter-spacing .08em). */
  @Builder
  section(title: string) {
    Text(title)
      .fontFamily(LL_FONT_FAMILY)
      .fontSize(Math.round(13 * Math.min(1.3, this.profile.textScale)))
      .fontWeight(FontWeight.Bold)
      .letterSpacing(1)
      .textCase(TextCase.UpperCase)
      .fontColor(this.pal().muted)
      .width('100%')
      .padding({ left: 6 })
      .margin({ top: TilesTheme.SPACE_S })
      .accessibilityLevel('yes')
  }

  /** Hairline separator inside grouped glass cards (line rgba(29,33,64,.12)). */
  @Builder
  sep(inset: number) {
    Divider()
      .strokeWidth(1)
      .color(this.pal().line)
      .margin({ left: inset, right: 16 })
  }

  /** Profile choice as a mini Living Light tile (palette gradient, radius 18). */
  @Builder
  profileChip(i: number) {
    Column({ space: 4 }) {
      Row() {
        SymbolGlyph(tileIcon(PROFILE_CHOICES[i].icon, ''))
          .fontSize(24)
          .fontColor([TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).on])
        Blank()
        if (this.profile.id === PROFILE_CHOICES[i].id) {
          SymbolGlyph($r('sys.symbol.checkmark_circle_fill'))
            .fontSize(22)
            .fontColor([TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).on])
        }
      }
      .width('100%')
      Text(PROFILE_CHOICES[i].label)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(TilesTheme.letterSpacing(18))
        .fontColor(TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).on)
        .margin({ top: 4 })
      Text(profileFor(PROFILE_CHOICES[i].id).name)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(13)
        .fontWeight(FontWeight.Medium)
        .fontColor(TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).onMuted)
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    .padding(14)
    .borderRadius(TilesTheme.LL_RADIUS_M)
    .linearGradient({
      angle: TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).gradient.angle,
      colors: TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).gradient.colors
    })
    .border({
      width: this.profile.id === PROFILE_CHOICES[i].id ? 2.5 : 0,
      color: TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).on
    })
    .shadow(this.profile.id === PROFILE_CHOICES[i].id ? TilesTheme.LL_SHADOW_TILE : TilesTheme.LL_SHADOW_SOFT)
    .opacity(this.profile.id === PROFILE_CHOICES[i].id ? 1.0 : 0.9)
    .scale({ x: this.profile.id === PROFILE_CHOICES[i].id ? 1.0 : 0.97, y: this.profile.id === PROFILE_CHOICES[i].id ? 1.0 : 0.97 })
    .animation({ duration: TilesTheme.LL_SHEET_DUR, curve: TilesTheme.ease() })
    .onClick(() => this.switchTo(PROFILE_CHOICES[i].id))
    .accessibilityText(PROFILE_CHOICES[i].label + ' profile' +
      (this.profile.id === PROFILE_CHOICES[i].id ? ', selected' : ''))
  }

  /** Round 36 vp icon badge used by every list row. */
  @Builder
  iconBadge(icon: string) {
    Row() {
      SymbolGlyph(this.glyph(icon))
        .fontSize(20)
        .fontColor([this.pal().accent])
    }
    .width(36)
    .height(36)
    .justifyContent(FlexAlign.Center)
    .borderRadius(18)
    .backgroundColor(this.pal().surface2)
  }

  @Builder
  toggleRow(title: string, sub: string, icon: string, isOn: boolean, onChange: (on: boolean) => void) {
    Row({ space: 12 }) {
      this.iconBadge(icon)
      Column({ space: 2 }) {
        Text(title)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().body)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(this.ty().body))
          .fontColor(this.pal().ink)
        Text(sub)
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().caption)
          .fontColor(this.pal().muted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Toggle({ type: ToggleType.Switch, isOn: isOn })
        .selectedColor(this.pal().accent)
        .switchPointColor('#FFFFFF')
        .switchStyle({ unselectedColor: this.pal().surface2 })
        .onChange((on: boolean) => onChange(on))
        .accessibilityText(title)
    }
    .width('100%')
    .constraintSize({ minHeight: Math.max(60, this.tap()) })
    .padding({ left: 16, right: 12, top: 6, bottom: 6 })
  }

  /** Dark-mode row reads this.dark directly (a by-value @Builder param does not re-render the switch). */
  @Builder
  darkRow() {
    Row({ space: 12 }) {
      this.iconBadge('moon_fill')
      Column({ space: 2 }) {
        Text('Dark mode')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().body)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(TilesTheme.letterSpacing(this.ty().body))
          .fontColor(this.pal().ink)
        Text('Deep indigo night background')
          .fontFamily(LL_FONT_FAMILY)
          .fontSize(this.ty().caption)
          .fontColor(this.pal().muted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Toggle({ type: ToggleType.Switch, isOn: this.dark })
        .selectedColor(this.pal().accent)
        .switchPointColor('#FFFFFF')
        .switchStyle({ unselectedColor: this.pal().surface2 })
        .onChange((on: boolean) => {
          if (on !== this.dark) {
            applyDarkMode(on);
          }
        })
        .accessibilityText('Dark mode')
    }
    .width('100%')
    .constraintSize({ minHeight: Math.max(60, this.tap()) })
    .padding({ left: 16, right: 12, top: 6, bottom: 6 })
  }

  @Builder
  rowButton(label: string, icon: string, onTap: () => void) {
    Row({ space: 12 }) {
      this.iconBadge(icon)
      Text(label)
        .fontFamily(LL_FONT_FAMILY)
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .letterSpacing(TilesTheme.letterSpacing(this.ty().label))
        .fontColor(this.pal().ink)
        .layoutWeight(1)
      SymbolGlyph($r('sys.symbol.chevron_right'))
        .fontSize(18)
        .fontColor([this.pal().muted])
    }
    .width('100%')
    .constraintSize({ minHeight: Math.max(56, this.tap()) })
    .padding({ left: 16, right: 14, top: 6, bottom: 6 })
    .onClick(onTap)
    .accessibilityText(label)
  }

  private glyph(name: string): Resource {
    switch (name) {
      case 'contrast':
        return $r('sys.symbol.contrast');
      case 'speaker_wave_3':
        return $r('sys.symbol.speaker_wave_3');
      case 'moon_fill':
        return $r('sys.symbol.moon_fill');
      case 'arrow_counterclockwise':
        return $r('sys.symbol.arrow_counterclockwise');
      case 'checkmark':
        return $r('sys.symbol.checkmark');
      case 'person_2_fill':
        return $r('sys.symbol.person_2_fill');
      case 'play_fill':
        return $r('sys.symbol.play_fill');
      default:
        return $r('sys.symbol.chevron_right');
    }
  }
}
