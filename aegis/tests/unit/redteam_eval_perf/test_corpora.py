from __future__ import annotations

from collections import Counter

from tests.corpora.loader import (
    HERE,
    load_manifest,
    load_pii,
    load_rows,
    secret_hits,
    verify_manifest,
)
from tests.corpora.secrets_gen import generate
from tests.corpora.tools.verify import LICENCE_TEXTS, committed_files


def test_counts_and_unique_ids():
    rows = load_rows()
    assert len(rows) == 1194
    c = Counter(r.label for r in rows)
    assert c == {"attack": 684, "benign": 510}
    assert len({r.id for r in rows}) == len(rows)


def test_counts_match_manifest_and_sha():
    assert verify_manifest() == []
    man = load_manifest()
    assert man["totals"]["rows"] == 1194
    assert man["totals"]["attack"] == 684


def test_every_licence_has_text():
    for lic in {r.licence for r in load_rows()}:
        assert lic in LICENCE_TEXTS, lic
        for f in LICENCE_TEXTS[lic]:
            assert (HERE / "licenses" / f).exists(), f


def test_no_secret_shaped_strings_committed():
    for rel in committed_files():
        text = (HERE / rel).read_text(encoding="utf-8")
        assert not secret_hits(text), rel


def test_pii_rows_have_gold_entities():
    pii = load_pii()
    assert len(pii) > 400
    pos = [p for p in pii if p.expect != "allow"]
    assert pos and all(e.get("value") for p in pos for e in p.entities)


def test_secrets_generated_at_runtime_are_secret_shaped_and_deterministic():
    a, b = generate(16), generate(16)
    assert [r.text for r in a] == [r.text for r in b]
    assert sum(bool(secret_hits(r.text)) for r in a) >= 10
    assert {r.subset for r in a} == {"secrets"}


def test_seen_by_tuning_split():
    rows = load_rows()
    held = {r.file for r in rows if not r.seen_by_tuning}
    assert held == {"public/deepset_prompt_injections.jsonl", "public/lakera_gandalf.jsonl",
                    "public/jailbreakbench_behaviors.jsonl", "public/xstest_safe.jsonl"}
