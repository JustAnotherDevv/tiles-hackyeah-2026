# Aegis design tokens and visual language

This file is the reference for the real dashboard (Vite + React + TypeScript + Tailwind + shadcn/ui + Recharts + Monaco + framer-motion). Every value here also exists in the clickable prototype, so you can compare your build against it side by side.

- **Prototype:** `staging/design/prototype/index.html`. It has no build step and no dependencies apart from Google Fonts. You can open the file directly, or serve the folder (`python3 -m http.server -d staging/design/prototype 4321`).
- **Token source:** `prototype/assets/tokens.css`. This document mirrors it one to one. Component styles are in `prototype/assets/app.css`.
- **Routes:** `#/overview`, `#/live`, `#/redaction`, `#/approvals`, `#/budgets`, `#/policy`, `#/feed`, `#/org`.
- **Keyboard:** `⌘K` opens the command palette, `g` followed by `c/l/r/a/b/p/f/o` jumps to a page, `Esc` closes overlays, and `Space` pauses the live feed.

---

## 1. Principles

1. **Dark first, security-ops calm.** The UI uses a cool graphite canvas with six surface steps. The interface stays quiet and the data and decisions carry the colour.
2. **Depth without glow.** Elevation comes from a 1 px hairline border, a 3–5 % white inset highlight on the top edge, and a soft black drop shadow. Do not use coloured glows, neon or blurred light blooms. A backdrop blur appears only on the sticky top bar and the modal overlay.
3. **Colour means something.** Decision colours (allow, redact, approval, block, downgrade) appear only for decisions. Brand iris is used for focus, primary actions and annotations. Status colours are never reused for chart series.
4. **Machine values are monospace.** Request, trace, control, signature and approval IDs use Geist Mono, as do hashes, model names, surfaces, YAML, headers and latencies inside tables.
5. **Every number explains itself.** Show the score against its threshold, the control ID, the policy and feed versions, and the latency. A block that nobody can explain counts as a bug.
6. **Motion confirms, never decorates.** Use expo-out on enter and short durations. Every animation reflects a state change: a new event arrives, a policy swaps, an approval resolves.

---

## 2. Colour

### 2.1 Neutrals (surfaces, borders, text)

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#07080A` | App canvas |
| `--bg-sidebar` | `#0A0B0E` | Sidebar, ticker, editor chrome |
| `--surface-1` | `#0E1013` | Card |
| `--surface-2` | `#13161A` | Hovered row, input, secondary button, selected list item |
| `--surface-3` | `#191C21` | Popover, drawer header, modal, toast, menu, tooltip |
| `--surface-4` | `#20242A` | Pressed state, segmented-control thumb, active cmdk item |
| `--border-subtle` | `#15181C` | Dividers inside cards, table rows |
| `--border` | `#1E2228` | Card and input borders |
| `--border-strong` | `#2A2F37` | Hover borders, popover ring |
| `--text-1` | `#ECEEF1` | Primary text (16.4:1 on card) |
| `--text-2` | `#A2A8B3` | Secondary text (8.0:1) |
| `--text-3` | `#7A808C` | Muted text, labels, axis ticks (4.8:1) |
| `--text-4` | `#4B5160` | Disabled or decorative only (2.4:1), never for information |

### 2.2 Brand: Aegis Iris

| Token | Value | Use |
|---|---|---|
| `--primary` | `#6D5DFC` | Primary button background (white text 4.54:1) |
| `--primary-hover` | `#7B6CFF` | Hover |
| `--primary-press` | `#5E4FE6` | Active |
| `--accent-fg` | `#9A8CFF` | Iris text and icons on dark: active nav icon, links, chart annotations |
| `--accent-subtle` | `rgba(124,108,255,.12)` | Selected or info backgrounds |
| `--accent-border` | `rgba(124,108,255,.32)` | Info borders |
| Focus ring | `0 0 0 2px var(--bg), 0 0 0 4px rgba(124,108,255,.65)` | Every focusable element |
| Logo mark | `linear-gradient(160deg,#7B6CFF,#4C3FD9)` | The **only** gradient in the product |

### 2.3 Decision semantics

Decision colours come in two sets. **UI** colours are bright enough for text and badges on dark surfaces. **Chart** colours are validated marks in the OKLCH L 0.48–0.67 band, with adjacent CVD ΔE ≥ 8 measured on `#0E1013`. Never put a chart colour on text, and never use a UI colour as a chart fill.

| Decision | UI fg | Subtle bg (10 %) | Border (26–30 %) | Chart mark | Icon (lucide) |
|---|---|---|---|---|---|
| allow | `#3CCB7F` | `rgba(60,203,127,.10)` | `rgba(60,203,127,.26)` | `#1E9F68` | `ShieldCheck` / `Check` |
| redact | `#5BA4F5` | `rgba(91,164,245,.10)` | `rgba(91,164,245,.28)` | `#3987E5` | `EyeOff` |
| approval | `#E8A93A` | `rgba(232,169,58,.10)` | `rgba(232,169,58,.28)` | `#C98500` | `Clock` |
| block | `#F2556F` | `rgba(242,85,111,.10)` | `rgba(242,85,111,.30)` | `#E5446D` | `Ban` |
| downgrade | `#F08A4B` | `rgba(240,138,75,.10)` | `rgba(240,138,75,.28)` | (UI only) | `ArrowDown` |
| neutral / log | `#8C93A0` | `rgba(140,147,160,.10)` | `rgba(140,147,160,.24)` | (UI only) | — |

The validator output for the stack order allow → redact → approval → block is: lightness band PASS, chroma PASS, worst adjacent CVD ΔE 9.7 (approval↔block, deutan) PASS, normal-vision ΔE 18.9 PASS, contrast ≥ 3:1 PASS. Destructive buttons use the solid fill `#C43350`, which gives white text 4.9:1.

### 2.4 Categorical (teams), in a fixed order that is never cycled

| Slot | Hex | Team in prototype |
|---|---|---|
| `--cat-1` | `#3987E5` | Trading |
| `--cat-2` | `#D95926` | Research |
| `--cat-3` | `#199E70` | Risk & Compliance |
| `--cat-4` | `#C98500` | Engineering |
| `--cat-5` | `#D55181` | Client Services |

All slots validate as adjacent pairs on `#0E1013`, with a worst CVD ΔE of 8.4. Line charts with two series use cat-1 (p50) and cat-2 (p95). Colour follows the entity, never its rank.

### 2.5 Other semantic sets

| Set | Values |
|---|---|
| Roles | Owner `#F2C66D` (bg 8 %, border 26 %) · Admin uses iris (`--accent-*`) · Member uses neutral (`--surface-2` / `--border-strong`) · Agent `#6FD3C8` · Self-approve uses the allow colours |
| Redaction entity types | Person `#9A8CFF` · Government ID `#E8A93A` · Financial `#5BA4F5` · Contact `#3FC1B0` · Secret `#F2556F` · Metadata `#A2A8B3` · Dropped (PCI) uses the block colours |
| Spans | Source spans get a `color-mix(--ec 13%)` background with a 1.5 px bottom underline. Wire placeholders use mono text, a 16 % background and a 1 px inset ring. Restored values use allow-subtle with a green underline. The shared hover highlight is a 1.5 px ring plus a 3 px halo in the same hue. |
| YAML syntax | key `#B5A8FF` · control/signature ID `#7CC4F2` · string `#8FD1A8` · number `#E8B865` · boolean `#F2849A` · comment `#4F5664` italic · punctuation `--text-3` |
| Chart chrome | grid `#1A1E24` (1 px solid, crisp edges) · axis `#2A2F37` · tick label `#7A808C` 10.5 px · annotation `#9A8CFF` (line at 55 % opacity, 3 px dot, mono 10 px label `#B5A8FF`) |
| Budget meter | ok/watch `#4A7FE0` · soft (≥ 80 %) `#C98500` · hard (≥ 100 %) `#E5446D` · track `--surface-3` · markers at 80 % (`--text-4`) and 100 % (`--text-3`) |
| Heatmap | sequential, one hue: `mix(#13161A → #E5446D, 0.12 + 0.88·√(v/max))`, with zero shown as `#13161A` |

---

## 3. Typography

- **Sans:** `"Geist", "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`. Weights are 400, 450 (nav), 500, 550 (card titles and badges) and 600.
- **Mono:** `"Geist Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace`. Weights are 400–600. Mono renders at about 0.93 em of the surrounding text with `letter-spacing: -0.01em`.
- **Google Fonts URL:** `https://fonts.googleapis.com/css2?family=Geist:wght@300..700&family=Geist+Mono:wght@400..600&display=swap`. For the React app, you can also use the `geist` npm package.
- **Body settings:** `-webkit-font-smoothing: antialiased; font-feature-settings: "ss01","cv11"`. Every number in a KPI tile, table cell or axis uses `font-variant-numeric: tabular-nums`.

| Token | Size / line-height | Weight | Tracking | Use |
|---|---|---|---|---|
| `text-2xs` | 10.5 / 14 | 500 | +0.08em uppercase | Nav group labels, section labels, chart ticks |
| `text-xs` | 11.5 / 16 | 500–550 | +0.01em | Badges, table headers, KPI labels, meta |
| `text-sm` | 12.5 / 18 | 400–500 | 0 | Secondary copy, buttons, mono IDs |
| `text-base` | 13.5 / 20 | 400 | 0 | Body, table cells (13 px in dense tables) |
| `text-md` | 15 / 22 | 600 | −0.01em | Drawer and modal titles |
| `text-lg` | 18 / 26 | 600 | −0.02em | Stat-strip values, feed status values |
| `text-xl` | 22 / 28 | 600 | −0.02em | Page titles |
| `text-2xl` | 28 / 32 | 600 | −0.03em | KPI values (with a `small` 14 px suffix in `--text-3`) |
| `text-3xl` | 44 / 48 | 600 | −0.03em | Hero figure, at most one per view |

Copy rules: use sentence case everywhere, including badges ("Medium risk", "Requires Admin"). Decision badges read Allow / Redact / Approval / Block / Downgrade. Write numbers as `48,213`, `$2,184.40`, `0.62 ms` and `p95 1.1 ms`. Show placeholders as `⟨PESEL_1⟩`.

---

## 4. Spacing, layout, radii, elevation

**Spacing** follows a 4 px grid: `2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64` (Tailwind `0.5 … 16`).

| Layout metric | Value |
|---|---|
| Sidebar width | 236 px; collapses to a 64 px icon rail below 1180 px |
| Top bar height | 52 px (sticky, `rgba(7,8,10,.86)` + `blur(10px) saturate(140%)`) |
| Content max width | 1680 px, page padding `24px 28px 64px` (16 px gutters on mobile) |
| Grid gap | 12 px (cards), 12-column grid for dashboards |
| Card padding | header `14px 16px 0`, body `12px 16px 16px`, footer `10px 16px` |
| Table row | 38 px dense, 52 px for two-line cells; header 34 px; cell padding `0 10px`, first and last columns 16 px |
| Drawer width | 600 px (decision trace) |
| Modal width | 480 px (520 px for forms) |
| Command palette | 600 px, 14vh from the top |

| Radius | Value | Use |
|---|---|---|
| `xs` | 4 px | Tags, kbd, table chips, heatmap cells |
| `sm` | 6 px | Badges, small buttons (7 px) |
| `md` | 8 px | Buttons, inputs, nav items, segmented thumb (7 px) |
| `lg` | 12 px | Cards, banners, toasts, menus, editor |
| `xl` | 16 px | Modal, command palette |
| `full` | 999 px | Chips, pills, role badges, avatars |

| Elevation | Value |
|---|---|
| `shadow-card` | `inset 0 1px 0 rgba(255,255,255,.035), 0 1px 2px rgba(0,0,0,.40), 0 6px 16px -8px rgba(0,0,0,.50)` |
| `shadow-raised` | `inset 0 1px 0 rgba(255,255,255,.05), 0 1px 2px rgba(0,0,0,.50)` (secondary buttons, active chip) |
| `shadow-pop` | `0 0 0 1px #2A2F37, 0 16px 40px -12px rgba(0,0,0,.80), 0 4px 10px -2px rgba(0,0,0,.50)` (popover, modal, toast, tooltip, cmdk) |
| `shadow-drawer` | `-1px 0 0 #2A2F37, -32px 0 80px -24px rgba(0,0,0,.85)` |
| Overlay | `rgba(3,4,6,.55)` + `blur(2px)` |
| Primary button | `inset 0 1px 0 rgba(255,255,255,.18), 0 1px 2px rgba(0,0,0,.5)` |

---

## 5. Motion

| Token | Duration | Use |
|---|---|---|
| `instant` | 80 ms | Hover colour, row hover |
| `fast` | 140 ms | Buttons, chips, toggles, tooltips |
| `base` | 220 ms | Segmented-control thumb, tabs, dropdowns, switch knob |
| `slow` | 360 ms | Page enter, drawer, modal, banners |
| `slower` | 640 ms | Chart grow, usage-bar fill, number tween |

| Easing | Curve | framer-motion |
|---|---|---|
| `ease-out` (default enter) | `cubic-bezier(0.16, 1, 0.3, 1)` | `ease: [0.16, 1, 0.3, 1]` |
| `ease-in-out` (A↔B moves) | `cubic-bezier(0.65, 0, 0.35, 1)` | `ease: [0.65, 0, 0.35, 1]` |
| `ease-in` (exits) | `cubic-bezier(0.7, 0, 0.84, 0)` | `ease: [0.7, 0, 0.84, 0]` |
| `ease-spring` (toasts, badges) | `cubic-bezier(0.34, 1.56, 0.64, 1)` | `type: "spring", stiffness: 420, damping: 30` |

Named patterns (copy these exactly):

- **Page enter:** opacity 0→1 with y 6→0 over 360 ms expo-out.
- **Drawer:** x 104 %→0 over 360 ms expo-out, overlay fade 360 ms. Trace stages stagger 45 ms each, sliding x −6→0 over 420 ms.
- **Modal:** scale 0.98→1 with y 8→0 over 360 ms, opacity over 220 ms.
- **Toast:** y 14→0 with scale 0.97→1 over 420 ms spring. Exit is x 0→24 with fade over 260 ms ease-in. Toasts auto-dismiss after 5.2 s, shown by a 2 px progress bar along the bottom.
- **Segmented control:** the thumb slides with `transform` and `width` over 220 ms expo-out (framer `layoutId`).
- **New live row:** background flash from `rgba(124,108,255,.14)`, or `rgba(242,85,111,.16)` for blocks, to transparent over 1.6 s.
- **Stream item enter:** y −10→0 with a flash over 700 ms.
- **Ticker:** JS-driven at 45 px/s and paused on hover. New events are appended without a jump (no CSS marquee).
- **Charts:** bars grow `scaleY` from the baseline over 640 ms. Lines draw with `stroke-dashoffset` over 1.1 s. Heatmap cells fade in with a stagger of 30 ms per row and 20 ms per column. The ring gauge uses `stroke-dashoffset` over 1.1 s.
- **Number tween:** 600 ms ease-out-quart, with progress clamped to [0, 1].
- **Live dot:** a solid 8 px dot with a 1.5 px ring that scales 0.6→1.9 and fades out every 1.8 s. This is the only looping animation besides the ticker.
- **Approval resolve:** fade and x +16 over the first 40 %, then collapse height over 420 ms.
- **Reduced motion:** all durations become 1 ms (`prefers-reduced-motion: reduce`).

```ts
// motion.ts — shared framer-motion presets
export const ease = { out: [0.16, 1, 0.3, 1], inOut: [0.65, 0, 0.35, 1], in: [0.7, 0, 0.84, 0] } as const;
export const dur = { instant: 0.08, fast: 0.14, base: 0.22, slow: 0.36, slower: 0.64 } as const;
export const pageEnter = { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: { duration: dur.slow, ease: ease.out } };
export const drawer = { initial: { x: "104%" }, animate: { x: 0 }, exit: { x: "104%" }, transition: { duration: dur.slow, ease: ease.out } };
export const toast = { initial: { opacity: 0, y: 14, scale: 0.97 }, animate: { opacity: 1, y: 0, scale: 1 }, exit: { opacity: 0, x: 24, transition: { duration: 0.26, ease: ease.in } }, transition: { type: "spring", stiffness: 420, damping: 30 } };
export const stagger = (i: number, step = 0.045) => ({ initial: { opacity: 0, x: -6 }, animate: { opacity: 1, x: 0 }, transition: { delay: i * step, duration: 0.42, ease: ease.out } });
```

---

## 6. Components (behavioural spec)

| Component | Spec |
|---|---|
| **Button** | Height 30 (sm 26, lg 36). Radius 8 (sm 7). 12.5 px weight 500, gap 6, icon 14. Variants: `primary` (iris), `secondary` (surface-2 + border + raised shadow), `ghost` (text-2, surface-2 on hover), `danger` (`#C43350`), `danger-ghost` (block subtle + border), `success` (`#178A57`). Active state is `translateY(.5px) scale(.985)`. Loading shows a 14 px spinner and "Applying…". |
| **Decision badge** | Height 20 (lg 24). Radius 6, 11.5 px weight 550. A 6 × 6 dot with 2 px radius in the current colour, a 1 px border in the decision border colour and a subtle background. |
| **Role badge** | A pill of height 20 with the Owner, Admin, Member, Agent or Self colours (see §2.5) and an optional 11 px shield or user icon. The label reads "Requires Admin" or "Self-approve". |
| **Tag** | Height 20, radius 4, mono 11 px, `--surface-2` with a border. Used for surfaces (`tool.call`), tools and models. |
| **Chip (filter)** | Pill of height 28 with a coloured 8 px square swatch and a mono count. When on: `--surface-3` + border-strong + raised shadow. |
| **Segmented control** | Track `--surface-1` with a border, radius 9, padding 2. Buttons are 24 px high (lg 28). The thumb is `--surface-4` with an inset highlight and a ring, and it slides. The top-bar "View as" switch (Owner / Admin / Member) uses this component and stays in sync with the switcher on the Approvals page. |
| **Card** | `--surface-1`, 1 px border, radius 12, `shadow-card`. Title is 13 px/550 with an optional 12 px muted subtitle, and actions sit on the right. |
| **KPI tile** | Label (12 px with a 14 px icon) → value (28 px/600, tabular) → foot (11.5 px, delta pill) → 28 px sparkline (1.75 px line + 10 % wash). The delta colour follows direction combined with whether up is good. |
| **Usage / bullet bar** | Height 8 (thin 6, thick 10), radius 4, track `--surface-3`. Markers are 2 px ticks at 80 % and 100 %. The fill colour follows state (§2.5) and animates width over 640 ms. |
| **Table** | Sticky 34 px header in 11.5 px `--text-3`. Rows are 38 px with `--border-subtle` dividers and hover `rgba(255,255,255,.018)`. A selected row uses `--accent-subtle`. Numbers are right-aligned and tabular. IDs and models use mono at 11.5 px. |
| **Decision trace drawer** | Header: decision badge + surface tag + tool tag + time + close. Below it: the title (mono for tool calls), then agent · team · model (requested → used). A reason box tinted by the decision shows the reason, control ID, policy version, feed serial and strictness. Next come 4 mini stats (overhead, upstream, cost, tokens or avoided). The **pipeline** is a grid `22px | control | score-vs-threshold | latency waterfall`. The score bar is 6 px with a 2 px white threshold tick, and the waterfall is 8 px bars on a 2 px track. Stages skipped by short-circuit render muted with a dashed-circle icon. The drawer ends with response headers (`X-Aegis-*`, `Server-Timing`), the audit-record JSON and a hash-chain badge. |
| **Redaction diff** | Two panes with a 30 px round arrow badge on the divider. Source spans are underlined and wire placeholders are chips (see §2.5). Hovering any span highlights its counterpart in all panes and in the entity table. A destination toggle switches between external and on-prem zones. |
| **Approval item** | 32 px icon tile, title 13 px/500, meta row (role badge, requester, countdown, two-person progress 2 × 22 × 4 px). A locked item shows a 14 px lock in `--text-4`. The selected item gets a 2 px iris left bar. The detail view shows requested action (mono code block with +/− diff colouring), justification (quote with a 2 px left rule), routing chain (steps joined by chevrons), context key-value grid and risk signals. When the viewer's role cannot approve, the footer shows a dashed lock note naming the eligible approvers in place of active buttons. |
| **Policy editor** | Monaco in the real app. Theme: background `#0A0B0E`, gutter `#090A0C`, line numbers `--text-4`, 12.5/20 mono, YAML colours from §2.5. Gutter marks: changed lines get a 2 px amber right rule and the error line a red background. The status bar is 28 px mono 11 px. Beside the editor: strictness segment, quick edits, diff (+ green 8 % / − red 8 % rows, hunk headers in iris), apply pipeline (parse → schema → compile → self-test → atomic swap with per-step ms), and version history. Success toast: "Policy v15 hot-reloaded in 184 ms". Failure toast: "Rejected — still on v14 · line 13:15 …". |
| **Banner** | Radius 12, a tinted gradient over `--surface-1`, a 28 px icon tile, title 600, description 12.5 px and a mono meta line. Variants: `block` (tamper rejected, control disabled), `warn` and `info`. |
| **Toast** | 380 px wide, stacking upward at bottom-right with at most 4. Each has a 26 px icon tile coloured by type (success, error, warn, info), a title, a description and a mono meta line (audit event name), plus a progress bar. |
| **Kill switch** | Top-bar `danger-ghost` button. Engaging it opens a modal with radio rows (agent, team or global). While engaged, a 34 px red bar sits under the top bar with Release (Owner only). |
| **Tooltip** | `--surface-3`, radius 10, `shadow-pop`, 12 px. The title is 600 and each row has a swatch, a label and a right-aligned value. |

---

## 7. Data-viz rules (Recharts mapping)

- Bars are at most 24 px thick with `radius={[4,4,0,0]}` on the top segment only. Stacked segments sit 2 px apart, using `stroke="#0E1013" strokeWidth={2}` or a manual gap.
- Lines are `strokeWidth={2}` with round joins. Area fills use `fillOpacity={0.10}`. End dots are r = 4 with a 2 px `#0E1013` stroke, and active dots use the same style.
- Grid: `<CartesianGrid stroke="#1A1E24" vertical={false} />`, solid, never dashed. Ticks use `fill:#7A808C; fontSize:10.5`, with no axis lines on the y axis.
- Always include a legend when there are 2 or more series. Direct end labels ("p95 1.2 ms") are allowed when there are 4 or fewer series, and the text uses text tokens, never the series colour.
- Hover is on by default: a crosshair line (`#4B5160`) with dots on line charts, and a whole-band hit area that dims the other columns to 55 % on bar charts.
- Never use a dual axis. Forecasts are dashed `4 4` in `--text-3`. Hard caps are 1 px solid `#C43350` with a left-aligned label.
- Version annotations are vertical iris lines with a 3 px dot and a mono label such as "policy v13" or "v14 · feed #43". The label flips left near the right edge, and staggered rows keep labels from colliding.

---

## 8. Tailwind config

### Tailwind v4 (CSS-first, recommended with current shadcn)

```css
/* src/index.css */
@import "tailwindcss";
@import "tw-animate-css";
@custom-variant dark (&:is(.dark *));

:root, .dark {
  --radius: 0.75rem;
  --background: #07080A;  --foreground: #ECEEF1;
  --card: #0E1013;        --card-foreground: #ECEEF1;
  --popover: #191C21;     --popover-foreground: #ECEEF1;
  --primary: #6D5DFC;     --primary-foreground: #FFFFFF;
  --secondary: #13161A;   --secondary-foreground: #ECEEF1;
  --muted: #13161A;       --muted-foreground: #7A808C;
  --accent: #20242A;      --accent-foreground: #ECEEF1;
  --destructive: #C43350; --destructive-foreground: #FFFFFF;
  --border: #1E2228;      --input: #1E2228;  --ring: #7C6CFF;
  --chart-1: #3987E5; --chart-2: #D95926; --chart-3: #199E70; --chart-4: #C98500; --chart-5: #D55181;
  --sidebar: #0A0B0E; --sidebar-foreground: #A2A8B3; --sidebar-primary: #6D5DFC; --sidebar-primary-foreground: #FFFFFF;
  --sidebar-accent: #13161A; --sidebar-accent-foreground: #ECEEF1; --sidebar-border: #15181C; --sidebar-ring: #7C6CFF;
  /* Aegis extensions */
  --surface-1: #0E1013; --surface-2: #13161A; --surface-3: #191C21; --surface-4: #20242A;
  --border-subtle: #15181C; --border-strong: #2A2F37;
  --text-1: #ECEEF1; --text-2: #A2A8B3; --text-3: #7A808C; --text-4: #4B5160;
  --accent-fg: #9A8CFF;
  --allow: #3CCB7F; --redact: #5BA4F5; --approval: #E8A93A; --block: #F2556F; --downgrade: #F08A4B; --neutral: #8C93A0;
  --chart-allow: #1E9F68; --chart-redact: #3987E5; --chart-approval: #C98500; --chart-block: #E5446D;
}

@theme inline {
  --font-sans: "Geist", "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono", "JetBrains Mono", ui-monospace, monospace;
  --color-background: var(--background); --color-foreground: var(--foreground);
  --color-card: var(--card); --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover); --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary); --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary); --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted); --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent); --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive); --color-border: var(--border); --color-input: var(--input); --color-ring: var(--ring);
  --color-chart-1: var(--chart-1); --color-chart-2: var(--chart-2); --color-chart-3: var(--chart-3); --color-chart-4: var(--chart-4); --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar); --color-sidebar-foreground: var(--sidebar-foreground); --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground); --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground); --color-sidebar-border: var(--sidebar-border); --color-sidebar-ring: var(--sidebar-ring);
  --color-surface-1: var(--surface-1); --color-surface-2: var(--surface-2); --color-surface-3: var(--surface-3); --color-surface-4: var(--surface-4);
  --color-border-subtle: var(--border-subtle); --color-border-strong: var(--border-strong);
  --color-text-1: var(--text-1); --color-text-2: var(--text-2); --color-text-3: var(--text-3); --color-text-4: var(--text-4);
  --color-accent-fg: var(--accent-fg);
  --color-allow: var(--allow); --color-redact: var(--redact); --color-approval: var(--approval); --color-block: var(--block); --color-downgrade: var(--downgrade); --color-neutral: var(--neutral);
  --color-chart-allow: var(--chart-allow); --color-chart-redact: var(--chart-redact); --color-chart-approval: var(--chart-approval); --color-chart-block: var(--chart-block);
  --radius-xs: 4px; --radius-sm: 6px; --radius-md: 8px; --radius-lg: 12px; --radius-xl: 16px;
  --text-2xs: 10.5px; --text-2xs--line-height: 14px;
  --text-xs: 11.5px;  --text-xs--line-height: 16px;
  --text-sm: 12.5px;  --text-sm--line-height: 18px;
  --text-base: 13.5px; --text-base--line-height: 20px;
  --text-md: 15px;    --text-md--line-height: 22px;
  --text-lg: 18px;    --text-lg--line-height: 26px;
  --text-xl: 22px;    --text-xl--line-height: 28px;
  --text-2xl: 28px;   --text-2xl--line-height: 32px;
  --text-3xl: 44px;   --text-3xl--line-height: 48px;
  --shadow-card: inset 0 1px 0 0 rgba(255,255,255,.035), 0 1px 2px 0 rgba(0,0,0,.40), 0 6px 16px -8px rgba(0,0,0,.50);
  --shadow-raised: inset 0 1px 0 0 rgba(255,255,255,.05), 0 1px 2px 0 rgba(0,0,0,.50);
  --shadow-pop: 0 0 0 1px #2A2F37, 0 16px 40px -12px rgba(0,0,0,.80), 0 4px 10px -2px rgba(0,0,0,.50);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1); --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1); --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
}

@layer base {
  html { color-scheme: dark; }
  body { @apply bg-background text-foreground font-sans antialiased; font-size: 13.5px; line-height: 20px; font-feature-settings: "ss01", "cv11"; }
  * { @apply border-border; }
  :focus-visible { outline: none; box-shadow: 0 0 0 2px var(--background), 0 0 0 4px rgba(124,108,255,.65); }
}
```

Add `class="dark"` to `<html>`. The app is dark-only, so `:root` and `.dark` intentionally share the same values. Override the `rounded-xl` on shadcn's `Card` with `rounded-lg` to get 12 px.

### Tailwind v3 (`tailwind.config.ts` + HSL variables)

```ts
import type { Config } from "tailwindcss";
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Geist", "Inter", "ui-sans-serif", "system-ui", "sans-serif"], mono: ["Geist Mono", "JetBrains Mono", "ui-monospace", "monospace"] },
      fontSize: { "2xs": ["10.5px", "14px"], xs: ["11.5px", "16px"], sm: ["12.5px", "18px"], base: ["13.5px", "20px"], md: ["15px", "22px"], lg: ["18px", "26px"], xl: ["22px", "28px"], "2xl": ["28px", "32px"], "3xl": ["44px", "48px"] },
      colors: {
        border: "hsl(var(--border))", input: "hsl(var(--input))", ring: "hsl(var(--ring))",
        background: "hsl(var(--background))", foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))", hover: "#7B6CFF", press: "#5E4FE6" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))", fg: "#9A8CFF" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        surface: { 1: "#0E1013", 2: "#13161A", 3: "#191C21", 4: "#20242A" },
        "border-subtle": "#15181C", "border-strong": "#2A2F37",
        text: { 1: "#ECEEF1", 2: "#A2A8B3", 3: "#7A808C", 4: "#4B5160" },
        allow: "#3CCB7F", redact: "#5BA4F5", approval: "#E8A93A", block: "#F2556F", downgrade: "#F08A4B", neutral: "#8C93A0",
        chart: { 1: "#3987E5", 2: "#D95926", 3: "#199E70", 4: "#C98500", 5: "#D55181", allow: "#1E9F68", redact: "#3987E5", approval: "#C98500", block: "#E5446D" },
      },
      borderRadius: { xs: "4px", sm: "6px", md: "8px", lg: "12px", xl: "16px" },
      boxShadow: {
        card: "inset 0 1px 0 0 rgba(255,255,255,.035), 0 1px 2px 0 rgba(0,0,0,.40), 0 6px 16px -8px rgba(0,0,0,.50)",
        raised: "inset 0 1px 0 0 rgba(255,255,255,.05), 0 1px 2px 0 rgba(0,0,0,.50)",
        pop: "0 0 0 1px #2A2F37, 0 16px 40px -12px rgba(0,0,0,.80), 0 4px 10px -2px rgba(0,0,0,.50)",
        drawer: "-1px 0 0 0 #2A2F37, -32px 0 80px -24px rgba(0,0,0,.85)",
      },
      transitionTimingFunction: { out: "cubic-bezier(0.16,1,0.3,1)", "in-out": "cubic-bezier(0.65,0,0.35,1)", spring: "cubic-bezier(0.34,1.56,0.64,1)" },
      transitionDuration: { instant: "80ms", fast: "140ms", base: "220ms", slow: "360ms", slower: "640ms" },
      keyframes: {
        "row-in": { "0%": { backgroundColor: "rgba(124,108,255,.14)" }, "100%": { backgroundColor: "transparent" } },
        ping: { "0%": { transform: "scale(.6)", opacity: ".9" }, "100%": { transform: "scale(1.9)", opacity: "0" } },
        "page-in": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { "row-in": "row-in 1.6s cubic-bezier(0.16,1,0.3,1)", ping: "ping 1.8s cubic-bezier(0.16,1,0.3,1) infinite", "page-in": "page-in 360ms cubic-bezier(0.16,1,0.3,1)" },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
```

```css
/* shadcn theme variables (Tailwind v3 / HSL triplets) — dark only */
@layer base {
  :root, .dark {
    --background: 220 17.6% 3.3%;      /* #07080A */
    --foreground: 216 15.2% 93.5%;     /* #ECEEF1 */
    --card: 216 15.2% 6.5%;            /* #0E1013 */
    --card-foreground: 216 15.2% 93.5%;
    --popover: 218 13.8% 11.4%;        /* #191C21 */
    --popover-foreground: 216 15.2% 93.5%;
    --primary: 246 96.4% 67.6%;        /* #6D5DFC */
    --primary-foreground: 0 0% 100%;
    --secondary: 214 15.6% 8.8%;       /* #13161A */
    --secondary-foreground: 216 15.2% 93.5%;
    --muted: 214 15.6% 8.8%;           /* #13161A */
    --muted-foreground: 220 7.3% 51.4%;/* #7A808C */
    --accent: 216 13.5% 14.5%;         /* #20242A (hover bg) */
    --accent-foreground: 216 15.2% 93.5%;
    --destructive: 348 58.7% 48.4%;    /* #C43350 */
    --destructive-foreground: 0 0% 100%;
    --border: 216 14.3% 13.7%;         /* #1E2228 */
    --input: 216 14.3% 13.7%;
    --ring: 247 100% 71.2%;            /* #7C6CFF */
    --chart-1: 213 76.8% 56.1%;        /* #3987E5 */
    --chart-2: 17 70.2% 50%;           /* #D95926 */
    --chart-3: 159 72.7% 35.9%;        /* #199E70 */
    --chart-4: 40 100% 39.4%;          /* #C98500 */
    --chart-5: 338 61.1% 57.6%;        /* #D55181 */
    --radius: 0.75rem;
  }
}
```

---

## 9. Icons

The real app uses `lucide-react` at 16 px (14 px in buttons and 13 px in dense metadata) with stroke 1.75. Every prototype icon is a Lucide glyph.

| Where | Lucide name |
|---|---|
| Nav | `Gauge` (Command Center), `Activity` (Live), `EyeOff` (Redaction), `Inbox` (Approvals), `Wallet` (Budgets), `FileCode` (Policy), `Radar` (Threat Feed), `Users` (Org) |
| Decisions | `ShieldCheck`, `EyeOff`, `Clock`, `Ban`, `ArrowDown` |
| Actions | `Power` (kill switch), `Zap` (simulate, hot reload), `Download`, `Upload`, `Send`, `Undo2`, `RefreshCw`, `Copy`, `Search`, `Command`, `SlidersHorizontal`, `Plus`, `Lock`, `ShieldOff` |
| Objects | `Bot` (agent avatar, 7 px radius tile), `Database`, `Globe`, `CreditCard`, `Cpu`, `Server`, `Hash`, `GitCommitHorizontal`, `Key`, `Sparkles` |

The logo is a shield outline containing an "A" monogram, white on the iris gradient in a 28 px tile with 8 px radius.

---

## 10. Screen inventory, mapped to components

| Route | Key blocks |
|---|---|
| `#/overview` Command Center | 6 KPI tiles (requests, blocked, redacted, spend vs budget with forecast, cost avoided, posture) · Bloomberg-style live ticker · stacked "Decisions per hour" with version annotations · live decision stream · team spend bullets · top controls bars · system status + posture ring · gateway overhead p50/p95 · agent × category heatmap |
| `#/live` Live decisions | Search, decision chips with counts, surface and agent selects · streaming table (new rows flash) · Simulate menu (preset attacks) · Export menu (JSONL, CSV, OCSF) · row → **decision trace drawer** |
| `#/redaction` | Sample switcher · destination zone toggle · stat strip · original ↔ wire panes · model-returned ↔ rehydrated panes · entity table with HMAC fingerprints · stripped metadata |
| `#/approvals` | "View as" role switch · tabs (Pending / You can approve / History) · inbox list (role badge, countdown, two-person progress, lock) · detail (payload diff, justification, routing chain, context, signals, approve/deny or lock note) |
| `#/budgets` | Org spend line (actual, forecast, hard cap, "cap hit" annotation) · runaway ladder · org → team → agent tree with bullet bars and "Request increase" modal that shows live approver routing |
| `#/policy` | YAML editor (highlight, gutter change marks, error line) · strictness segment · quick edits · live diff with semantic summary · apply pipeline · version history · disabled-control banner |
| `#/feed` | Tamper-rejected banner · status strip (serial, Ed25519, last update, expiry, counts) · signatures table · update pipeline · feed event timeline · Simulate publish / tamper |
| `#/org` | Org hero · Members / Agents / Approval policies / Roles & permissions matrix |

Fake data for the Acme Capital org lives in `prototype/assets/data.js`. It includes members, agents, teams, budgets, approvals, signatures, the policy YAML and redaction samples. Its shapes loosely follow `aicl.audit/1` (research 04 §4.3), so implementers can reuse it for fixtures and Storybook.
