import { AbilityConstant, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { Log } from '../common/Format';
import { Keys, PocketStore } from '../data/PocketStore';
import { PARAM_APPROVAL_ID, PARAM_TARGET } from '../platform/NotificationService';
import { BackgroundRefresh } from '../platform/BackgroundRefresh';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    try {
      // Aegis Pocket is designed dark-first.
      this.context.getApplicationContext().setColorMode(ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
    } catch (err) {
      Log.error('Failed to set colorMode: ' + JSON.stringify(err));
    }
    PocketStore.seedStorage();
    this.handleWant(want);
    PocketStore.get().init(this.context);
    // Background Tasks Kit: repeating deferred task that keeps the widget current while the app is closed.
    BackgroundRefresh.schedule(this.context);
    Log.info('Ability onCreate');
  }

  /** Called when a notification (WantAgent) or the widget (postCardAction router) re-opens the running app. */
  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    this.handleWant(want);
  }

  onDestroy(): void {
    PocketStore.get().stop();
    Log.info('Ability onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        Log.error('Failed to load the content: ' + JSON.stringify(err));
        return;
      }
      try {
        const win: window.Window = windowStage.getMainWindowSync();
        win.setWindowBackgroundColor('#0B0F17');
        win.setWindowSystemBarProperties({
          statusBarColor: '#0B0F17',
          statusBarContentColor: '#E6EDF7',
          navigationBarColor: '#0B0F17',
          navigationBarContentColor: '#E6EDF7'
        }).catch((e: Error) => {
          Log.warn('system bar style failed: ' + e.message);
        });
      } catch (e) {
        Log.warn('window styling failed: ' + JSON.stringify(e));
      }
      // Ask once for notification permission (system dialog), as required before publishing.
      PocketStore.get().requestNotifications().then((ok: boolean) => {
        Log.info('Notifications enabled: ' + ok);
      });
    });
  }

  onWindowStageDestroy(): void {
    Log.info('Ability onWindowStageDestroy');
  }

  onForeground(): void {
    PocketStore.get().start();
    PocketStore.get().syncNotificationState();
  }

  onBackground(): void {
    // Keep timers: the OS freezes background apps anyway; polling resumes in onForeground.
    Log.info('Ability onBackground');
  }

  private handleWant(want: Want): void {
    const params: Record<string, Object> | undefined = want.parameters;
    if (params === undefined) {
      return;
    }
    const approvalId: Object | undefined = params[PARAM_APPROVAL_ID];
    if (typeof approvalId === 'string' && (approvalId as string).length > 0) {
      AppStorage.setOrCreate<string>(Keys.OPEN_APPROVAL, (approvalId as string) + '#' + Date.now().toString());
      return;
    }
    // postCardAction 'router': the card's params arrive as a JSON string in want.parameters.params.
    let target: Object | undefined = params[PARAM_TARGET];
    const cardParams: Object | undefined = params['params'];
    if (target === undefined && typeof cardParams === 'string') {
      try {
        const parsed: Record<string, Object> = JSON.parse(cardParams as string) as Record<string, Object>;
        target = parsed[PARAM_TARGET];
      } catch (e) {
        Log.warn('Bad widget params');
      }
    }
    if (typeof target === 'string' && (target as string).length > 0) {
      AppStorage.setOrCreate<string>(Keys.OPEN_TARGET, (target as string) + '#' + Date.now().toString());
    }
  }
}
