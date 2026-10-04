from __future__ import annotations

from tests.bench.servertiming import controls, parse


def test_parse_core_and_controls():
    h = 'aegis;dur=1.25;desc="gateway overhead, incl. parse", ctl;dur=0.8, upstream;dur=12, ctl-DLP-01;dur=0.21, total;dur=13.3'
    t = parse(h)
    assert t["aegis"] == 1.25 and t["ctl"] == 0.8 and t["upstream"] == 12.0 and t["total"] == 13.3
    assert controls(t) == {"DLP-01": 0.21}


def test_parse_empty_and_garbage():
    assert parse(None) == {}
    assert parse("nonsense, x;desc=y") == {}
