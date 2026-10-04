"""RED-V03: fixture evaluation gate (626 labelled EN/PL cases + adversarial + hard negatives)."""

from __future__ import annotations

from aegis.redaction import evaluate


def test_fixture_quality_gate() -> None:
    m = evaluate.evaluate()
    assert m["cases"] >= 600
    assert evaluate.check(m) == []
    o = m["overall"]
    assert o["validated_recall"] == 1.0
    assert o["leak_rate"] == 0.0
    assert o["hard_negative_fp_rate"] == 0.0


def test_public_metrics_shape() -> None:
    pub = evaluate.public_metrics(evaluate.evaluate())
    for key in ("generated_at", "cases", "gold", "overall", "latency_ms", "by_entity"):
        assert key in pub
    for key in ("precision", "recall", "f1", "leak_rate", "hard_negative_fp_rate"):
        assert key in pub["overall"]
    row = next(r for r in pub["by_entity"] if r["entity"] == "PAN")
    assert row["data_class"] == "RESTRICTED"
    assert row["recall"] == 1.0
