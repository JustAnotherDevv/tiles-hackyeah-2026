"""Per-control micro-benchmark (in-process, deterministic by default; plan 19 §2.9 source 3).

For every enabled, non-`off` control in the active snapshot and every mix interaction it applies
to: run `enrich` for all applicable controls first (like pipeline step 3), then time
`await control.evaluate(ctx, i, cfg)` individually.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from tests.eval.metrics import pct_summary


def interactions(n_prompts: int = 120) -> list[Any]:
    from tests.bench.mix import build_mix
    from tests.corpora.loader import CorpusRow, load_rows
    from tests.eval.adapter import to_case

    out = []
    for k, it in enumerate(build_mix(n_prompts)):
        row = CorpusRow(id=f"MICRO-{k}", text=it.text, label="benign", category="bench", lang="en",
                        source="bench", licence="-", expected_action="allow")
        out.append(to_case(row).interaction)
    # one of every non-prompt surface so tool / MCP / output controls are measured too
    for r in load_rows(subsets=["handwritten", "public"]):
        if r.surface != "user_prompt":
            out.append(to_case(r).interaction)
    return out


async def run_micro(rt: Any, *, n_prompts: int = 120, repeats: int = 1) -> list[dict[str, Any]]:
    snap = rt.policy.snapshot()
    cfgs = dict(getattr(snap, "controls", {}) or {})
    controls = []
    for c in rt.controls.all():
        cfg = cfgs.get(c.id)
        if cfg is None or not cfg.enabled or cfg.mode == "off":
            continue
        controls.append((c, cfg))
    controls.sort(key=lambda x: getattr(x[0], "priority", 100))
    ident = None
    try:
        ident = await rt.org.resolve_identity({"x-aegis-agent": "chaos-agent@platform"})
    except Exception:
        pass
    from aegis.core.types import Identity

    ident = ident or Identity(org_id="acme-capital", agent_id="chaos-agent@platform")
    times: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    kinds = {c.id: getattr(c, "kind", None) for c, _ in controls}
    for n, base in enumerate(interactions(n_prompts)):
        for _ in range(repeats):
            i = base.model_copy(deep=True)
            i.raw = base.raw
            ctx = rt.pipeline.new_context(source="test", identity=ident, session_id=f"micro-{n}", dry_run=True)
            ctx.policy = snap
            applicable = [(c, cfg) for c, cfg in controls if c.applies_to.matches(i)]
            for c, cfg in applicable:
                try:
                    await asyncio.wait_for(c.enrich(ctx, i, cfg), 2.0)
                except Exception:
                    pass
            for c, cfg in applicable:
                t0 = time.perf_counter()
                try:
                    await asyncio.wait_for(c.evaluate(ctx, i, cfg), 5.0)
                except Exception:
                    errors[c.id] += 1
                    continue
                times[c.id].append((time.perf_counter() - t0) * 1000)
    rows = []
    for cid in sorted(set(times) | set(errors)):
        s = pct_summary(times.get(cid, []), ndigits=4)
        rows.append({"control_id": cid, "kind": kinds.get(cid), "mode": "deterministic" if rt.settings.semantic_off
                     else "semantic", "p50_ms": s["p50"], "p95_ms": s["p95"], "p99_ms": s["p99"],
                     "count": s["n"], "errors": errors.get(cid, 0), "source": "micro"})
    return rows


__all__ = ["interactions", "run_micro"]
