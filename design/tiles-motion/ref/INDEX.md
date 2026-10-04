# Direction C "Living Light" — reference renders

Rendered by LL-QA (headless Chrome + CDP) from `../Tiles_Motion_bundle.html?stagedir=C`, clicking each flow button and capturing the **C column** phone (393x852 CSS px, 1x, +12px margin incl. bezel) at fixed ms after click. `*-caregiver.png` = Kasia's caregiver phone shown beside the main phone. `sheet-<flow>.png` = all frames of a flow side by side (quickest to look at). Script: scratchpad/llqa/cdp.py.

Common to all home screens: bg gradient lavender (#EDF1FC) → pink (#F6F0FA) → peach (#FFF3EA); status bar "8:00 · signal/wifi/82/battery" in ink; greeting 26-28px bold ink, sub line muted 15px; tiles = 135° pastel gradients, radius ~26, soft blue-tinted shadow, icon (filled Material Symbol) top-left then title (bold) then muted body; round 44px speaker button (white 35% circle) top-right on read-aloud tiles; Ask dock = dark ink (#1D2140) pill, full width minus 16px gutters, sparkle icon + "Ask Tiles…" + round mic button (lighter ink circle) at right, floats over content near bottom; gesture bar at bottom.

## 1. Onboarding morph (`C-onboarding-*`)
- `start` (0.7 s): chooser. Kicker "TILES · SETUP" (letter-spaced muted), H1 "Who is this phone for?" (~32px), muted paragraph. Four full-width cards radius ~22: Senior (sun gradient, walking icon, "Halina, 78 · big, calm, read aloud", → arrow), Kid (leaf), Low vision (**ink/dark** card, light text, eye-off icon), Everyday (sky). Icon left, title 20px bold, subtitle 14px.
- `mid` (3.6 s): Halina home built. Top: "WHO IS THIS PHONE FOR?" kicker + 4 pill segmented chips (selected = ink fill/white text, others white surface with line border). Greeting "Dzień dobry, Halino", "Monday 5 October · pills at 8:00". 2-col grid: Pills 8:00 (sun, full-width, speaker btn), Call Kasia (leaf), Guardian (mint, "On · 2 calls blocked"), 14° and rain (sky, full-width, speaker), SOS (rose, "Hold 2 s"), Photos (sand), More apps. Ask dock 64px.
- `zosia` (6.8 s): "Hej, Zosia!" — Homework checklist tile (sun, big "3/5 done" numerals, round check circles, struck-through done items), Focus (plum, timer 15:00 with smiling creature face), Call Mum (leaf), Energy today (mint, progress bar dark fill), Ask dock 56px.
- `michal` (9.8 s): "Dzień dobry, Michale" — huge type; Hold to speak (ink tile, full width), Call Ania (leaf), SOS (rose), "14°, rain" (sky), 2 new messages (sun). Dock 72px.
- `end` (13.6 s): "Morning, Daniel" — 4-col dense grid: Tram 18 in 6 min (sky 2x1), Rain 14° (sand), Focus 25:00 (plum), Dinner Fri 19:30 (peach 2x2 with vote chips + dark "Vote" pill + "Change"), Ola, Kuba free (mint), Standup 10:00 (sun), Run 12 km (leaf), Call Ola (rose), Playlist (ink), Photos (sky), 3 unread (plum), 6 412 steps (sand, progress bar). Dock 52px.

## 2. Ask Tiles (`C-ask-*`, Halina)
- `open` (1.6 s): home dimmed by scrim (rgba(29,33,64,.25)); bottom sheet (white ~84% glass, radius ~26 top, grabber) with sparkle + "Ask Tiles" title 20px and round grey close (×) button; two suggestion rows (white cards w/ line border, leading icon: alarm, fork-knife); input row: grey pill input ("Remind…"), round grey mic button, round **accent #4F5BD5** send (↑) button.
- `mid` (4.5 s): sheet shrinks; "••• Tiles is thinking…" accent dots + muted text; input holds full prompt.
- `gen` (8.2 s): sheet closed; new tile "Euthyrox 8:00 / Every morning" (sun) being born over the grid — elevated with stronger shadow, with chips "Taken" (dark pill) + "Later" (tinted pill).
- `end` (10.5 s): new tile slotted at top of grid, Pills 8:00 below; toast pill (ink #1D2140, white text) "Added to Halina's home" above dock.

## 3. Tile interaction (`C-interact-*`, Halina)
- `start`: normal home. `done` (1.5 s): Pills tile flooded green (leaf) with big check-circle + "Taken / 8:02 · Kasia can see it" centred.
- `mid` (4.3 s): full-screen call — dark ink gradient (#1D2140→#2E3466), large sun-gradient avatar "K", "Kasia" 30px, "Calling…", bottom row: mute (translucent circle), red hang-up (danger #C62B4A, 72px), speaker.
- `speak` (8 s): read-aloud card docked above Ask dock: white card with accent wave bars, karaoke text with current word highlighted in accent, round ink stop button.
- `drag` (11.5 s): edit mode — "Done" ink pill top-right, each tile has small dark (×) badge at top-left corner, dragged weather tile lifted with big shadow.
- `end` (13.9 s): back to normal, Taken tile stays green.

## 4. Adaptation (`C-adapt-*`, Halina + Kasia caregiver)
- `sug` (2 s): suggestion card (white surface, radius 22, shadow) above dock: accent kicker "✦ TILES NOTICED", × close, title "11 missed taps today", muted body, buttons "Preview" (ink pill filled) + "Not now" (outline pill).
- `mid` (3.6 s): preview — tiles grown ~40%; card reads "After: text 40% bigger, 14 apps hidden", Before/After segmented control (after = ink filled), "Send to Kasia" (ink w/ send icon) + "Back".
- `sent` (7.5 s): card row "K avatar (accent circle) · Sent to Kasia for approval · accent dot".
- `end` (12.3 s): Halina home with bigger text/tiles, toast "Kasia approved · bigger text, fewer apps". Caregiver (`end-caregiver`): header avatar "H" sun circle, "Mama · Halina", green dot "Phone active · just now", "KASIA" outline chip; "NEEDS YOU" kicker; approval card (white, "✦ APPROVAL · MAMA", title, body, "✓ Approved · 8:04"); "TODAY" list card (rows with tinted round icons: Pills 8:00 — not yet / due, Guardian on · 2 calls blocked / this week, Weather read aloud / 7:40); bottom full-width ink "Call Mama" pill.

## 5. Guardian (`C-guardian-*`)
- `ring` (1.5 s): incoming call screen on LIGHT bg: grey avatar circle, "Unknown number" 21px, "+48 512 ··· 418 · mobile", ok-soft chip "🛡 Guardian on"; bottom: "SCAM RISK" kicker + big green "0%", grey track; "Hang up" (danger pill w/ icon) + "Keep listening" (outline pill).
- `mid` (6 s): transcript bubbles (white cards radius ~16), flag chips (danger-soft bg, danger text, flag icon: "asks for money", "pressure: right now"), chip now "Listening"; risk "76%" in danger red, red bar.
- `scam` (9.3 s): full scam screen: big danger-soft circle with danger shield, H1 "This looks like a scam." 34px centred, "Hang up. Kasia already knows." muted, white flag chips, huge danger "Hang up" button (radius ~22, 76px tall), underlined "Call Kasia instead".
- `end` (12.8 s): home, Guardian tile "On · 3 calls blocked", toast "Guardian blocked the call · Kasia knows". Caregiver `scam-caregiver`: alert card in **rose/danger-soft gradient**: "🛡 GUARDIAN ALERT", "Likely scam call to Mama", body, "Call Mama" (dark maroon dangerInk pill) + "Report" (outline).

## 6. Kid mode (`C-kid-*`, Zosia + caregiver)
- `start`: homework 3/5. `focus` (3.3 s): 4/5 ticked. `mid` (5.8 s): Focus timer counting (14:57); **pending tile** "Spelling game" = dashed-outline translucent tile with lock chip "Waiting for Mum" (ink pill); toast "Asked Mum — new tiles wait for a parent". Caregiver: "ZOSIA ASKS" card in sun gradient: "New tile: Spelling game", quote body, "Allow" (dark brown pill) + "Later" (outline).
- `end` (10 s): Spelling game tile becomes solid rose tile; toast "Mum said yes!"; caregiver card shows "✓ Allowed · 16:12"; bottom "Call Zosia" ink pill.

## 7. Widgets & lock (`C-widgets-*`)
- `mid` (2.2 s): lock screen on wallpaper gradient (#C9D4FF→#F3D4EC→#FFE1CC): giant clock "8:00" (~88px bold ink), "Monday, 5 October"; notification card (white ~85%, radius 22): accent app-icon square "Tiles · now", "Pills 8:00", "Euthyrox 50 µg — tap when taken", "✓ Taken" ink pill + "10 min" outline pill; bottom flashlight + camera round white buttons.
- `taken` (4.2 s): notification collapses to "✓ Taken · 8:02 / Kasia can see it" (grey check circle).
- `end` (9.2 s): "HOME-SCREEN WIDGETS · FORM KIT" on wallpaper: 2x2 "Taken" mint widget with "Done ✓" button; 2x4 row of 4 mini tiles (Call Kasia leaf, Taken mint, 14° rain sky, SOS rose; icon over label, centred); "Senior 4x4 — big buttons": 2x2 grid of big tiles (Call Kasia/Daughter, Taken ✓ 8:02, 14° rain/Umbrella, SOS/Hold 2 s) with icon top-left, 24px bold title.
