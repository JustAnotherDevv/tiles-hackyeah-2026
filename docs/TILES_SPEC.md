# Tiles — product + build spec (source of truth for the build fleet)

**Tiles: a phone that reshapes itself around the person using it.** Native HarmonyOS app (ArkTS/ArkUI, API 20+,
runs on the HarmonyOS 6.1 emulator). HackYeah 2026 Huawei "Imagine What's Next" — themes **Human-Centric** +
**Intelligent Experiences**. Replaces the earlier "Aegis Pocket" concept (an AI-approvals companion) — Tiles is NOT
a dashboard and NOT an approvals app.

## The idea
The home screen is a grid of **big, colorful tiles**. Each tile is a small, live, actionable card ("Pills 8:00 —
tap when taken", "Call Kasia", "14° and rain — take the umbrella", "Homework: 3 of 5 done", "Dinner Fri 19:30 at
Veganda — 3 friends"). An **AI assistant** ("Ask Tiles…" bar at the bottom, type or speak) turns a request into new
tiles — **generative UI**: the assistant outputs a structured `TileSpec` (layout, color, content blocks, actions)
which the app renders natively. The app **adapts per person (ICP)** and learns from use ("11 missed taps today →
make text 40% bigger, hide 14 unused apps, read tiles aloud"), and a **family member / caregiver approves changes**.

## ICPs (profiles) — each a different generated home
- **Senior — Halina, 78**: very large tiles (2x1/2x2), high contrast, text scale 1.4, read-aloud on tap,
  pills reminders, "Call Kasia" (daughter), weather + what to wear, **Guardian** scam-shield tile (flags suspicious
  SMS/calls: "asks for money", "pressure: right now" → "This looks like a scam. Hang up. Kasia already knows.",
  simulated input, labelled), SOS tile. Changes approved by caregiver Kasia.
- **Kid — Zosia, 8**: playful bright palette, homework checklist, focus timer, "Call Mum", screen-time balance
  tile (as a friendly meter), a "today's adventure" tile; anything new the assistant proposes waits for a parent.
- **Low vision / motor — Michał**: voice-first, extra-large targets, read-everything-aloud, fewer tiles, simple
  2-column grid, high contrast.
- **Everyday — Daniel, 29**: dense colorful grid, plans with friends ("Dinner Friday with Ola and Kuba, vegan, near
  Kazimierz, under 80 zł" → plan tile with options + vote buttons), focus timer, commute.
A **profile switcher** (onboarding + settings) demonstrates the same app regenerating itself for each ICP.

## Generative UI — the core data model (ArkTS, implement exactly; additive changes only)
`entry/src/main/ets/tiles/model/Tile.ets`
```ts
export class TileAction { label: string = ''; kind: string = 'done'; // call|remind|speak|open|done|vote|navigate|sos|dismiss
  arg: string = ''; }
export class TileBlock { kind: string = 'text'; // text|big|list|checklist|progress|buttons|timer|chips|alert|weather
  text: string = ''; value: string = ''; items: string[] = []; checked: boolean[] = []; progress: number = 0;
  actions: TileAction[] = []; }
export class TileSpec { id: string = ''; type: string = 'custom'; // pills|call|weather|guardian|plan|timer|homework|
  // screentime|reminder|note|sos|commute|adventure|custom
  title: string = ''; subtitle: string = ''; icon: string = '';   // SymbolGlyph name or resource name
  color: string = 'sky';   // palette key, see Theme
  size: string = '2x1';    // 1x1 | 2x1 | 2x2
  blocks: TileBlock[] = []; source: string = 'seed'; // seed|assistant|adaptation
  speakText: string = ''; pinned: boolean = false; createdAt: number = 0; }
export class Profile { id: string = 'everyday'; // senior|kid|lowvision|everyday
  name: string = ''; textScale: number = 1.0; highContrast: boolean = false; readAloud: boolean = false;
  columns: number = 4; caregiver: string = ''; caregiverRole: string = ''; }
export class Suggestion { id: string = ''; title: string = ''; detail: string = ''; change: string = '';
  // e.g. textScale:1.4 | hide:apps | readAloud:on | addTile:<json>
  status: string = 'pending'; reason: string = ''; }
export class ComposeResult { reply: string = ''; tiles: TileSpec[] = []; needsApproval: boolean = false;
  followUps: string[] = []; }
```
Store `entry/src/main/ets/tiles/data/TileStore.ets` (singleton, AppStorage-backed, persisted with the existing
`platform/PocketPersist.ets`/Preferences helpers): keys `tiles.list`, `tiles.profile`, `tiles.suggestions`,
`tiles.pending` (assistant proposals awaiting approval). API: `tiles(): TileSpec[]`, `setProfile(p)`,
`addTiles(t[])`, `removeTile(id)`, `moveTile(from,to)`, `propose(r: ComposeResult)`, `approvePending(id)`,
`declinePending(id)`, `suggestions()`, `decideSuggestion(id, approve)`, `recordTap(tileId, missed: boolean)`.
Composer `entry/src/main/ets/tiles/ai/Composer.ets`: `compose(prompt: string, profile: Profile): ComposeResult` —
**on-device, deterministic intent planner** (keyword + slot extraction for EN + PL: time, day, person, place, food,
budget, medicine, homework subject…) mapping to tile templates per ICP; returns a friendly reply + 1–3 TileSpecs +
follow-up chips. Clearly documented as the pluggable "generator"; the same JSON schema can come from an LLM through
the Aegis gateway (sibling project, local-first guardrails) in a future live mode — do not claim an LLM is used.
Adaptation `tiles/ai/Adaptation.ets`: turns usage signals (missed taps, unused tiles, time of day) into
`Suggestion`s.

## Visual language
Colorful, warm, friendly, premium (think Material You expressive + Nothing + Duolingo restraint), NOT a dark
enterprise dashboard. Light warm background (#F6F3EE) with a dark mode; tile palette keys: sun #FFC83D, coral
#FF6B5A, sky #3DA5FF, mint #2ED3A0, grape #9B7BFF, peach #FF9F6B, leaf #7BD957, ink #1C2230 (each with on-color
text that passes WCAG AA; senior/lowvision profiles use high-contrast variants). Rounded 24–28 px tiles, big type,
SymbolGlyph icons. Motion: tiles spring in when generated, gentle press-scale, shared-element tile → detail,
grid reflow animations; respect reduced motion. WCAG 2.1 AA, tap targets ≥48 vp (≥64 for senior).

## Screens (files under `entry/src/main/ets/tiles/`)
- `pages` shell: `entry/src/main/ets/pages/Index.ets` → Tiles home (owned by T-HOME).
- Home grid (`views/HomeView.ets`): greeting + date + profile chip, adaptive Grid of tiles (sizes per spec,
  long-press to reorder/remove), "Ask Tiles…" assistant bar pinned at bottom, suggestion banner.
- Tile renderer (`components/TileView.ets` + `components/blocks/*`): renders any TileSpec natively.
- Tile detail (`views/TileDetailView.ets`): full-screen version of a tile with its actions.
- Assistant sheet (`views/AssistantSheet.ets`): conversation, quick chips per ICP, "Tiles is making…" generation
  animation, proposed tiles preview → Add / (for senior/kid) "Ask Kasia/Mum to approve".
- Onboarding + profile picker (`views/OnboardingView.ets`), Caregiver view (`views/CaregiverView.ets`: pending
  proposals + adaptation suggestions → Approve / Decline, shown as "Kasia's phone" simulation), Guardian
  (`views/GuardianView.ets`), Settings (`views/TilesSettingsView.ets`).

## Platform capabilities to use (judged: "use of platform capabilities")
Form Kit home-screen widget (top tiles + next reminder), Notification Kit (pill/reminder + caregiver alerts),
reminderAgentManager (Background Tasks Kit) for scheduled reminders, Core Speech Kit text-to-speech for read-aloud
(fallback: visual "speaking" state if TTS unavailable on emulator), Vibrator haptics, call via Want to the dialer,
accessibility (accessibilityText, large fonts), dark mode. Verify each API in the grounded docs (skills) before use;
ordinary-app APIs only.

## Non-goals / honesty
No real personal data; scam detection is simulated input (labelled "Demo call"); assistant is on-device
rule-based generator (say so); keep it robust on the emulator.
