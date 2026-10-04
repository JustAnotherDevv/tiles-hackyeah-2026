import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { Profile, TileSpec } from '../model/Tile';
import { TileStore } from '../data/TileStore';
import { profileFor } from '../data/SeedTiles';
import { Adaptation, copyProfile } from '../ai/Adaptation';
import { TilesTheme, ThemePalette, TypeScale } from '../theme/TilesTheme';
import { tileIcon } from '../components/blocks/BlockStyle';
import { TilesPlatform } from '../platform/TilesPlatform';
import { PROFILE_CHOICES } from './OnboardingView';

/** AppStorage key for light/dark (same key as views/ShellKeys K_DARK; Index syncs it from the app color mode). */
export const K_DARK: string = 'tiles.dark';

/** Applies the dark-mode choice app-wide: AppStorage flag for the views + the application color mode. */
export function applyDarkMode(dark: boolean): void {
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

  aboutToAppear(): void {
    this.syncDrafts();
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
    try {
      this.getUIContext().getPromptAction().showToast({ message: msg, duration: 2000 });
    } catch (e) {
      // cosmetic
    }
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

  build() {
    NavDestination() {
      Scroll() {
        Column({ space: TilesTheme.SPACE_L }) {
          Row({ space: 10 }) {
            Row() {
              SymbolGlyph($r('sys.symbol.chevron_left'))
                .fontSize(24)
                .fontColor([this.pal().text])
            }
            .width(TilesTheme.tapTarget(this.profile))
            .height(TilesTheme.tapTarget(this.profile))
            .justifyContent(FlexAlign.Center)
            .borderRadius(TilesTheme.tapTarget(this.profile) / 2)
            .backgroundColor(this.pal().surface)
            .onClick(() => this.nav.pop())
            .accessibilityText('Back')
            Text('Settings')
              .fontSize(this.ty().headline)
              .fontWeight(FontWeight.Bolder)
              .fontColor(this.pal().text)
          }
          .width('100%')

          // ----- profile -----
          this.section('Who is this phone for?')
          Column({ space: TilesTheme.SPACE_M }) {
            Row({ space: TilesTheme.SPACE_M }) {
              this.profileChip(0)
              this.profileChip(1)
            }
            .width('100%')
            Row({ space: TilesTheme.SPACE_M }) {
              this.profileChip(2)
              this.profileChip(3)
            }
            .width('100%')
            Text('Switching regenerates the home for that person: their tiles, size, colors and helper.')
              .fontSize(this.ty().caption)
              .fontColor(this.pal().textMuted)
              .width('100%')
            this.rowButton('Run setup again', 'arrow_counterclockwise', () => {
              this.nav.pushPathByName('onboarding', '');
            })
          }
          .padding(TilesTheme.SPACE_L)
          .borderRadius(TilesTheme.RADIUS_TILE)
          .backgroundColor(this.pal().surface)

          // ----- display -----
          this.section('Display')
          Column({ space: TilesTheme.SPACE_M }) {
            Row() {
              Text('Text size')
                .fontSize(this.ty().body)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.pal().text)
                .layoutWeight(1)
              Text(Math.round(this.scaleDraft * 100).toString() + '%')
                .fontSize(this.ty().body)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.pal().text)
            }
            .width('100%')
            Row({ space: 8 }) {
              Text('A')
                .fontSize(14)
                .fontColor(this.pal().textMuted)
              Slider({
                value: this.scaleDraft,
                min: 0.85,
                max: 2.0,
                step: 0.05,
                style: SliderStyle.OutSet
              })
                .layoutWeight(1)
                .selectedColor(this.pal().accent)
                .blockColor(this.pal().accent)
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
                .fontSize(26)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.pal().textMuted)
            }
            .width('100%')
            Text('Pills 8:00 — tap when taken')
              .fontSize(Math.round(17 * this.scaleDraft))
              .fontWeight(FontWeight.Bold)
              .fontColor(TilesTheme.tile('mint', this.profile.highContrast, this.dark).on)
              .width('100%')
              .padding(TilesTheme.SPACE_L)
              .borderRadius(TilesTheme.RADIUS_INNER)
              .backgroundColor(TilesTheme.tile('mint', this.profile.highContrast, this.dark).bg)

            this.toggleRow('High contrast', 'Deeper colors, black or white text, outlines', 'contrast',
              this.profile.highContrast, (on: boolean) => {
                this.update((p: Profile) => {
                  p.highContrast = on;
                });
              })
            this.toggleRow('Read tiles aloud', 'Speaks a tile when it is opened', 'speaker_wave_3',
              this.profile.readAloud, (on: boolean) => {
                this.update((p: Profile) => {
                  p.readAloud = on;
                });
              })
            this.toggleRow('Dark mode', 'Warm dark background', 'moon_fill', this.dark, (on: boolean) => {
              applyDarkMode(on);
            })
          }
          .padding(TilesTheme.SPACE_L)
          .borderRadius(TilesTheme.RADIUS_TILE)
          .backgroundColor(this.pal().surface)

          // ----- caregiver -----
          this.section('Caregiver')
          Column({ space: TilesTheme.SPACE_M }) {
            Text(this.profile.caregiver.length > 0 ?
              this.profile.caregiver + ' approves new tiles and suggested changes for ' + this.profile.name + '.' :
              'No caregiver: changes are approved on this phone.')
              .fontSize(this.ty().label)
              .fontColor(this.pal().textMuted)
              .width('100%')
            Row({ space: TilesTheme.SPACE_S }) {
              TextInput({ text: this.caregiverDraft, placeholder: 'Name, e.g. Kasia' })
                .onChange((v: string) => {
                  this.caregiverDraft = v;
                })
                .fontSize(this.ty().body)
                .fontColor(this.pal().text)
                .placeholderColor(this.pal().textMuted)
                .backgroundColor(this.pal().surfaceAlt)
                .borderRadius(TilesTheme.RADIUS_BUTTON)
                .height(TilesTheme.tapTarget(this.profile))
                .layoutWeight(3)
              TextInput({ text: this.roleDraft, placeholder: 'daughter' })
                .onChange((v: string) => {
                  this.roleDraft = v;
                })
                .fontSize(this.ty().body)
                .fontColor(this.pal().text)
                .placeholderColor(this.pal().textMuted)
                .backgroundColor(this.pal().surfaceAlt)
                .borderRadius(TilesTheme.RADIUS_BUTTON)
                .height(TilesTheme.tapTarget(this.profile))
                .layoutWeight(2)
            }
            .width('100%')
            this.rowButton('Save caregiver', 'checkmark', () => {
              const cg: string = this.caregiverDraft.trim();
              const role: string = cg.length > 0 ? this.roleDraft.trim() : '';
              this.update((p: Profile) => {
                p.caregiver = cg;
                p.caregiverRole = role;
              });
              this.toast(cg.length > 0 ? cg + ' is now the caregiver' : 'Caregiver removed');
            })
            this.rowButton(this.profile.caregiver.length > 0 ? 'Open ' + this.profile.caregiver + '\'s phone (simulated)' :
              'Review suggestions', 'person_2_fill', () => {
              this.nav.pushPathByName('caregiver', '');
            })
          }
          .padding(TilesTheme.SPACE_L)
          .borderRadius(TilesTheme.RADIUS_TILE)
          .backgroundColor(this.pal().surface)

          // ----- demo -----
          this.section('Demo')
          Column({ space: TilesTheme.SPACE_M }) {
            this.rowButton('Simulate a day of use (demo data)', 'play_fill', () => {
              this.toast(Adaptation.simulateDay());
            })
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
              .fontSize(this.ty().caption)
              .fontColor(this.pal().textMuted)
              .width('100%')
          }
          .padding(TilesTheme.SPACE_L)
          .borderRadius(TilesTheme.RADIUS_TILE)
          .backgroundColor(this.pal().surface)

          // ----- about -----
          this.section('About')
          Text('Tiles · HarmonyOS (API 20+). The assistant is an on-device, rule-based generator that outputs ' +
            'tiles as structured data (no LLM, no account). Adaptation suggestions come from on-device usage ' +
            'rules; "simulate a day", Guardian demo calls and the caregiver\'s phone are clearly labelled ' +
            'simulations. People and places are fictional.')
            .fontSize(this.ty().caption)
            .fontColor(this.pal().textMuted)
            .width('100%')
            .padding(TilesTheme.SPACE_L)
            .borderRadius(TilesTheme.RADIUS_TILE)
            .backgroundColor(this.pal().surface)
            .margin({ bottom: 32 })
        }
        .padding({ left: TilesTheme.GUTTER, right: TilesTheme.GUTTER, top: 12, bottom: 24 })
      }
      .scrollBar(BarState.Off)
      .align(Alignment.Top)
      .width('100%')
      .height('100%')
      .backgroundColor(this.pal().bg)
    }
    .hideTitleBar(true)
    .onShown(() => {
      this.syncDrafts();
    })
  }

  @Builder
  section(title: string) {
    Text(title)
      .fontSize(this.ty().title)
      .fontWeight(FontWeight.Bolder)
      .fontColor(this.pal().text)
      .width('100%')
      .margin({ top: TilesTheme.SPACE_S })
      .accessibilityLevel('yes')
  }

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
        .fontSize(18)
        .fontWeight(FontWeight.Bolder)
        .fontColor(TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).on)
      Text(profileFor(PROFILE_CHOICES[i].id).name)
        .fontSize(13)
        .fontColor(TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).onMuted)
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
    .padding(12)
    .borderRadius(TilesTheme.RADIUS_INNER + 4)
    .backgroundColor(TilesTheme.tile(PROFILE_CHOICES[i].color, false, this.dark).bg)
    .border({ width: this.profile.id === PROFILE_CHOICES[i].id ? 3 : 0, color: this.pal().text })
    .opacity(this.profile.id === PROFILE_CHOICES[i].id ? 1.0 : 0.85)
    .onClick(() => this.switchTo(PROFILE_CHOICES[i].id))
    .accessibilityText(PROFILE_CHOICES[i].label + ' profile' +
      (this.profile.id === PROFILE_CHOICES[i].id ? ', selected' : ''))
  }

  @Builder
  toggleRow(title: string, sub: string, icon: string, isOn: boolean, onChange: (on: boolean) => void) {
    Row({ space: 12 }) {
      SymbolGlyph(this.glyph(icon))
        .fontSize(24)
        .fontColor([this.pal().text])
      Column({ space: 2 }) {
        Text(title)
          .fontSize(this.ty().body)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.pal().text)
        Text(sub)
          .fontSize(this.ty().caption)
          .fontColor(this.pal().textMuted)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Toggle({ type: ToggleType.Switch, isOn: isOn })
        .selectedColor(this.pal().success)
        .onChange((on: boolean) => onChange(on))
        .accessibilityText(title)
    }
    .width('100%')
    .constraintSize({ minHeight: TilesTheme.tapTarget(this.profile) })
  }

  @Builder
  rowButton(label: string, icon: string, onTap: () => void) {
    Row({ space: 10 }) {
      SymbolGlyph(this.glyph(icon))
        .fontSize(20)
        .fontColor([this.pal().text])
      Text(label)
        .fontSize(this.ty().label)
        .fontWeight(FontWeight.Bold)
        .fontColor(this.pal().text)
        .layoutWeight(1)
      SymbolGlyph($r('sys.symbol.chevron_right'))
        .fontSize(18)
        .fontColor([this.pal().textMuted])
    }
    .width('100%')
    .height(TilesTheme.tapTarget(this.profile))
    .padding({ left: 14, right: 14 })
    .borderRadius(TilesTheme.RADIUS_BUTTON)
    .backgroundColor(this.pal().surfaceAlt)
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
