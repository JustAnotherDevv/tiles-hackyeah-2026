"""Audit record -> OCSF 1.9.0 event (research 04 section 4.4).

* non-allow decisions + `feed.rejected` / `policy.rejected` / `mcp.tool_changed`
  -> Detection Finding (class_uid 2004, category_uid 2, activity_id 1 Create, type_uid 200401)
* everything else -> API Activity (class_uid 6003, category_uid 6, type_uid 600300 + activity_id)

Security-control profile mapping (action_id / disposition_id):
allow 1 Allowed / 1 Allowed · log 3 Observed / 17 Logged · redact 4 Modified / 11 Corrected ·
require_approval 2 Denied / 14 Delayed · block 2 Denied / 2 Blocked.
No content, no raw values: only ids, entities, spans without values, fingerprints.
"""

from __future__ import annotations

from typing import Any

from aegis import __version__
from aegis.metrics.otel import genai_attributes, operation_name
from aegis.metrics.timing import to_utc

OCSF_VERSION = "1.9.0"
SEVERITY_ID = {"info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}
SEVERITY_CAPTION = {1: "Informational", 2: "Low", 3: "Medium", 4: "High", 5: "Critical"}
CONTROL_ACTION = {
    "allow": (1, "Allowed", 1, "Allowed"),
    "log": (3, "Observed", 17, "Logged"),
    "redact": (4, "Modified", 11, "Corrected"),
    "require_approval": (2, "Denied", 14, "Delayed"),
    "block": (2, "Denied", 2, "Blocked"),
}
FINDING_EVENTS = {"feed.rejected", "policy.rejected", "mcp.tool_changed"}
API_ACTIVITY = {
    "approval.created": (1, "Create"),
    "policy.applied": (3, "Update"),
    "policy.rollback": (3, "Update"),
    "feed.updated": (3, "Update"),
    "killswitch.toggled": (3, "Update"),
    "org.changed": (3, "Update"),
    "approval.decided": (3, "Update"),
}


def _summary(rec: dict[str, Any]) -> dict[str, Any]:
    data = rec.get("data") or {}
    s = data.get("summary")
    return s if isinstance(s, dict) else {}


def _severity(rec: dict[str, Any]) -> str:
    data = rec.get("data") or {}
    detail = data.get("detail") or {}
    sev = None
    for dec in detail.get("decisions") or []:
        if isinstance(dec, dict) and dec.get("control_id") == rec.get("control_id"):
            sev = dec.get("severity")
            break
    if sev:
        return str(sev)
    action = rec.get("action")
    if action == "block":
        return "high"
    if action in {"require_approval", "redact"}:
        return "medium"
    if rec.get("event_type") in FINDING_EVENTS:
        return "high"
    return "info"


def is_finding(rec: dict[str, Any]) -> bool:
    et = rec.get("event_type")
    if et == "decision":
        return (rec.get("action") or "allow") != "allow" and (rec.get("data") or {}).get(
            "phase"
        ) != "outcome"
    return et in FINDING_EVENTS


def _common(rec: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    ts = to_utc(rec.get("ts"))
    sev = _severity(rec)
    actor = rec.get("actor") or s.get("identity") or {}
    dest = rec.get("destination") or s.get("destination") or {}
    out: dict[str, Any] = {
        "time": int(ts.timestamp() * 1000) if ts else None,
        "severity_id": SEVERITY_ID.get(sev, 1),
        "severity": SEVERITY_CAPTION.get(SEVERITY_ID.get(sev, 1)),
        "metadata": {
            "version": OCSF_VERSION,
            "product": {
                "name": "Aegis AI Control Layer",
                "vendor_name": "Aegis",
                "version": __version__,
            },
            "uid": rec.get("event_id"),
            "correlation_uid": rec.get("request_id"),
            "log_name": "aegis.audit",
            "profiles": ["security_control"],
        },
        "actor": {
            "user": {"uid": actor.get("member_id")} if actor.get("member_id") else None,
            "app_name": actor.get("agent_id"),
        },
        "policy": {
            "uid": str(rec.get("policy_version") or s.get("policy_version") or 0),
            "name": "aegis-policy",
        },
        "unmapped": {
            "aegis": {
                "seq": rec.get("seq"),
                "hash": rec.get("hash"),
                "prev_hash": rec.get("prev_hash"),
                "event_type": rec.get("event_type"),
                "surface": rec.get("surface") or s.get("surface"),
                "controls": rec.get("controls") or s.get("controls") or [],
                "feed_serial": rec.get("feed_serial"),
            },
            "otel": (rec.get("data") or {}).get("otel") or (genai_attributes(s) if s else {}),
        },
    }
    model = rec.get("model") or s.get("model")
    if model:
        out["ai_model"] = {"name": model, "ai_provider": dest.get("provider") or dest.get("name")}
    if actor.get("agent_id"):
        out["ai_agent"] = {
            "uid": actor.get("agent_id"),
            "name": actor.get("display_name") or actor.get("agent_id"),
        }
    action = rec.get("action")
    if action in CONTROL_ACTION:
        aid, acap, did, dcap = CONTROL_ACTION[action]
        out.update({"action_id": aid, "action": acap, "disposition_id": did, "disposition": dcap})
    return out


def to_ocsf(rec: dict[str, Any]) -> dict[str, Any]:
    s = _summary(rec)
    out = _common(rec, s)
    data = rec.get("data") or {}
    if is_finding(rec):
        control = (
            rec.get("control_id")
            or s.get("control_id")
            or data.get("kind")
            or rec.get("event_type")
        )
        reason = rec.get("reason") or s.get("reason") or ""
        cats = sorted(
            {
                f.get("category")
                for dec in ((data.get("detail") or {}).get("decisions") or [])
                if isinstance(dec, dict)
                for f in (dec.get("findings") or [])
                if isinstance(f, dict) and f.get("category")
            }
        )
        tool = rec.get("tool_name") or s.get("tool_name")
        model = rec.get("model") or s.get("model")
        resources = []
        if model:
            resources.append({"type": "ai_model", "name": model})
        if tool:
            resources.append({"type": "tool", "name": tool})
        score = rec.get("score") if rec.get("score") is not None else s.get("score")
        out.update(
            {
                "class_uid": 2004,
                "class_name": "Detection Finding",
                "category_uid": 2,
                "category_name": "Findings",
                "activity_id": 1,
                "activity_name": "Create",
                "type_uid": 200401,
                "type_name": "Detection Finding: Create",
                "status_id": 1,
                "status": "New",
                "finding_info": {
                    "uid": rec.get("decision_id") or rec.get("event_id"),
                    "title": f"{control}: {reason}"[:300],
                    "analytic": {"uid": control, "name": control, "type_id": 1, "type": "Rule"},
                    "types": cats or [rec.get("event_type")],
                },
                "evidences": [
                    {
                        "data": {
                            "surface": rec.get("surface") or s.get("surface"),
                            "tool_name": tool,
                            "entities": s.get("entities") or [],
                            "redaction_spans": data.get("redaction_spans") or [],
                        }
                    }
                ],
                "resources": resources,
                "risk_score": round(float(score) * 100)
                if isinstance(score, (int, float))
                else None,
                "is_alert": rec.get("action") in {"block", "require_approval"}
                or rec.get("event_type") in FINDING_EVENTS,
                "message": reason[:300],
            }
        )
    else:
        et = rec.get("event_type") or "system"
        activity_id, activity_name = API_ACTIVITY.get(et, (99, "Other"))
        op = (
            operation_name(rec.get("kind") or s.get("kind"), rec.get("surface") or s.get("surface"))
            or et
        )
        dest = rec.get("destination") or s.get("destination") or {}
        actor = rec.get("actor") or s.get("identity") or {}
        out.update(
            {
                "class_uid": 6003,
                "class_name": "API Activity",
                "category_uid": 6,
                "category_name": "Application Activity",
                "activity_id": activity_id,
                "activity_name": activity_name,
                "type_uid": 600300 + activity_id,
                "type_name": f"API Activity: {activity_name}",
                "status_id": 1,
                "status": "Success",
                "api": {
                    "operation": op,
                    "service": {"name": dest.get("provider") or dest.get("name") or "aegis"},
                },
                "src_endpoint": {
                    "name": actor.get("agent_id") or actor.get("member_id") or "aegis"
                },
                "duration": rec.get("latency_ms")
                if rec.get("latency_ms") is not None
                else s.get("latency_ms"),
                "message": (rec.get("reason") or data.get("kind") or et)[:300]
                if isinstance(rec.get("reason") or data.get("kind") or et, str)
                else et,
            }
        )
    return {k: v for k, v in out.items() if v is not None}


__all__ = ["OCSF_VERSION", "is_finding", "to_ocsf"]
