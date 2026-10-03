from __future__ import annotations

from tests.corpora.loader import load_rows
from tests.eval.heatmap import ascii_heatmap, build_heatmap
from tests.eval.scoring import CaseResult
from tests.eval.schemas import validate


def fake_results():
    out = []
    for r in load_rows(subsets=["generated"]):
        det = r.label == "attack" and r.get("transform") != "base64"
        out.append(CaseResult(id=r.id, profile="balanced", mode="deterministic", label=r.label, category=r.category,
                              lang=r.lang, surface="model.request", source=r.file, split="tuning",
                              expected_action=r.expected_action, action="block" if det else "allow",
                              primary_control="INJ-01" if det else None, detected=det,
                              transform=r.get("transform"), seed_id=r.get("seed_id")))
    return out


def test_heatmap_shape_and_rates():
    hm = build_heatmap([{"profile": "balanced", "mode": "deterministic", "results": fake_results()},
                        {"profile": "strict", "mode": "deterministic", "results": fake_results()}])
    validate("heatmap", hm)
    assert len(hm["seeds"]) == 20 and len(hm["transforms"]) == 12
    assert len(hm["cells"]) == 20 and all(len(row) == 12 for row in hm["cells"])
    b64 = next(c for c in hm["col_rate"] if c["transform"] == "base64")
    assert b64["rate"] == 0.0
    assert hm["overall"]["n"] == 226
    assert any(c is None for row in hm["cells"] for c in row)  # diacritics n/a on EN seeds
    assert hm["benign"]["n"] == 27 and hm["variants"][0]["profile"] == "strict"
    assert "INJ-EN-01" in ascii_heatmap(hm)
