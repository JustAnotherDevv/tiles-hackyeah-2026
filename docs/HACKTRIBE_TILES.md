# HackTribe submission: Tiles (Huawei "Imagine What's Next")

Copy-paste text for the HackTribe entry. The Goldman Sachs submission (Aegis, in `aegis/`) is a separate entry.
This replaces the earlier concept, Aegis Pocket (`docs/HACKTRIBE_POCKET.md`, superseded).

## Title (≤5 words)

**Tiles: A Phone That Adapts** (5 words)

## Team

JustAnotherDevv

> Placeholder. Before submitting, replace this line on HackTribe with each member's real first name, surname and
> email, one per line. Never commit those details to this public repository.

## Links

- Repository: https://github.com/JustAnotherDevv/tiles-hackyeah-2026 (Tiles at the root; build, install and launch
  steps in `README.md`; `aegis/` is the separate Goldman Sachs entry)
- `.hap`: GitHub Release of the repository (debug-signed with the OpenHarmony SDK key, no Huawei ID needed)
- Demo video: (add the link after recording)

## Description (≤500 words)

Word count: run `sed -n '/^```text/,/^```$/p' docs/HACKTRIBE_TILES.md | sed '1d;$d' | wc -w` (whitespace split,
placeholder team line included). On HackTribe, replace `Team: JustAnotherDevv` with each member's real name,
surname and email (about 4 words per member).

```text
Phones are designed for one average person. Halina, 78, squints at tiny icons, misses taps and nearly fell for a "your grandson needs money" call. Zosia, 8, needs fewer, friendlier choices. Michał, with low vision, needs everything read aloud. Daniel, 29, wants Friday's dinner with friends settled. Same phone, four different people.

Tiles is a native HarmonyOS app that reshapes the phone around the person using it. The home screen is a grid of big, colourful tiles. Each tile is a small, live, actionable card: "Pills 8:00, tap when taken", "Call Kasia", "14° and rain, take the umbrella", "Homework: 3 of 5 done", "Dinner Fri 19:30 at Veganda, vote".

Ask Tiles. Type a request ("Remind me to take Euthyrox at 8 every morning", "Dinner Friday with Ola and Kuba, vegan, near Kazimierz, under 80 zł") and the assistant answers with new tiles. This is generative UI: the assistant returns not text but a structured TileSpec (size, colour, content blocks such as checklist, progress, timer, chips and buttons, and actions such as call, remind, speak and vote) that the app renders natively in ArkUI. Today the generator is an on-device, deterministic intent planner for English and Polish (it extracts time, day, person, place, food, budget and medicine). No cloud model, and no personal data leaves the phone; a language model behind guardrails could fill the same schema later.

One app, four homes. A profile switcher regenerates the home for each person: very large, high-contrast tiles with read-aloud and an SOS tile for Halina; a playful homework checklist, focus timer and screen-time meter for Zosia; a voice-first two-column layout for Michał; a dense, colourful grid with plans and commute for Daniel.

It adapts, but asks first. Tiles turns usage signals (missed taps, unused tiles, time of day) into plain suggestions such as "11 missed taps today: make text 40% bigger?". For seniors and kids, every adaptation and every tile the assistant proposes waits for a caregiver or parent to approve it on the Caregiver screen (shown as a "Kasia's phone" simulation in the demo).

Guardian. A scam-shield tile for seniors explains red flags in a suspicious call or SMS ("asks for money", "pressure: right now") and turns the screen into one calm instruction: "This looks like a scam. Hang up. Kasia already knows." In the demo the call is simulated and labelled "Demo call".

Native ArkTS/ArkUI for HarmonyOS (minimum API 20, compiled against API 24), running on the HarmonyOS 6.1 phone emulator. Platform capabilities: Form Kit home-screen widgets (2x2, 2x4, 4x4), Notification Kit pill notifications and caregiver alerts, calls handed to the system dial screen, read-aloud through the system screen reader, vibrator haptics, ArkData persistence, high-contrast text scaling and dark mode.

Themes: Human-Centric Technology (accessibility, seniors, kids, digital wellbeing) with Intelligent Experiences (generative UI, on-device personalisation).

Code and build steps: https://github.com/JustAnotherDevv/tiles-hackyeah-2026 (repository root). AI-assisted development is documented in AI_WORKFLOW.md.

Team: JustAnotherDevv
```

> The platform-capabilities sentence matches README "Platform capabilities used". It deliberately does not claim
> background reminders: `reminderAgentManager` needs an AppGallery entitlement, so the reminder fallback runs only
> while the app is open. It also does not claim a TTS engine; read-aloud goes through the screen reader.

## Demo video script (≤60 s)

Record on the DevEco HarmonyOS 6.1 phone emulator. All people and data are fictional; the Guardian call is
simulated and labelled "Demo call"; say that the assistant is an on-device rule-based generator.

| Time | Screen | Voice-over / caption |
|---|---|---|
| 0-5 s | Onboarding: "Who is this phone for?" with four profiles | "One phone, four very different people. Tiles reshapes the phone around the person using it." |
| 5-13 s | Pick **Senior (Halina)** → home regenerates: huge high-contrast tiles (Pills 8:00, Call Kasia, Weather, Guardian, SOS) | "For Halina, 78: big tiles, high contrast, everything one tap away." |
| 13-18 s | Tap **Pills 8:00** → "Taken"; tap a tile → read aloud | "Tap when taken. Tiles reads every tile aloud." |
| 18-30 s | **Ask Tiles…**: "Remind me to take Euthyrox at 8 every morning" → "Tiles is making…" → new tile springs into the grid; "Ask Kasia to approve" | "Ask in plain words. The assistant answers with a real tile, not text. It runs on the phone." |
| 30-38 s | **Caregiver** screen ("Kasia's phone", simulated): pending tile + "11 missed taps → text 40 % bigger" → Approve → home text grows | "Tiles learns from use, but family approves every change." |
| 38-46 s | **Guardian** demo call: red flags pop in → "This looks like a scam. Hang up. Kasia already knows." | "Guardian spots a scam call and tells her what to do. Demo call, simulated." |
| 46-54 s | Switch to **Kid (Zosia)** then **Everyday (Daniel)**: homework checklist + timer; dinner plan tile with vote buttons | "The same app regenerates for a child, and for a busy 29-year-old planning dinner with friends." |
| 54-60 s | Home-screen **widget** with the next reminder; title card | "Tiles. A phone that adapts. Native HarmonyOS." |
