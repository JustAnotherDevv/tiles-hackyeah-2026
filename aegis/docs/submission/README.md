# Submission kit (HackTribe · Goldman Sachs · AI Control Layer)

**Deadline:** upload by **Sun 4 Oct 10:00** (hard deadline **11:00**; some docs say 23:00, treat 11:00 as
real). Jury from 11:00, finalists 15:00, pitches 16:00. The team leader uploads on HackTribe (Discord login).
Drafts stay editable until the deadline. Phase 1 needs ≥ 50 % of the score to be prize-eligible.

## Files

| File | What | Paste / upload from |
|---|---|---|
| [HACKTRIBE.md](HACKTRIBE.md) | title, ≤ 500-word description + team, checkpoint text, gallery captions, opening instructions, claims-to-verify | `out/HACKTRIBE.md` (rendered with real numbers) |
| [DECK.md](DECK.md) + `deck/deck.html` | 10-slide English deck (copy, speaker notes, criteria map) | `out/Aegis_HackYeah2026_GS_AIControlLayer.pdf` |
| [VIDEO_60S.md](VIDEO_60S.md) | shot list ↔ scene commands, VO, captions, ffmpeg recipe | YouTube Unlisted URL |
| [../demo-script.md](../demo-script.md) | 4:30 live runbook + fallbacks + Q&A prep | finalist pitch |
| [../JUDGES.md](../JUDGES.md) | judge instructions (test suite, playground, live policy edit, feed publish) | linked from the opening instructions |
| `build.py` | `collect` numbers from `reports/` → `numbers.json`; `render` placeholders → `out/`; `--pdf` (headless Chrome); `--check` limits | — |
| `video/cards.html` | title / architecture / end cards for the video | screen-record in Chrome |

## Final pass (DEMO-16, after integration; ~15 min)

```bash
make test && make eval && make bench           # writes reports/*  (owners' commands)
make up                                        # optional: live numbers (audit verify, coverage)
uv run --frozen python docs/submission/build.py collect --url http://127.0.0.1:8787
uv run --frozen python docs/submission/build.py render --pdf --check
mdls -raw -name kMDItemNumberOfPages docs/submission/out/Aegis_HackYeah2026_GS_AIControlLayer.pdf   # 10
uv run --frozen python docs/submission/build.py --check --strict   # fails while any {{TBD}} is unresolved
```

Then: fill team names/emails (`[NAME — EMAIL]` in HACKTRIBE.md, README.md and `deck/deck.html`), the repo
URL (`[PUBLIC REPO URL]`), tick the claims table in HACKTRIBE.md §2, fill the build-status table in
[../architecture.md](../architecture.md#build-status), and copy real screenshots into `docs/assets/screens/`.

## Upload checklist

- [ ] Title ≤ 5 words: "Aegis: Local-First AI Guardrails"
- [ ] Description ≤ 500 words **including** every member's first name, surname and email (`build.py --check`)
- [ ] Every member has a Discord account
- [ ] ≥ 1 image (architecture PNG + 4 screenshots)
- [ ] PDF ≤ 10 slides, English, fonts embedded, readable on a phone
- [ ] Video ≤ 60 s (target 0:58), Unlisted, plays logged out
- [ ] Public repo URL; README quick start works from a clean clone; `reports/` committed; no secrets in history
      (`gitleaks detect`; staging fixtures with secret-shaped strings dropped, `feed_service/state/` ignored)
- [ ] Opening instructions pasted (HACKTRIBE.md §4)
- [ ] Links checked in a private window

## Numbers policy

Every number in the README, deck, description and video must come from `reports/` (or a live API call
recorded by `build.py collect` with source + timestamp in `numbers.json`). Unmeasured values stay visible as
`[TBD: key]`, or are labelled "target". Never "100 % secure", never "compliant".
