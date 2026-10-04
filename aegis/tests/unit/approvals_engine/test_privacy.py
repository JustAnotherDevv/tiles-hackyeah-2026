"""APR-V08: approval payloads, SSE messages and audit data never carry raw identifiers.

Fake identifiers are generated at runtime (no realistic PII literals in the repo)."""

from __future__ import annotations

import json
import random

from aegis.core.types import Decision


def _luhn_complete(prefix: str) -> str:
    digits = [int(c) for c in prefix]
    total = 0
    for idx, d in enumerate(reversed(digits)):
        if idx % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return prefix + str((10 - total % 10) % 10)


def _fake_pan(rng: random.Random) -> str:
    return _luhn_complete("4" + "".join(str(rng.randint(0, 9)) for _ in range(14)))


def _fake_pesel(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(11))


def _dump(obj) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, ensure_ascii=False, default=str)


async def test_payload_sse_and_audit_are_masked(svc, h, fake_rt) -> None:
    rng = random.Random()
    pan, pesel = _fake_pan(rng), _fake_pesel(rng)
    i = h.spend(50.0, extra_args={"card_number": pan, "note": f"customer pesel {pesel}"})
    req = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    await svc.vote(req.id, h.member("u_emily"), "approve")
    stored = await svc.get(req.id)
    blobs = {
        "payload": _dump(stored.payload),
        "sse": _dump([m.data for m in fake_rt.bus.messages]),
        "audit": _dump([e.data for e in fake_rt.audit.events]),
        "audit_full": _dump([e.model_dump(mode="json") for e in fake_rt.audit.events]),
    }
    for name, blob in blobs.items():
        assert pan not in blob, f"raw PAN leaked into {name}"
        assert pesel not in blob, f"raw PESEL leaked into {name}"


async def test_sse_carries_yaml_digest_not_yaml(svc, h, fake_rt) -> None:
    yaml_text = "profile: balanced\nbudgets:\n  limits:\n    - {scope: team:trading, window: day, usd: 75}\n"
    change = {"kind": "budget.raise", "path": "budgets.limits[scope=team:trading,window=day].usd",
              "scope": "team:trading", "dimension": "usd", "before": 60, "after": 75,
              "increase_pct": 25, "loosening": True}
    i = h.config_interaction([change], proposal={"yaml": yaml_text, "base_version": 1})
    from aegis.core.types import ApprovalDraft

    draft = ApprovalDraft(kind="config_change", action_type="budget.raise",
                          title="Piotr wants to raise team:trading", labels={"scope": "team:trading"},
                          payload={"changes": [change], "proposal": i.meta["proposal"]})
    d = Decision(action="require_approval", control_id="GOV-05", reason="needs admin", approval=draft)
    req = await svc.request(h.ctx(h.member("u_piotr"), source="dashboard"), i, d)
    assert req.status == "pending"
    created = fake_rt.bus.events("approval.created")[-1]
    proposal = created["payload"]["proposal"]
    assert "yaml" not in proposal
    assert len(proposal["yaml_sha256"]) == 64 and proposal["yaml_bytes"] == len(yaml_text.encode())
    assert "usd: 75}" not in _dump(created)
    # the full YAML is still available to GET /api/approvals/{id} (svc.get)
    full = await svc.get(req.id)
    assert full.payload["proposal"]["yaml"] == yaml_text


async def test_fallback_mask_without_redactor(svc, h, fake_rt) -> None:
    fake_rt.redactor = None  # redaction-engine absent -> local fallback mask
    rng = random.Random()
    pan = _fake_pan(rng)
    i = h.spend(50.0, extra_args={"card_number": pan})
    req = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    assert pan not in _dump(req.payload)
    assert pan not in _dump([m.data for m in fake_rt.bus.messages])
