# Prompt: alternative high-fidelity, animated UI mocks for Aegis Pocket

Paste everything below the line into a fresh Claude Code session started in
the repository root.

---

You are a senior product designer + motion designer + front-end prototyper. Explore **alternative UI directions for
"Aegis Pocket"** as **interactive, animated, high-fidelity mobile mockups** (motion-design quality, not wireframes).
This is design exploration only: build standalone web prototypes; do **not** edit the real app.

## Hard rules (other agents are working in this repo right now)
- Write ONLY inside `design/pocket-motion/` (create it). Do not edit `entry/`, `AppScope/`, `aegis/`, build files,
  README/SUBMISSION docs, and do not run git.
- Do not start/stop the HarmonyOS emulator, DevEco Studio, hvigor/devecocli, or the Aegis gateway (an agent is
  recording the demo video on the emulator). The Mac has 8 GB RAM: keep one dev server at most (pick a free port,
  e.g. 5310), no headless-Chrome loops, stop servers when done.
- Self-contained: no CDN at runtime is preferred (but a single-file HTML using unpkg/esm.sh for React + Framer Motion
  / Motion One / GSAP is acceptable for speed). No backend; all data is mock (label it "Mock data").

## What Aegis Pocket is
Native HarmonyOS app (ArkTS/ArkUI, API 20+, tested on a HarmonyOS 6.1 phone emulator) for the HackYeah 2026 Huawei
"Imagine What's Next" challenge (themes: Intelligent / Human-Centric). It is the **human-in-the-loop companion for
AI agents** governed by **Aegis**, a local-first AI guardrail gateway (sibling project in `aegis/`). When an agent
wants to do something risky — buy a subscription, read a PII table, raise a budget, install a package, send data to
a third party — the gateway pauses it and asks the right human. Pocket puts that decision in your pocket:
notification → context → step-up biometric → approve/deny, with role rules (member / admin / owner, two-person rule).

Current screens (bottom tabs: Home · Inbox · Preview · Settings), see `entry/src/main/ets/views/*`:
- **Home**: "N requests waiting for you" ring + "Review now"; security posture (requests, blocked, redacted, spend
  today vs budget, cost avoided, overhead p50); "Needs attention" list; MOCK/LIVE badge.
- **Inbox**: pending/decided requests: title, requester agent (e.g. `trading-copilot@trading`), action type, amount,
  required role pill ("needs admin", "needs owner ×2"), expiry countdown, persona switcher (Piotr = member,
  Emily/Marek = admin, Katarzyna = owner).
- **Detail**: facts, policy checks (control id + result), agent note (untrusted), **"Why a human is asked" risk
  card** (0–100 score + reasons), budget before→after for raises, two-person progress, Approve / Deny; Approve on
  admin/owner/two-person/≥$100 triggers **step-up auth** (face / fingerprint / PIN via User Authentication Kit; on an
  emulator a clearly labelled manual-confirmation fallback); locked buttons explain why ("Needs an admin — you
  sponsor trading-copilot@trading").
- **Preview ("What data leaves")**: type/paste text → on-device detection replaces PII with placeholders
  (`[EMAIL_1]`, `[PESEL_1]`, `[IBAN_1]`, `[PAN_1]`; PESEL checksum, IBAN mod-97, card Luhn) — nothing is sent.
- **Settings**: mock/live mode, gateway URL, connection test, persona, notifications (deep link to system settings).
- **Home-screen service widgets** (Form Kit 2×2 and 2×4): posture + pending count; "No data yet" when empty.
- **Notifications** for new requests (tap opens the request); distinct haptics for approve / deny / new request.

Mock requests to use (from `entry/src/main/ets/data/MockRepository.ets`):
1. Buy MarketPulse Pro (mp-pro-monthly) — $50 — `trading-copilot@trading` — needs admin (rule spend-admin, ACT-01)
2. Buy MarketPulse Enterprise seats — $480 — needs owner ×2 (two-person)
3. Raise team:trading daily budget $60 → $150 — needs owner
4. Read customers table (contains PII) — `research-agent@research` — needs admin
5. `pip install pandas==2.2.3` — package install — self/auto
6. Upload customer list to paste.example — egress — blocked/deny

Data model (simplified, `entry/src/main/ets/model/Models.ets`): ApprovalItem {id, kind (action | config_change |
budget_raise | mcp_pin), actionType, title, summary, requesterAgent, requesterMember, teamId, amountUsd, resource,
requiredRole (auto | self | admin | owner | deny), twoPerson, ruleId, controlId, status (pending | approved | denied |
expired | cancelled), createdAt, expiresAt, votes[], canVote, whyNot, facts[], checks[], agentNote, budgetBefore,
budgetAfter}; PostureStats {requests, blocked, redacted, approvalsPending, spendTodayUsd, budgetUsedPct,
activeAgents, costAvoidedUsd, p50OverheadMs, source mock|live}.

Current visual language (`entry/src/main/ets/common/Theme.ets`) — dark-first: BG #0B0F17, surfaces #131A26 /
#1A2333 / #222D41, border #243047, text #E6EDF7 / dim #8A97AD, accent #4F8CFF, good #2FD08A, warn #F5B544,
bad #FF5A6A; role tones: owner fuchsia #E879F9, admin sky #38BDF8, member slate #94A3B8; radii 8/14/20; spacing
4/8/12/16/24. The sibling Aegis web dashboard just moved to an "enterprise" look (IBM Plex Sans/Mono, one blue
accent, flat surfaces, no glows/gradients) — Pocket may diverge (it's a consumer-grade mobile companion) but should
feel like the same product family. Reference screenshot of the current app: `docs/screenshots/` (if present).

## What to produce
Build **3 distinct design directions** as interactive mobile prototypes in a phone frame (393×852 viewport, HarmonyOS
status bar / gesture bar), each a coherent system (type, color, iconography, components, motion language):
- **A — "Calm Control"**: refined, quiet, enterprise-trustworthy (think Apple Wallet + Linear restraint); motion
  communicates state only.
- **B — "Signal"**: bold, high-contrast, glanceable decisions (big amount + verdict, card stack you swipe to
  approve/deny with spring physics, haptic-style visual feedback).
- **C — "Intelligent / Spatial"**: depth and light — layered glass cards, a living risk orb/ring that reacts to the
  risk score, subtle parallax; still legible and accessible.
For each direction, make these flows fully interactive and animated (60 fps, `prefers-reduced-motion` respected):
1. **Incoming request**: notification banner slides in → tap → shared-element transition into Detail.
2. **Detail → Approve with step-up**: risk card builds in (score counts up, reasons stagger in), press-and-hold or
   swipe-to-approve, biometric sheet (Face ID-style scan animation) → success morph (checkmark, card collapses into
   the inbox, counter decrements, widget updates). Include the **locked state** (member can't approve: explain why)
   and **two-person** progress (1/2 → 2/2).
3. **Deny** with a reason chip, undo snackbar.
4. **Inbox**: list ↔ stack view toggle, filter by role, expiry countdown micro-animations, empty "All clear" state.
5. **"What data leaves" preview**: live typing with PII tokens morphing into placeholders (`jan@acme.pl` →
   `[EMAIL_1]`), a "stays on device / leaves device" split visual.
6. **Home-screen widget** 2×2 and 2×4 states (pending count, posture, no-data), plus a tap-to-open transition.
7. **Persona switch** (member → admin → owner) re-evaluates eligibility with a visible transition.
Polish bar: typographic hierarchy, consistent spacing/radii, real copy (no lorem), tabular numbers with units,
accessible contrast (WCAG AA), tap targets ≥44 px, focus states, a light-mode variant for at least one direction.

## Tech suggestion
Vite + React + TypeScript + Framer Motion (or Motion One) in `design/pocket-motion/`, one route per direction plus a
gallery index that shows the three phones side-by-side with a "play flow" button per flow; a `?autoplay=1` mode that
loops each flow for screen recording. Optionally export short MP4/GIF captures of each flow with ffmpeg (only if RAM
allows; one at a time).

## Deliverables
- `design/pocket-motion/` app + `README.md` (how to run: `npm i && npm run dev -- --port 5310`), gallery at `/`.
- `design/pocket-motion/NOTES.md`: rationale per direction, motion spec table (element, trigger, duration, easing /
  spring params), tokens, and **how each direction would map to ArkUI** (`animateTo`, `transition`,
  `geometryTransition` for shared elements, `Swiper`/gestures, `@ohos.vibrator` haptics, Form Kit widget limits —
  widgets support only limited animation) so the winning direction can be ported to `entry/` later.
- A recommendation: which direction to adopt for the hackathon demo video and why.
