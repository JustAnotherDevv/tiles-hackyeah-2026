"""SEM-02: deterministic heuristic scorer (EN + PL)."""

from __future__ import annotations

import pytest
from semtest_helpers import BENIGN_HARD, FINANCE_BENIGN, INJECTIONS, SAFE_SCARY, UNSAFE

from aegis.semantic import heuristic as h


@pytest.mark.parametrize("text", INJECTIONS)
def test_injections_score_high(text):
    r = h.injection(text)
    assert r.score >= 0.8, (text, r)
    assert r.model == "heuristic"


@pytest.mark.parametrize("text", BENIGN_HARD + FINANCE_BENIGN)
def test_benign_injection_low(text):
    assert h.injection(text).score < 0.5, text


@pytest.mark.parametrize("text", UNSAFE)
def test_unsafe_moderation(text):
    r = h.moderation(text)
    assert r.label == "Unsafe" and r.score >= 0.8
    assert "Violent" in r.categories


@pytest.mark.parametrize("text", SAFE_SCARY + FINANCE_BENIGN)
def test_safe_moderation(text):
    r = h.moderation(text)
    assert r.score < 0.5, (text, r)


def test_hard_negatives_below_point_three():
    assert h.injection("Ignore the typos in my previous message").score < 0.3
    assert h.injection("Explain what a prompt injection attack is").score < 0.3


def test_embeddings_deterministic_and_normalised():
    a = h.embed(["Summarise the quarterly report", "Podsumuj raport kwartalny"])
    b = h.embed(["Summarise the quarterly report", "Podsumuj raport kwartalny"])
    assert a == b
    assert len(a[0]) == 384
    assert abs(h.cosine(a[0], a[0]) - 1.0) < 1e-6
    assert abs(sum(x * x for x in a[0]) - 1.0) < 1e-6


def test_similarity_on_vs_off_topic():
    purpose = ["market data, stock prices, positions, portfolio risk"]
    on = h.similarity("Show portfolio risk and positions for the desk", purpose)
    off = h.similarity("Write a sonnet about autumn leaves", purpose)
    assert on.score > off.score


def test_judge_overlap():
    rule = "The text must not reveal unannounced mergers or acquisitions"
    hit = h.judge(rule, "We will announce the acquisition and merger of Kowalski Logistics")
    miss = h.judge(rule, "What is the weather in Krakow?")
    assert hit.score > miss.score
    assert miss.score < 0.7


def test_fold_with_map_offsets():
    text = "Notatka: Projekt Sokół!"
    folded, idx = h.fold_with_map(text)
    i = folded.index("projekt sokol")
    a, b = h.to_original(idx, i, i + len("projekt sokol"))
    assert text[a:b] == "Projekt Sokół"
