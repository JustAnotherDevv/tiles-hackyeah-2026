# Tiles demo video

| File | What |
|---|---|
| `tiles-demo.mp4` | The demo: 34.2 s, 1920×1080, 30 fps, H.264 (yuv420p, faststart), 11.4 MB, AAC stereo music bed |
| `captions.srt` | One caption per segment (English), same text as the burned-in captions plus the scene titles |
| `poster.png` | 1920×1080 poster frame (outro card) |

## What each segment shows

| Time (s) | What it shows | Real / simulated |
|---|---|---|
| 0.0–4.3 | Title: the Tiles mark assembles from tiles, wordmark and tagline | Motion graphics |
| 4.3–8.1 | One phone, four people: Halina 78, Zosia 8, Michał (low vision), Daniel 29, each with an illustrative mini home | Motion graphics; personas fictional (footnote on screen) |
| 8.1–9.2 | Section card “Shapeshift” | Motion graphics |
| 9.2–16.1 | Onboarding “Who is this phone for?” → tap Senior → the home morphs into Halina’s home | Real app on the HarmonyOS 6.1.1 emulator |
| 16.1–17.3 | Section card “Guardian” | Motion graphics |
| 17.3–25.2 | Guardian: incoming demo call, red flags and scam risk, “Hang up. Kasia already knows.” | **Demo call (simulated)** — labelled on screen |
| 25.2–29.6 | Built on HarmonyOS: the platform kits the app uses | Motion graphics; kits the app uses (haptics need a real device, as the card says) |
| 29.6–34.2 | Outro: Tiles, HackYeah 2026 · Huawei — Imagine What’s Next, repository URL | Motion graphics |

## What is real and what is simulated

- **App footage is the real Tiles app** (`com.hackyeah.tiles`) running on the DevEco **HarmonyOS 6.1.1 (API 24) phone
  emulator**. The emulator has no screen recorder, so app clips are bursts of full-resolution screenshots
  (`snapshot_display`) re-timed to their real capture times, then composited into a drawn phone frame on the
  "Living Light" gradient. Taps were injected with `uitest`; no touch indicator is drawn.
- **Guardian**: the incoming call is a **demo call (simulated input)** built into the app (Polish script; the burned-in
  caption gives the English gist); the red flags, risk score and the caregiver alert are computed on the phone by
  explainable rules.
- Ask Tiles (generative UI) and the caregiver approval flow exist in the app but are not shown in this cut.
- **Personas** (Halina, Zosia, Michał, Daniel, Kasia) are fictional. Phone numbers and names in the footage are fictional.
- The **"Built on HarmonyOS"** card lists only kits the app uses and that were verified on the emulator (see the
  capability table in the main `README.md`). Scheduled reminders and spoken text-to-speech are deliberately not claimed.
- Title, people, platform and outro cards are motion graphics (HTML/CSS rendered frame by frame in headless Chrome,
  or ImageMagick + ffmpeg), not app footage.
- Audio: a calm music bed and soft transition sounds, synthesised from scratch in code (additive/FM synthesis and filtered noise). No downloaded or copyrighted music.

## How it was made / how to rebuild

The video was assembled by a small set of scripts (kept outside the repository because they read the raw emulator
captures):

1. **Record**: drive the app on the emulator with `hdc shell uitest uiInput …` while two loops call
   `hdc shell snapshot_display`; pull the JPEGs and assemble them with ffmpeg `concat` using their real timestamps
   (30 fps, optional `minterpolate`).
2. **Frame**: a gradient plate (165°, `#EDF1FC → #F6F0FA → #FFF3EA`), a phone frame PNG with a transparent screen hole
   and a rounded screen mask; footage is scaled to the screen rect, `alphamerge`d with the mask, overlaid on the plate
   and the phone PNG on top. A slow push-in is done with the `perspective` filter (sub-pixel, eased).
3. **Motion graphics**: HTML scenes using Manrope (`entry/src/main/resources/rawfile/fonts/`, OFL) and the app's
   Living Light tokens, rendered deterministically frame by frame.
4. **Edit**: all segments are normalised to 1920×1080/30 fps, trimmed or frozen to the EDL durations and joined with
   0.6 s eased crossfades (`xfade=transition=custom`, smoothstep). Caption cards (Manrope, glass card) are overlaid
   with a fade and a short eased slide. Final encode:

   ```sh
   ffmpeg … -c:v libx264 -preset slow -crf 19 -profile:v high -pix_fmt yuv420p -movflags +faststart \
     -c:a aac -b:a 128k tiles-demo.mp4
   ```

To re-record on your own machine: install the signed `.hap` (see the main `README.md`), start the emulator, walk the
flows listed in the table above (Settings → onboarding → Senior; Guardian → Demo call), and capture with `hdc shell snapshot_display -f /data/local/tmp/x.jpeg` in a loop.

## Superseded files

`aegis-pocket-demo-60s.mp4`, `aegis-pocket-captions.srt`, `captions.txt` and `cover.png` belong to the earlier
Aegis Pocket concept and are kept for transparency only (produced by `scripts/pocket-video/record.sh`).
