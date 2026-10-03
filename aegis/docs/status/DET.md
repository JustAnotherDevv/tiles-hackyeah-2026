# DET — detection quality (status)

## Method
- Split respected: tuning = handwritten/generated/indirect; held-out = deepset, gandalf, JBB, XSTest, secrets_gen.
- New `tests/eval/devscan.py` lists tuning/dev rows one by one and gives held-out results only as per-source counts (no row text), so held-out data can't leak into tuning.
- Scoring note: in `AEGIS_SEMANTIC=off` mode, INJ-02 and INJ-03 decisions are `degraded`. B24 scoring therefore doesn't count them as detections even when they block. Counted detection in deterministic mode comes only from signatures (INJ-01/INJ-04), MCP, ACT, EXE and DLP.

## Change
- `src/aegis/semantic/heuristic.py`: added PL/EN meta-discussion cues (regul*, wykryw*, fraz*, filtr*, regex, signature, rule). "Write a rule that detects the phrase …" is now discounted as a mention, not treated as use.

## Numbers (deterministic, balanced)
| | before | after |
|---|---|---|
| attack, all | 66.7% (483/724) | unchanged |
| held-out attack | 39.2% (143/365) | 39.2% |
| tuning FP | 7/135 (5.2%) | 1/135 (0.7%; remaining = ACT-01 $15 spend) |
| held-out FP | 1/375 | 1/375 (INJ-03 on JBB benign twin) |
Tests: injection_defense + semantic_models + redteam_eval_perf green, ruff clean.

## Not done
- No new signatures. Detection, overall and held-out, is unchanged.
- No semantic-ON run.
- Ad-hoc judge-style check not run.
