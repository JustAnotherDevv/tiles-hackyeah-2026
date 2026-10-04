"""Seeded request mix: 80 % benign / 15 % PII-or-secret / 5 % attack (plan 19 §2.9)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

SEED = 20261003
FILLER = ("Quarterly desk review: liquidity remained stable, spreads tightened and the team rebalanced the "
          "portfolio toward short-duration bonds ahead of the rate decision. ")


@dataclass
class MixItem:
    kind: str  # benign | pii | attack
    text: str


def build_mix(n: int = 400, seed: int = SEED, *, pad_to_bytes: int | None = None) -> list[MixItem]:
    from tests.corpora.loader import load_pii, load_rows
    from tests.corpora.secrets_gen import generate

    rng = random.Random(seed)
    rows = load_rows(subsets=["public", "handwritten"])
    benign = [r.text for r in rows if r.label == "benign" and r.surface == "user_prompt"
              and (r.file.endswith(("xstest_safe.jsonl", "finance_benign.jsonl", "jailbreakbench_behaviors.jsonl")))]
    attacks = [r.text for r in rows if r.label == "attack" and r.surface == "user_prompt"
               and r.file.endswith(("deepset_prompt_injections.jsonl", "lakera_gandalf.jsonl"))]
    pii = [p.text for p in load_pii(("positives_en", "positives_pl"))] + [s.text for s in generate(40, seed)]
    items: list[MixItem] = []
    for _ in range(n):
        x = rng.random()
        if x < 0.80:
            items.append(MixItem("benign", rng.choice(benign)))
        elif x < 0.95:
            items.append(MixItem("pii", rng.choice(pii)))
        else:
            items.append(MixItem("attack", rng.choice(attacks)))
    if pad_to_bytes:
        for it in items:
            if len(it.text.encode()) < pad_to_bytes:
                reps = (pad_to_bytes - len(it.text.encode())) // len(FILLER) + 1
                it.text = (it.text + "\n\n" + FILLER * reps)[:pad_to_bytes]
    return items


def guard_body(text: str, session: str, *, dry_run: bool = False) -> dict[str, Any]:
    return {"interaction": {"surface": "model.request", "kind": "model_call", "destination": "remote",
                            "model": "mock-echo", "text": text, "max_output_tokens": 256,
                            "meta": {"source": "bench"}},
            "identity": {"agent_id": "chaos-agent@platform"}, "session_id": session, "dry_run": dry_run}


def openai_body(text: str, model: str = "mock-echo", *, stream: bool = False) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": text}], "max_tokens": 64, "stream": stream}


__all__ = ["MixItem", "build_mix", "guard_body", "openai_body"]
