from __future__ import annotations

import pytest

from tests.eval.metrics import pct_summary, percentile, stratified_sample, wilson


@pytest.mark.parametrize(("k", "n", "lo", "hi"), [(0, 10, 0.0, 0.278), (10, 10, 0.722, 1.0), (50, 100, 0.404, 0.596)])
def test_wilson_known_values(k, n, lo, hi):
    a, b = wilson(k, n)
    assert a == pytest.approx(lo, abs=1e-3)
    assert b == pytest.approx(hi, abs=1e-3)


def test_wilson_empty():
    assert wilson(0, 0) is None


def test_percentile_linear_interpolation():
    xs = [1, 2, 3, 4, 5]
    assert percentile(xs, 50) == 3
    assert percentile(xs, 95) == pytest.approx(4.8)
    assert percentile([], 50) is None
    assert pct_summary([2.0])["p99"] == 2.0


def test_stratified_sample_is_deterministic_and_covers_strata():
    items = [(c, i) for c in "abcd" for i in range(50)]
    s1 = stratified_sample(items, 40, key=lambda x: (x[0],))
    s2 = stratified_sample(items, 40, key=lambda x: (x[0],))
    assert s1 == s2 and len(s1) == 40
    assert {x[0] for x in s1} == set("abcd")
