"""Evaluate EvalCases in-process (rt.pipeline.evaluate, dry_run) or over HTTP (/v1/guard dry_run)."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

from aegis.core.types import Identity
from aegis.sdk.cast import agent_headers  # ASI03: X-Aegis-Agent + its key
from tests.eval.adapter import EvalCase
from tests.eval.scoring import CaseResult, score_verdict

CASE_TIMEOUT_S = 10.0
_DIGITS = re.compile(r"\d")


def local_mask(text: str, n: int = 60) -> str:
    """Fallback preview: truncate + mask digits (used if rt.redactor is unavailable)."""
    t = " ".join((text or "").split())
    t = _DIGITS.sub("#", t)
    return t if len(t) <= n else t[: n - 1] + "…"


def make_previewer(rt: Any | None) -> Callable[[str], str]:
    red = getattr(rt, "redactor", None) if rt is not None else None
    mask = getattr(red, "mask_for_log", None)

    def preview(text: str) -> str:
        if callable(mask):
            try:
                return " ".join(str(mask(text, 120)).split())
            except Exception:
                pass
        return local_mask(text)

    return preview


def new_result(case: EvalCase, profile: str, mode: str) -> CaseResult:
    r = case.row
    return CaseResult(
        id=r.id, profile=profile, mode=mode, label=r.label, category=r.category, lang=r.lang,
        surface=case.interaction.surface, source=r.file or r.source,
        split="tuning" if r.seen_by_tuning else "held_out", expected_action=r.expected_action,
        transform=r.get("transform"), seed_id=r.get("seed_id"),
    )


async def resolve_identity(rt: Any, agent_id: str) -> Identity:
    try:
        ident = await rt.org.resolve_identity({"x-aegis-agent": agent_id})
        if isinstance(ident, Identity) and ident.agent_id:
            return ident
    except Exception:
        pass
    # TODO(integration): constructed fallback if org-rbac cannot resolve the seed agent
    return Identity(org_id="acme-capital", team_id="platform", agent_id=agent_id, member_id="u_tomasz",
                    role="agent", authenticated=True)


async def run_inprocess(
    rt: Any,
    cases: list[EvalCase],
    *,
    profile: str,
    mode: str,
    concurrency: int = 8,
    deadline: float | None = None,
    keep_segments: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> list[CaseResult]:
    """Evaluate every case with `dry_run=True`. Exceptions / timeouts -> `error` (never detected)."""
    sem = asyncio.Semaphore(max(1, concurrency))
    preview = make_previewer(rt)
    idents: dict[str, Identity] = {}
    for aid in {c.agent_id for c in cases}:
        idents[aid] = await resolve_identity(rt, aid)
    results: list[CaseResult | None] = [None] * len(cases)
    done = 0

    async def one(idx: int, case: EvalCase) -> None:
        nonlocal done
        res = new_result(case, profile, mode)
        res.preview = preview(case.row.text)
        async with sem:
            if deadline is not None and time.monotonic() > deadline:
                res.error = "skipped: time budget exhausted"
                results[idx] = res
                return
            try:
                ctx = rt.pipeline.new_context(source="test", identity=idents[case.agent_id],
                                              session_id=case.session_id(profile), dry_run=True)
                verdict = await asyncio.wait_for(
                    rt.pipeline.evaluate(ctx, case.fresh_interaction(), dry_run=True), CASE_TIMEOUT_S)
                score_verdict(res, verdict)
                if keep_segments:
                    res.segments_out = [s.text for s in (verdict.segments or [])]
            except TimeoutError:
                res.error = f"timeout > {CASE_TIMEOUT_S:.0f}s"
            except Exception as e:
                res.error = f"exception: {type(e).__name__}: {e}"[:300]
        results[idx] = res
        done += 1
        if on_progress:
            on_progress(done)

    await asyncio.gather(*(one(i, c) for i, c in enumerate(cases)))
    return [r for r in results if r is not None]


async def run_http(
    base_url: str,
    cases: list[EvalCase],
    *,
    profile: str,
    mode: str,
    concurrency: int = 4,
    deadline: float | None = None,
    keep_segments: bool = False,
    transport: Any = None,
) -> list[CaseResult]:
    """POST /v1/guard with dry_run=true (never pollutes budgets/audit, never changes policy)."""
    import httpx

    sem = asyncio.Semaphore(max(1, min(concurrency, 4)))
    results: list[CaseResult | None] = [None] * len(cases)
    async with httpx.AsyncClient(base_url=base_url, timeout=CASE_TIMEOUT_S, transport=transport) as client:

        async def one(idx: int, case: EvalCase) -> None:
            res = new_result(case, profile, mode)
            res.preview = local_mask(case.row.text)
            async with sem:
                if deadline is not None and time.monotonic() > deadline:
                    res.error = "skipped: time budget exhausted"
                    results[idx] = res
                    return
                body = dict(case.guard_body)
                body["session_id"] = case.session_id(profile)
                try:
                    r = await client.post("/v1/guard", json=body,
                                          headers=agent_headers(case.agent_id))  # ASI03
                    if r.status_code != 200:
                        res.error = f"http {r.status_code}: {r.text[:120]}"
                    else:
                        data = r.json()
                        score_verdict(res, data.get("verdict") or {})
                        if keep_segments:
                            res.segments_out = [s.get("text", "") for s in data.get("segments") or []]
                except Exception as e:
                    res.error = f"exception: {type(e).__name__}: {e}"[:300]
            results[idx] = res

        await asyncio.gather(*(one(i, c) for i, c in enumerate(cases)))
    return [r for r in results if r is not None]


__all__ = ["local_mask", "make_previewer", "resolve_identity", "run_http", "run_inprocess"]
