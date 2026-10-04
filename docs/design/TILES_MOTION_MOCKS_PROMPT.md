# Prompt: high-fidelity, animated design explorations for **Tiles**

Paste everything below the line into a fresh Claude Code session started in the repository root
(`tiles-hackyeah-2026`). It supersedes `POCKET_MOTION_MOCKS_PROMPT.md` (Aegis Pocket was a dropped concept).

---

You are a world-class product designer, motion designer and front-end prototyper. Create **interactive, animated,
high-fidelity mobile prototypes** exploring visual + interaction directions for **Tiles — a phone that reshapes
itself around the person using it**. This is design exploration: build standalone web prototypes; do **not** edit
the real app.

## Hard rules (a build fleet is working in this repo right now)
- Write ONLY inside `design/tiles-motion/` (create it). Don't edit `entry/`, `AppScope/`, `aegis/`, `docs/`,
  build files; no git. Don't start/stop the HarmonyOS emulator, DevEco Studio, hvigor or any gateway.
- 8 GB RAM Mac: at most one dev server (free port, e.g. 5320); no headless-Chrome loops; stop servers when done.
- All data is mock and fictional (Halina, Kasia, Zosia, Michał, Daniel…); no real personal data.

## Read first
`docs/TILES_SPEC.md` (product + generative-UI data model: TileSpec / TileBlock / TileAction / Profile /
Suggestion), `mockups/ideas.html` (concepts "Shapeshift", "Guardian", "Multiplayer agent" — the seeds of Tiles),
and the current app screenshots in `docs/screenshots/tiles/` if they exist.

## The product in one paragraph
Tiles is a native HarmonyOS app (HackYeah 2026, Huawei "Imagine What's Next", themes Human-Centric + Intelligent
Experiences). The home screen is a grid of **big, colorful, live tiles** — each a tiny actionable card ("Pills 8:00
— tap when taken", "Call Kasia", "14° and rain — take the umbrella", "Homework 3/5", "Dinner Fri 19:30 · Veganda ·
vote"). An **AI assistant** ("Ask Tiles…", type or speak) turns requests into new tiles — **generative UI**: the
assistant emits a structured TileSpec (size 1x1/2x1/2x2, palette color, blocks: text, big number, list, checklist,
progress, timer, chips, alert, weather, buttons; actions: call, remind, speak, vote, done, SOS) that renders
natively. The phone **adapts per person (ICP)** and learns from use ("11 missed taps today → text 40% bigger, hide
14 unused apps, read tiles aloud") while a **caregiver/parent approves changes** from their own phone. A **Guardian**
tile shields seniors from scam calls/SMS with explainable red flags, entirely on-device.

## ICPs to design for (each gets its own generated home)
- **Senior — Halina, 78**: huge tiles, high contrast, read-aloud, pills, call daughter Kasia, weather/what to wear,
  Guardian scam shield, SOS. Calm, dignified, never childish.
- **Kid — Zosia, 8**: playful but not noisy; homework checklist, focus timer with a friendly creature, call Mum,
  screen-time as a fair "energy" meter, today's adventure; new tiles wait for a parent.
- **Low vision / motor — Michał**: voice-first, 2 columns, enormous targets, everything spoken, minimal motion.
- **Everyday — Daniel, 29**: dense, expressive grid; plans with friends (agents coordinate; only free/busy leaves
  your phone), focus, commute.
- **Caregiver — Kasia (Halina's daughter)**: a companion view on her phone: approve Halina's tile changes, see
  "took 8:00 pills", get Guardian alerts.

## Produce 3 distinct directions (each a coherent system: type, color, shape, iconography, motion language)
- **A — "Warm Paper"**: light, warm, tactile; colorful tiles like paper cards; Material You *expressive* shapes;
  gentle springs.
- **B — "Bold Blocks"**: saturated color blocks, oversized type, Metro/Nothing-inspired; snappy, confident motion.
- **C — "Living Light"**: soft gradients and depth, tiles that breathe with live data (pulse on reminder,
  shimmer when the assistant is generating); spatial parallax; still WCAG AA.

For each direction, build these **interactive, animated flows** (60 fps; `prefers-reduced-motion` honored):
1. **Onboarding — "Who is this phone for?"**: pick Senior / Kid / Low vision / Everyday → the home **morphs** into
   that ICP's layout (tiles resize, recolor, reflow — the signature "shapeshift" moment).
2. **Ask Tiles → generative UI**: user types/speaks "Remind me to take Euthyrox at 8 every morning" or "Dinner
   Friday with Ola and Kuba, vegan, near Kazimierz, under 80 zł" → typing/thinking state → a **tile is born**
   (skeleton assembles block by block, color floods in, it flies into the grid and the grid reflows).
3. **Tile interaction**: tap Pills → "Taken ✓" with confetti-free, satisfying micro-interaction; Call Kasia →
   call sheet; read-aloud waveform when speaking a tile; long-press → reorder (grid physics) / remove.
4. **Adaptation**: "Tiles noticed 11 missed taps" suggestion card → preview before/after (text grows, 14 app tiles
   fold away) → **sent to Kasia for approval** → on Kasia's phone (side-by-side second device) she approves → change
   animates in on Halina's phone.
5. **Guardian**: incoming demo call transcript, red flags pop in ("asks for money", "pressure: right now", "don't
   tell Mum"), risk meter climbs to 92%, the screen calmly transforms into one giant instruction "This looks like a
   scam. Hang up. Kasia already knows." + Kasia's phone gets the alert.
6. **Kid mode**: homework checklist + focus timer creature; a new tile proposed by the assistant waits for Mum.
7. **Home-screen widget** (2x2, 2x4, senior 4x4 big buttons) and a lock-screen / notification for the 8:00 pill.
Quality bar: real copy (EN, with a few Polish touches), tabular numbers, accessible contrast (WCAG 2.1 AA), tap
targets ≥48 px (≥64 px senior), focus states, dark mode for at least one direction, no lorem, no emoji-as-icons
(use a good icon set, e.g. Phosphor or Material Symbols Rounded).

## Tech
Vite + React + TypeScript + Framer Motion (layout animations / shared layout for the morph and tile birth),
optional Rive/Lottie only if offline. One route per direction + a gallery `/` showing phones side by side (393×852
frames, HarmonyOS status/gesture bars) with "Play flow" buttons and an `?autoplay=1` loop mode for screen recording.
Drive every screen from a JSON TileSpec (same shape as `docs/TILES_SPEC.md`) so the prototypes prove the
generative-UI idea, not just pictures.

## Deliverables
- `design/tiles-motion/` app + `README.md` (`npm i && npm run dev -- --port 5320`).
- `design/tiles-motion/NOTES.md`: rationale per direction; motion spec table (element, trigger, duration, easing /
  spring stiffness+damping); tokens (palette with on-colors, type scale, radii, spacing per ICP); accessibility
  notes per ICP; **ArkUI porting guide** for the winning direction (`animateTo`, `transition`, `geometryTransition`
  for tile → detail, Grid/GridItem layout animation, `SymbolGlyph`, `@ohos.vibrator`, Form Kit widget limits).
- A clear recommendation: which direction to ship in the HarmonyOS app for the demo, and the 5 highest-impact
  changes to port first.
