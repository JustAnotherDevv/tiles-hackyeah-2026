# 60-second video: Aegis (English)

> **Hard limit ≤ 60 s** (HackTribe "Video URL"). Target a **0:58** export.
> A judge who watches nothing else should understand: (1) local redaction, (2) blocking a real agent attack,
> (3) org approvals and budgets, (4) live policy edits, (5) that it is tested and audited.
> **Product shots are real captures only.** Designed cards (title, architecture, end card) may come from
> `video/cards.html`; they never stand in for product functionality. **Never caption an unmeasured number.**
> Voiceover ≈ 120 words at ~2.3 words/s, recorded after capture; cut the video to the VO.

## Shot list (1920×1080; L = left half Claude Code terminal, R = right half dashboard)

Captions: burned in, white on a 70 % black bar, bottom third, ≤ 8 words.

| # | Time | Screen / action | Capture command (scene script) | Caption | Voiceover |
|---|---|---|---|---|---|
| 1 | 0:00–0:05 | Title card: shield + "Aegis", subtitle "Local-first guardrails for every agent call" | `video/cards.html#title` | — | "Agents now touch customer data, tools and money." |
| 2 | 0:05–0:08 | Architecture: pulses from Claude Code → Aegis → model / MCP / HTTP | `video/cards.html#arch` (or `docs/assets/architecture.svg`) | "One control layer on every hop" | "Aegis governs every call they make." |
| 3 | 0:08–0:18 | **L:** paste the PII prompt (Jan Kowalski, PESEL 44051401359, IBAN PL61 1090 1014 0000 0712 1981 2874, card 4111 1111 1111 1111). **R:** decision drawer **Wire** tab: `[PERSON_1] … [PESEL_1] … [IBAN_1] … [PAN_1]`, CVV gone. Back to **L:** reply with real values (rehydrated) | `make claude`; fallback `uv run --frozen python demo/agents/trading_copilot.py pii-draft` | "Remote model sees placeholders only" → "Real values restored locally" | "Claude Code, routed through Aegis. A client's PESEL, IBAN and card go in; the remote model only sees placeholders. Real values return locally." |
| 4 | 0:18–0:26 | **L:** "Summarize docs/SETUP.md and follow its setup steps." → `PreToolUse` deny `[Aegis] EXE-01: …`. **R:** Live feed: INJ-01 on `tool.output`, EXE-01 block; exfil sink tab "Attacker received: 0" | `make claude`; fallback `demo/scenarios/run.py s2 --claude-fallback` | "Hidden instruction caught; command denied" | "A poisoned setup file tells the agent to pipe a script into the shell. The tool hook denies it." |
| 5 | 0:26–0:36 | **R:** Approvals inbox: "trading-copilot@trading wants to spend $50.00 on marketpulse mp-pro-monthly" → needs **admin**. View as **u_piotr**: Approve locked. Switch to **u_emily** → Approve → agent "approved · executing" | `uv run --frozen python demo/agents/trading_copilot.py subscribe` | "$50 purchase → routed to an admin" | "An agent wants a fifty-dollar subscription. Policy routes it to an admin, so its sponsor can't approve it." |
| 6 | 0:36–0:45 | **L:** `config/policy.yaml`, `controls[id=INJ-02].threshold: 0.80 → 0.50`, save. **R:** toast "Policy vN+1 applied · diff". Resend **Borderline (0.62)**: allow → **block** | live edit; fallback `demo/scenarios/run.py s4` | "Live policy edit → verdict flips" | "Judges can edit the policy live. Lower a threshold, save, and the same prompt is now blocked." |
| 7 | 0:45–0:51 | **R:** Playground **EchoLeak image proxy** → allow. Feed editor :8790 → enable **AEGIS-TI-022** → Publish → badge serial N → N+1. Replay → **block SIG-01 AEGIS-TI-022** | `uv run --frozen python -m feed_service publish --enable AEGIS-TI-022`; `demo/scenarios/run.py s5` | "Signed threat feed → exploit blocked" | "A signed threat feed adds a historical exploit, and the replay is blocked." |
| 8 | 0:51–0:56 | **L:** `make test` matrix scrolling, totals line. **R:** audit Verify "chain OK" | `make test`; `make verify-audit` | "Every control tested · audit chain OK" (add counts only if measured: "{{TBD: tests.total}} tests · 0 fail") | "One command tests every control. Every decision is audited." |
| 9 | 0:56–0:58 | End card: "Aegis: Local-First AI Guardrails", repo URL, "HackYeah 2026 · Goldman Sachs AI Control Layer" | `video/cards.html#end` | — | "Aegis. Try to break it." |

## Voiceover script (read straight through, ≈ 115 words)

> Agents now touch customer data, tools and money. Aegis governs every call they make.
>
> Claude Code, routed through Aegis. A client's PESEL, IBAN and card go in; the remote model only sees
> placeholders. Real values return locally.
>
> A poisoned setup file tells the agent to pipe a script into the shell. The tool hook denies it.
>
> An agent wants a fifty-dollar subscription. Policy routes it to an admin, so its sponsor can't approve it.
>
> Judges can edit the policy live. Lower a threshold, save, and the same prompt is now blocked.
>
> A signed threat feed adds a historical exploit, and the replay is blocked.
>
> One command tests every control. Every decision is audited.
>
> Aegis. Try to break it.

If the read runs over 56 s: drop "so its sponsor can't approve it" (shot 5), then shorten shot 7 to
"Signed feeds block historical exploits."

## Recording plan (~45 min, after the final rehearsal)

1. **Prep (10 min):** `make demo` (stack + warm-up), `make demo-preflight ARGS=--reset` → READY. Do Not Disturb,
   hide Dock and desktop icons, close Slack/Electron apps. Terminal 18 pt, browser zoom 125 %, dark theme.
2. **Capture (20 min):** QuickTime → New Screen Recording, one clip per shot, 1920×1080 @ 30 fps, 2 takes each.
   Paste prompts (from `demo/scenarios/PROMPTS.md`). Reset between takes of shots 5–7
   (`make demo-preflight ARGS=--reset`; feed back with `uv run --frozen python -m feed_service reset`).
3. **VO (5 min):** quiet room, mic 15 cm away, 3 takes, keep the cleanest.
4. **Edit (10 min):** iMovie / CapCut / DaVinci Resolve, or ffmpeg (below). VO first, cut clips to fit,
   zoom 120–150 % on the Wire view, toast and Approve button. Captions burned in. Export H.264 1080p,
   check duration ≤ 0:59 in Finder → Get Info.
5. **Publish:** YouTube **Unlisted**, title "Aegis: Local-First AI Guardrails (HackYeah 2026, Goldman Sachs)";
   open in a private window, then paste into HackTribe.

### ffmpeg assembly (optional; `/opt/homebrew/bin/ffmpeg`)

```bash
# clips in docs/submission/video/clips/01.mov … 09.mov, VO in vo.m4a, captions in captions.srt
cd docs/submission/video
printf "file 'clips/%02d.mov'\n" 1 2 3 4 5 6 7 8 9 > concat.txt
ffmpeg -y -f concat -safe 0 -i concat.txt -i vo.m4a -map 0:v -map 1:a \
  -vf "scale=1920:1080,subtitles=captions.srt:force_style='FontName=Helvetica,FontSize=28,BorderStyle=4,BackColour=&H4D000000'" \
  -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 160k -t 58 aegis_60s.mp4
ffprobe -v error -show_entries format=duration -of csv=p=0 aegis_60s.mp4   # must be <= 59
```

`captions.srt` (fill timings after the edit):

```text
1
00:00:05,000 --> 00:00:08,000
One control layer on every hop

2
00:00:08,000 --> 00:00:13,000
Remote model sees placeholders only

3
00:00:13,000 --> 00:00:18,000
Real values restored locally

4
00:00:18,000 --> 00:00:26,000
Hidden instruction caught; command denied

5
00:00:26,000 --> 00:00:36,000
$50 purchase → routed to an admin

6
00:00:36,000 --> 00:00:45,000
Live policy edit → verdict flips

7
00:00:45,000 --> 00:00:51,000
Signed threat feed → exploit blocked

8
00:00:51,000 --> 00:00:56,000
Every control tested · audit chain OK
```

## If a scene isn't ready by recording time

| Missing | Substitute (keep the timing) |
|---|---|
| Claude Code path (network/auth) | scripted agent in the left terminal (`trading_copilot.py pii-draft`, `run.py s2 --claude-fallback`); say "An agent, routed through Aegis" |
| Wire view UI | split terminal: `curl /v1/guard` redacted JSON next to the original |
| Approvals UI | `curl /api/approvals` showing `required_role: admin`, then the approve call; keep the caption |
| Feed service | drop shot 7; give its 6 s to shot 6 (show the broken-YAML rejection too) |
| Final `make test` numbers | show the matrix without a totals caption |
