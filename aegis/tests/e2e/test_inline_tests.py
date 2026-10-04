"""Auto-collected inline tests (plan 18 §2.7 I): tests travel with rules.

1. Policy: `POST /api/policy/validate {yaml: <current>}` runs every inline `tests:` entry of the
   loaded policy; each SelfTestResult becomes a matrix entry (source `policy`). A rule a judge adds
   with its own `tests:` is therefore tested with no code.
2. Feed: each signature's `tests.positive/negative` from the active bundle is replayed through
   `/v1/guard` (positive → SIG-01 non-allow; negative → no SIG-01 decision). Unknown shapes skip.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

import pytest

from tests.lib.client import KIND_BY_SURFACE
from tests.lib.matrix import RESULTS, Entry
from tests.lib.privacy import mask_text
from tests.lib.stack import is_live

ROOT = Path(__file__).resolve().parents[2]
SEED_BUNDLE = ROOT / "config" / "feeds" / "seed_bundle.json"


def _missing(reason: str) -> None:
    """Hermetic: the golden policy ships inline tests and the routes, so absence is a failure.
    Live (AEGIS_LIVE_URL): the remote gateway may run another build/policy, so skip."""
    if is_live():
        pytest.skip(reason)
    pytest.fail(reason, pytrace=False)


def _blockish(a: str | None) -> bool:
    return a in ("block", "require_approval", "redact")


def test_policy_inline_tests(gw: Any) -> None:
    pol = gw.policy()
    if not pol.get("yaml"):
        _missing("GET /api/policy unavailable")
    r = gw.api("POST", "/api/policy/validate", json={"yaml": pol["yaml"]})
    if r.status_code in (404, 405, 501):
        _missing(f"/api/policy/validate not available ({r.status_code})")
    assert r.status_code == 200, r.text[:300]
    rep = r.json()
    results = rep.get("selftest") or []
    if not results:
        _missing("policy has no inline tests (or self-test not run)")
    failed = []
    for t in results:
        exp = t.get("expect") or "allow"
        col = (
            "attack"
            if exp in ("block", "require_approval")
            else ("redact" if exp == "redact" else "benign")
        )
        ok = bool(t.get("passed"))
        RESULTS.add(
            Entry(
                id=f"POLICY-{t.get('name')}",
                control=t.get("control"),
                suite="inline",
                polarity="benign" if col == "benign" else "attack",
                expect=exp,
                column=col,
                outcome="pass" if ok else "fail",
                got=t.get("got"),
                got_control=t.get("got_control"),
                reason=""
                if ok
                else f"expected {exp}, got {t.get('got')} by {t.get('got_control')}",
                via="policy",
                latency_ms=t.get("latency_ms"),
                source="policy inline tests",
            )
        )
        if not ok:
            failed.append(
                f"{t.get('name')}: expected {exp}, got {t.get('got')} ({t.get('got_control')})"
            )
    assert rep.get("selftest_passed", not failed) or not failed, (
        "policy inline tests failed:\n" + "\n".join(failed)
    )
    assert not failed, "policy inline tests failed:\n" + "\n".join(failed)


def _feed_bundle(gw: Any) -> dict[str, Any] | None:
    if gw.mode == "live":
        r = gw.api("GET", "/api/feed/signatures")
        if r.status_code == 200:
            items = r.json().get("items") or []
            full = []
            for it in items:
                d = gw.api("GET", f"/api/feed/signatures/{it.get('id')}")
                if d.status_code == 200:
                    full.append(d.json().get("signature") or d.json())
            return {"signatures": full}
    if SEED_BUNDLE.exists():
        return json.loads(SEED_BUNDLE.read_text())
    return None


def _feed_cases() -> list[Any]:
    if not SEED_BUNDLE.exists():
        return []
    b = json.loads(SEED_BUNDLE.read_text())
    out = []
    for s in b.get("signatures") or []:
        if s.get("status") in ("withdrawn", "deprecated", "experimental"):
            continue
        for pol in ("positive", "negative"):
            for i, t in enumerate((s.get("tests") or {}).get(pol) or []):
                out.append(pytest.param(s["id"], pol, t, id=f"{s['id']}-{pol[:3]}{i}"))
    return out


def _interaction(t: dict[str, Any]) -> dict[str, Any] | None:
    surface = t.get("surface")
    if not surface or surface.startswith("a2a."):
        return None
    i: dict[str, Any] = {"surface": surface, "kind": KIND_BY_SURFACE.get(surface, "model_call")}
    for k in ("text", "tool_name", "tool_args", "url", "http_method", "meta"):
        if t.get(k) is not None:
            i[k] = t[k]
    if t.get("raw") is not None and surface == "artifact.file":
        import base64

        raw = t["raw"] if isinstance(t["raw"], str) else json.dumps(t["raw"])
        i.setdefault("meta", {})["artifact_b64"] = base64.b64encode(raw.encode()).decode()
        i["direction"] = "in"
    elif t.get("raw") is not None:
        i.setdefault("meta", {})["raw_result" if surface == "mcp.list" else "raw"] = t["raw"]
        if isinstance(t["raw"], str) and "text" not in i:
            i["text"] = t["raw"]
    if surface.startswith(("mcp.", "egress.")):
        i["destination"] = "third_party"
    elif surface.startswith("tool."):
        i["destination"] = "local"
    else:
        i["destination"] = "remote"
    if not any(k in i for k in ("text", "tool_args", "url", "meta")):
        return None
    return i


@pytest.mark.parametrize(("sig_id", "polarity", "t"), _feed_cases())
def test_feed_signature_inline(gw: Any, sig_id: str, polarity: str, t: dict[str, Any]) -> None:
    inter = _interaction(t)
    if inter is None:
        pytest.skip(f"unsupported feed test shape ({sorted(t)})")
    r = gw.guard(
        inter,
        who="chaos-agent@platform",
        session=f"t-feed-{secrets.token_hex(3)}",
        dry_run=gw.mode == "live",
    )
    assert r.status_code == 200, r.text[:300]
    v = r.json().get("verdict") or {}
    sig_decs = [d for d in v.get("decisions") or [] if d.get("control_id") == "SIG-01"]
    ids = {f.get("detector") for d in sig_decs for f in d.get("findings") or []} | {
        (f.get("meta") or {}).get("signature_id") for d in sig_decs for f in d.get("findings") or []
    }
    if ids - {None}:
        hit = sig_id in ids  # attribution by signature id (A-49 Finding.detector)
    else:
        hit = any(d.get("action") not in (None, "allow") for d in sig_decs)
    ok = hit if polarity == "positive" else not hit
    exp = "block" if polarity == "positive" else "allow"
    RESULTS.add(
        Entry(
            id=f"FEED-{sig_id}-{t.get('name', '')}"[:80],
            control="SIG-01",
            suite="inline",
            polarity="attack" if polarity == "positive" else "benign",
            expect=exp,
            column="attack" if polarity == "positive" else "benign",
            outcome="pass" if ok else "fail",
            got=v.get("action"),
            got_control=(v.get("primary") or {}).get("control_id"),
            reason="" if ok else f"{sig_id} {polarity} test: SIG-01 hit={hit}",
            via="guard",
            surface=inter["surface"],
            latency_ms=v.get("latency_ms"),
            tags=[f"sig:{sig_id}"],
            source="feed signature tests",
            preview=mask_text(str(t.get("text") or t.get("url") or "")),
        )
    )
    assert ok, (
        f"{sig_id} {polarity} test {t.get('name')!r}: SIG-01 hit={hit}, verdict={v.get('action')}"
    )
