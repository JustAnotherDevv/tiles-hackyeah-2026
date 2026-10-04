"""End-to-end DLP leak leg (plan 19 EVAL-10).

PII fixtures (positives EN/PL, adversarial, holdout) + runtime secrets go through `model.request`
toward a remote model. A gold value *leaks* when it is still present in the text that would
actually leave (`verdict.segments` after redaction): verbatim, normalized (case/whitespace/
punctuation-insensitive) or, for numeric identifiers with >= 6 digits, as a digit subsequence.
A blocked request leaks nothing. Hard negatives measure over-block / intervention.
Re-implements the leak definition of staging/pii/evaluate.py on the real pipeline output.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from tests.corpora.loader import CorpusRow, PiiRow, load_pii
from tests.corpora.secrets_gen import generate as gen_secrets
from tests.corpora.secrets_gen import secret_value
from tests.eval.metrics import wilson
from tests.eval.scoring import CaseResult

POSITIVE_FILES = ("positives_en", "positives_pl", "adversarial", "holdout")
NEGATIVE_FILES = ("hard_negatives",)
_NORM = re.compile(r"[\W_]+", re.UNICODE)
_NONDIGIT = re.compile(r"\D+")
MIN_DIGITS = 6


def _norm(s: str) -> str:
    return _NORM.sub("", s).lower()


def leaked(value: str, out_text: str) -> bool:
    if not value:
        return False
    if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", out_text):
        return True
    nv = _norm(value)
    if len(nv) >= MIN_DIGITS and nv in _norm(out_text):
        return True
    dv = _NONDIGIT.sub("", value)
    return len(dv) >= MIN_DIGITS and len(dv) >= 0.6 * len(nv) and dv in _NONDIGIT.sub("", out_text)


def to_rows(pii: list[PiiRow], secrets: list[CorpusRow]) -> tuple[list[CorpusRow], dict[str, list[dict]]]:
    """PII fixtures -> CorpusRows (attack = must protect, benign = hard negative) + gold map."""
    rows: list[CorpusRow] = []
    gold: dict[str, list[dict[str, Any]]] = {}
    for p in pii:
        name = Path(p.file).stem
        neg = name in NEGATIVE_FILES or p.expect == "allow"
        lang = p.lang if p.lang in {"en", "pl", "de", "uk", "ru"} else "en"
        rows.append(CorpusRow(
            id=f"PII-{p.id}", text=p.text, label="benign" if neg else "attack",
            category=f"pii.{name}", lang=lang, source="aegis-generated (pii fixtures)",
            licence="Aegis-original", expected_action="allow" if neg else "redact",
            file=p.file, subset="pii",
        ))
        gold[f"PII-{p.id}"] = [] if neg else [
            {"type": e.get("type"), "value": e.get("value")} for e in p.entities if e.get("value")
        ]
    for s in secrets:
        rows.append(s)
        gold[s.id] = [{"type": s.category.split(".", 1)[-1].upper(), "value": secret_value(s)}]
    return rows, gold


def load_dlp_rows(n_secrets: int = 40) -> tuple[list[CorpusRow], dict[str, list[dict]]]:
    pii = load_pii(POSITIVE_FILES + NEGATIVE_FILES)
    return to_rows(pii, gen_secrets(n_secrets))


def score(results: list[CaseResult], gold: dict[str, list[dict]], profile: str, mode: str) -> dict[str, Any]:
    ent_tot: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # type -> [protected, n]
    lang_tot: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    file_tot: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows_leaky = rows_pos = 0
    neg_n = neg_ob = neg_itv = 0
    errors = 0
    leaks: list[dict[str, Any]] = []
    for r in results:
        if r.error is not None:
            errors += 1
            continue
        if r.label == "benign":
            neg_n += 1
            neg_ob += int(r.over_block)
            neg_itv += int(r.intervened)
            continue
        ents = gold.get(r.id) or []
        if not ents:
            continue
        rows_pos += 1
        blocked = r.action in {"block", "require_approval"}
        out_text = "\n".join(r.segments_out or []) if not blocked else ""
        any_leak = False
        for e in ents:
            lk = (not blocked) and leaked(str(e["value"]), out_text)
            t = str(e["type"])
            ent_tot[t][1] += 1
            ent_tot[t][0] += int(not lk)
            lang_tot[r.lang][1] += 1
            lang_tot[r.lang][0] += int(not lk)
            file_tot[r.category][1] += 1
            file_tot[r.category][0] += int(not lk)
            if lk:
                any_leak = True
                if len(leaks) < 20:
                    leaks.append({"id": r.id, "entity": t, "lang": r.lang, "action": r.action,
                                  "preview": r.preview})
        rows_leaky += int(any_leak)
    ent_n = sum(v[1] for v in ent_tot.values())
    ent_leak = sum(v[1] - v[0] for v in ent_tot.values())

    def block(d: dict[str, list[int]]) -> dict[str, Any]:
        return {k: {"protected": p, "n": n, "protected_rate": round(p / n, 4) if n else None,
                    "ci95": wilson(p, n)} for k, (p, n) in sorted(d.items())}

    return {
        "profile": profile,
        "mode": mode,
        "entities": ent_n,
        "leaked_entities": ent_leak,
        "leak_rate": round(ent_leak / ent_n, 4) if ent_n else None,
        "leak_ci95": wilson(ent_leak, ent_n),
        "rows": rows_pos,
        "rows_with_leak": rows_leaky,
        "row_leak_rate": round(rows_leaky / rows_pos, 4) if rows_pos else None,
        "by_entity": block(ent_tot),
        "by_lang": block(lang_tot),
        "by_file": block(file_tot),
        "hard_negatives": {"n": neg_n, "over_block": neg_ob, "fpr": round(neg_ob / neg_n, 4) if neg_n else None,
                           "ci95": wilson(neg_ob, neg_n), "intervened": neg_itv,
                           "intervention_rate": round(neg_itv / neg_n, 4) if neg_n else None},
        "errors": errors,
        "leaks": leaks,
    }


def detector_metrics_summary(reports_dir: Path) -> dict[str, Any] | None:
    """Embed redaction-engine's reports/dlp-metrics.json (detector P/R) if present."""
    p = reports_dir / "dlp-metrics.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    keep = {k: data[k] for k in ("generated_at", "overall", "micro", "macro", "summary", "by_entity", "precision",
                                  "recall", "f1") if k in data}
    keep["source_file"] = _rel(p)
    return keep or {"source_file": _rel(p)}


def _rel(p: Path) -> str:
    """Repo-relative path (public reports must not carry local absolute paths)."""
    root = Path(__file__).resolve().parents[2]
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.name


__all__ = ["detector_metrics_summary", "leaked", "load_dlp_rows", "score", "to_rows"]
