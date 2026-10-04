# Aegis Pocket demo video (≤60 s)

| File | What |
|---|---|
| `aegis-pocket-demo-60s.mp4` | The video: H.264, 1920×1080, 30 fps, silent AAC track, under 58 s, burned-in captions, title and end cards |
| `cover.png` | 1920×1080 cover image (the title card, with the first Home screenshot in the phone frame) |
| `captions.txt` / `captions.srt` | Timeline and caption of every beat (generated) |

These files are produced by `scripts/pocket-video/record.sh`. They do not exist until it has been run against a
running emulator.

## Prerequisites

1. **Emulator running**: DevEco phone emulator `AegisPhone` (HarmonyOS 6.1.1(24)), started from DevEco Device Manager
   or `/Applications/DevEco-Studio.app/Contents/tools/emulator/Emulator -start AegisPhone`. `hdc list targets` must
   show it. The script never starts the emulator itself.
2. **Signed `.hap`** at `entry/build/default/outputs/default/entry-default-signed.hap` (signing configured in DevEco,
   then rebuilt). Or install it yourself and pass `--no-install`, or pass `--hap <path>`.
3. Tools: `hdc` (found on `PATH` or at `/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc`;
   override with `HDC=...`), `ffmpeg` + `ffprobe`, `uv` (Pillow is fetched into an ephemeral environment), `python3`.
4. Optional: the **AI posture widget** (2x4) already placed on the first home-screen page. If it is not found, the
   widget beat is left out (no caption claims it).
5. Do not touch the emulator while the script drives it (about 90 s).

## Run (one command, from the repository root)

```bash
scripts/pocket-video/record.sh
```

Variants:

```bash
scripts/pocket-video/record.sh --no-install          # app already installed
scripts/pocket-video/record.sh --target 127.0.0.1:5555 # pick a target when several are connected
scripts/pocket-video/record.sh --render-only         # re-encode from the last capture (no device needed)
scripts/pocket-video/record.sh --dry-run             # no device: placeholder frames, output only in the build dir
```

Intermediate files go to `$POCKET_VIDEO_BUILD` (default `$TMPDIR/pocket-video-build`), never inside the repo:
`raw/` (pulled screenshots), `capture.json` (frame times, beat labels, chosen caption variants), `drive.log`,
`composed/` (stills) and `concat.txt`. `POCKET_VIDEO_WRAP` can prefix the render step with a wrapper command (for
example a lock script on a low-memory machine).

## What the script does

1. **Preflight**: finds `hdc`, checks `hdc list targets` and `hdc shell`, installs the `.hap` with `hdc install -r`
   and checks that `com.hackyeah.aegispocket` is installed.
2. **Drive** (`scripts/pocket-video/drive.py`, standard library only): force-stops and starts `EntryAbility` so the
   mock data and its first simulated request (about 20 s after start) reset; allows the notification permission
   dialog if shown; makes sure the app is in mock mode and the persona is Emily (admin). Controls are found by text
   in `uitest dumpLayout` output; input uses `uitest uiInput click / swipe / text / keyEvent`. Shot list:
   1. Home posture (time-lapse while waiting for the simulated request)
   2. the in-app banner for the new mock request
   3. notification shade (swipe down from the top left), tap the "Approval needed" notification
   4. request detail scrolled to the "Why a human is asked" risk card and the untrusted agent note
   5. Inbox → the seeded $50 MarketPulse Pro request
   6. Approve → step-up: on the emulator, the app's labelled "Device authentication unavailable" fallback dialog
   7. "Approve without biometrics" → toast → back to the inbox
   8. Preview tab: synthetic email, PESEL, IBAN and card number typed in (`shots.json` → `sample_text`), scrolled to
      the redacted result; falls back to the built-in synthetic sample if typing fails
   9. Home key → the widget, if placed
3. **Capture**: a background thread runs `hdc shell snapshot_display -f` in a loop (the DevEco emulator does not
   support screen recording) and labels every frame with the active beat. Frames are pulled at the end.
4. **Render** (`scripts/pocket-video/render.py`, Pillow + ffmpeg): each frame is placed in a phone frame centred on a
   dark branded 1920×1080 background, with the beat title on the left, the caption on the right and the footer
   "DevEco HarmonyOS emulator · HarmonyOS 6.1.1 (API 24) · mock data". Within a beat, frames play over 70 % of the
   beat and the settled last frame holds for the rest; beats are joined with 0.3 s crossfades. Durations come from
   `scripts/pocket-video/shots.json` and are scaled down if the total would exceed 57.5 s.

## Captions are factual

- Every product shot is labelled "mock data": requests, agents, amounts and posture numbers are simulated on the
  device (`entry/src/main/ets/data/MockRepository.ets`).
- The step-up beat says the emulator has no authenticator and shows the app's labelled manual fallback. If a real
  system authentication sheet appears instead, the driver cancels it (nothing is approved) and the alternative
  captions in `shots.json` (`variants.sheet`) are used.
- If the notification is not found in the shade, the request is opened from the inbox and the caption says so
  (`variants.banner`). If typing fails, the Preview caption says the built-in sample was used (`variants.sample`).
- Edit captions in `scripts/pocket-video/shots.json`, then `--render-only` re-encodes without the device.

## Limits

- No voice-over. The voice-over script is in `docs/HACKTRIBE_POCKET.md`.
- Screenshots come at a few frames per second, so motion is shown as a fast slideshow, not real-time video.
- The driver's text matching assumes the emulator UI is in English (the permission dialog also accepts "允许").
- Status: dry-run assembly (placeholder frames) verified; the device path has not been run yet, because the emulator
  was not running when the pipeline was written. Review the first real output before publishing.
