# Aegis 60-second demo video

| File | What |
|---|---|
| `aegis-demo-60s.mp4` | The video: H.264, 1920×1080, 30 fps, silent AAC track, under 58 s, burned-in captions |
| `cover.png` | 1920×1080 cover image for the HackTribe image field (the title card's last frame) |
| `captions.txt` | Timeline and caption of every beat (generated) |
| `test-summary.txt` | Captured `make test` summary used on the test card (first line is its caption) |
| `cards.html` | Designed title and end cards (not product footage) |
| `captions.srt` | Caption template for the manual QuickTime recording plan in `../VIDEO_60S.md` |

## How it was produced

This video was made automatically by an AI agent. No one recorded the screen by hand.

1. **Live stack.** `AEGIS_SEMANTIC=off make up` started the real gateway, feed, and mocks on the fixed
   ports. Then `make demo-preflight ARGS=--reset` and `demo/scenarios/warmup.py --fast` ran to build
   dashboard history.
2. **Capture** (`scripts/video/capture.py`). Headless Google Chrome, driven over the DevTools Protocol
   (`scripts/video/cdp.py`), screenshots the real `/ui` dashboard at 1600×900 CSS px ×1.2, which gives
   1920×1080. At the same time the real demo commands run:
   - `trading_copilot.py pii-draft`, then the Wire tab in the decision drawer
   - `run.py s2 --claude-fallback`, the EXE-01 drawer, and the live feed
   - `trading_copilot.py subscribe`, viewed as `u_piotr` (Approve locked) and as `u_emily` (Approve, then the agent executes)
   - an edit to `config/policy.yaml` (`INJ-02 threshold 0.80 → 0.50`, saved), which the file watcher
     hot-reloads, then the Playground Borderline preset is run again
   - Playground EchoLeak (allow), then the feed editor on :8790 (Enable AEGIS-TI-022 → Publish), then
     EchoLeak again (block)
   - the Audit page's **Verify chain** and `make verify-audit`

   Clicks go through DOM `.click()`. The golden policy and the demo state are restored afterwards.
3. **Render** (`scripts/video/render.py`):
   - Terminal cards are the real ANSI stdout of those commands, converted to HTML. Some cards show an
     excerpt of the lines.
   - Each caption is a transparent PNG.
   - The title and end cards come from `cards.html`, rendered frame by frame through the Web
     Animations API.
   - Each still gets a short ffmpeg clip with a slow eased zoom, then 0.35 s crossfades join the clips.
   - Every product shot is labelled `live capture · real stack · AEGIS_SEMANTIC=off (deterministic)`.
     The injection terminal card is labelled `scripted Claude Code hook events`, because it uses
     `--claude-fallback`, not a live `claude` session.
4. **Numbers.** Captions only quote values that came out of that run: the policy edit, the feed
   serials, the `make test` counts, and the audit chain. Feed serials and policy versions change on
   every run.

## Regenerate (one command)

```bash
cd aegis
scripts/video/make_video.sh               # capture + render (starts/stops the stack if :8787 is free)
scripts/video/make_video.sh --run-tests   # also re-run `make test` and refresh test-summary.txt
scripts/video/make_video.sh --render-only # re-encode from the last capture in $VIDEO_BUILD
```

You need Google Chrome, `/opt/homebrew/bin/ffmpeg`, and `uv`. Ports 8787 and 8790–8794 must be free, or
already serving the Aegis stack. CDP uses port 8799. Intermediate files go to `$VIDEO_BUILD`, which
defaults to `$TMPDIR/aegis-video-build` and is never written inside the repo. Each clip is cached by a
hash of its inputs, so a render that changes only captions is quick. On a loaded 8 GB machine a full run
takes about 10–15 minutes.

## Limits

- The video has no voiceover. The VO script in `../VIDEO_60S.md` can be recorded over it.
- Scene 2 uses the scripted Claude Code hook events (`--claude-fallback`). They hit the same controls as
  the live hook, but this is not a recording of an interactive `claude` session.
- Semantic models were off (deterministic mode), so no caption claims a model-based detection.
